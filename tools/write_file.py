import asyncio
import difflib
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field
import aiofiles

def expand_path(path: str) -> str:
    """扩展路径中的 ~ 和环境变量，并转换为绝对路径"""
    expanded = os.path.expanduser(os.path.expandvars(path))
    return os.path.abspath(expanded)

def get_file_modification_time(file_path: str) -> Optional[float]:
    """返回文件的修改时间戳（毫秒），文件不存在返回 None"""
    try:
        return os.path.getmtime(file_path) * 1000
    except FileNotFoundError:
        return None

def generate_unified_diff(original: str, updated: str, file_path: str) -> List[Dict]:
    """生成简化的结构化 patch（每个 hunk 包含 oldStart, oldLines, newStart, newLines, lines）"""
    if original == updated:
        return []
    original_lines = original.splitlines(keepends=True)
    updated_lines = updated.splitlines(keepends=True)
    diff = difflib.unified_diff(
        original_lines, updated_lines,
        fromfile=f'a/{file_path}', tofile=f'b/{file_path}',
        lineterm=''
    )
    diff_lines = list(diff)
    if not diff_lines:
        return []
    # 解析 unified diff 头部，提取行号范围
    # 简单做法：把整个 diff 作为单个 hunk，lines 包含所有行
    # 为了满足 hunk 结构，构造一个基本 hunk
    hunk = {
        "oldStart": 1,
        "oldLines": len(original_lines),
        "newStart": 1,
        "newLines": len(updated_lines),
        "lines": diff_lines
    }
    return [hunk]

class ReadFileState:
    """存储每个文件读取时的内容和时间戳"""
    def __init__(self):
        self._state: Dict[str, Dict] = {}

    def get(self, file_path: str) -> Optional[Dict]:
        return self._state.get(file_path)

    def set(self, file_path: str, info: Dict):
        self._state[file_path] = info

# 全局单例，供 Read 和 Write 工具共享
_global_read_file_state = ReadFileState()


class FileWriteInput(BaseModel):
    file_path: str = Field(description="要写入的文件的绝对路径")
    content: str = Field(description="要写入的内容")

class FileWriteOutput(BaseModel):
    type: str  # "create" 或 "update"
    filePath: str
    content: str
    structuredPatch: List[Dict]
    originalFile: Optional[str]
    gitDiff: Optional[Dict] = None

class FileWriteTool(BaseTool):
    name: str = "Write"
    description: str = (
        "Write content to a file (absolute path). "
        "Creates parent directories if needed. "
        "Before writing, the file must have been read first (for safety)."
    )
    args_schema: Type[BaseModel] = FileWriteInput

    read_file_state: ReadFileState = Field(default_factory=lambda: _global_read_file_state)
    permission_check: Optional[callable] = Field(default=None, repr=False)  # 签名 (full_path, context) -> Optional[str]
    root_dir: Optional[str] = Field(default=None, repr=False)  # 限制只能写入此目录

    def _ensure_parent_dir(self, file_path: str):
        parent = os.path.dirname(file_path)
        if parent:
            Path(parent).mkdir(parents=True, exist_ok=True)

    async def _read_file_content(self, file_path: str) -> Optional[str]:
        """异步读取文件内容，文件不存在时返回 None"""
        try:
            async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                return await f.read()
        except FileNotFoundError:
            return None

    async def _write_file_content_atomic(self, file_path: str, content: str):
        """原子写入：先写临时文件，再替换"""
        self._ensure_parent_dir(file_path)
        dir_name = os.path.dirname(file_path)
        # 创建临时文件（在同一目录下，保证 rename 原子性）
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=dir_name, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        # 重命名为目标文件（POSIX 上原子，Windows 上也可能原子）
        os.replace(tmp_path, file_path)
        # 验证文件是否创建成功
        if not os.path.exists(file_path):
            raise RuntimeError(f"Failed to create file after replace: {file_path}")

    def _validate_permission(self, full_path: str) -> Optional[str]:
        """权限检查"""
        # root_dir 限制
        if self.root_dir:
            abs_root = os.path.abspath(self.root_dir)
            abs_path = os.path.abspath(full_path)
            if not abs_path.startswith(abs_root):
                return f"Writing files outside {self.root_dir} is not allowed"
        if self.permission_check:
            return self.permission_check(full_path, None)
        # 默认禁止写入系统敏感目录
        sensitive_dirs = ['/etc', '/usr', '/bin', '/sbin', '/boot']
        norm_path = os.path.abspath(full_path)
        for d in sensitive_dirs:
            if norm_path.startswith(d):
                return f"Writing to {d} is not allowed"
        return None

    async def _arun(self, file_path: str, content: str) -> str:
        """异步执行，返回人类可读的结果字符串"""
        # 1. 扩展路径
        full_path = expand_path(file_path)
        # 2. 权限检查（返回错误消息而不是抛出异常）
        perm_err = self._validate_permission(full_path)
        if perm_err:
            return f"Error: {perm_err}\nPath used: {full_path}"
        # 3. 检查是否为目录
        if os.path.isdir(full_path):
            return f"Error: Cannot write to directory: {full_path}"

        # 4. 读取现有内容
        old_content = await self._read_file_content(full_path)
        is_new = old_content is None

        # 5. 乐观锁检查
        last_read = self.read_file_state.get(full_path)
        if not is_new:
            current_mtime = get_file_modification_time(full_path)
            if last_read is None:
                return "Error: File has been modified since read. Please read it again before writing."
            if current_mtime is not None and current_mtime > last_read.get('timestamp', 0):
                # 时间戳变大，可能被修改，进一步比较内容
                if old_content != last_read.get('content'):
                    return "Error: File has been modified since read. Please read it again before writing."
        else:
            # 新文件：如果之前从未读取过，允许创建（但也可以要求先读？TS 允许创建新文件）
            pass

        # 6. 原子写入（直接 await，因为 _write_file_content_atomic 是 async 函数）
        try:
            await self._write_file_content_atomic(full_path, content)
            # 再次验证文件存在
            if not os.path.exists(full_path):
                return f"Write completed but file does not exist: {full_path}"
        except Exception as e:
            return f"Failed to write file: {e}"

        # 7. 生成 patch
        patch = []
        if not is_new:
            patch = generate_unified_diff(old_content, content, full_path)

        # 8. 更新读取状态
        new_mtime = get_file_modification_time(full_path)
        self.read_file_state.set(full_path, {
            'content': content,
            'timestamp': new_mtime,
            'offset': None,
            'limit': None,
        })

        # 9. 返回人类可读结果
        if is_new:
            return f"File created successfully at: {full_path}"
        else:
            return f"The file {full_path} has been updated successfully."

    # 同步版本（LangChain 可能调用，这里抛出异常强制使用异步）
    def _run(self, file_path: str, content: str) -> str:
        raise NotImplementedError("Use async version (call _arun directly in async context).")