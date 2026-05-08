"""
查询相关记忆模块。

通过扫描记忆文件头部并让模型选择最相关的记忆，
找到与查询相关的记忆文件。

返回最相关记忆的绝对文件路径 + mtime（最多 5 个）。
"""

from dataclasses import dataclass
from typing import List, Optional, Set

from .memory_scan import MemoryHeader, format_memory_manifest, scan_memory_files
from .paths import get_auto_mem_path


# =============================================================================
# 类型定义
# =============================================================================


@dataclass
class RelevantMemory:
    """相关记忆。"""
    path: str
    mtime_ms: float


# =============================================================================
# 提示模板
# =============================================================================

SELECT_MEMORIES_SYSTEM_PROMPT = """\
You are selecting memories that will be useful to TinyClaude as it processes a user's query. You will be given the user's query and a list of available memory files with their filenames and descriptions.

Return a list of filenames for the memories that will clearly be useful to TinyClaude as it processes the user's query (up to 5). Only include memories that you are certain will be helpful based on their name and description.
- If you are unsure if a memory will be useful in processing the user's query, then do not include it in your list. Be selective and discerning.
- If there are no memories in the list that would clearly be useful, feel free to return an empty list.
- If a list of recently-used tools is provided, do not select memories that are usage reference or API documentation for those tools (TinyClaude is already exercising them). DO still select memories containing warnings, gotchas, or known issues about those tools — active use is exactly when those matter.
"""


# =============================================================================
# 记忆选择逻辑
# =============================================================================


async def find_relevant_memories(
    query: str,
    memory_dir: Optional[str] = None,
    signal: Optional["asyncio.Event"] = None,
    recent_tools: Optional[List[str]] = None,
    already_surfaced: Optional[Set[str]] = None,
) -> List[RelevantMemory]:
    """
    找到与查询相关的记忆文件。

    参数:
        query: 用户查询
        memory_dir: 记忆目录路径（默认为 get_auto_mem_path()）
        signal: 中断信号
        recent_tools: 最近使用的工具列表
        already_surfaced: 之前已展示的记忆路径集合

    返回:
        相关记忆列表（最多 5 个）
    """
    if memory_dir is None:
        memory_dir = get_auto_mem_path()

    if recent_tools is None:
        recent_tools = []

    if already_surfaced is None:
        already_surfaced = set()

    # 扫描记忆文件
    memories = await scan_memory_files(memory_dir, signal)

    # 过滤已展示的记忆
    memories = [m for m in memories if m.file_path not in already_surfaced]

    if not memories:
        return []

    # 选择相关记忆
    selected_filenames = await _select_relevant_memories(
        query, memories, signal, recent_tools
    )

    # 构建结果映射
    by_filename = {m.filename: m for m in memories}
    selected = [
        by_filename[fn]
        for fn in selected_filenames
        if fn in by_filename
    ]

    return [RelevantMemory(path=m.file_path, mtime_ms=m.mtime_ms) for m in selected]


async def _select_relevant_memories(
    query: str,
    memories: List[MemoryHeader],
    signal: Optional["asyncio.Event"],
    recent_tools: List[str],
) -> List[str]:
    """
    使用模型选择相关记忆。

    注意：这里简化了原始实现，原始实现使用 sideQuery 调用模型。
    在 Python 版本中，我们使用简单的基于规则的匹配。
    """
    # 简单的基于关键词的匹配作为后备
    valid_filenames = [m.filename for m in memories]

    # 构建清单
    manifest = format_memory_manifest(memories)

    # TODO: 实现真实的模型调用
    # 在完整实现中，这里应该调用模型 API 来选择相关记忆
    # 目前返回简单的基于查询关键词的匹配

    query_lower = query.lower()
    selected = []

    for m in memories:
        # 基于描述和类型的简单匹配
        score = 0
        desc = (m.description or "").lower()

        # 查询词在描述中出现
        query_words = [
            w for w in query_lower.split() if len(w) > 3
        ]
        for word in query_words:
            if word in desc or word in m.filename.lower():
                score += 1

        if score > 0:
            selected.append((m.filename, score))

    # 按分数排序并取前 5 个
    selected.sort(key=lambda x: x[1], reverse=True)
    return [fn for fn, _ in selected[:5]]
