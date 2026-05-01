"""
Fork Subagent - 主代理逻辑分身

从主代理 fork 出一个轻量级分身，继承其 LLM 和工具，
使用独立的系统上下文和对话历史，执行指定任务。

使用示例：
    from agent.fork_subagent import fork_agent

    # 基础用法
    result = await fork_agent(
        agent=agent,
        system_messages=system_msgs,
        context_messages=history_msgs,
        task="分析这段代码"
    )

    # 流式用法
    async for chunk in fork_agent_stream(agent, system_msgs, history_msgs, task):
        print(chunk)
"""

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from dataclasses import dataclass, field
from typing import List, Optional, Any, Callable, AsyncIterator
from .agent_factory import AgentLoop
import logging


@dataclass
class ForkResult:
    """Fork 执行结果"""
    success: bool
    content: str
    final_messages: List[BaseMessage] = field(default_factory=list)
    tool_call_count: int = 0
    error: Optional[str] = None


@dataclass
class ForkStreamEvent:
    """流式事件"""
    type: str  # "token" | "tool_start" | "tool_end" | "done"
    content: Optional[str] = None
    tool: Optional[str] = None
    input: Optional[str] = None
    output: Optional[str] = None
    messages: Optional[List[BaseMessage]] = None
    tool_call_count: Optional[int] = None


from utils.logging_utils import get_shared_logger


@dataclass
class ForkedAgent:
    """轻量级分身代理"""
    system_messages: List[SystemMessage]
    context_messages: List[BaseMessage]
    tools: List[BaseTool]
    llm: Any
    debug: bool = False
    debug_prefix: str = "[ForkAgent]"
    logger: Optional[logging.Logger] = field(default=None, repr=False)
    _result: Optional[ForkResult] = field(default=None, repr=False)
    tool_call_count: int = 0

    def _debug_log(self, msg: str) -> None:
        if self.debug:
            # 如果外部传入了 logger 则使用，否则创建一个默认的
            log = self.logger or get_shared_logger(self.debug_prefix)
            log.debug(f"{self.debug_prefix} {msg}")

    @property
    def result(self) -> Optional[ForkResult]:
        return self._result

    @property
    def is_finished(self) -> bool:
        return self._result is not None

    @property
    def all_messages(self) -> List[BaseMessage]:
        """获取完整消息列表：系统消息 + 历史"""
        return self.system_messages + self.context_messages

    async def run(self, task: str) -> str:
        """执行分身任务（非流式）"""
        result = ""
        async for event in self.stream(task):
            if event.type == "token" and event.content:
                result += event.content
            elif event.type == "done":
                self.tool_call_count = event.tool_call_count or 0
        return result

    async def stream(
        self,
        task: str,
        max_turns: Optional[int] = None,
    ) -> AsyncIterator[ForkStreamEvent]:
        """
        流式执行分身任务

        Args:
            task: 当前任务指令
            max_turns: 可选，最大循环次数

        Yields:
            ForkStreamEvent 流式事件
        """
        agent = AgentLoop(llm=self.llm, tools=self.tools, max_turns=max_turns or 50)
        history = self.all_messages

        # Debug: 打印消息列表
        self._debug_log(f"[CONTEXT] system_messages count: {len(self.system_messages)}")
        self._debug_log(f"[CONTEXT] context_messages count: {len(self.context_messages)}")
        self._debug_log(f"[CONTEXT] task: {task[:2000]}...")
        if self.context_messages:
            self._debug_log(f"[CONTEXT] first message: {self.context_messages[0].content[:200]}...")

        token_buffer = ""  # token 缓冲区
        buffer_size = 50  # 达到此字符数输出一次
        tool_call_count = 0  # 手动计数工具调用

        async for event in agent.astream(task, history=history, max_turns=max_turns):
            if event["type"] == "token":
                token_buffer += event["content"]
                
                # 缓冲区满或收到换行时输出
                if len(token_buffer) >= buffer_size or '\n' in token_buffer:
                    self._debug_log(f"[TOKEN] {token_buffer}")
                    token_buffer = ""
                
                yield ForkStreamEvent(type="token", content=event["content"])

            elif event["type"] == "tool_start":
                tool_name = event.get("tool", "")
                tool_input = event.get("input", "")
                # 工具开始时输出剩余的缓冲区
                if token_buffer:
                    self._debug_log(f"[TOKEN] {token_buffer}")
                    token_buffer = ""
                truncated_input = tool_input[:2000] + ("..." if len(tool_input) > 2000 else "")
                self._debug_log(f"[TOOL] {tool_name} start: {truncated_input}")
                yield ForkStreamEvent(type="tool_start", tool=tool_name, input=tool_input)

            elif event["type"] == "tool_end":
                tool_name = event.get("tool", "")
                tool_output = event.get("output", "")
                tool_call_count += 1  # 手动计数
                truncated_output = tool_output[:2000] + ("..." if len(tool_output) > 2000 else "")
                self._debug_log(f"[TOOL] {tool_name} end: {truncated_output}")
                yield ForkStreamEvent(type="tool_end", tool=tool_name, output=tool_output)

            elif event["type"] == "done":
                # 最后输出剩余缓冲区
                if token_buffer:
                    self._debug_log(f"[TOKEN] {token_buffer}")
                self.tool_call_count = tool_call_count  # 使用手动计数
                self._debug_log(f"[DONE] tool_count={self.tool_call_count}")
                yield ForkStreamEvent(
                    type="done",
                    messages=event.get("messages"),
                    tool_call_count=self.tool_call_count,
                )


async def fork_agent(
    agent: AgentLoop,
    system_messages: Optional[List[SystemMessage]] = None,
    context_messages: Optional[List[BaseMessage]] = None,
    task: str = "",
    model_name: Optional[str] = None,
    debug: bool = False,
    debug_prefix: str = "[ForkAgent]",
    logger: Optional[logging.Logger] = None,
    max_turns: Optional[int] = None,
) -> ForkResult:
    """
    Fork 主代理创建一个逻辑分身

    Args:
        agent: 主代理实例
        system_messages: 系统消息列表
        context_messages: 对话历史（非系统消息）
        task: 当前任务指令
        model_name: 可选，指定不同模型
        debug: 是否开启 debug 日志（打印 token、工具调用等）
        debug_prefix: debug 日志前缀
        logger: 可选，共享的日志记录器（会与 extract_memories 写入同一文件）
        max_turns: 可选，最大循环次数（覆盖 agent 默认值）

    Returns:
        ForkResult 执行结果
    """
    if model_name:
        from .model.llm_factory import LLMFactory
        llm = LLMFactory.create_llm(model_name)
    else:
        llm = agent.llm

    forked = ForkedAgent(
        system_messages=list(system_messages or []),
        context_messages=list(context_messages or []),
        tools=list(agent.tools),
        llm=llm,
        debug=debug,
        debug_prefix=debug_prefix,
        logger=logger,
    )

    full_response = ""
    tool_count = 0
    final_msgs = None

    try:
        async for event in forked.stream(task, max_turns=max_turns):
            if event.type == "token":
                full_response += event.content or ""
            elif event.type == "done":
                final_msgs = event.messages
                tool_count = event.tool_call_count or 0

        return ForkResult(
            success=True,
            content=full_response,
            final_messages=final_msgs or forked.all_messages,
            tool_call_count=tool_count,
        )
    except Exception as e:
        log = logger or get_shared_logger(debug_prefix)
        log.debug(f"{debug_prefix} Error: {e}")
        return ForkResult(success=False, content="", error=str(e))
