from dataclasses import dataclass
from typing import Optional

from config.config import (
    SessionMemoryConfig as UnifiedSessionMemoryConfig,
    get_session_memory_config as _get_unified_sm_config,
    reload_all_config as _reload_unified_config,
)


# =============================================================================
# 向后兼容的配置模型
# =============================================================================

DEFAULT_MIN_MESSAGE_TOKENS_TO_INIT = 1000
DEFAULT_MIN_TOKENS_BETWEEN_UPDATE = 500
DEFAULT_TOOL_CALLS_BETWEEN_UPDATES = 3
DEFAULT_MAX_TURNS = 50


@dataclass
class SessionMemoryConfig:
    """Session Memory 配置（向后兼容）"""
    minimum_message_tokens_to_init: int = DEFAULT_MIN_MESSAGE_TOKENS_TO_INIT
    minimum_tokens_between_update: int = DEFAULT_MIN_TOKENS_BETWEEN_UPDATE
    tool_calls_between_updates: int = DEFAULT_TOOL_CALLS_BETWEEN_UPDATES
    enabled: bool = True
    max_turns: int = DEFAULT_MAX_TURNS
    model_name: Optional[str] = "qwen3_8b"
    max_section_length: int = 2000
    max_total_tokens: int = 12000


# =============================================================================
# 全局状态
# =============================================================================

_last_summarized_index: Optional[int] = None
_tokens_at_last_extraction: int = 0
_session_memory_initialized: bool = False


# =============================================================================
# 配置访问
# =============================================================================

def get_config() -> SessionMemoryConfig:
    """获取 Session Memory 配置（使用统一配置）"""
    unified = _get_unified_sm_config()
    return SessionMemoryConfig(
        minimum_message_tokens_to_init=unified.minimum_message_tokens_to_init,
        minimum_tokens_between_update=unified.minimum_tokens_between_update,
        tool_calls_between_updates=unified.tool_calls_between_updates,
        enabled=unified.enabled,
        max_turns=unified.max_turns,
        model_name=unified.model_name,
        max_section_length=unified.max_section_length,
        max_total_tokens=unified.max_total_tokens,
    )


def set_config(config: SessionMemoryConfig) -> None:
    """设置配置（注意：统一配置模式下此操作无效）"""
    import logging
    logging.warning("set_config is deprecated in unified config mode. Edit config/settings.yaml instead.")


def reload_config() -> SessionMemoryConfig:
    """重新加载配置"""
    _reload_unified_config()
    return get_config()


# =============================================================================
# 状态访问函数
# =============================================================================

def get_last_summarized_index() -> Optional[int]:
    """获取最后总结的消息索引"""
    return _last_summarized_index


def set_last_summarized_index(index: Optional[int]) -> None:
    """设置最后总结的消息索引"""
    global _last_summarized_index
    _last_summarized_index = index


def get_tokens_at_last_extraction() -> int:
    """获取上次提取时的 token 数"""
    return _tokens_at_last_extraction


def record_extraction_token_count(count: int) -> None:
    """记录当前 token 数用于下次间隔计算"""
    global _tokens_at_last_extraction
    _tokens_at_last_extraction = count


def is_session_memory_initialized() -> bool:
    """检查是否已初始化"""
    return _session_memory_initialized


def mark_session_memory_initialized() -> None:
    """标记已初始化"""
    global _session_memory_initialized
    _session_memory_initialized = True


def has_met_init_threshold(current_token_count: int) -> bool:
    """检查是否达到初始化阈值"""
    return current_token_count >= get_config().minimum_message_tokens_to_init


def has_met_update_threshold(current_token_count: int) -> bool:
    """检查是否达到更新阈值"""
    tokens_since_last = current_token_count - _tokens_at_last_extraction
    return tokens_since_last >= get_config().minimum_tokens_between_update


def get_tool_calls_between_updates() -> int:
    """获取更新间隔的工具调用数"""
    return get_config().tool_calls_between_updates


def reset_state() -> None:
    """重置所有状态"""
    global _last_summarized_index, _tokens_at_last_extraction, _session_memory_initialized
    _reload_unified_config()
    _last_summarized_index = None
    _tokens_at_last_extraction = 0
    _session_memory_initialized = False


# =============================================================================
# 配置路径函数（保留用于兼容性）
# =============================================================================

def get_config_dir() -> str:
    """获取配置目录（已废弃，返回统一配置目录）"""
    return "config"


def get_config_path() -> str:
    """获取配置文件路径（已废弃）"""
    return "config/settings.yaml"


def load_config_from_yaml() -> None:
    """从 YAML 加载配置（已废弃，使用统一配置）"""
    return None


def save_config_to_yaml(config: SessionMemoryConfig) -> str:
    """保存配置到 YAML（已废弃，使用 config/settings.yaml）"""
    import logging
    logging.warning("save_config_to_yaml is deprecated. Edit config/settings.yaml instead.")
    return "config/settings.yaml"


def create_default_config_file() -> str:
    """创建默认配置文件（已废弃）"""
    return "config/settings.yaml"
