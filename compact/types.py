"""
Compact 模块类型定义

参考 Claude Code CLI: services/compact/types.ts (隐式)
"""

from dataclasses import dataclass, field
from typing import List, Optional, Any, Dict, Literal
from datetime import datetime


# ============================================================================
# Token 相关类型
# ============================================================================

@dataclass
class TokenUsage:
    """Token 使用量"""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    @property
    def total(self) -> int:
        """总 token 数"""
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_input_tokens
            + self.cache_creation_input_tokens
        )


@dataclass
class TokenWarningState:
    """Token 警告状态"""
    percent_left: float                    # 剩余百分比
    is_above_warning_threshold: bool      # 是否超过警告阈值
    is_above_error_threshold: bool       # 是否超过错误阈值
    is_above_autocompact_threshold: bool # 是否触发自动压缩
    is_at_blocking_limit: bool            # 是否达到阻塞限制
    autocompact_threshold: int           # 自动压缩触发阈值
    warning_threshold: int                # 警告阈值
    error_threshold: int                 # 错误阈值
    blocking_limit: int                  # 阻塞限制


# ============================================================================
# Session Memory 压缩配置
# ============================================================================

@dataclass
class SessionMemoryCompactConfig:
    """Session Memory 压缩配置"""
    min_tokens: int = 10_000              # 保留最小 token 数
    min_text_block_messages: int = 5      # 保留最小文本消息数
    max_tokens: int = 40_000             # 保留最大 token 数（硬上限）


DEFAULT_SM_COMPACT_CONFIG = SessionMemoryCompactConfig()


# ============================================================================
# 自动压缩阈值常量
# ============================================================================

AUTOCOMPACT_BUFFER_TOKENS = 13_000       # 自动压缩缓冲
WARNING_THRESHOLD_BUFFER_TOKENS = 20_000   # 警告阈值缓冲
ERROR_THRESHOLD_BUFFER_TOKENS = 20_000    # 错误阈值缓冲
MANUAL_COMPACT_BUFFER_TOKENS = 3_000      # 手动压缩缓冲
MAX_OUTPUT_TOKENS_FOR_SUMMARY = 20_000   # 摘要输出预留
MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3  # 最大连续失败次数


# ============================================================================
# Compaction 结果类型
# ============================================================================

@dataclass
class CompactBoundaryMetadata:
    """压缩边界元数据"""
    preserved_segment: Optional[Dict[str, str]] = None  # { headUuid, anchorUuid, tailUuid }
    pre_compact_discovered_tools: Optional[List[str]] = None


@dataclass
class CompactionResult:
    """
    压缩结果

    参考 Claude Code CLI CompactionResult 接口
    """
    boundary_marker: "SystemMessage"       # 压缩边界消息
    summary_messages: List["UserMessage"]  # 摘要消息列表
    attachments: List["AttachmentMessage"]  # 附件列表
    hook_results: List["HookResultMessage"]  # Hook 结果列表
    messages_to_keep: Optional[List["Message"]] = None  # 保留的消息
    user_display_message: Optional[str] = None  # 用户显示消息
    pre_compact_token_count: Optional[int] = None  # 压缩前 token 数
    post_compact_token_count: Optional[int] = None  # 压缩后 token 数
    true_post_compact_token_count: Optional[int] = None  # 真实压缩后 token 数
    compaction_usage: Optional[TokenUsage] = None  # 压缩 API 使用量


@dataclass
class MicrocompactResult:
    """微压缩结果"""
    messages: List["Message"]  # 处理后的消息
    compaction_info: Optional[Dict[str, Any]] = None  # 额外压缩信息


@dataclass
class AutoCompactResult:
    """自动压缩结果"""
    was_compacted: bool
    compaction_result: Optional[CompactionResult] = None
    consecutive_failures: int = 0


@dataclass
class AutoCompactTrackingState:
    """
    自动压缩跟踪状态

    参考 Claude Code CLI AutoCompactTrackingState
    """
    compacted: bool = False
    turn_counter: int = 0
    turn_id: str = ""                    # 每轮唯一 ID
    consecutive_failures: int = 0         # 连续失败次数


# ============================================================================
# 消息类型（简化版，对应 Claude Code CLI Message 类型）
# ============================================================================

@dataclass
class Message:
    """
    消息基类（简化版）

    实际使用时使用 langchain_core.messages 中的消息类型
    """
    type: str                            # 消息类型: human, ai, system, tool
    content: str | List[Dict[str, Any]]  # 消息内容
    uuid: Optional[str] = None           # 唯一标识
    message_id: Optional[str] = None     # API 消息 ID（用于合并流式分块）
    timestamp: Optional[datetime] = None
    additional_kwargs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SystemMessage(Message):
    """系统消息"""
    type: str = "system"


@dataclass
class UserMessage(Message):
    """用户消息"""
    type: str = "human"
    is_meta: bool = False
    is_compact_summary: bool = False
    is_visible_in_transcript_only: bool = False


@dataclass
class AssistantMessage(Message):
    """助手消息"""
    type: str = "ai"
    tool_calls: Optional[List[Dict[str, Any]]] = None
    is_api_error_message: bool = False


@dataclass
class ToolMessage(Message):
    """工具消息"""
    type: str = "tool"
    tool_call_id: Optional[str] = None


@dataclass
class HookResultMessage(Message):
    """Hook 结果消息"""
    type: str = "hook_result"


@dataclass
class AttachmentMessage(Message):
    """附件消息"""
    type: str = "attachment"
    attachment: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# 错误类型
# ============================================================================

class CompactError(Exception):
    """压缩相关错误基类"""
    pass


class NotEnoughMessagesError(CompactError):
    """消息不足错误"""
    pass


class PromptTooLongError(CompactError):
    """上下文太长错误"""
    pass


class UserAbortError(CompactError):
    """用户中止错误"""
    pass


class IncompleteResponseError(CompactError):
    """不完整响应错误"""
    pass


# ============================================================================
# Hook 相关类型
# ============================================================================

@dataclass
class HookResult:
    """Hook 执行结果"""
    new_custom_instructions: Optional[str] = None
    user_display_message: Optional[str] = None


# ============================================================================
# 压缩触发类型
# ============================================================================

CompactTrigger = Literal["auto", "manual"]


# ============================================================================
# 部分压缩方向
# ============================================================================

PartialCompactDirection = Literal["from", "up_to"]
