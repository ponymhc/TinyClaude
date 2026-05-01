"""
Token 管理模块（基于 litellm，直接支持 LangChain 消息）
"""

from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from xxlimited import Str
from litellm import token_counter
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage, ToolMessage


@dataclass
class TokenUsage:
    """Token 使用统计"""
    total: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            total=self.total + other.total,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


class TokenCounter:
    
    @staticmethod
    def _to_litellm_dict(msg: BaseMessage) -> Dict[str, Any]:

        if isinstance(msg, SystemMessage):
            return {"role": "system", "content": msg.content}
        if isinstance(msg, HumanMessage):
            return {"role": "user", "content": msg.content}
        if isinstance(msg, AIMessage):
            result = {"role": "assistant", "content": msg.content or ""}
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                tool_calls = []
                for tc in msg.tool_calls:
                    if isinstance(tc, dict):
                        tool_calls.append({
                            "id": tc.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": tc.get("name", ""),
                                "arguments": tc.get("args", {})
                            }
                        })
                    else:
                        tool_calls.append({
                            "id": getattr(tc, "id", ""),
                            "type": "function",
                            "function": {
                                "name": getattr(tc, "name", ""),
                                "arguments": getattr(tc, "args", {})
                            }
                        })
                result["tool_calls"] = tool_calls
            return result
        if isinstance(msg, ToolMessage):
            return {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id,
                        "content": msg.content,
                        "is_error": getattr(msg, "is_error", False),
                    }
                ]
            }
        return {"role": "unknown", "content": str(msg.content)}
    
    @staticmethod
    def _normalize_messages(messages: List[Any]) -> List[Dict[str, Any]]:
        normalized = []
        for msg in messages:
            if isinstance(msg, dict):
                normalized.append(msg)
            elif isinstance(msg, BaseMessage):
                normalized.append(TokenCounter._to_litellm_dict(msg))
            else:
                normalized.append({"role": "user", "content": str(msg)})
        return normalized
    
    def count(self, messages: List[BaseMessage]) -> int:
        return token_counter(messages=self._normalize_messages(messages))

    def count_text(self, text: Str) -> int:
        return self.count(messages=[HumanMessage(content=text)])

    def create_tracker(self) -> "TokenTracker":
        return TokenTracker(self)


class TokenTracker:
    """
    Token 追踪器，支持 input/output 分类统计
    """

    def __init__(self, counter: TokenCounter):
        self._counter = counter
        self._usage = TokenUsage()

    def _is_input_message(self, message: BaseMessage) -> bool:
        """判断是否为 input 类消息"""
        return isinstance(message, (HumanMessage, SystemMessage))

    def add_messages(self, messages: List[BaseMessage]) -> TokenUsage:
        """添加消息列表，自动分类 input/output"""
        if not messages:
            return TokenUsage()

        input_msgs = [m for m in messages if self._is_input_message(m)]
        output_msgs = [m for m in messages if not self._is_input_message(m)]

        input_added = self._counter.count(input_msgs) if input_msgs else 0
        output_added = self._counter.count(output_msgs) if output_msgs else 0

        self._usage.input_tokens += input_added
        self._usage.output_tokens += output_added
        self._usage.total += input_added + output_added

        return TokenUsage(
            total=input_added + output_added,
            input_tokens=input_added,
            output_tokens=output_added,
        )

    def add_message(self, message: BaseMessage) -> int:
        """添加单条消息"""
        added = self._counter.count([message])
        self._usage.total += added
        if self._is_input_message(message):
            self._usage.input_tokens += added
        else:
            self._usage.output_tokens += added
        return added

    def add_input_messages(self, messages: List[BaseMessage]) -> int:
        """添加 input 类消息（Human, System）"""
        if not messages:
            return 0
        added = self._counter.count(messages)
        self._usage.input_tokens += added
        self._usage.total += added
        return added

    def add_output_messages(self, messages: List[BaseMessage]) -> int:
        """添加 output 类消息（AI, Tool）"""
        if not messages:
            return 0
        added = self._counter.count(messages)
        self._usage.output_tokens += added
        self._usage.total += added
        return added

    def reset(self) -> None:
        """重置统计"""
        self._usage = TokenUsage()

    def get_usage(self) -> TokenUsage:
        """获取使用统计"""
        return self._usage


class TokenBudget:
    """Token 预算管理器"""

    def __init__(
        self,
        max_tokens: int = 200_000,
        warning_threshold: float = 0.8,
        auto_compact_threshold: float = 0.9,
    ):
        self.max_tokens = max_tokens
        self.warning_threshold = warning_threshold
        self.auto_compact_threshold = auto_compact_threshold

    def is_warning(self, usage: int) -> bool:
        return usage >= self.max_tokens * self.warning_threshold

    def needs_compact(self, usage: int) -> bool:
        return usage >= self.max_tokens * self.auto_compact_threshold

    def remaining(self, usage: int) -> int:
        return max(0, self.max_tokens - usage)

    def usage_ratio(self, usage: int) -> float:
        return usage / self.max_tokens

    def is_warning_usage(self, token_usage: TokenUsage) -> bool:
        """检查 TokenUsage 是否达到警告阈值"""
        return self.is_warning(token_usage.total)

    def needs_compact_usage(self, token_usage: TokenUsage) -> bool:
        """检查 TokenUsage 是否需要压缩"""
        return self.needs_compact(token_usage.total)


if __name__ == "__main__":
    from langchain_core.messages import HumanMessage, AIMessage

    counter = TokenCounter()
    msgs = [HumanMessage(content="你好，请帮我算一下 token")]
    print(f"token 数: {counter.count(msgs)}")

    tracker = counter.create_tracker()
    usage = tracker.add_messages(msgs)
    print(f"追踪器总 token: {tracker.get_usage().total}")
    print(f"input tokens: {tracker.get_usage().input_tokens}")
    print(f"output tokens: {tracker.get_usage().output_tokens}")

    # 测试 output 消息
    ai_msgs = [AIMessage(content="这是一个回复")]
    usage = tracker.add_messages(ai_msgs)
    print(f"\n添加 AI 消息后:")
    print(f"总 token: {tracker.get_usage().total}")
    print(f"input tokens: {tracker.get_usage().input_tokens}")
    print(f"output tokens: {tracker.get_usage().output_tokens}")