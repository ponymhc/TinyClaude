"""
消息处理模块

参考 Claude Code CLI: services/utils/messages.ts

提供消息创建、转换和检查的工具函数
"""

from typing import List, Optional, Any, Dict, Union
from dataclasses import dataclass, field
from datetime import datetime
import uuid

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
    ToolMessage,
)


# ============================================================================
# 消息创建函数
# ============================================================================

def create_user_message(
    content: str,
    is_compact_summary: bool = False,
    is_visible_in_transcript_only: bool = False,
    is_meta: bool = False,
    additional_kwargs: Optional[Dict[str, Any]] = None,
) -> HumanMessage:
    """
    创建用户消息

    参考 Claude Code CLI: createUserMessage()

    Args:
        content: 消息内容
        is_compact_summary: 是否为压缩摘要
        is_visible_in_transcript_only: 是否只显示在 transcript 中
        is_meta: 是否为元数据消息
        additional_kwargs: 额外参数

    Returns:
        HumanMessage
    """
    kwargs = additional_kwargs or {}
    kwargs["is_compact_summary"] = is_compact_summary
    kwargs["is_visible_in_transcript_only"] = is_visible_in_transcript_only

    return HumanMessage(
        content=content,
        additional_kwargs=kwargs,
        id=str(uuid.uuid4()),
    )


def create_compact_boundary_message(
    compact_type: str,  # "auto" or "manual"
    pre_compact_token_count: int,
    last_message_uuid: Optional[str] = None,
    custom_instructions: Optional[str] = None,
    messages_summarized: Optional[int] = None,
) -> SystemMessage:
    """
    创建压缩边界消息

    参考 Claude Code CLI: createCompactBoundaryMessage()

    Args:
        compact_type: 压缩类型 "auto" 或 "manual"
        pre_compact_token_count: 压缩前 token 数
        last_message_uuid: 最后一条消息的 UUID
        custom_instructions: 自定义指令
        messages_summarized: 被总结的消息数

    Returns:
        SystemMessage
    """
    content = "[Previous conversation has been compressed]"

    additional_kwargs = {
        "type": "compact_boundary",
        "compact_type": compact_type,
        "pre_compact_token_count": pre_compact_token_count,
        "compact_timestamp": datetime.now().isoformat(),
    }

    if last_message_uuid:
        additional_kwargs["last_message_uuid"] = last_message_uuid

    if custom_instructions:
        additional_kwargs["custom_instructions"] = custom_instructions

    if messages_summarized is not None:
        additional_kwargs["messages_summarized"] = messages_summarized

    return SystemMessage(
        content=content,
        additional_kwargs=additional_kwargs,
        id=str(uuid.uuid4()),
    )


# ============================================================================
# 消息检查函数
# ============================================================================

def is_compact_boundary_message(message: BaseMessage) -> bool:
    """
    检查消息是否为压缩边界消息

    参考 Claude Code CLI: isCompactBoundaryMessage()

    Args:
        message: 消息

    Returns:
        是否为压缩边界消息
    """
    # 检查 additional_kwargs
    additional_kwargs = getattr(message, "additional_kwargs", {}) or {}
    if additional_kwargs.get("type") == "compact_boundary":
        return True

    # 检查内容
    content = getattr(message, "content", "") or ""
    if isinstance(content, str) and "[Previous conversation has been compressed]" in content:
        return True

    return False


def has_text_blocks(message: Any) -> bool:
    """
    检查消息是否包含文本内容块

    参考 Claude Code CLI: hasTextBlocks()

    Args:
        message: 消息

    Returns:
        是否包含文本内容
    """
    msg_type = getattr(message, "type", None)

    if msg_type == "ai" or isinstance(message, AIMessage):
        content = getattr(message, "content", None)
        if isinstance(content, list):
            return any(block.get("type") == "text" for block in content if isinstance(block, dict))
        return False

    if msg_type == "human" or msg_type == "user" or isinstance(message, HumanMessage):
        content = getattr(message, "content", None)
        if isinstance(content, str):
            return len(content) > 0
        if isinstance(content, list):
            return any(block.get("type") == "text" for block in content if isinstance(block, dict))
        return False

    return False


def get_message_id(message: Any) -> Optional[str]:
    """
    获取消息的 message_id（用于合并流式分块）

    Args:
        message: 消息

    Returns:
        message_id 或 None
    """
    additional_kwargs = getattr(message, "additional_kwargs", {}) or {}
    return additional_kwargs.get("message_id") or getattr(message, "message_id", None)


def get_message_uuid(message: Any) -> Optional[str]:
    """
    获取消息的 uuid

    Args:
        message: 消息

    Returns:
        uuid 或 None
    """
    return getattr(message, "id", None) or getattr(message, "uuid", None)


# ============================================================================
# 消息转换函数
# ============================================================================

def get_last_assistant_message(messages: List[BaseMessage]) -> Optional[AIMessage]:
    """
    获取最后一条 assistant 消息

    Args:
        messages: 消息列表

    Returns:
        最后一条 AIMessage 或 None
    """
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return message
    return None


def get_messages_after_boundary(messages: List[BaseMessage]) -> List[BaseMessage]:
    """
    获取压缩边界之后的消息

    参考 Claude Code CLI: getMessagesAfterCompactBoundary()

    Args:
        messages: 消息列表

    Returns:
        边界后的消息列表
    """
    result = []
    found_boundary = False

    for message in messages:
        if is_compact_boundary_message(message):
            found_boundary = True
            continue
        if found_boundary:
            result.append(message)

    return result


def get_assistant_message_text(message: AIMessage) -> Optional[str]:
    """
    获取 assistant 消息中的文本内容

    Args:
        message: AIMessage

    Returns:
        文本内容或 None
    """
    content = getattr(message, "content", None)
    if content is None:
        return None

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
        return "\n".join(texts) if texts else None

    return None


# ============================================================================
# 消息合并函数（用于 API 调用）
# ============================================================================

def normalize_messages_for_api(messages: List[BaseMessage]) -> List[Dict[str, Any]]:
    """
    将消息列表标准化为 API 格式

    参考 Claude Code CLI: normalizeMessagesForAPI()

    这个函数处理流式输出产生的分块消息，
    将同一 message.id 的多个消息块合并。

    Args:
        messages: 消息列表

    Returns:
        标准化后的消息列表
    """
    result = []
    pending_blocks = {}

    for message in messages:
        msg_id = get_message_id(message)
        msg_type = getattr(message, "type", "unknown")

        if msg_type == "system":
            result.append({
                "role": "system",
                "content": getattr(message, "content", ""),
            })
        elif msg_type == "human" or msg_type == "user":
            result.append({
                "role": "user",
                "content": getattr(message, "content", ""),
            })
        elif msg_type == "ai" or msg_type == "assistant":
            content = getattr(message, "content", None)
            if isinstance(content, str):
                result.append({
                    "role": "assistant",
                    "content": content,
                })
            elif isinstance(content, list):
                # 暂不处理复杂内容
                result.append({
                    "role": "assistant",
                    "content": str(content),
                })
        elif msg_type == "tool":
            result.append({
                "role": "user",
                "content": getattr(message, "content", ""),
            })

    return result


# ============================================================================
# 消息链重建
# ============================================================================

def build_post_compact_messages(
    boundary_marker: SystemMessage,
    summary_messages: List[HumanMessage],
    messages_to_keep: Optional[List[BaseMessage]] = None,
    attachments: Optional[List[Any]] = None,
    hook_results: Optional[List[Any]] = None,
) -> List[BaseMessage]:
    """
    构建压缩后的消息列表

    参考 Claude Code CLI: buildPostCompactMessages()

    顺序: boundaryMarker, summaryMessages, messagesToKeep, attachments, hookResults

    Args:
        boundary_marker: 压缩边界消息
        summary_messages: 摘要消息列表
        messages_to_keep: 保留的消息列表
        attachments: 附件列表
        hook_results: Hook 结果列表

    Returns:
        压缩后的消息列表
    """
    result: List[BaseMessage] = [boundary_marker]
    result.extend(summary_messages)

    if messages_to_keep:
        result.extend(messages_to_keep)

    if attachments:
        result.extend(attachments)

    if hook_results:
        result.extend(hook_results)

    return result
