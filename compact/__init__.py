"""
Compact 模块 - 对话上下文压缩功能

参考 Claude Code CLI: services/compact/
"""

from .types import (
    # Token 相关
    TokenUsage,
    TokenWarningState,
    # 配置
    SessionMemoryCompactConfig,
    DEFAULT_SM_COMPACT_CONFIG,
    # 常量
    AUTOCOMPACT_BUFFER_TOKENS,
    WARNING_THRESHOLD_BUFFER_TOKENS,
    ERROR_THRESHOLD_BUFFER_TOKENS,
    MANUAL_COMPACT_BUFFER_TOKENS,
    MAX_OUTPUT_TOKENS_FOR_SUMMARY,
    MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES,
    # 结果类型
    CompactionResult,
    MicrocompactResult,
    AutoCompactResult,
    AutoCompactTrackingState,
    # Hook 类型
    HookResult,
    # 错误类型
    CompactError,
    NotEnoughMessagesError,
    PromptTooLongError,
    UserAbortError,
    IncompleteResponseError,
)

from .config import (
    get_context_window_for_model,
    get_effective_context_window_size,
    get_auto_compact_threshold,
    is_auto_compact_enabled,
    calculate_token_warning_state,
    get_sm_compact_config,
    set_sm_compact_config,
)

from .token_estimation import (
    rough_token_count_estimation,
    estimate_message_tokens,
    estimate_tokens_for_messages,
    calculate_tool_result_tokens,
    get_session_total_tokens,
    get_session_token_usage,
)

from .messages import (
    create_user_message,
    create_compact_boundary_message,
    is_compact_boundary_message,
    has_text_blocks,
    get_message_id,
    get_message_uuid,
    get_last_assistant_message,
    get_messages_after_boundary,
    get_assistant_message_text,
    build_post_compact_messages,
)

from .session_memory_compact import (
    adjust_index_to_preserve_api_invariants,
    calculate_messages_to_keep_index,
    should_use_session_memory_compaction,
    try_session_memory_compaction,
)


__all__ = [
    # types
    "TokenUsage",
    "TokenWarningState",
    "SessionMemoryCompactConfig",
    "DEFAULT_SM_COMPACT_CONFIG",
    "AUTOCOMPACT_BUFFER_TOKENS",
    "WARNING_THRESHOLD_BUFFER_TOKENS",
    "ERROR_THRESHOLD_BUFFER_TOKENS",
    "MANUAL_COMPACT_BUFFER_TOKENS",
    "MAX_OUTPUT_TOKENS_FOR_SUMMARY",
    "MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES",
    "CompactionResult",
    "MicrocompactResult",
    "AutoCompactResult",
    "AutoCompactTrackingState",
    "HookResult",
    "CompactError",
    "NotEnoughMessagesError",
    "PromptTooLongError",
    "UserAbortError",
    "IncompleteResponseError",
    # config
    "get_context_window_for_model",
    "get_effective_context_window_size",
    "get_auto_compact_threshold",
    "is_auto_compact_enabled",
    "calculate_token_warning_state",
    "get_sm_compact_config",
    "set_sm_compact_config",
    # token_estimation
    "rough_token_count_estimation",
    "estimate_message_tokens",
    "estimate_tokens_for_messages",
    "calculate_tool_result_tokens",
    "get_session_total_tokens",
    "get_session_token_usage",
    # messages
    "create_user_message",
    "create_compact_boundary_message",
    "is_compact_boundary_message",
    "has_text_blocks",
    "get_message_id",
    "get_message_uuid",
    "get_last_assistant_message",
    "get_messages_after_boundary",
    "get_assistant_message_text",
    "build_post_compact_messages",
    # session_memory_compact
    "adjust_index_to_preserve_api_invariants",
    "calculate_messages_to_keep_index",
    "should_use_session_memory_compaction",
    "try_session_memory_compaction",
]
