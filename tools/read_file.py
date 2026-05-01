"""
File Read Tool - 读取文件内容，支持文本、图像、PDF、Notebook，记录读取状态用于乐观锁。
"""

import asyncio
import mimetypes
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from dataclasses import dataclass, field

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

# 可选依赖：用于图像处理、PDF、Notebook
try:
    from PIL import Image
    import io
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import pypdf
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

try:
    import nbformat
    HAS_NBFORMAT = True
except ImportError:
    HAS_NBFORMAT = False

# 辅助函数（与 WriteTool 保持一致）
def expand_path(path: str) -> str:
    """扩展 ~ 和环境变量，并转换为绝对路径"""
    expanded = os.path.expanduser(os.path.expandvars(path))
    return os.path.abspath(expanded)

def get_file_modification_time(file_path: str) -> Optional[float]:
    """返回毫秒级修改时间"""
    try:
        return os.path.getmtime(file_path) * 1000
    except FileNotFoundError:
        return None

# 全局读取状态（与 WriteTool 共享）
class ReadFileState:
    def __init__(self):
        self._state: Dict[str, Dict] = {}

    def get(self, file_path: str) -> Optional[Dict]:
        return self._state.get(file_path)

    def set(self, file_path: str, info: Dict):
        self._state[file_path] = info

_global_read_file_state = ReadFileState()

# 工具输入 Schema
class FileReadInput(BaseModel):
    file_path: str = Field(description="要读取的文件的绝对路径")
    offset: Optional[int] = Field(default=None, description="起始行号（从1开始），仅文本文件有效")
    limit: Optional[int] = Field(default=None, description="读取行数限制，仅文本文件有效")
    pages: Optional[str] = Field(default=None, description="PDF页面范围，如 '1-5', '3', '10-20'")

# 输出类型（简化，省略部分结构）
class FileReadOutput(BaseModel):
    type: str  # 'text', 'image', 'notebook', 'pdf', 'parts', 'file_unchanged'
    filePath: str
    content: Optional[str] = None
    base64: Optional[str] = None
    mediaType: Optional[str] = None
    originalSize: Optional[int] = None
    dimensions: Optional[Dict] = None
    cells: Optional[List] = None
    numLines: Optional[int] = None
    startLine: Optional[int] = None
    totalLines: Optional[int] = None
    pageCount: Optional[int] = None

# 工具类
class FileReadTool(BaseTool):
    model_config = ConfigDict(extra='allow')
    
    name: str = "Read"
    description: str = "Read a file (text, image, PDF, notebook). For large text files use offset/limit."
    args_schema: type[BaseModel] = FileReadInput

    # 可配置参数
    max_size_bytes: int = 10 * 1024 * 1024  # 10MB
    max_tokens: int = 100_000  # 粗略token限制
    read_file_state: ReadFileState = field(default_factory=lambda: _global_read_file_state)
    permission_check: Optional[callable] = Field(default=None, repr=False)
    root_dir: Optional[str] = Field(default=None, repr=False)  # 限制只能读取此目录下的文件

    # ---------- 权限与路径验证 ----------
    def _check_permission(self, path: str) -> Optional[str]:
        # root_dir 限制
        root_dir = getattr(self, 'root_dir', None)
        if root_dir:
            abs_root = os.path.abspath(root_dir)
            abs_path = os.path.abspath(path)
            if not abs_path.startswith(abs_root):
                return f"Reading files outside {root_dir} is not allowed"
        if self.permission_check:
            return self.permission_check(path)
        # 基本拒绝规则：系统敏感目录
        sensitive = ['/etc', '/usr', '/bin', '/sbin', '/boot', '/dev']
        for s in sensitive:
            if path.startswith(s):
                return f"Reading from {s} is not allowed"
        return None

    def _is_blocked_device(self, path: str) -> bool:
        """阻止会阻塞或产生无限输出的设备文件"""
        blocked = {
            '/dev/zero', '/dev/random', '/dev/urandom', '/dev/full',
            '/dev/stdin', '/dev/tty', '/dev/console', '/dev/stdout', '/dev/stderr'
        }
        if path in blocked:
            return True
        if path.startswith('/proc/') and any(path.endswith(f'/fd/{i}') for i in range(3)):
            return True
        return False

    # ---------- 异步文件读取 ----------
    async def _read_file_range(
        self, path: str, offset_line: int, limit: Optional[int], max_bytes: int
    ) -> Tuple[str, int, int, int, int, float]:
        """
        读取文本文件的指定行范围。
        返回: (content, num_lines, total_lines, total_bytes, read_bytes, mtime_ms)
        """
        # 获取总行数和总字节数（同步）
        total_lines = 0
        total_bytes = 0
        try:
            with open(path, 'rb') as f:
                total_bytes = os.fstat(f.fileno()).st_size
                # 粗略统计行数（读取整个文件可能大，但对于大小限制内的文件可行）
                if total_bytes <= max_bytes:
                    total_lines = sum(1 for _ in f)
                else:
                    # 如果太大，只读取头部估计（或跳过），这里简化：先读文件可能慢，但offset/limit场景一般文件不大
                    # 我们允许读取整个文件到内存（受max_bytes限制），否则报错
                    raise ValueError(f"File too large ({total_bytes} bytes) > max {max_bytes}")
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {path}")

        # 读取内容
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
            total_lines = len(lines)
            if offset_line > total_lines:
                return "", 0, total_lines, total_bytes, 0, get_file_modification_time(path) or 0
            start_idx = max(0, offset_line - 1)
            end_idx = None if limit is None else start_idx + limit
            selected = lines[start_idx:end_idx]
            content = ''.join(selected)
            read_bytes = sum(len(l.encode('utf-8')) for l in selected)
            mtime_ms = get_file_modification_time(path) or 0
            return content, len(selected), total_lines, total_bytes, read_bytes, mtime_ms

    async def _read_image(self, path: str) -> FileReadOutput:
        """读取图像，可选压缩以适应 token 限制"""
        if not HAS_PIL:
            raise RuntimeError("Pillow not installed, cannot read images")
        with open(path, 'rb') as f:
            data = f.read()
        size = len(data)
        # 基础压缩：如果尺寸过大，调整大小
        img = Image.open(io.BytesIO(data))
        orig_width, orig_height = img.size
        # 简单的token估算：base64长度 * 0.75 ~ 实际字节，每个token ~4字符？简化：限制图片最大边长800
        max_dim = 800
        if max(orig_width, orig_height) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            img.save(buffer, format=img.format or 'PNG')
            data = buffer.getvalue()
            size = len(data)
        base64_data = data.encode('base64') if hasattr(data, 'encode') else data  # Python3 bytes has no encode
        # 正确方式：
        import base64
        base64_str = base64.b64encode(data).decode('ascii')
        return FileReadOutput(
            type='image',
            filePath=path,
            base64=base64_str,
            mediaType=f"image/{img.format.lower()}" if img.format else "image/png",
            originalSize=size,
            dimensions={'originalWidth': orig_width, 'originalHeight': orig_height}
        )

    async def _read_pdf(self, path: str, pages: Optional[str]) -> Union[FileReadOutput, List[Dict]]:
        """读取PDF，返回FileReadOutput或附加的图片块列表"""
        if not HAS_PYPDF:
            raise RuntimeError("pypdf not installed, cannot read PDFs")
        import base64
        with open(path, 'rb') as f:
            data = f.read()
        size = len(data)
        if pages:
            # 解析页面范围
            match = re.match(r'(\d+)(?:-(\d+))?', pages)
            if not match:
                raise ValueError(f"Invalid pages format: {pages}")
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else start
            if end - start + 1 > 10:  # 限制最多10页
                raise ValueError(f"Page range too large: {pages}")
            # 使用 pypdf 提取指定页面（需要额外处理，这里简化：读取全部并返回base64）
            # 为简化，直接返回整个PDF base64
            pass
        # 返回整个PDF的base64
        return FileReadOutput(
            type='pdf',
            filePath=path,
            base64=base64.b64encode(data).decode('ascii'),
            originalSize=size,
            mediaType='application/pdf'
        )

    async def _read_notebook(self, path: str) -> FileReadOutput:
        if not HAS_NBFORMAT:
            raise RuntimeError("nbformat not installed, cannot read notebooks")
        with open(path, 'r', encoding='utf-8') as f:
            nb = nbformat.read(f, as_version=4)
        cells = []
        for cell in nb.cells:
            cells.append({
                'cell_type': cell.cell_type,
                'source': cell.source,
                'outputs': cell.get('outputs', []),
                'metadata': cell.metadata
            })
        return FileReadOutput(
            type='notebook',
            filePath=path,
            cells=cells
        )

    async def _read_text(self, path: str, offset: Optional[int], limit: Optional[int]) -> FileReadOutput:
        max_bytes = self.max_size_bytes
        offset_line = offset if offset is not None else 1
        content, num_lines, total_lines, total_bytes, read_bytes, mtime = await self._read_file_range(
            path, offset_line, limit, max_bytes
        )
        # 更新读取状态（供写工具使用）
        self.read_file_state.set(path, {
            'content': content,
            'timestamp': mtime,
            'offset': offset,
            'limit': limit,
            'isPartialView': limit is not None
        })
        return FileReadOutput(
            type='text',
            filePath=path,
            content=content,
            numLines=num_lines,
            startLine=offset_line,
            totalLines=total_lines
        )

    # ---------- 主入口 ----------
    async def _arun(self, file_path: str, offset: Optional[int] = None,
                    limit: Optional[int] = None, pages: Optional[str] = None) -> str:
        """LangChain要求返回字符串，这里返回人类可读的结果摘要"""
        # 实际读取逻辑
        full_path = expand_path(file_path)
        # 权限检查（返回错误消息而不是抛出异常，让 agent 可以更正）
        perm_err = self._check_permission(full_path)
        if perm_err:
            return f"Error: {perm_err}\nPath used: {full_path}"
        # 阻止设备文件
        if self._is_blocked_device(full_path):
            return f"Error: Cannot read device file: {full_path}"
        # 根据扩展名选择读取方式
        ext = os.path.splitext(full_path)[1].lower()
        try:
            if ext in {'.png', '.jpg', '.jpeg', '.gif', '.webp'}:
                result = await self._read_image(full_path)
                return f"Read image: {result.filePath} ({result.originalSize} bytes)"
            elif ext == '.ipynb':
                result = await self._read_notebook(full_path)
                return f"Read notebook: {result.filePath} with {len(result.cells)} cells"
            elif ext == '.pdf':
                result = await self._read_pdf(full_path, pages)
                return f"Read PDF: {result.filePath} ({result.originalSize} bytes)"
            else:
                result = await self._read_text(full_path, offset, limit)
                return f"Read {result.numLines} lines from {result.filePath}:\n{result.content}"
        except Exception as e:
            # 处理文件不存在，尝试相似文件名建议
            if isinstance(e, FileNotFoundError):
                # 简单查找相似文件
                dirname = os.path.dirname(full_path)
                if os.path.exists(dirname):
                    files = os.listdir(dirname)
                    similar = [f for f in files if f.lower().startswith(os.path.basename(full_path).lower()[:3])]
                    hint = f" Did you mean {similar[0]}?" if similar else ""
                else:
                    hint = ""
                return f"Error: File does not exist: {full_path}.{hint}"
            raise

    def _run(self, file_path: str, offset: Optional[int] = None,
             limit: Optional[int] = None, pages: Optional[str] = None) -> str:
        raise NotImplementedError("Use async version (_arun)")

# 全局实例
def get_read_tool() -> FileReadTool:
    return FileReadTool()