"""
File Edit Tool - 编辑文件内容（字符串替换），支持 replace_all 和乐观锁。
"""

import asyncio
import difflib
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

# 复用之前实现的 expand_path, get_file_modification_time, ReadFileState
from .read_file import expand_path, get_file_modification_time, ReadFileState, _global_read_file_state

# =============================================================================
# 辅助函数
# =============================================================================

def find_actual_string(content: str, old_string: str) -> Optional[str]:
    """
    在文件中查找实际匹配的字符串（处理引号风格差异）。
    返回实际匹配到的字符串，若未找到返回 None。
    """
    if old_string in content:
        return old_string
    # 可选：处理单/双引号差异，但为简化，先只做精确匹配
    return None

def preserve_quote_style(old_string: str, actual_old_string: str, new_string: str) -> str:
    """
    保留引号风格（在 TS 版本中用于处理智能引号）。
    这里简化：如果 actual_old_string 与 old_string 不同（例如引号被规范化），
    则尝试将 new_string 中的引号替换为实际文件中的引号风格。
    简单实现：直接返回 new_string，不做特殊处理。
    """
    return new_string

def get_patch_for_edit(
    file_path: str,
    file_contents: str,
    old_string: str,
    new_string: str,
    replace_all: bool,
) -> Tuple[List[Dict], str]:
    """
    生成 unified diff patch 并返回更新后的文件内容。
    返回 (patch, updated_content)
    """
    if replace_all:
        updated_content = file_contents.replace(old_string, new_string)
    else:
        updated_content = file_contents.replace(old_string, new_string, 1)

    # 生成 unified diff
    original_lines = file_contents.splitlines(keepends=True)
    updated_lines = updated_content.splitlines(keepends=True)
    diff = difflib.unified_diff(
        original_lines, updated_lines,
        fromfile=f'a/{file_path}', tofile=f'b/{file_path}',
        lineterm=''
    )
    diff_lines = list(diff)
    # 构建简化的 patch 结构（每个 hunk 包含 oldStart, oldLines, newStart, newLines, lines）
    # 为简化，将整个 diff 作为单个 hunk
    patch = [{
        "oldStart": 1,
        "oldLines": len(original_lines),
        "newStart": 1,
        "newLines": len(updated_lines),
        "lines": diff_lines
    }] if diff_lines else []
    return patch, updated_content

def validate_settings_file_edit(file_path: str, content_before: str, content_after: str) -> Optional[Dict]:
    """
    验证对设置文件的编辑是否安全（简化版，返回 None 表示允许）。
    可扩展。
    """
    return None

# =============================================================================
# 输入输出 Schema
# =============================================================================

class FileEditInput(BaseModel):
    file_path: str = Field(description="要编辑的文件的绝对路径")
    old_string: str = Field(description="要替换的字符串")
    new_string: str = Field(description="替换后的字符串")
    replace_all: bool = Field(default=False, description="是否替换所有出现（默认只替换第一个）")

class FileEditOutput(BaseModel):
    filePath: str
    oldString: str
    newString: str
    originalFile: str
    structuredPatch: List[Dict]
    userModified: bool = False
    replaceAll: bool = False

class FileEditTool(BaseTool):
    name: str = "Edit"
    description: str = (
        "Edit a file by replacing occurrences of old_string with new_string. "
        "Use replace_all=True to replace all occurrences. "
        "The file must have been read before editing (optimistic lock)."
    )
    args_schema: type[BaseModel] = FileEditInput

    # 可配置依赖
    read_file_state: ReadFileState = Field(default_factory=lambda: _global_read_file_state)
    permission_check: Optional[callable] = Field(default=None, repr=False)  # (path) -> Optional[str]
    max_edit_file_size: int = 1024 * 1024 * 1024  # 1 GiB
    root_dir: Optional[str] = Field(default=None, repr=False)  # 限制只能编辑此目录下的文件

    # ---------- 辅助方法 ----------
    def _check_permission(self, path: str) -> Optional[str]:
        # root_dir 限制
        if self.root_dir:
            abs_root = os.path.abspath(self.root_dir)
            abs_path = os.path.abspath(path)
            if not abs_path.startswith(abs_root):
                return f"Editing files outside {self.root_dir} is not allowed"
        if self.permission_check:
            return self.permission_check(path)
        # 默认禁止系统敏感目录
        sensitive = ['/etc', '/usr', '/bin', '/sbin', '/boot', '/dev']
        for s in sensitive:
            if path.startswith(s):
                return f"Editing files in {s} is not allowed"
        return None

    async def _read_file_content(self, path: str) -> Optional[str]:
        """异步读取文件内容，返回规范化换行为 LF 的字符串，文件不存在返回 None"""
        try:
            import aiofiles
            async with aiofiles.open(path, 'r', encoding='utf-8') as f:
                content = await f.read()
        except ImportError:
            # 回退同步读取
            def _read():
                with open(path, 'r', encoding='utf-8') as f:
                    return f.read()
            content = await asyncio.to_thread(_read)
        except FileNotFoundError:
            return None
        # 统一换行为 LF
        return content.replace('\r\n', '\n')

    async def _write_file_atomic(self, path: str, content: str):
        """原子写入：先写临时文件再替换"""
        dir_name = os.path.dirname(path)
        Path(dir_name).mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=dir_name, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        os.replace(tmp_path, path)

    # ---------- 核心执行 ----------
    async def _arun(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> str:
        """异步执行编辑，返回人类可读的结果字符串"""
        # 1. 路径规范化与权限检查（返回错误消息而不是抛出异常）
        full_path = expand_path(file_path)
        perm_err = self._check_permission(full_path)
        if perm_err:
            return f"Error: {perm_err}\nPath used: {full_path}"

        # 2. 读取文件内容（如果存在）
        original_content = await self._read_file_content(full_path)
        file_exists = original_content is not None

        # 3. 处理创建新文件的情况（old_string 为空且文件不存在）
        if not file_exists:
            if old_string == "":
                # 创建新文件
                new_content = new_string
                await self._write_file_atomic(full_path, new_content)
                # 更新 readFileState
                mtime = get_file_modification_time(full_path) or 0
                self.read_file_state.set(full_path, {
                    'content': new_content,
                    'timestamp': mtime,
                    'offset': None,
                    'limit': None,
                })
                return f"File created successfully: {full_path}"
            else:
                # 文件不存在但 old_string 非空，返回错误信息
                return f"Error: File does not exist: {full_path}"

        # 4. 文件存在，检查大小限制
        try:
            stat = await asyncio.to_thread(os.stat, full_path)
            if stat.st_size > self.max_edit_file_size:
                raise ValueError(f"File too large to edit: {stat.st_size} bytes > {self.max_edit_file_size} bytes")
        except Exception as e:
            if not isinstance(e, FileNotFoundError):
                raise

        # 5. 乐观锁：检查 readFileState 是否过期
        last_read = self.read_file_state.get(full_path)
        current_mtime = get_file_modification_time(full_path)
        if last_read is None:
            return "Error: File has not been read yet. Read it first before editing."
        if current_mtime is not None and current_mtime > last_read.get('timestamp', 0):
            # 时间戳变大，进一步比较内容是否真的改变
            if original_content != last_read.get('content'):
                return (
                    "Error: File has been modified since read. "
                    "Please read it again before editing."
                )

        # 6. 处理空 old_string 但文件非空（禁止创建覆盖）
        if old_string == "" and original_content.strip() != "":
            return "Error: Cannot create new file - file already exists."

        # 7. 查找实际匹配的字符串（处理引号等）
        actual_old = find_actual_string(original_content, old_string)
        if not actual_old:
            return f"Error: String to replace not found in file:\n{old_string}"

        # 8. 统计匹配次数
        matches = original_content.count(actual_old)
        if matches > 1 and not replace_all:
            return (
                f"Error: Found {matches} matches of the string to replace, but replace_all is false. "
                "To replace all occurrences, set replace_all to true. "
                "To replace only one occurrence, please provide more context."
            )

        # 9. 保留引号风格（简化）
        actual_new = preserve_quote_style(old_string, actual_old, new_string)

        # 10. 生成 patch 和更新后的内容
        patch, updated_content = get_patch_for_edit(
            full_path, original_content, actual_old, actual_new, replace_all
        )

        # 11. 可选：针对设置文件的额外验证
        validation = validate_settings_file_edit(full_path, original_content, updated_content)
        if validation is not None:
            return f"Error: {validation}"

        # 12. 原子写入
        await self._write_file_atomic(full_path, updated_content)

        # 13. 更新 readFileState
        new_mtime = get_file_modification_time(full_path) or 0
        self.read_file_state.set(full_path, {
            'content': updated_content,
            'timestamp': new_mtime,
            'offset': None,
            'limit': None,
        })

        # 14. 记录操作（日志可添加）
        # 可选：触发 LSP 通知等，这里简化

        # 15. 返回结果消息
        if replace_all:
            return f"The file {full_path} has been updated. All occurrences were successfully replaced."
        else:
            return f"The file {full_path} has been updated successfully."

    def _run(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
        raise NotImplementedError("Use async version (_arun)")

# 全局单例实例（可选）
_global_edit_tool = None

def get_edit_tool() -> FileEditTool:
    global _global_edit_tool
    if _global_edit_tool is None:
        _global_edit_tool = FileEditTool()
    return _global_edit_tool