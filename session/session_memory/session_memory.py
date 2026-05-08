import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import List, Any, Optional, Callable, Set, TYPE_CHECKING
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import BaseTool

# Session memory 专用的日志基础目录
from utils.logging_utils import get_session_logger


# ============================================================================
# 日志工具函数
# ============================================================================

def _get_session_memory_logger(session_id: str) -> logging.Logger:
    """获取会话级别的 session memory 日志记录器"""
    return get_session_logger("session_memory", session_id)


def _debug_log(message: str, session_id: Optional[str] = None) -> None:
    """调试日志，写入会话级别的日志文件"""
    if not session_id:
        return
    logger = _get_session_memory_logger(session_id)
    logger.debug(message)

from .config import (
    get_config,
    set_config,
    SessionMemoryConfig,
    get_last_summarized_index,
    set_last_summarized_index,
    record_extraction_token_count,
    is_session_memory_initialized,
    mark_session_memory_initialized,
    has_met_init_threshold,
    has_met_update_threshold,
    get_tool_calls_between_updates,
    get_tokens_at_last_extraction,
)
from .prompts import (
    load_template,
    build_session_memory_update_prompt,
    is_session_memory_empty,
)
from .paths import (
    get_session_memory_path,
    ensure_session_memory_dir,
    ensure_session_memory_file,
)


# ============================================================================
# 辅助函数
# ============================================================================

def _rough_token_count(text: str) -> int:
    """粗略估算 token 数"""
    if not text:
        return 0
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - chinese_chars
    return int(chinese_chars * 2 + other_chars * 0.25)


def estimate_messages_token_count(messages: List[Any]) -> int:
    """估算消息列表的 token 数"""
    total = 0
    for msg in messages:
        content = getattr(msg, "content", "") or ""
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    total += _rough_token_count(item["text"])
                elif isinstance(item, str):
                    total += _rough_token_count(item)
        elif isinstance(content, str):
            total += _rough_token_count(content)
    return total


def count_tool_calls_since(
    messages: List[Any],
    since_index: Optional[int],
) -> int:
    """计算从指定索引以来的工具调用数"""
    tool_call_count = 0
    start_idx = (since_index + 1) if since_index is not None else 0
    
    for i in range(start_idx, len(messages)):
        msg = messages[i]
        if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
            tool_call_count += len(msg.tool_calls)
    
    return tool_call_count


def has_tool_calls_in_last_assistant_turn(messages: List[Any]) -> bool:
    """检查最后一个 Assistant 消息是否有工具调用"""
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if isinstance(msg, AIMessage):
            return hasattr(msg, "tool_calls") and bool(msg.tool_calls)
    return False


def is_model_visible_message(message: BaseMessage) -> bool:
    """检查消息是否对模型可见"""
    return isinstance(message, (HumanMessage, AIMessage, SystemMessage))


# ============================================================================
# Session Memory Runner
# ============================================================================

def get_memory_tools(session_memory_dir: str) -> List[BaseTool]:
    """
    获取 memory 目录专用的工具列表。
    只包含 read_file 和 Edit 工具，限制在 session_memory_dir 范围内。
    """
    import os
    
    # 确保 session_memory_dir 是绝对路径
    session_memory_dir = os.path.abspath(session_memory_dir)
    
    # 延迟导入，避免循环依赖
    from tools import (
        create_read_file_tool,
        create_edit_file_tool,
    )

    tools = []

    # Read 工具：限制在 session_memory_dir
    read = create_read_file_tool()
    read.root_dir = session_memory_dir
    tools.append(read)

    # Edit 工具：限制在 session_memory_dir
    edit = create_edit_file_tool()
    edit.root_dir = session_memory_dir
    tools.append(edit)

    return tools


def is_session_memory_enabled() -> bool:
    """检查是否启用 Session Memory"""
    if os.environ.get("DISABLE_SESSION_MEMORY"):
        return False
    
    config = get_config()
    return config.enabled


def should_extract_memory(
    messages: List[Any],
    session_id: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
) -> bool:
    """
    判断是否应该提取记忆
    
    触发条件：
    1. Token 达到初始化阈值（首次）
    2. Token 增量达到更新阈值 AND 工具调用数达到阈值
    3. Token 增量达到更新阈值 AND 最后一个 assistant 无工具调用
    """
    def _log(msg: str) -> None:
        if logger:
            logger.debug(msg)
        elif session_id:
            _debug_log(msg, session_id)
    
    if not is_session_memory_enabled():
        _log("Session memory disabled")
        return False
    
    config = get_config()
    current_token_count = estimate_messages_token_count(messages)
    tokens_at_last = get_tokens_at_last_extraction()
    tokens_since_last = current_token_count - tokens_at_last if tokens_at_last else 0
    
    _log(f"[Threshold Check] current_tokens={current_token_count}, "
         f"init_threshold={config.minimum_message_tokens_to_init}, "
         f"update_threshold={config.minimum_tokens_between_update}, "
         f"tokens_since_last={tokens_since_last}, "
         f"tool_calls_threshold={config.tool_calls_between_updates}, "
         f"initialized={is_session_memory_initialized()}")
    
    # 检查初始化阈值
    if not is_session_memory_initialized():
        if not has_met_init_threshold(current_token_count):
            _log(f"[Threshold Check] NOT MET - init threshold: {current_token_count} < {config.minimum_message_tokens_to_init}")
            return False
        _log("[Threshold Check] Init threshold met, marking initialized")
        mark_session_memory_initialized()
    
    # 检查更新阈值（必须满足）
    if not has_met_update_threshold(current_token_count):
        _log(f"[Threshold Check] NOT MET - update threshold: {tokens_since_last} < {config.minimum_tokens_between_update}")
        return False
    
    # 检查工具调用阈值
    last_summarized_idx = get_last_summarized_index()
    tool_calls_since = count_tool_calls_since(messages, last_summarized_idx)
    has_met_tool_threshold = tool_calls_since >= config.tool_calls_between_updates
    
    # 检查最后一个 assistant 是否有工具调用
    has_tool_calls_in_last = has_tool_calls_in_last_assistant_turn(messages)
    
    _log(f"[Threshold Check] tool_calls_since={tool_calls_since}, "
         f"has_tool_calls_in_last={has_tool_calls_in_last}")
    
    # 触发条件：
    # 1. 两个阈值都满足，或
    # 2. token 阈值满足且最后一个 assistant 无工具调用（自然对话间隙）
    should_extract = has_met_tool_threshold or (not has_tool_calls_in_last)
    
    if should_extract:
        _log("[Threshold Check] EXTRACTING - threshold conditions met")
        if messages:
            set_last_summarized_index(len(messages) - 1)
    else:
        _log(f"[Threshold Check] NOT EXTRACTING - tool_calls={tool_calls_since} < {config.tool_calls_between_updates} AND last turn has tools")
    
    return should_extract


class SessionMemoryRunner:
    """
    Session Memory 提取运行器
    
    使用 asyncio 原生并发控制，参考 ExtractMemoriesRunner 的实现。
    """

    def __init__(self, storage: Optional[Any] = None, session_id: Optional[str] = None) -> None:
        """
        初始化 Session Memory Runner
        
        Args:
            storage: SessionStorage 实例，用于获取 sessions_dir
            session_id: 会话 ID
        """
        self._storage = storage
        self._session_id = session_id
        
        # 并发控制
        self._current_task: Optional[asyncio.Task] = None
        self._stashed_messages: Optional[List[BaseMessage]] = None
        self._lock = asyncio.Lock()
        self._in_flight_events: Set[asyncio.Event] = set()
        
        # 门控
        self._has_logged_gate_failure = False
        
        # 日志记录器
        self._logger: Optional[logging.Logger] = None

    def set_session_id(self, session_id: str) -> None:
        """设置会话ID"""
        self._session_id = session_id
        self._logger = _get_session_memory_logger(session_id)

    def set_storage(self, storage: Any) -> None:
        """设置 storage，用于获取 sessions_dir"""
        self._storage = storage

    async def execute(
        self,
        messages: List[BaseMessage],
    ) -> None:
        """
        执行 Session Memory 提取（fire-and-forget）
        
        Args:
            messages: 消息列表
            agent: 主 AgentLoop 实例（用于 fork 子代理）
        """
        # 确保 logger 已初始化
        if self._logger is None and self._session_id:
            self._logger = _get_session_memory_logger(self._session_id)
        
        # 记录调用（无论是否启用）
        if self._logger:
            self._logger.debug(f"execute called, enabled={is_session_memory_enabled()}, messages={len(messages)}")
        
        if not is_session_memory_enabled():
            if not self._has_logged_gate_failure:
                if self._logger:
                    self._logger.debug("Session memory disabled by configuration")
            return
        
        async with self._lock:
            # 如果有任务在进行中，暂存上下文用于后续执行
            if self._current_task is not None and not self._current_task.done():
                self._logger.debug("Extraction in progress - stashing for trailing run")
                self._stashed_messages = messages
                return
            
            # 创建新任务
            event = asyncio.Event()
            self._in_flight_events.add(event)
            self._current_task = asyncio.create_task(
                self._run_with_trailing(messages, event)
            )

    async def _run_with_trailing(
        self,
        messages: List[BaseMessage],
        event: asyncio.Event,
    ) -> None:
        """运行提取任务，完成后处理暂存的上下文"""
        try:
            await self._run_extraction(messages)
        finally:
            event.set()
            self._in_flight_events.discard(event)
            
            async with self._lock:
                stashed = self._stashed_messages
                self._stashed_messages = None
                self._current_task = None
            
            if stashed:
                self._logger.debug("Running trailing extraction for stashed context")
                await self.execute(stashed)

    async def _run_extraction(
        self,
        messages: List[BaseMessage],
    ) -> None:
        """核心提取逻辑"""
        self._logger.debug(f"Starting extraction with {len(messages)} messages, session_id={self._session_id}")
        
        try:
            # 检查是否应该提取
            if not should_extract_memory(messages, logger=self._logger):
                return
            
            # 获取 sessions_dir（使用 storage 的目录）
            sessions_dir = None
            if self._storage and hasattr(self._storage, 'storage_dir'):
                sessions_dir = str(self._storage.storage_dir)
                self._logger.debug(f"Using storage_dir: {sessions_dir}")
            
            # 确保目录和文件存在（会话级别隔离）
            memory_path = ensure_session_memory_file(self._session_id, sessions_dir)
            self._logger.debug(f"Using session memory file: {memory_path}")
            
            # 读取当前 session memory 内容
            current_memory = ""
            if os.path.exists(memory_path):
                with open(memory_path, "r", encoding="utf-8") as f:
                    current_memory = f.read()
            
            # 如果是空模板，使用默认模板
            if is_session_memory_empty(current_memory):
                current_memory = load_template()
            
            # 构建提取提示
            user_prompt = build_session_memory_update_prompt(current_memory, memory_path)
            self._logger.debug(f"Built extraction prompt for: {memory_path}")
            
            # 构建系统提示（限制只使用 Edit 工具）
            # 使用 storage 的 sessions_dir 或从 memory_path 推导
            session_dir = sessions_dir if sessions_dir else os.path.dirname(memory_path)
            system_prompt = f"""You are a session memory assistant. Your ONLY task is to use the Edit tool to update the session notes file at {memory_path}.

IMPORTANT RULES:
- You can ONLY use the Read and Edit tools
- Do NOT call any other tools
- Preserve the file structure exactly
- Stop after making the edits
- The file should be located at: {memory_path}
- Working directory: {session_dir}"""
            
            # 获取 session memory 专用的工具
            memory_tools = get_memory_tools(session_dir)
            self._logger.debug(f"Memory tools: {[t.name for t in memory_tools]}")
            
            # 创建系统消息
            system_messages = [
                SystemMessage(content=system_prompt)
            ]
            
            # 过滤非系统消息
            non_system_messages = [m for m in messages if not isinstance(m, SystemMessage)]
            
            # 使用 fork_agent 执行提取
            from agent.fork_subagent import fork_agent
            from agent.model.llm_factory import LLMFactory
            from agent.agent_factory import AgentLoop
            
            config = get_config()
            max_turns = config.max_turns
            model_name = config.model_name
            
            # 创建子代理的 LLM 和 AgentLoop
            self._logger.debug(f"Creating session memory agent, model_name={model_name}, max_turns={max_turns}")
            if not model_name:
                self._logger.error("Failed to create memory agent: model_name not configured")
                return
            
            llm = LLMFactory.create_llm(model_name)
            memory_agent = AgentLoop(llm=llm, tools=memory_tools, max_turns=max_turns)
            
            if not memory_agent:
                self._logger.error("Failed to create memory agent: no LLM available")
                return
            
            self._logger.debug(f"Calling fork_agent for session memory extraction")
            result = await fork_agent(
                agent=memory_agent,
                system_messages=system_messages,
                context_messages=non_system_messages,
                task=user_prompt,
                debug=True,
                debug_prefix="[SessionMemory]",
                logger=self._logger,
            )
            
            self._logger.debug(f"fork_agent returned, success={result.success}")
            
            if result.success:
                # 记录 token 数
                record_extraction_token_count(estimate_messages_token_count(messages))
                self._logger.info("Session memory extraction completed successfully")
            else:
                self._logger.error(f"Session memory extraction failed: {result.error}")
                
        except Exception as e:
            self._logger.error(f"Session memory extraction error: {e}", exc_info=True)

    async def drain(self, timeout_ms: int = 30000) -> None:
        """等待所有进行中的提取完成"""
        if not self._in_flight_events:
            return
        
        timeout_sec = timeout_ms / 1000
        import time
        start = time.time()
        events = list(self._in_flight_events)
        
        for event in events:
            remaining = timeout_sec - (time.time() - start)
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(event.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                self._logger.warning("Drain timeout waiting for extraction")
                break


# ============================================================================
# 全局实例和便捷函数
# ============================================================================

_runner: Optional[SessionMemoryRunner] = None


def init_session_memory() -> None:
    """初始化 Session Memory Runner"""
    global _runner
    _runner = SessionMemoryRunner()


def get_runner() -> SessionMemoryRunner:
    """获取 Runner 实例"""
    global _runner
    if _runner is None:
        _runner = SessionMemoryRunner()
    return _runner


async def execute_session_memory(
    messages: List[BaseMessage],
) -> None:
    """在 query loop 结束时运行 session memory 提取"""
    runner = get_runner()
    await runner.execute(messages)


async def drain_session_memory(timeout_ms: int = 30000) -> None:
    """等待所有进行中的提取完成"""
    runner = get_runner()
    await runner.drain(timeout_ms)


# ============================================================================
# 便捷函数（保持向后兼容）
# ============================================================================

async def setup_session_memory_file() -> tuple:
    """设置 Session Memory 文件"""
    ensure_session_memory_dir()
    memory_path = get_session_memory_path()
    
    if not os.path.exists(memory_path):
        template = load_template()
        with open(memory_path, "w", encoding="utf-8", mode=0o600) as f:
            f.write(template)
    
    try:
        with open(memory_path, "r", encoding="utf-8") as f:
            current_memory = f.read()
    except Exception:
        current_memory = ""
    
    return memory_path, current_memory


async def get_session_memory_content() -> Optional[str]:
    """获取 Session Memory 内容"""
    memory_path = get_session_memory_path()
    
    if not os.path.exists(memory_path):
        return None
    
    try:
        with open(memory_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        if is_session_memory_empty(content):
            return None
        
        return content
    except Exception:
        return None


def get_session_memory_content_sync() -> Optional[str]:
    """同步版本获取 Session Memory 内容"""
    memory_path = get_session_memory_path()
    
    if not os.path.exists(memory_path):
        return None
    
    try:
        with open(memory_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        if is_session_memory_empty(content):
            return None
        
        return content
    except Exception:
        return None
