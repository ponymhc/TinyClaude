"""
Agent 循环后置钩子 - 处理 agent 执行完成后的逻辑

包含：
- 消息持久化
- Token 计数更新
- 事件生成
- 后台自动记忆提取
- 后台 Session Memory 提取
"""

from __future__ import annotations
import asyncio
import logging
from typing import TYPE_CHECKING, List, AsyncGenerator, Optional, Any

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage, SystemMessage

from session.storage import SessionStorage, StoredMessage
from utils.token import TokenTracker
from extract_memories import ExtractMemoriesRunner
from session.memory import SessionMemoryRunner

if TYPE_CHECKING:
    from session.session import SessionState
    from agent.agent_factory import AgentLoop


class AfterHook:
    """
    Agent 循环后置钩子

    使用方式：
        session.after_hook.process(state, all_messages, history, full_response, agent)
    """

    def __init__(
        self,
        storage: Optional[SessionStorage] = None,
        token_tracker: Optional[TokenTracker] = None,
    ):
        self.storage = storage
        self.token_tracker = token_tracker
        self._io_lock = asyncio.Lock()
        # 初始化长期记忆提取器
        self._memory_extractor = ExtractMemoriesRunner()
        # 初始化 Session Memory 提取器（传入 storage）
        self._session_memory_runner = SessionMemoryRunner(storage=storage)

    def _message_to_stored(self, message: BaseMessage, turn_id: int) -> StoredMessage:
        """将 LangChain 消息转换为存储格式"""
        if isinstance(message, HumanMessage):
            return StoredMessage(
                type="human", 
                content=message.content, 
                turn_id=turn_id,
                additional_kwargs=message.additional_kwargs,
            )
        elif isinstance(message, AIMessage):
            return StoredMessage(
                type="ai",
                content=message.content,
                turn_id=turn_id,
                tool_calls=[
                    {"name": tc.get("name"), "args": tc.get("args"), "id": tc.get("id")}
                    for tc in getattr(message, "tool_calls", []) or []
                ],
                additional_kwargs=message.additional_kwargs,
            )
        elif isinstance(message, ToolMessage):
            return StoredMessage(
                type="tool",
                content=message.content,
                turn_id=turn_id,
                tool_call_id=message.tool_call_id,
                additional_kwargs=message.additional_kwargs,
            )
        else:
            return StoredMessage(
                type="other", 
                content=str(message.content), 
                turn_id=turn_id,
                additional_kwargs=message.additional_kwargs,
            )

    def _update_state_memory(
        self,
        state: "SessionState",
        all_messages: List[BaseMessage],
        history: List[BaseMessage],
    ) -> None:
        """
        仅更新内存中的消息列表和 token 计数，不执行 I/O
        """
        if not state:
            return

        # 找出新增的消息（从 history 长度+1 开始）
        new_start_index = len(history) + 1
        new_messages = all_messages[new_start_index:]

        # 更新内存中的消息列表
        state.messages = all_messages

        # 更新 token 计数（增量）
        if self.token_tracker and new_messages:
            self.token_tracker.add_output_messages(new_messages)
            usage = self.token_tracker.get_usage()
            state.total_tokens = usage.total
            state.input_tokens = usage.input_tokens
            state.output_tokens = usage.output_tokens

    async def _persist_io(
        self,
        state: "SessionState",
        all_messages: List[BaseMessage],
        history: List[BaseMessage],
    ) -> None:
        """
        后台执行 I/O 持久化：保存消息和 token 统计
        使用会话锁，确保该会话的 I/O 操作串行执行
        """
        async with self._io_lock:
            try:
                new_start_index = len(history) + 1
                new_messages = all_messages[new_start_index:]
                # 新的 turn_id 是 state.turn_count
                new_turn_id = state.turn_count

                if self.storage:
                    for msg in new_messages:
                        stored = self._message_to_stored(msg, turn_id=new_turn_id)
                        await self.storage.save_message(state.session_id, stored)
                    if self.token_tracker:
                        await self.storage.update_token_stats(
                            state.session_id,
                            self.token_tracker.get_usage()
                        )
            except Exception as e:
                logging.getLogger(__name__).error(
                    f"Background I/O failed for session {state.session_id}: {e}",
                    exc_info=True
                )

    def generate_end_events(
        self,
        state: "SessionState",
        full_response: str,
    ) -> List[dict]:
        """
        生成 agent 循环结束后的结束事件

        Args:
            state: 会话状态
            full_response: 完整的 AI 回复内容

        Returns:
            结束事件列表
        """
        events = [
            {"type": "turn_end", "turn": state.turn_count},
            {"type": "done", "content": full_response, "turn_count": state.turn_count},
        ]
        return events

    async def process(
        self,
        state: SessionState,
        all_messages: List[BaseMessage],
        history: List[BaseMessage],
        full_response: str,
    ) -> AsyncGenerator[dict, None]:
        """
        执行 agent 循环后的所有后置处理

        Args:
            state: 会话状态
            all_messages: 完整消息列表
            history: 历史消息列表
            full_response: 完整 AI 回复
            agent: AgentLoop 实例（用于 fork 子代理）

        Yields:
            turn_end 和 done 事件
        """
        # 1. 同步内存更新（立即完成）
        self._update_state_memory(state, all_messages, history)

        # 2. 启动后台 I/O 持久化任务（不等待）
        asyncio.create_task(self._persist_io(state, all_messages, history))

        # 3. 启动后台长期记忆提取任务
        if self._memory_extractor:
            self._memory_extractor.set_session_id(state.session_id)
            
            def on_memory_saved(msg: SystemMessage) -> None:
                logging.getLogger(__name__).info(f"Memory extraction completed: {msg.content}")

            asyncio.create_task(
                self._memory_extractor.execute(all_messages, on_memory_saved)
            )

        # 4. 启动后台 Session Memory 提取任务（使用 fork_agent）
        if self._session_memory_runner:
            self._session_memory_runner.set_session_id(state.session_id)
            asyncio.create_task(
                self._session_memory_runner.execute(all_messages)
            )

        # 5. 立即生成并返回结束事件
        for event in self.generate_end_events(state, full_response):
            yield event
