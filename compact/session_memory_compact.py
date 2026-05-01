"""
Session Memory 压缩模块

参考 Claude Code CLI: services/compact/sessionMemoryCompact.ts

使用 Session Memory 文件作为压缩摘要，替代传统的 LLM 摘要生成。

核心流程：
1. 检查是否使用 Session Memory 压缩
2. 读取 Session Memory 文件内容
3. 计算保留哪些消息（基于 lastSummarizedIndex + 配置的 minTokens/minTextBlockMessages）
4. 创建压缩边界消息 + Session Memory 摘要

Token 获取方式：
- 优先使用 SessionState.total_tokens（API 返回的实际值）
- 估算仅用于没有 SessionState 的场景
"""

import logging
from typing import List, Any, Optional, Set, TYPE_CHECKING

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage

from .config import get_sm_compact_config
from .token_estimation import estimate_message_tokens
from .messages import (
    is_compact_boundary_message,
    create_compact_boundary_message,
    create_user_message,
    get_message_id,
    get_message_uuid,
)

if TYPE_CHECKING:
    from session.session import SessionState


logger = logging.getLogger(__name__)


# ============================================================================
# 辅助函数
# ============================================================================

def _get_tool_result_ids(message: Any) -> List[str]:
    """
    获取消息中的 tool_result IDs

    参考 Claude Code CLI: getToolResultIds()

    Args:
        message: 消息

    Returns:
        tool_result IDs 列表
    """
    msg_type = getattr(message, "type", None)
    if msg_type not in ("human", "user"):
        return []

    content = getattr(message, "content", None)
    if not isinstance(content, list):
        return []

    return [
        block.get("tool_use_id", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]


def _has_tool_use_with_ids(message: Any, tool_use_ids: Set[str]) -> bool:
    """
    检查消息是否包含指定 ID 的 tool_use

    参考 Claude Code CLI: hasToolUseWithIds()

    Args:
        message: 消息
        tool_use_ids: 需要检查的 tool_use IDs

    Returns:
        是否包含
    """
    msg_type = getattr(message, "type", None)
    if msg_type not in ("ai", "assistant"):
        return False

    content = getattr(message, "content", None)
    if not isinstance(content, list):
        return False

    return any(
        block.get("type") == "tool_use" and block.get("id") in tool_use_ids
        for block in content
        if isinstance(block, dict)
    )


def _has_text_blocks(message: Any) -> bool:
    """
    检查消息是否包含文本内容

    参考 Claude Code CLI: hasTextBlocks()

    Args:
        message: 消息

    Returns:
        是否包含文本
    """
    msg_type = getattr(message, "type", None)

    if msg_type in ("ai", "assistant"):
        content = getattr(message, "content", None)
        if isinstance(content, str):
            return len(content) > 0
        if isinstance(content, list):
            return any(
                block.get("type") == "text"
                for block in content
                if isinstance(block, dict)
            )

    if msg_type in ("human", "user"):
        content = getattr(message, "content", None)
        if isinstance(content, str):
            return len(content) > 0
        if isinstance(content, list):
            return any(
                block.get("type") == "text"
                for block in content
                if isinstance(block, dict)
            )

    return False


# ============================================================================
# API 不变量保持
# ============================================================================

def adjust_index_to_preserve_api_invariants(
    messages: List[Any],
    start_index: int,
) -> int:
    """
    调整起始索引，确保不拆分 tool_use/tool_result 对和 thinking blocks

    参考 Claude Code CLI: adjustIndexToPreserveAPIInvariants()

    Step 1: 处理 tool_use/tool_result 对
    如果保留的消息中有 tool_result，需要包含对应的 tool_use 消息。

    Step 2: 处理 thinking blocks
    如果保留的 assistant 消息有共享的 message.id，需要包含之前的 thinking blocks。
    Claude Code CLI 处理流式输出产生的分块消息：
      Index N:   assistant, message.id: X, content: [thinking]
      Index N+1: assistant, message.id: X, content: [tool_use]
    如果 startIndex = N+1，需要包含 N 的 thinking block 才能正确合并。

    Args:
        messages: 消息列表
        start_index: 起始索引

    Returns:
        调整后的索引
    """
    if start_index <= 0 or start_index >= len(messages):
        return start_index

    adjusted_index = start_index

    # Step 1: 处理 tool_use/tool_result 对
    all_tool_result_ids: List[str] = []
    for i in range(start_index, len(messages)):
        all_tool_result_ids.extend(_get_tool_result_ids(messages[i]))

    if all_tool_result_ids:
        needed_tool_use_ids = set(all_tool_result_ids)

        for i in range(adjusted_index - 1, -1, -1):
            if _has_tool_use_with_ids(messages[i], needed_tool_use_ids):
                adjusted_index = i
                content = getattr(messages[i], "content", None)
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tool_id = block.get("id", "")
                            if tool_id in needed_tool_use_ids:
                                needed_tool_use_ids.discard(tool_id)

    # Step 2: 处理共享 message.id 的 thinking blocks
    if adjusted_index > 0:
        message_ids_in_kept_range: Set[str] = set()
        for i in range(adjusted_index, len(messages)):
            msg_id = get_message_id(messages[i])
            if msg_id:
                message_ids_in_kept_range.add(msg_id)

        for i in range(adjusted_index - 1, -1, -1):
            msg_id = get_message_id(messages[i])
            if msg_id and msg_id in message_ids_in_kept_range:
                adjusted_index = i

    return adjusted_index


# ============================================================================
# 消息保留计算
# ============================================================================

def calculate_messages_to_keep_index(
    messages: List[Any],
    last_summarized_index: int,
) -> int:
    """
    计算压缩后保留的消息起始索引

    参考 Claude Code CLI: calculateMessagesToKeepIndex()

    从 lastSummarizedIndex 开始，扩展直到满足：
    - 至少 config.minTokens tokens
    - 至少 config.minTextBlockMessages 条文本消息
    - 不超过 config.maxTokens tokens

    Args:
        messages: 消息列表
        last_summarized_index: 最后总结的索引

    Returns:
        保留消息的起始索引
    """
    config = get_sm_compact_config()

    if len(messages) == 0:
        return 0

    # 从 lastSummarizedIndex 之后开始
    start_index = last_summarized_index + 1 if last_summarized_index >= 0 else 0

    # 计算当前 token 数和文本消息数
    total_tokens = 0
    text_block_count = 0
    for i in range(start_index, len(messages)):
        msg = messages[i]
        total_tokens += estimate_message_tokens([msg])
        if _has_text_blocks(msg):
            text_block_count += 1

    # 检查是否已达上限
    if total_tokens >= config.max_tokens:
        return adjust_index_to_preserve_api_invariants(messages, start_index)

    # 检查是否已满足最小要求
    if (
        total_tokens >= config.min_tokens
        and text_block_count >= config.min_text_block_messages
    ):
        return adjust_index_to_preserve_api_invariants(messages, start_index)

    # 向前扩展直到满足条件或达到上限
    # 地板：最后一个压缩边界之后
    floor = 0
    for i in range(len(messages) - 1, -1, -1):
        if is_compact_boundary_message(messages[i]):
            floor = i + 1
            break

    for i in range(start_index - 1, max(floor - 1, -1), -1):
        msg = messages[i]
        total_tokens += estimate_message_tokens([msg])
        if _has_text_blocks(msg):
            text_block_count += 1
        start_index = i

        # 达到上限则停止
        if total_tokens >= config.max_tokens:
            break

        # 满足两个最小要求则停止
        if (
            total_tokens >= config.min_tokens
            and text_block_count >= config.min_text_block_messages
        ):
            break

    return adjust_index_to_preserve_api_invariants(messages, start_index)


# ============================================================================
# Session Memory 访问
# ============================================================================

def should_use_session_memory_compaction() -> bool:
    """
    检查是否应该使用 Session Memory 压缩

    参考 Claude Code CLI: shouldUseSessionMemoryCompaction()

    必须同时满足：
    1. Session Memory 功能启用
    2. Session Memory 已初始化（有内容）

    Returns:
        是否使用 Session Memory 压缩
    """
    import os

    # 环境变量覆盖
    if os.environ.get("ENABLE_SM_COMPACT"):
        return True
    if os.environ.get("DISABLE_SM_COMPACT"):
        return False

    # 检查 Session Memory 功能
    try:
        from session.memory import (
            is_session_memory_enabled,
            is_session_memory_initialized,
            get_session_memory_content,
            is_session_memory_empty,
        )

        # 必须启用 Session Memory
        if not is_session_memory_enabled():
            return False

        # 必须已初始化
        if not is_session_memory_initialized():
            return False

        # 检查是否有实际内容
        content = get_session_memory_content()
        if content is None:
            return False

        if is_session_memory_empty(content):
            return False

        return True

    except ImportError:
        logger.warning("Session Memory 模块未导入，跳过 Session Memory 压缩")
        return False


# ============================================================================
# 压缩执行
# ============================================================================

async def try_session_memory_compaction(
    messages: List[Any],
    session_state: Optional["SessionState"] = None,
    auto_compact_threshold: Optional[int] = None,
) -> Optional[dict]:
    """
    尝试使用 Session Memory 进行压缩

    参考 Claude Code CLI: trySessionMemoryCompaction()

    处理两种场景：
    1. 正常情况：lastSummarizedMessageId 已设置，只保留该 ID 之后的消息
    2. 恢复会话：lastSummarizedMessageId 未设置但 Session Memory 有内容，
       保留所有消息但使用 Session Memory 作为摘要

    Token 获取：
    - 优先使用 session_state.total_tokens（API 返回的实际值）
    - 仅在没有 session_state 时使用估算

    Args:
        messages: 当前消息列表
        session_state: SessionState 实例（包含实际 token 统计）
        auto_compact_threshold: 可选的自动压缩阈值

    Returns:
        压缩结果字典，包含：
        - messages: 压缩后的消息列表
        - boundary_marker: 压缩边界消息
        - summary_message: 摘要消息
        - messages_to_keep: 保留的消息
        或 None 表示不能使用 Session Memory 压缩
    """
    # 检查是否使用 Session Memory 压缩
    if not should_use_session_memory_compaction():
        return None

    try:
        # 导入 Session Memory 相关函数
        from session.memory import (
            get_session_memory_content,
            get_last_summarized_index,
            is_session_memory_empty,
        )
        from session.memory.prompts import truncate_session_memory_for_compact

        # 获取 Session Memory 内容
        session_memory = await get_session_memory_content()
        if session_memory is None:
            return None

        # 检查是否为空模板
        if is_session_memory_empty(session_memory):
            return None

        # 获取最后总结的索引
        last_summarized_index = get_last_summarized_index()

        # 计算保留的消息起始索引
        start_index = calculate_messages_to_keep_index(messages, last_summarized_index)

        # 过滤掉旧的压缩边界消息
        messages_to_keep = [
            msg for msg in messages[start_index:]
            if not is_compact_boundary_message(msg)
        ]

        # 截断过长的 Session Memory
        truncated_memory, was_truncated = truncate_session_memory_for_compact(session_memory)

        # 获取压缩前 token 数（优先使用实际值）
        if session_state is not None:
            pre_compact_tokens = session_state.total_tokens
        else:
            pre_compact_tokens = estimate_message_tokens(messages)

        # 创建边界消息
        last_uuid = get_message_uuid(messages[-1]) if messages else None
        boundary_msg = create_compact_boundary_message(
            compact_type="auto",
            pre_compact_token_count=pre_compact_tokens,
            last_message_uuid=last_uuid,
        )

        # 构建摘要内容
        summary_content = _build_compact_summary_message(
            truncated_memory, was_truncated, session_memory
        )

        # 创建摘要消息
        summary_msg = create_user_message(
            content=summary_content,
            is_compact_summary=True,
            is_visible_in_transcript_only=True,
        )

        # 保留系统消息
        system_messages = [msg for msg in messages if isinstance(msg, SystemMessage)]

        # 构建压缩后的消息列表
        compacted_messages = system_messages + [boundary_msg, summary_msg] + messages_to_keep

        # 估算压缩后 token 数（由于消息减少，token 会降低）
        # 注意：这里使用估算因为压缩后的 token 需要重新计算
        post_compact_tokens = estimate_message_tokens(compacted_messages)

        # 检查阈值
        if auto_compact_threshold and post_compact_tokens >= auto_compact_threshold:
            logger.info(
                f"Session Memory 压缩后 token 数 {post_compact_tokens} "
                f"仍超过阈值 {auto_compact_threshold}，跳过"
            )
            return None

        return {
            "messages": compacted_messages,
            "boundary_marker": boundary_msg,
            "summary_message": summary_msg,
            "messages_to_keep": messages_to_keep,
            "pre_compact_token_count": pre_compact_tokens,
            "post_compact_token_count": post_compact_tokens,
            "was_truncated": was_truncated,
        }

    except Exception as e:
        logger.error(f"Session Memory 压缩失败: {e}", exc_info=True)
        return None


def _build_compact_summary_message(
    truncated_memory: str,
    was_truncated: bool,
    original_memory: str,
) -> str:
    """
    构建压缩摘要消息内容

    Args:
        truncated_memory: 截断后的 Session Memory
        was_truncated: 是否被截断
        original_memory: 原始 Session Memory

    Returns:
        摘要消息内容
    """
    content = f"""会话摘要：

{truncated_memory}"""

    if was_truncated:
        # 获取 Session Memory 文件路径
        try:
            from session.memory.paths import get_session_memory_path
            memory_path = get_session_memory_path()
            content += f"\n\n部分 Session Memory 内容因过长被截断。完整内容可查看: {memory_path}"
        except ImportError:
            content += "\n\n注意：部分 Session Memory 内容因过长被截断。"

    return content
