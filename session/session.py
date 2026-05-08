"""
会话管理 - 管理多轮对话和用户输入

核心职责：
- 管理 messages 历史
- 协调 AgentLoop 处理单次输入
- 支持流式事件输出
- 集成存储层实现持久化
- 集成 token 计数与追踪（基于 litellm）
"""

# from compact.micro_compact import MicroCompactResult, compact_tool_results, collect_compactable_tool_ids
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage, SystemMessage
from session.storage import SessionStorage, StoredMessage, TokenUsage
from utils.token import TokenCounter, TokenTracker, TokenBudget
from typing import List, AsyncGenerator, Optional, Any
from session.file_storage import FileSessionStorage
from session.config import SessionManagerConfig
from session.before_hook import BeforeHook
from agent.agent_factory import AgentLoop
from session.after_hook import AfterHook
from dataclasses import dataclass, field
from datetime import datetime
import uuid

@dataclass
class SessionState:
    """会话状态"""
    session_id: str
    messages: List[BaseMessage] = field(default_factory=list)
    turn_count: int = 0
    max_turns: Optional[int] = None
    created_at: datetime = field(default_factory=datetime.now)
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class SessionManager:
    """
    会话管理器

    使用配置初始化：
        config = SessionManagerConfig.from_yaml("config.yaml")
        manager = SessionManager.from_config(agent, config)

    或直接初始化：
        config = SessionManagerConfig(
            storage={"storage_dir": "~/.my_sessions"},
            session={"max_turns": 50}
        )
        manager = SessionManager.from_config(agent, config)
    """

    def __init__(
        self,
        agent: AgentLoop,
        storage: Optional[SessionStorage] = None,
        max_turns: Optional[int] = None,
        system_messages: Optional[List[SystemMessage]] = None,
        token_budget: Optional[TokenBudget] = None,
    ):
        self.agent = agent
        self.storage = storage
        self.max_turns = max_turns
        self.system_messages = system_messages or []

        # ----- token 管理组件 -----
        self.token_counter = TokenCounter()
        self.token_tracker: Optional[TokenTracker] = None
        self.token_budget = token_budget or TokenBudget()
        self.state: Optional[SessionState] = None

        # ----- hooks -----
        self.before_hook: Optional[BeforeHook] = None
        self.after_hook: Optional[AfterHook] = None

    @classmethod
    def from_config(
        cls,
        agent: AgentLoop,
        config: SessionManagerConfig,
        system_messages: Optional[List[SystemMessage]] = None,
        logs_dir: Optional[str] = None,
    ) -> "SessionManager":
        """
        从配置创建 SessionManager

        Args:
            agent: AgentLoop 实例
            config: SessionManagerConfig 配置
            system_messages: SystemMessage 列表（通常来自 prompt 模块）
            logs_dir: 日志目录（用于删除会话时清理日志）

        Returns:
            SessionManager 实例
        """
        # 初始化存储
        storage = FileSessionStorage(
            storage_dir=config.storage.storage_dir,  # 使用组合后的存储目录
            max_messages_in_memory=config.storage.max_messages_in_memory,
            logs_dir=logs_dir,
        )

        # 根据配置创建 TokenBudget
        token_budget = TokenBudget(
            max_tokens=config.token_budget.max_tokens,
            warning_threshold=config.token_budget.warning_threshold,
            auto_compact_threshold=config.token_budget.auto_compact_threshold,
        )

        return cls(
            agent=agent,
            storage=storage,
            max_turns=config.max_turns,
            system_messages=system_messages,
            token_budget=token_budget,
        )

    async def create_session(self, title: Optional[str] = None) -> str:
        """创建新会话"""
        if self.storage:
            session_id = await self.storage.create_session(title)
        else:
            session_id = str(uuid.uuid4())

        self.state = SessionState(
            session_id=session_id,
            turn_count=0,
            max_turns=self.max_turns,
        )

        # 初始化 token 追踪器
        self.token_tracker = self.token_counter.create_tracker()

        # 初始化 hooks
        self.before_hook = BeforeHook(
            token_tracker=self.token_tracker,
            token_budget=self.token_budget,
        )
        self.after_hook = AfterHook(
            storage=self.storage,
            token_tracker=self.token_tracker,
        )

        # 添加 system messages 到消息历史
        if self.system_messages:
            self.state.messages.extend(self.system_messages)
            # 追踪 system messages 的 token 数
            self.token_tracker.add_messages(self.system_messages)

        return session_id

    async def load_session(self, session_id: str) -> bool:
        """加载已有会话"""
        if not self.storage:
            return False

        metadata = await self.storage.get_metadata(session_id)
        if not metadata:
            return False

        stored_messages = await self.storage.get_messages(session_id)

        messages = []
        for msg in stored_messages:
            if msg.type == "human":
                human_kwargs = {}
                if msg.additional_kwargs:
                    human_kwargs["additional_kwargs"] = msg.additional_kwargs
                messages.append(HumanMessage(content=msg.content, **human_kwargs))
            elif msg.type == "ai":
                ai_kwargs = {}
                if msg.tool_calls:
                    ai_kwargs["tool_calls"] = [
                        {
                            "name": tc.get("name"),
                            "args": tc.get("args"),
                            "id": tc.get("id"),
                        }
                        for tc in msg.tool_calls
                    ]
                if msg.additional_kwargs:
                    ai_kwargs["additional_kwargs"] = msg.additional_kwargs
                messages.append(AIMessage(content=msg.content, **ai_kwargs))
            elif msg.type == "tool":
                messages.append(ToolMessage(content=msg.content, tool_call_id=msg.tool_call_id or ""))

        self.state = SessionState(
            session_id=session_id,
            messages=messages,
            turn_count=metadata.turn_count,
            max_turns=self.max_turns,
            created_at=metadata.created_at,
            total_tokens=metadata.total_tokens,
            input_tokens=metadata.input_tokens,
            output_tokens=metadata.output_tokens,
        )

        # 重建 token 追踪器：基于 metadata 中的 token 统计
        self.token_tracker = self.token_counter.create_tracker()
        if messages:
            self.token_tracker.add_messages(messages)

        # 初始化 hooks（从 memdir config 读取配置）
        self.before_hook = BeforeHook(
            token_tracker=self.token_tracker,
            token_budget=self.token_budget,
        )
        self.after_hook = AfterHook(
            storage=self.storage,
            token_tracker=self.token_tracker,
        )

        return True

    async def _ensure_session(self, session_id: Optional[str]) -> None:
        """确保会话已初始化"""
        if self.state is not None:
            return
        if session_id and self.storage:
            if not await self.load_session(session_id):
                await self.create_session()
        else:
            await self.create_session()

        if self.state is None:
            raise RuntimeError("会话状态未初始化")

    def _is_turn_limit_reached(self) -> bool:
        """检查是否达到轮次限制"""
        return self.state.max_turns is not None and self.state.turn_count >= self.state.max_turns

    async def _append_user_message(self, user_input: str) -> List[BaseMessage]:
        """追加用户消息到历史并返回历史（不含当前消息）"""
        history = self.state.messages.copy()

        user_msg = HumanMessage(content=user_input)
        self.state.messages.append(user_msg)
        self.state.turn_count += 1

        # 更新 token 计数（增量）
        if self.token_tracker:
            self.token_tracker.add_input_messages([user_msg])
            usage = self.token_tracker.get_usage()
            self.state.total_tokens = usage.total
            self.state.input_tokens = usage.input_tokens
            self.state.output_tokens = usage.output_tokens

        if self.storage:
            await self.storage.save_message(
                self.state.session_id,
                StoredMessage(type="human", content=user_input, turn_id=self.state.turn_count)
            )
        return history

    def _replace_memory_messages(
        self,
        messages: List[BaseMessage],
        new_memory_messages: List[BaseMessage],
    ) -> List[BaseMessage]:
        """
        替换消息列表中的记忆上下文消息。

        在 system 消息之后插入新的记忆消息，移除旧的记忆消息。
        保留所有其他消息（用户消息、AI 响应等）。

        Args:
            messages: 当前消息列表
            new_memory_messages: 新的记忆上下文消息

        Returns:
            替换后的消息列表
        """
        # 分离消息类型
        system_messages = [m for m in messages if isinstance(m, SystemMessage)]
        other_messages = []
        for m in messages:
            if isinstance(m, SystemMessage):
                continue
            # 检查是否为元数据消息
            is_meta = False
            if m.additional_kwargs and m.additional_kwargs.get("is_meta") is True:
                is_meta = True
            # 后备检查：如果内容包含 system-reminder 标签，也视为元数据
            elif isinstance(m.content, str) and "<system-reminder>" in m.content:
                is_meta = True
            if not is_meta:
                other_messages.append(m)

        # 在 system 消息之后插入新的记忆上下文
        return system_messages + new_memory_messages + other_messages

    async def _stream_and_accumulate(
        self,
        user_input: str,
        history: List[BaseMessage],
    ) -> AsyncGenerator[dict[str, Any], None]:
        """流式处理 Agent 响应并累积完整回复"""
        async for event in self.agent.astream(user_input, history=history):
            yield event


    async def chat(
        self,
        user_input: str,
        session_id: Optional[str] = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        处理用户输入，返回流式事件

        Yields:
            - {"type": "turn_start", "turn": int}
            - {"type": "token", "content": str, "thinking": bool}
            - {"type": "tool_start", "tool": str, "input": str}
            - {"type": "tool_end", "tool": str, "output": str}
            - {"type": "warning", "content": str}      # token 预算警告
            - {"type": "done", "content": str, "turn_count": int}
        """
        # 1. 确保会话已初始化
        await self._ensure_session(session_id)

        # 2. 前置检查（异步 hook）
        memory_messages = []
        async for events in self.before_hook.process(self.state):
            for event in events:
                yield event
                # 提取记忆上下文
                if event.get("type") == "memory_context":
                    memory_messages = event.get("messages", [])
                if event["type"] == "done":
                    return

        # 3. 获取当前历史消息
        history = self.state.messages.copy()

        # 转换记忆消息字典为 HumanMessage
        if memory_messages and isinstance(memory_messages[0], dict):
            memory_messages = [
                HumanMessage(content=msg["content"], additional_kwargs={"is_meta": True})
                for msg in memory_messages if isinstance(msg, dict) and "content" in msg
            ]

        # 4. 替换记忆上下文（在 system 消息之后插入新的，移除旧的）
        new_history = self._replace_memory_messages(history, memory_messages)

        # 6. 更新状态中的消息列表
        self.state.messages = new_history

        # 7. 追加用户消息
        await self._append_user_message(user_input)

        yield {"type": "turn_start", "turn": self.state.turn_count}

        # 8. 流式处理 Agent 响应
        full_response = ""
        all_messages = None
        async for event in self._stream_and_accumulate(user_input, self.state.messages):
            yield event
            if event["type"] == "token":
                full_response += event["content"]
            elif event["type"] == "done" and event.get("messages"):
                all_messages = event["messages"]

        # 9. 后置处理
        if all_messages:
            async for event in self.after_hook.process(
                self.state,
                all_messages,
                new_history,  # 用户消息追加之前的历史
                full_response,
            ):
                yield event
            return

    def reset(self) -> None:
        """重置当前会话状态（同时重置 token 追踪器）"""
        if self.state:
            self.state.messages = []
            self.state.turn_count = 0
            self.state.total_tokens = 0
            self.state.input_tokens = 0
            self.state.output_tokens = 0
            if self.token_tracker:
                self.token_tracker.reset()

    async def delete_current_session(self) -> None:
        """删除当前会话"""
        if self.storage and self.state:
            await self.storage.delete_session(self.state.session_id)
            self.state = None
            if self.token_tracker:
                self.token_tracker.reset()

    def get_messages(self) -> List[BaseMessage]:
        """获取当前会话的所有消息"""
        return self.state.messages if self.state else []

    def get_session_id(self) -> Optional[str]:
        """获取当前会话 ID"""
        return self.state.session_id if self.state else None

    def add_system_message(self, content: str) -> None:
        """添加系统消息到会话开头，并更新 token 计数"""
        if self.state:
            sys_msg = HumanMessage(content=content)
            self.state.messages.insert(0, sys_msg)
            if self.token_tracker:
                self.token_tracker.add_message(sys_msg)

    def get_token_usage(self) -> TokenUsage:
        """获取当前会话的 token 使用统计"""
        return self.token_tracker.get_usage() if self.token_tracker else TokenUsage()
    
    def get_non_system_messages(self) -> List[BaseMessage]:
        """
        获取所有非系统消息
        
        返回messages中所有SystemMessage之后的消息。
        如果没有SystemMessage，返回所有消息。
        """
        if not self.state:
            return []
        
        # 直接通过 system_messages 属性确定下标
        return self.state.messages[len(self.system_messages):]
    
    def get_system_messages_end_index(self) -> int:
        """
        获取系统消息结束的索引位置
        
        返回messages中最后一个SystemMessage的索引+1。
        如果没有SystemMessage，返回0。
        """
        # 直接通过 system_messages 属性确定下标
        return len(self.system_messages)

    async def close(self) -> None:
        """关闭会话管理器"""
        if self.storage:
            await self.storage.close()

    # ========== 压缩相关方法 ==========

    def get_compaction_stats(self) -> dict:
        """
        获取压缩统计信息

        Returns:
            包含可压缩工具信息的字典
        """
        if not self.state:
            return {}
        
        compactable_ids = collect_compactable_tool_ids(self.state.messages)
        return {
            "compactable_tools_count": len(compactable_ids),
            "compactable_ids_list": compactable_ids,
        }

    def estimate_current_tokens(self) -> int:
        """
        估算当前消息的 token 数量

        Returns:
            估算的 token 数
        """
        if not self.state or not self.token_tracker:
            return 0
        return self.token_tracker.get_usage().total

    # def micro_compact(self, target_tokens: Optional[int] = None) -> MicroCompactResult:
    #     """
    #     执行微压缩（精简工具结果）

    #     Args:
    #         target_tokens: 目标保留的最大 token 数

    #     Returns:
    #         MicroCompactResult 压缩结果
    #     """
    #     if not self.state:
    #         raise RuntimeError("会话未初始化")

    #     result = compact_tool_results(
    #         self.state.messages,
    #         target_tokens=target_tokens,
    #     )

    #     # 更新消息列表
    #     self.state.messages = result.messages

    #     # 重新计算 token
    #     if self.token_tracker:
    #         self.token_tracker.reset()
    #         self.token_tracker.add_messages(self.state.messages)
    #         usage = self.token_tracker.get_usage()
    #         self.state.total_tokens = usage.total
    #         self.state.input_tokens = usage.input_tokens
    #         self.state.output_tokens = usage.output_tokens

    #     return result

    # def should_auto_compact(self, threshold: Optional[float] = None) -> bool:
    #     """
    #     检查是否应该自动压缩

    #     Args:
    #         threshold: 压缩阈值（None 使用配置中的 auto_compact_threshold）

    #     Returns:
    #         是否应该压缩
    #     """
    #     if not self.state or not self.token_budget:
    #         return False

    #     if threshold is None:
    #         threshold = self.token_budget.auto_compact_threshold

    #     current_usage = self.token_tracker.get_usage() if self.token_tracker else None
    #     if not current_usage:
    #         return False

    #     return current_usage.total >= self.token_budget.max_tokens * threshold