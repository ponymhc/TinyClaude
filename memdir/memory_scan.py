import asyncio
import os
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .memory_types import MemoryType, parse_memory_type


_max_files: Optional[int] = None
_frontmatter_max_lines: Optional[int] = None

def _get_max_memory_files() -> int:
    global _max_files
    if _max_files is None:
        from .config import get_max_memory_files as _get
        _max_files = _get()
    return _max_files

def _get_frontmatter_max_lines() -> int:
    global _frontmatter_max_lines
    if _frontmatter_max_lines is None:
        from .config import get_max_frontmatter_lines as _get
        _frontmatter_max_lines = _get()
    return _frontmatter_max_lines


# =============================================================================
# 类型定义
# =============================================================================


@dataclass
class MemoryHeader:
    """记忆文件头信息。"""
    filename: str
    file_path: str
    mtime_ms: float
    description: Optional[str]
    memory_type: Optional[MemoryType]


@dataclass
class FrontmatterResult:
    """Frontmatter 解析结果。"""
    frontmatter: dict
    content: str


# =============================================================================
# Frontmatter 解析
# =============================================================================


def parse_frontmatter(content: str, file_path: str) -> FrontmatterResult:
    """
    解析 markdown 文件的 YAML frontmatter。

    格式：
        ---
        key: value
        ---
        content
    """
    lines = content.split("\n")

    # 查找 frontmatter 边界
    start = -1
    end = -1

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "---":
            if start == -1:
                start = i
            elif start != -1 and end == -1:
                end = i
                break

    if start == -1 or end == -1:
        return FrontmatterResult(frontmatter={}, content=content)

    # 解析 frontmatter
    fm_lines = lines[start + 1 : end]
    frontmatter: dict = {}

    for line in fm_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # 简单的 key: value 解析
        if ":" in line:
            key, _, value = line.partition(":")
            frontmatter[key.strip()] = value.strip()

    # 提取 content 部分
    body = "\n".join(lines[end + 1 :]).strip()

    return FrontmatterResult(frontmatter=frontmatter, content=body)


# =============================================================================
# 记忆文件扫描
# =============================================================================


async def scan_memory_files(
    memory_dir: str, signal: Optional["asyncio.Event"] = None
) -> List[MemoryHeader]:
    """
    扫描记忆目录中的 .md 文件，读取它们的 frontmatter，
    并返回按最新优先排序的头列表（最多 max_memory_files）。

    并行读取：使用 asyncio.gather 同时读取多个文件的 frontmatter，
    然后按 mtime 排序。常见情况 (N ≤ 200) 比串行读取快数倍。
    """
    max_files = _get_max_memory_files()
    max_frontmatter_lines = _get_frontmatter_max_lines()

    async def read_single_file(file_path: str) -> Optional[MemoryHeader]:
        """读取单个文件的 frontmatter 和元数据。"""
        try:
            # 获取 mtime
            stat = os.stat(file_path)
            mtime_ms = stat.st_mtime * 1000

            # 读取 frontmatter（前 N 行）
            with open(file_path, "r", encoding="utf-8") as f:
                lines = [f.readline() for _ in range(max_frontmatter_lines)]
                content = "".join(lines)

            result = parse_frontmatter(content, file_path)
            rel_path = os.path.relpath(file_path, memory_dir)

            return MemoryHeader(
                filename=rel_path,
                file_path=file_path,
                mtime_ms=mtime_ms,
                description=result.frontmatter.get("description") or None,
                memory_type=parse_memory_type(
                    result.frontmatter.get("type")
                ),
            )
        except (OSError, IOError):
            return None

    try:
        entries = []
        # 排除的目录
        exclude_dirs = {'logs', '.git', '__pycache__'}
        for root, dirs, files in os.walk(memory_dir):
            # 过滤排除的目录
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            for name in files:
                if name.endswith(".md") and name != "MEMORY.md":
                    entries.append(os.path.join(root, name))

        # 限制文件数量
        entries = entries[:max_files]

        # 并行读取所有文件的 frontmatter
        if entries:
            results = await asyncio.gather(
                *[read_single_file(fp) for fp in entries],
                return_exceptions=True
            )
            headers = [r for r in results if r is not None and not isinstance(r, Exception)]
        else:
            headers = []

        # 按 mtime 降序排序
        headers.sort(key=lambda h: h.mtime_ms, reverse=True)

        return headers[:max_files]

    except (OSError, IOError):
        return []


def format_memory_manifest(memories: List[MemoryHeader]) -> str:
    """
    将记忆头格式化为文本清单：每行一个文件，
    格式为 [type] filename (timestamp): description。
    """
    lines = []
    for m in memories:
        tag = f"[{m.memory_type}] " if m.memory_type else ""
        ts = ""
        try:
            ts = __import__("datetime").datetime.fromtimestamp(
                m.mtime_ms / 1000
            ).isoformat()
        except Exception:
            pass

        if m.description:
            lines.append(f"- {tag}{m.filename} ({ts}): {m.description}")
        else:
            lines.append(f"- {tag}{m.filename} ({ts})")

    return "\n".join(lines)
