"""
Compact 配置管理

参考 Claude Code CLI: services/compact/autoCompact.ts
"""

import os
from typing import Optional

from .types import (
    SessionMemoryCompactConfig,
    DEFAULT_SM_COMPACT_CONFIG,
    AUTOCOMPACT_BUFFER_TOKENS,
    WARNING_THRESHOLD_BUFFER_TOKENS,
    ERROR_THRESHOLD_BUFFER_TOKENS,
    MANUAL_COMPACT_BUFFER_TOKENS,
    MAX_OUTPUT_TOKENS_FOR_SUMMARY,
    MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES,
)


# ============================================================================
# 模型上下文窗口
# ============================================================================

# 各模型的上下文窗口大小（tokens）
MODEL_CONTEXT_WINDOWS = {
    # Claude 3.5
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-5-sonnet-latest": 200_000,
    # Claude 3 Opus
    "claude-3-opus-20240229": 200_000,
    "claude-3-opus-latest": 200_000,
    # Claude 3 Sonnet
    "claude-3-sonnet-20240229": 200_000,
    "claude-3-sonnet-latest": 200_000,
    # Claude 3 Haiku
    "claude-3-haiku-20240307": 200_000,
    "claude-3-haiku-latest": 200_000,
    # Claude 2
    "claude-2.1": 200_000,
    "claude-2.0": 200_000,
    # Claude Instant
    "claude-instant-1.2": 100_000,
    # Qwen 系列
    "qwen3_8b": 32_000,
    "qwen3_32b": 32_000,
    "qwen2.5_72b": 32_000,
    # 默认
    "default": 200_000,
}


def get_context_window_for_model(model: str) -> int:
    """
    获取模型的上下文窗口大小

    Args:
        model: 模型名称

    Returns:
        上下文窗口大小（tokens）
    """
    # 检查环境变量覆盖
    env_window = os.environ.get("TINY_CLAUDE_CONTEXT_WINDOW")
    if env_window:
        try:
            return int(env_window)
        except ValueError:
            pass

    # 从已知模型中查找
    if model in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[model]

    # 尝试前缀匹配
    for known_model, window in MODEL_CONTEXT_WINDOWS.items():
        if model.startswith(known_model.split("-")[0]):
            return window

    return MODEL_CONTEXT_WINDOWS["default"]


def get_max_output_tokens_for_model(model: str) -> int:
    """
    获取模型的最大输出 token 数

    Args:
        model: 模型名称

    Returns:
        最大输出 token 数
    """
    # Claude 系列默认 8192
    if "claude" in model.lower():
        return 8192

    # Qwen 系列
    if "qwen" in model.lower():
        if "3-32b" in model.lower():
            return 16_384
        return 8_192

    # 默认
    return 8_192


# ============================================================================
# 有效上下文窗口
# ============================================================================

def get_effective_context_window_size(model: str) -> int:
    """
    获取有效的上下文窗口大小（减去输出预留）

    参考 Claude Code CLI: getEffectiveContextWindowSize()

    Args:
        model: 模型名称

    Returns:
        有效上下文窗口大小（tokens）
    """
    reserved_tokens = min(
        get_max_output_tokens_for_model(model),
        MAX_OUTPUT_TOKENS_FOR_SUMMARY,
    )

    # 检查环境变量覆盖
    env_window = os.environ.get("TINY_CLAUDE_AUTO_COMPACT_WINDOW")
    if env_window:
        try:
            parsed = int(env_window)
            if parsed > 0:
                return parsed - reserved_tokens
        except ValueError:
            pass

    context_window = get_context_window_for_model(model)
    return context_window - reserved_tokens


# ============================================================================
# 自动压缩阈值
# ============================================================================

def get_auto_compact_threshold(model: str) -> int:
    """
    获取自动压缩触发阈值

    参考 Claude Code CLI: getAutoCompactThreshold()

    计算公式: effectiveContextWindow - AUTOCOMPACT_BUFFER_TOKENS (13_000)

    Args:
        model: 模型名称

    Returns:
        自动压缩触发阈值（tokens）
    """
    effective_window = get_effective_context_window_size(model)

    # 检查环境变量百分比覆盖
    env_percent = os.environ.get("TINY_CLAUDE_AUTOCOMPACT_PCT_OVERRIDE")
    if env_percent:
        try:
            parsed = float(env_percent)
            if 0 < parsed <= 100:
                percentage_threshold = int(effective_window * (parsed / 100))
                return min(percentage_threshold, effective_window - AUTOCOMPACT_BUFFER_TOKENS)
        except ValueError:
            pass

    return effective_window - AUTOCOMPACT_BUFFER_TOKENS


# ============================================================================
# Token 警告状态
# ============================================================================

def is_auto_compact_enabled() -> bool:
    """
    检查是否启用自动压缩

    参考 Claude Code CLI: isAutoCompactEnabled()

    Returns:
        是否启用
    """
    # 环境变量禁用
    if os.environ.get("DISABLE_COMPACT"):
        return False
    if os.environ.get("DISABLE_AUTO_COMPACT"):
        return False

    # TODO: 从用户配置读取
    # from config.config import get_global_config
    # user_config = get_global_config()
    # return user_config.auto_compact_enabled

    # 默认启用
    return True


def calculate_token_warning_state(
    token_usage: int,
    model: str,
) -> "TokenWarningState":
    """
    计算 Token 警告状态

    参考 Claude Code CLI: calculateTokenWarningState()

    Args:
        token_usage: 当前 token 使用量
        model: 模型名称

    Returns:
        TokenWarningState
    """
    from .types import TokenWarningState

    auto_compact_threshold = get_auto_compact_threshold(model)
    threshold = auto_compact_threshold if is_auto_compact_enabled() else get_effective_context_window_size(model)

    # 计算剩余百分比
    if threshold > 0:
        percent_left = max(0, round((threshold - token_usage) / threshold * 100))
    else:
        percent_left = 0

    # 各阈值
    warning_threshold = threshold - WARNING_THRESHOLD_BUFFER_TOKENS
    error_threshold = threshold - ERROR_THRESHOLD_BUFFER_TOKENS
    blocking_limit = threshold - MANUAL_COMPACT_BUFFER_TOKENS

    # 检查是否超过各阈值
    is_above_warning_threshold = token_usage >= warning_threshold
    is_above_error_threshold = token_usage >= error_threshold
    is_above_autocompact_threshold = (
        is_auto_compact_enabled() and token_usage >= auto_compact_threshold
    )

    # 检查阻塞限制
    # 允许环境变量覆盖
    blocking_limit_override = os.environ.get("TINY_CLAUDE_BLOCKING_LIMIT_OVERRIDE")
    if blocking_limit_override:
        try:
            parsed = int(blocking_limit_override)
            if parsed > 0:
                blocking_limit = parsed
        except ValueError:
            pass

    is_at_blocking_limit = token_usage >= blocking_limit

    return TokenWarningState(
        percent_left=percent_left,
        is_above_warning_threshold=is_above_warning_threshold,
        is_above_error_threshold=is_above_error_threshold,
        is_above_autocompact_threshold=is_above_autocompact_threshold,
        is_at_blocking_limit=is_at_blocking_limit,
        autocompact_threshold=auto_compact_threshold,
        warning_threshold=warning_threshold,
        error_threshold=error_threshold,
        blocking_limit=blocking_limit,
    )


# ============================================================================
# Session Memory 压缩配置
# ============================================================================

_sm_compact_config: SessionMemoryCompactConfig = DEFAULT_SM_COMPACT_CONFIG


def get_sm_compact_config() -> SessionMemoryCompactConfig:
    """
    获取 Session Memory 压缩配置

    Returns:
        SessionMemoryCompactConfig
    """
    return _sm_compact_config


def set_sm_compact_config(config: SessionMemoryCompactConfig) -> None:
    """
    设置 Session Memory 压缩配置

    Args:
        config: 新配置
    """
    global _sm_compact_config
    _sm_compact_config = config


def reset_sm_compact_config() -> SessionMemoryCompactConfig:
    """
    重置 Session Memory 压缩配置为默认值

    Returns:
        默认配置
    """
    global _sm_compact_config
    _sm_compact_config = DEFAULT_SM_COMPACT_CONFIG
    return _sm_compact_config
