"""
记忆目录 (memdir) 模块。

提供文件基础的持久化个人记忆系统，包括：
1. 记忆类型定义和分类
2. 路径管理和安全验证
3. 记忆文件扫描和解析
4. 记忆提示构建
5. 自动记忆提取

主要入口：
- load_memory_prompt(): 加载记忆提示到系统提示
- init_extract_memories() / execute_extract_memories(): 自动提取

配置：
- 使用 Pydantic 配置模型管理所有设置
- 配置文件搜索顺序：MEMDIR_CONFIG_PATH > ~/.config/memdir/config.json > 项目目录 > ~/.memdir.json
"""

from .config import (
    AutoMemoryConfig,
    get_config,
    reload_config,
    find_config_file,
    get_config_paths,
    is_auto_memory_enabled,
    get_auto_mem_dirname,
    get_auto_mem_entrypoint_name,
    get_max_entrypoint_lines,
    get_max_entrypoint_bytes,
    get_memory_base_dir,
    get_logs_subdir,
    get_max_memory_files,
    get_max_frontmatter_lines,
    get_exclude_patterns,
    get_extraction_model,
)

from .memory_types import (
    MEMORY_FRONTMATTER_EXAMPLE,
    MEMORY_TYPES,
    TYPES_SECTION_INDIVIDUAL,
    TRUSTING_RECALL_SECTION,
    WHAT_NOT_TO_SAVE_SECTION,
    WHEN_TO_ACCESS_SECTION,
    MemoryType,
    parse_memory_type,
)

from .memory_age import (
    memory_age,
    memory_age_days,
    memory_freshness_note,
    memory_freshness_text,
)

from .paths import (
    AUTO_MEM_DIRNAME,
    AUTO_MEM_ENTRYPOINT_NAME,
    MAX_ENTRYPOINT_BYTES,
    MAX_ENTRYPOINT_LINES,
    get_auto_mem_daily_log_path,
    get_auto_mem_entrypoint,
    get_auto_mem_path,
    get_memory_base_dir as get_memory_base_dir_from_paths,
    is_auto_mem_path,
    is_auto_memory_enabled as is_auto_memory_enabled_from_paths,
    validate_memory_path,
)

from .memory_scan import (
    FrontmatterResult,
    MemoryHeader,
    format_memory_manifest,
    parse_frontmatter,
    scan_memory_files,
)

from .memdir import (
    DIRS_EXIST_GUIDANCE,
    DIR_EXISTS_GUIDANCE,
    AUTO_MEM_DISPLAY_NAME,
    EntrypointTruncation,
    build_memory_lines,
    ensure_memory_dir_exists,
    load_memory_prompt,
    truncate_entrypoint_content,
)

from extract_memories import (
    AppendSystemMessageFn,
    execute_extract_memories,
    extract_written_paths,
    has_memory_writes_since,
    init_extract_memories,
)

from .load_all_memories import (
    MemdirContext,
    MemdirIndex,
    MemoryMetadata,
    format_memdir_as_system_reminder,
    format_memdir_context,
    get_memory_summary,
    load_all_memories_for_context,
    load_memdir_context,
    read_memory_md,
    scan_memory_metadata,
)


__all__ = [
    # config
    "AutoMemoryConfig",
    "get_config",
    "reload_config",
    "find_config_file",
    "get_config_paths",
    # memory_types
    "MEMORY_TYPES",
    "MemoryType",
    "parse_memory_type",
    "MEMORY_FRONTMATTER_EXAMPLE",
    "TYPES_SECTION_INDIVIDUAL",
    "TRUSTING_RECALL_SECTION",
    "WHAT_NOT_TO_SAVE_SECTION",
    "WHEN_TO_ACCESS_SECTION",
    # memory_age
    "memory_age",
    "memory_age_days",
    "memory_freshness_note",
    "memory_freshness_text",
    # paths
    "AUTO_MEM_DIRNAME",
    "AUTO_MEM_ENTRYPOINT_NAME",
    "MAX_ENTRYPOINT_BYTES",
    "MAX_ENTRYPOINT_LINES",
    "get_auto_mem_daily_log_path",
    "get_auto_mem_entrypoint",
    "get_auto_mem_path",
    "get_memory_base_dir",
    "has_auto_mem_path_override",
    "is_auto_mem_path",
    "is_auto_memory_enabled",
    "validate_memory_path",
    # memory_scan
    "MemoryHeader",
    "FrontmatterResult",
    "format_memory_manifest",
    "parse_frontmatter",
    "scan_memory_files",
    # memdir
    "DIR_EXISTS_GUIDANCE",
    "DIRS_EXIST_GUIDANCE",
    "AUTO_MEM_DISPLAY_NAME",
    "EntrypointTruncation",
    "build_memory_lines",
    "ensure_memory_dir_exists",
    "load_memory_prompt",
    "truncate_entrypoint_content",
    # extract_memories
    "AppendSystemMessageFn",
    "execute_extract_memories",
    "extract_written_paths",
    "has_memory_writes_since",
    "init_extract_memories",
    # load_all_memories
    "MemdirContext",
    "MemdirIndex",
    "MemoryMetadata",
    "format_memdir_as_system_reminder",
    "format_memdir_context",
    "get_memory_summary",
    "load_all_memories_for_context",
    "load_memdir_context",
    "read_memory_md",
    "scan_memory_metadata",
]
