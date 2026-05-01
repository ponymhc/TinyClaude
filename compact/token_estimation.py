"""
Token 估算模块 - 与 Session 集成

参考 Claude Code CLI: services/tokenEstimation.ts

注意：在 TinyClaude 中，token 数通过 API 响应获取并存储在 SessionState 中。
这里的函数主要用于需要估算的场景（如判断是否触发压缩）。

主要使用 SessionState.total_tokens 而非估算：
- SessionState.total_tokens: API 返回的实际 token 数
- 估算仅用于：
  1. 压缩前的初步判断
  2. 没有 SessionState 可用时
"""

from typing import List, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from session.session import SessionState


# ============================================================================
# Token 估算（用于没有 API 返回时的场景）
# ============================================================================

BYTES_PER_TOKEN = 4  # 约 4 字符/token


def rough_token_count_estimation(text: str) -> int:
    """
    粗略估算文本 token 数

    Args:
        text: 文本内容

    Returns:
        估算的 token 数
    """
    if not text:
        return 0
    return max(1, len(text) // BYTES_PER_TOKEN)


def estimate_message_tokens(messages: List[Any]) -> int:
    """
    估算消息列表的 token 数

    注意：这是粗略估算，仅在没有 API 返回时使用。
    优先使用 SessionState.total_tokens。

    Args:
        messages: 消息列表

    Returns:
        估算的 token 数
    """
    from langchain_core.messages import BaseMessage

    total_tokens = 0

    for message in messages:
        if not isinstance(message, BaseMessage):
            continue

        content = getattr(message, "content", None)
        if content is None:
            continue

        # 字符串内容
        if isinstance(content, str):
            total_tokens += rough_token_count_estimation(content)
            continue

        # 列表内容（多模态消息）
        if not isinstance(content, list):
            continue

        for block in content:
            if not isinstance(block, dict):
                continue

            block_type = block.get("type")

            if block_type == "text":
                total_tokens += rough_token_count_estimation(block.get("text", ""))

            elif block_type == "tool_result":
                result_content = block.get("content", "")
                if isinstance(result_content, str):
                    total_tokens += rough_token_count_estimation(result_content)

            elif block_type in ("image", "document"):
                # 图片/文档约 2000 tokens
                total_tokens += 2000

    # 保守估算：乘以 4/3
    return int(total_tokens * 4 / 3)


def estimate_tokens_for_messages(messages: List[Any]) -> int:
    """
    估算消息列表的 token 数（别名）

    Args:
        messages: 消息列表

    Returns:
        估算的 token 数
    """
    return estimate_message_tokens(messages)


# ============================================================================
# Session State 集成
# ============================================================================

def get_session_total_tokens(session_state: "SessionState") -> int:
    """
    从 SessionState 获取实际 token 数

    这是优先使用的方式，返回 API 返回的实际 token 统计。

    Args:
        session_state: SessionState 实例

    Returns:
        总 token 数
    """
    return getattr(session_state, "total_tokens", 0)


def get_session_token_usage(session_state: "SessionState") -> dict:
    """
    从 SessionState 获取完整的 token 使用统计

    Args:
        session_state: SessionState 实例

    Returns:
        dict with total, input, output tokens
    """
    return {
        "total": get_session_total_tokens(session_state),
        "input": getattr(session_state, "input_tokens", 0),
        "output": getattr(session_state, "output_tokens", 0),
    }


def calculate_tool_result_tokens(block: dict) -> int:
    """
    计算工具结果块的 token 数

    Args:
        block: 工具结果块

    Returns:
        token 数
    """
    content = block.get("content", "")
    if isinstance(content, str):
        return rough_token_count_estimation(content)
    return 0
