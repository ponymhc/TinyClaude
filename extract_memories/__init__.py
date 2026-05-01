"""
后台记忆提取模块。

参考 TypeScript 版本: services/extractMemories/

目录结构:
- extract_memories/
  - __init__.py
  - prompts.py      # 提取提示模板
  - extract_memories.py  # 核心提取逻辑
"""

from .extract_memories import (
    # 初始化
    init_extract_memories,
    get_runner,

    # 主入口
    execute_extract_memories,
    drain_pending_extraction,

    # Runner
    ExtractMemoriesRunner,

    # 类型
    UsageStats,
    MemoryExtractionResult,
    AppendSystemMessageFn,

    # 工具函数
    extract_written_paths,
    has_memory_writes_since,
)

from .prompts import build_extract_auto_only_prompt

__all__ = [
    # 初始化
    'init_extract_memories',
    'get_runner',

    # 主入口
    'execute_extract_memories',
    'drain_pending_extraction',

    # Runner
    'ExtractMemoriesRunner',

    # 类型
    'UsageStats',
    'MemoryExtractionResult',
    'AppendSystemMessageFn',

    # 工具函数
    'extract_written_paths',
    'has_memory_writes_since',

    # 提示构建
    'build_extract_auto_only_prompt',
]
