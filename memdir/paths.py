"""
记忆目录路径管理模块。

路径解析流程：
1. 配置文件中 automemory.directory（完整路径覆盖）
2. 默认路径：{base_dir}/{dirname}

其中：
- base_dir: 默认为 ~/memdir
- dirname: 默认为 memory
"""

import os
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .config import (
    get_auto_mem_dirname,
    get_auto_mem_entrypoint_name,
    get_logs_subdir,
    get_max_entrypoint_bytes,
    get_max_entrypoint_lines,
    get_memory_base_dir,
    is_auto_memory_enabled,
)


# =============================================================================
# 配置常量（从配置读取或使用默认值）
# =============================================================================

MAX_ENTRYPOINT_LINES = get_max_entrypoint_lines()
MAX_ENTRYPOINT_BYTES = get_max_entrypoint_bytes()
AUTO_MEM_DIRNAME = get_auto_mem_dirname()
AUTO_MEM_ENTRYPOINT_NAME = get_auto_mem_entrypoint_name()


# =============================================================================
# 路径验证
# =============================================================================


def _get_project_name() -> str:
    """获取当前项目名称（从 CWD 派生）。"""
    project_root = os.getcwd()
    return _sanitize_path(project_root)


def _sanitize_path(path: str) -> str:
    """简单路径清理，移除不安全字符。"""
    return re.sub(r"[^\w\-_.]", "_", os.path.basename(path))


def validate_memory_path(raw: Optional[str], expand_tilde: bool = True) -> Optional[str]:
    """
    规范化并验证候选自动记忆目录路径。

    安全检查：拒绝以下危险路径：
    - 相对路径 (!isAbsolute): "../foo" — 会相对于 CWD 解释
    - 根/近根 (长度 < 3): "/" → ""; "/a" 太短
    - Windows 驱动器根 (C: 正则): "C:\\" → "C:"
    - UNC 路径 (\\\\server\\share): 网络路径 — 不透明信任边界
    - null 字节: 在 syscalls 中可能被截断

    返回规范化路径（带恰好一个尾部分隔符），
    或路径未设置/为空/被拒绝时返回 None。
    """
    if not raw:
        return None

    candidate = raw

    # 支持 ~/ 展开
    if expand_tilde and (candidate.startswith("~/") or candidate.startswith("~\\")):
        rest = candidate[2:]
        # 拒绝平凡的剩余部分
        if rest in ("", ".", "..") or rest.startswith(".."):
            return None
        candidate = os.path.join(Path.home(), rest)

    # 规范化并移除尾部分隔符
    normalized = os.path.normpath(candidate).rstrip("/\\")

    # 安全检查
    if not os.path.isabs(normalized):
        return None
    if len(normalized) < 3:
        return None
    if re.match(r"^[A-Za-z]:$", normalized):
        return None
    if normalized.startswith("\\\\") or normalized.startswith("//"):
        return None
    if "\0" in normalized:
        return None

    # 添加恰好一个尾部分隔符
    return normalized + os.sep


# =============================================================================
# 自动记忆目录解析
# =============================================================================


@lru_cache(maxsize=1)
def get_auto_mem_path() -> str:
    """
    返回自动记忆目录路径：{base_dir}/{dirname}
    注意：get_memory_base_dir() 已经包含了 dirname
    """
    base_dir = get_memory_base_dir()
    return base_dir + os.sep


def get_auto_mem_daily_log_path(date: Optional[datetime] = None) -> str:
    """
    返回给定日期的每日日志文件路径。
    形状: <autoMemPath>/<logs_subdir>/YYYY/MM/YYYY-MM-DD.md
    """
    if date is None:
        date = datetime.now()

    yyyy = date.strftime("%Y")
    mm = date.strftime("%m")
    dd = date.strftime("%d")
    logs_subdir = get_logs_subdir()

    return os.path.join(
        get_auto_mem_path(), logs_subdir, yyyy, mm, f"{yyyy}-{mm}-{dd}.md"
    )


def get_auto_mem_entrypoint() -> str:
    """返回自动记忆入口点 (MEMORY.md 在自动记忆目录内)。"""
    return os.path.join(get_auto_mem_path(), AUTO_MEM_ENTRYPOINT_NAME)


def is_auto_mem_path(absolute_path: str) -> bool:
    """
    检查绝对路径是否在自动记忆目录内。

    安全：规范化以防止通过 .. 段绕过路径遍历。
    """
    normalized = os.path.normpath(absolute_path)
    return normalized.startswith(get_auto_mem_path())



