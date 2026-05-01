"""
Session Memory 模块

自动维护一个 Markdown 文件，记录当前对话的关键信息。
使用后台任务定期提取信息，不中断主对话流程。

参考 Claude Code: services/SessionMemory/

使用方式:
    from session.memory import (
        should_extract_memory,
        extract_session_memory,
        manually_extract_session_memory,
        get_session_memory_content,
    )
"""

from .config import (
    SessionMemoryConfig,
    get_config,
    set_config,
    get_config_dir,
    get_config_path,
    load_config_from_yaml,
    save_config_to_yaml,
    create_default_config_file,
    DEFAULT_MIN_MESSAGE_TOKENS_TO_INIT,
    DEFAULT_MIN_TOKENS_BETWEEN_UPDATE,
    DEFAULT_TOOL_CALLS_BETWEEN_UPDATES,
)

from .prompts import (
    load_template,
    build_session_memory_update_prompt,
    is_session_memory_empty,
    DEFAULT_SESSION_MEMORY_TEMPLATE,
)

from .paths import (
    get_session_memory_path,
    ensure_session_memory_dir,
    ensure_session_memory_file,
)

from .session_memory import (
    SessionMemoryRunner,
    is_session_memory_enabled,
    should_extract_memory,
    setup_session_memory_file,
    get_session_memory_content,
    get_session_memory_content_sync,
    execute_session_memory,
    drain_session_memory,
    estimate_messages_token_count,
)


__all__ = [
    # config
    "SessionMemoryConfig",
    "get_config",
    "set_config",
    "get_config_dir",
    "get_config_path",
    "load_config_from_yaml",
    "save_config_to_yaml",
    "create_default_config_file",
    "DEFAULT_MIN_MESSAGE_TOKENS_TO_INIT",
    "DEFAULT_MIN_TOKENS_BETWEEN_UPDATE",
    "DEFAULT_TOOL_CALLS_BETWEEN_UPDATES",
    # prompts
    "load_template",
    "build_session_memory_update_prompt",
    "is_session_memory_empty",
    "DEFAULT_SESSION_MEMORY_TEMPLATE",
    # paths
    "get_session_memory_path",
    "ensure_session_memory_dir",
    "ensure_session_memory_file",
    # session_memory
    "SessionMemoryRunner",
    "is_session_memory_enabled",
    "should_extract_memory",
    "setup_session_memory_file",
    "get_session_memory_content",
    "get_session_memory_content_sync",
    "execute_session_memory",
    "drain_session_memory",
    "estimate_messages_token_count",
]
