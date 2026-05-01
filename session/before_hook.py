"""
Agent 循环前置钩子 - 处理 agent 执行前的逻辑

职责：
- 记忆上下文加载
- Token 预算警告
- 轮次限制检查
"""

import asyncio
from typing import List, Optional, Any, TYPE_CHECKING, AsyncGenerator
from utils.token import TokenTracker, TokenBudget

if TYPE_CHECKING:
    from session.session import SessionState


class BeforeHook:
    """
    Agent 循环前置钩子
    
    使用方式：
        async for event in session.before_hook.process(state):
            yield event
    """

    def __init__(
        self,
        token_tracker: Optional[TokenTracker] = None,
        token_budget: Optional[TokenBudget] = None,
    ):
        self.token_tracker = token_tracker
        self.token_budget = token_budget

    async def load_memdir_context(self) -> List[dict]:
        """
        加载记忆上下文（插入到 system prompt 后）
        
        Returns:
            待注入的消息列表，每个元素格式：
            {"role": "user", "content": str, "is_meta": True}
        """
        # 延迟导入避免循环依赖
        from memdir.load_all_memories import load_all_memories_for_context
        from utils.skill_loader import load_skills_context
        
        messages = []
        try:
            memory_messages = await load_all_memories_for_context()
            for msg in memory_messages:
                messages.append({
                    "role": "user",
                    "content": msg.content,
                    "is_meta": True
                })
        except Exception:
            pass  # 静默失败，不阻塞主流程
        
        try:
            skill_messages = load_skills_context()
            for msg in skill_messages:
                messages.append({
                    "role": "user",
                    "content": msg.content,
                    "is_meta": True
                })
        except Exception:
            pass  # 静默失败，不阻塞主流程
        
        return messages

    async def process(self, state: "SessionState") -> AsyncGenerator[List[dict[str, Any]], None]:
        """
        执行前置检查
        
        Args:
            state: 会话状态
            
        Yields:
            事件列表（可能是警告事件或空列表）
        """
        events = []

        # 记忆上下文加载
        memory_events = await self._load_memories(state)
        events.extend(memory_events)

        # Token 预算警告
        events.extend(self._check_token_budget(state))

        # 轮次限制检查
        if self._is_turn_limit_reached(state):
            events.append({
                "type": "done",
                "content": "",
                "reason": "max_turns",
                "turn_count": state.turn_count
            })

        if events:
            yield events

    async def _load_memories(self, state: "SessionState") -> List[dict[str, Any]]:
        """加载记忆上下文"""
        events = []
        try:
            memory_messages = await self.load_memdir_context()
            if memory_messages:
                events.append({
                    "type": "memory_context",
                    "messages": memory_messages
                })
        except Exception:
            pass
        return events

    def _check_token_budget(self, state: "SessionState") -> List[dict[str, Any]]:
        """检查 token 预算并生成警告"""
        events = []
        if not self.token_tracker or not self.token_budget:
            return events

        current_usage = self.token_tracker.get_usage()
        if self.token_budget.needs_compact_usage(current_usage):
            events.append({
                "type": "warning",
                "content": f"Token 使用量已达 {current_usage.total}/{self.token_budget.max_tokens}，"
                           f"建议手动执行 /compact 或等待后续自动压缩。"
            })
        elif self.token_budget.is_warning_usage(current_usage):
            events.append({
                "type": "warning",
                "content": f"Token 使用量较高: {current_usage.total}/{self.token_budget.max_tokens} "
                           f"({self.token_budget.usage_ratio(current_usage.total):.1%})"
                           f" (input: {current_usage.input_tokens}, output: {current_usage.output_tokens})"
            })
        return events

    def _is_turn_limit_reached(self, state: "SessionState") -> bool:
        """检查是否达到轮次限制"""
        return state.max_turns is not None and state.turn_count >= state.max_turns

    def should_stop(self, state: "SessionState") -> bool:
        """检查是否应该停止对话"""
        return self._is_turn_limit_reached(state)
