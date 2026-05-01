"""
后台记忆提取模块 - LangChain/LangGraph 兼容版。

在每个完整 query loop 结束时（模型产生最终响应且无工具调用时）运行，
从当前会话 transcript 中提取持久的记忆并写入自动记忆目录。

使用 fork_agent 创建子代理执行提取任务。
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Set, Dict, Any, TYPE_CHECKING

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import BaseTool

if TYPE_CHECKING:
    from agent.fork_subagent import ForkResult

# AgentLoop 在这里导入，避免 TYPE_CHECKING 导致的运行时错误
from agent.agent_factory import AgentLoop

# 运行时导入延迟到具体使用处，避免循环依赖

from .prompts import build_extract_auto_only_prompt
from prompt.builder import get_cached_static_messages, build_dynamic_messages
from prompt.dynamic_sections import DynamicSectionContext


def get_memory_tools(memory_dir: str) -> List[BaseTool]:
    """
    获取 memory 目录专用的工具列表。
    所有文件操作工具被限制在 memory_dir 范围内。
    """
    import os
    
    # 确保 memory_dir 是绝对路径
    memory_dir = os.path.abspath(memory_dir)
    
    # 延迟导入，避免循环依赖
    from tools import (
        create_bash_tool,
        create_glob_tool,
        create_grep_tool,
        create_read_file_tool,
        create_edit_file_tool,
        create_write_file_tool,
    )

    tools = []

    # Bash 工具：限制在 memory_dir
    bash = create_bash_tool(memory_dir)
    tools.append(bash)

    # Glob 工具：限制在 memory_dir
    glob = create_glob_tool(memory_dir)
    tools.append(glob)

    # Grep 工具：限制在 memory_dir
    grep = create_grep_tool(memory_dir)
    tools.append(grep)

    # Read 工具：限制在 memory_dir
    read = create_read_file_tool()
    read.root_dir = memory_dir
    tools.append(read)

    # Edit 工具：限制在 memory_dir
    edit = create_edit_file_tool()
    edit.root_dir = memory_dir
    tools.append(edit)

    # Write 工具：限制在 memory_dir
    write = create_write_file_tool()
    write.root_dir = memory_dir
    tools.append(write)

    return tools


@dataclass
class UsageStats:
    """使用统计。"""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class MemoryExtractionResult:
    """记忆提取结果（内部使用）。"""
    messages: List[BaseMessage]
    total_usage: UsageStats


# 回调类型：用于向主对话追加系统消息
AppendSystemMessageFn = Callable[[SystemMessage], None]


def rebuild_system_messages_for(cwd: str) -> List[SystemMessage]:
    """
    为指定 cwd 重新构建 system messages
    
    使用当前 cwd 的静态消息 + 新的动态消息，
    确保 cwd 与实际工作目录一致。
    """
    static_messages = get_cached_static_messages()
    ctx = DynamicSectionContext(cwd=cwd)
    dynamic_messages = build_dynamic_messages(ctx)
    return static_messages + dynamic_messages


def get_fork_agent_cwd() -> str:
    """
    获取 fork_agent 使用的 cwd
    
    使用 memdir 配置的 base_dir 和 dirname 拼接
    """
    from memdir.config import get_memory_base_dir, get_auto_mem_dirname
    base_dir = get_memory_base_dir()
    dirname = get_auto_mem_dirname()
    return os.path.join(base_dir, dirname)


def is_model_visible_message(message: BaseMessage) -> bool:
    """检查消息是否对模型可见（发送到 API）。"""
    # HumanMessage, AIMessage, SystemMessage 都可见
    return isinstance(message, (HumanMessage, AIMessage, SystemMessage))


def count_model_visible_messages_since(
    messages: List[BaseMessage],
    since_id: Optional[str],
) -> int:
    """计算自指定消息 ID 之后新增的模型可见消息数量。"""
    if since_id is None:
        return sum(1 for m in messages if is_model_visible_message(m))

    found_start = False
    count = 0
    for msg in messages:
        msg_id = getattr(msg, 'id', None)
        if not found_start:
            if msg_id == since_id:
                found_start = True
            continue
        if is_model_visible_message(msg):
            count += 1

    if not found_start:
        return sum(1 for m in messages if is_model_visible_message(m))
    return count


def extract_written_paths(messages: List[BaseMessage]) -> List[str]:
    """从 AIMessage 的 tool_calls 中提取所有被写入的文件路径（Edit/Write）。"""
    paths: List[str] = []
    for msg in messages:
        if not isinstance(msg, AIMessage):
            continue
        for tool_call in getattr(msg, 'tool_calls', []):
            tool_name = tool_call.get('name', '')
            if tool_name in ('Edit', 'Write'):
                args = tool_call.get('args', {})
                file_path = args.get('file_path')
                if file_path and isinstance(file_path, str):
                    paths.append(file_path)
    return list(set(paths))


def _update_memory_index(memory_dir: str, written_paths: List[str]) -> None:
    """自动更新 MEMORY.md 索引文件，添加新记忆文件的条目。"""
    from memdir.paths import get_auto_mem_entrypoint_name
    
    index_path = os.path.join(memory_dir, get_auto_mem_entrypoint_name())
    
    # 读取当前索引
    try:
        with open(index_path, 'r', encoding='utf-8') as f:
            current_content = f.read()
    except FileNotFoundError:
        current_content = "# Memory Index\n\n"
    
    # 读取每个新记忆文件的标题
    for path in written_paths:
        if os.path.basename(path) == get_auto_mem_entrypoint_name():
            continue  # 跳过索引文件本身
        
        filename = os.path.basename(path)
        
        # 检查是否已存在
        if f"[{filename}]" in current_content:
            continue
        
        # 从记忆文件读取标题
        title = filename.replace('.md', '')
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            # 尝试从 frontmatter 提取标题
            if content.startswith('---'):
                parts = content.split('---', 2)
                if len(parts) >= 3:
                    frontmatter = parts[1]
                    for line in frontmatter.split('\n'):
                        if line.startswith('title:'):
                            title = line.split(':', 1)[1].strip().strip('"\'')
                            break
        except Exception:
            pass
        
        # 添加索引条目（格式：- [Title](file.md) — one-line hook）
        hook = f"Memory file: {filename}"
        new_entry = f"- [{title}]({filename}) — {hook}\n"
        
        # 在 "# Memory Index" 后添加
        if "# Memory Index" in current_content:
            lines = current_content.split('\n', 2)
            if len(lines) >= 2:
                current_content = lines[0] + '\n' + lines[1] + '\n' + new_entry + (lines[2] if len(lines) > 2 else '')
    
    # 写回索引文件
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(current_content)


def has_memory_writes_since(
    messages: List[BaseMessage],
    since_id: Optional[str],
    memory_dir: str,
) -> bool:
    """检查自指定消息 ID 之后是否有对记忆文件的写入。"""
    found_start = since_id is None
    for msg in messages:
        msg_id = getattr(msg, 'id', None)
        if not found_start:
            if msg_id == since_id:
                found_start = True
            continue
        if not isinstance(msg, AIMessage):
            continue
        for tool_call in getattr(msg, 'tool_calls', []):
            tool_name = tool_call.get('name', '')
            if tool_name in ('Edit', 'Write'):
                args = tool_call.get('args', {})
                file_path = args.get('file_path')
                if file_path and isinstance(file_path, str) and file_path.startswith(memory_dir):
                    return True
    return False


def count_assistant_messages(messages: List[BaseMessage]) -> int:
    """计算 AIMessage 数量。"""
    return sum(1 for m in messages if isinstance(m, AIMessage))


class ExtractMemoriesRunner:
    """记忆提取运行器，使用 asyncio 原生并发控制。"""

    def __init__(self, session_id: Optional[str] = None) -> None:
        """从 memdir config 读取配置创建记忆提取器。"""
        # 会话ID，用于会话级别的日志
        self._session_id = session_id
        
        # 并发控制
        self._current_task: Optional[asyncio.Task] = None
        self._stashed_context: Optional[dict] = None
        self._lock = asyncio.Lock()
        self._in_flight_events: Set[asyncio.Event] = set()

        # 游标
        self._last_message_id: Optional[str] = None

        # 门控和节流
        self._has_logged_gate_failure = False
        self._turns_since_last_extraction = 0
        self._extract_enabled = True
        self._throttle_turns = 1

    def set_session_id(self, session_id: str) -> None:
        """设置会话ID。"""
        self._session_id = session_id

    def configure(self, extract_enabled: bool = True, throttle_turns: int = 1) -> None:
        self._extract_enabled = extract_enabled
        self._throttle_turns = throttle_turns

    async def execute(
        self,
        messages: List[BaseMessage],
        append_system_message: Optional[AppendSystemMessageFn] = None,
    ) -> None:
        """执行记忆提取的主入口（fire-and-forget）。"""
        if not self._extract_enabled:
            if not self._has_logged_gate_failure:
                _debug_log('[extractMemories] gate disabled by configuration', self._session_id)
            return

        # 直接从 memdir.config 导入，避免循环依赖
        from memdir.config import is_auto_memory_enabled
        if not is_auto_memory_enabled():
            return

        async with self._lock:
            if self._current_task is not None and not self._current_task.done():
                _debug_log('[extractMemories] extraction in progress — stashing for trailing run', self._session_id)
                self._stashed_context = {
                    'messages': messages,
                    'append_system_message': append_system_message,
                }
                return

            # 创建新任务
            event = asyncio.Event()
            self._in_flight_events.add(event)
            self._current_task = asyncio.create_task(
                self._run_with_trailing(messages, append_system_message, event)
            )

    async def _run_with_trailing(
        self,
        messages: List[BaseMessage],
        append_system_message: Optional[AppendSystemMessageFn],
        event: asyncio.Event,
    ) -> None:
        """运行提取任务，完成后处理暂存的上下文。"""
        try:
            await self._run_extraction(messages, append_system_message)
        except Exception as e:
            _debug_log(f'[extractMemories] extraction error: {e}', self._session_id)
        finally:
            event.set()
            self._in_flight_events.discard(event)

            async with self._lock:
                stashed = self._stashed_context
                self._stashed_context = None
                self._current_task = None

            if stashed:
                _debug_log('[extractMemories] running trailing extraction for stashed context', self._session_id)
                await self.execute(
                    stashed['messages'],
                    stashed['append_system_message'],
                )

    async def _run_extraction(
        self,
        messages: List[BaseMessage],
        append_system_message: Optional[AppendSystemMessageFn],
        is_trailing_run: bool = False,
    ) -> Optional[MemoryExtractionResult]:
        """核心提取逻辑。"""
        # 直接从 memdir.config 导入，避免循环依赖
        from memdir.config import get_memory_base_dir
        from memdir.memory_scan import format_memory_manifest, scan_memory_files
        import os

        memory_dir = get_memory_base_dir()
        new_message_count = count_model_visible_messages_since(messages, self._last_message_id)

        # 互斥检查：主 Agent 已写入记忆
        if has_memory_writes_since(messages, self._last_message_id, memory_dir):
            _debug_log('[extractMemories] skipping — conversation already wrote to memory files', self._session_id)
            if messages:
                self._last_message_id = getattr(messages[-1], 'id', None)
            return None

        # 节流
        if not is_trailing_run:
            self._turns_since_last_extraction += 1
            if self._turns_since_last_extraction < self._throttle_turns:
                return None
        self._turns_since_last_extraction = 0
        _debug_log(f'[extractMemories] starting — {new_message_count} new messages, memoryDir={memory_dir}', self._session_id)

        try:
            # 扫描现有记忆
            existing_memories = await scan_memory_files(memory_dir, None)
            manifest = format_memory_manifest(existing_memories)

            # 构建提取提示
            user_prompt = build_extract_auto_only_prompt(new_message_count, manifest)

            # 获取 memory 目录专用的工具（自动限制在 memory_dir 范围内）
            memory_tools = get_memory_tools(memory_dir)
            _debug_log(f'[extractMemories] memory tools: {[t.name for t in memory_tools]}', self._session_id)

            _debug_log(f'[extractMemories] calling fork_agent with {len(messages)} messages', self._session_id)

            # 检查记忆目录是否存在
            import os
            if not os.path.exists(memory_dir):
                _debug_log(f'[extractMemories] creating memory dir: {memory_dir}', self._session_id)
                os.makedirs(memory_dir, exist_ok=True)
                
                # 创建 MEMORY.md 入口文件
                from memdir.paths import get_auto_mem_entrypoint_name
                entrypoint_name = get_auto_mem_entrypoint_name()
                memory_md_path = os.path.join(memory_dir, entrypoint_name)
                
                if not os.path.exists(memory_md_path):
                    with open(memory_md_path, "w", encoding="utf-8") as f:
                        f.write("# Memory Index\n\n")
                    _debug_log(f'[extractMemories] created {entrypoint_name} file', self._session_id)
            else:
                _debug_log(f'[extractMemories] memory dir exists: {memory_dir}', self._session_id)
                
                # 确保 MEMORY.md 存在（即使目录已存在）
                from memdir.paths import get_auto_mem_entrypoint_name
                entrypoint_name = get_auto_mem_entrypoint_name()
                memory_md_path = os.path.join(memory_dir, entrypoint_name)
                
                if not os.path.exists(memory_md_path):
                    with open(memory_md_path, "w", encoding="utf-8") as f:
                        f.write("# Memory Index\n\n")
                    _debug_log(f'[extractMemories] created missing {entrypoint_name} file', self._session_id)

            # 重新构建 system messages（使用实际的 memory_dir 作为 cwd）
            system_messages = rebuild_system_messages_for(memory_dir)
            
            # 分离系统消息和对话消息
            non_system_messages = [m for m in messages if not isinstance(m, SystemMessage)]

            # 从 memdir config 读取提取模型配置
            from memdir.config import get_extraction_model
            extraction_model = get_extraction_model()
            _debug_log(f'[extractMemories] using model: {extraction_model}', self._session_id)
            
            # 创建独立的 LLM 实例给记忆提取 agent 使用
            from agent.model.llm_factory import LLMFactory
            from agent.agent_factory import AgentLoop
            
            if extraction_model:
                memory_llm = LLMFactory.create_llm(extraction_model)
            else:
                raise RuntimeError("No extraction model configured in memdir config")
            
            memory_agent = AgentLoop(
                llm=memory_llm,
                tools=memory_tools,
                model_name=extraction_model,
            )

            # 使用 fork_agent 执行提取任务，传入会话级别的共享 logger
            from agent.fork_subagent import fork_agent
            logger = _get_extract_memory_logger(self._session_id)
            result = await fork_agent(
                agent=memory_agent,
                system_messages=system_messages,
                context_messages=non_system_messages,
                task=user_prompt,
                debug=True,
                debug_prefix="[extractMemories]",
                logger=logger,
            )

            _debug_log(f'[extractMemories] fork_agent returned, success={result.success}', self._session_id)

            # 打印子代理的最终回复内容
            if result.final_messages:
                last_msg = result.final_messages[-1]
                if hasattr(last_msg, 'content'):
                    content_preview = str(last_msg.content)[:500]
                    _debug_log(f'[extractMemories] last message preview: {content_preview}', self._session_id)

            if not result.success:
                _debug_log(f'[extractMemories] fork_agent failed: {result.error}', self._session_id)
                return None

            # 更新游标
            if messages:
                self._last_message_id = getattr(messages[-1], 'id', None)

            written_paths = extract_written_paths(result.final_messages)
            turn_count = count_assistant_messages(result.final_messages)

            # 自动更新 MEMORY.md 索引（确保即使 subagent 未完成索引更新，主代码也能处理）
            if written_paths:
                try:
                    _update_memory_index(memory_dir, written_paths)
                    _debug_log(f'[extractMemories] updated MEMORY.md index', self._session_id)
                except Exception as e:
                    _debug_log(f'[extractMemories] failed to update MEMORY.md: {e}', self._session_id)

            # 模拟 UsageStats（fork_agent 当前未返回 token 统计，可扩展）
            usage = UsageStats()

            _debug_log(
                f'[extractMemories] finished — {len(written_paths)} files written, '
                f'turns={turn_count}',
                self._session_id
            )

            if written_paths:
                _debug_log(f'[extractMemories] memories saved: {", ".join(written_paths)}', self._session_id)
            else:
                _debug_log('[extractMemories] no memories saved this run', self._session_id)

            memory_paths = [p for p in written_paths if os.path.basename(p) != 'MEMORY.md']

            if memory_paths and append_system_message:
                msg = SystemMessage(
                    content=f'Saved {len(memory_paths)} memories: {", ".join(memory_paths)}'
                )
                append_system_message(msg)

            return MemoryExtractionResult(
                messages=result.final_messages,
                total_usage=usage,
            )

        except Exception as e:
            _debug_log(f'[extractMemories] error: {e}', self._session_id)
            return None

    async def drain(self, timeout_ms: int = 60000) -> None:
        """等待所有进行中的提取完成。"""
        if not self._in_flight_events:
            return

        timeout_sec = timeout_ms / 1000
        start = time.time()
        events = list(self._in_flight_events)
        for event in events:
            remaining = timeout_sec - (time.time() - start)
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(event.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                _debug_log('[extractMemories] drain timeout', self._session_id)
                break

_runner: Optional[ExtractMemoriesRunner] = None


def init_extract_memories() -> None:
    """初始化记忆提取系统，从 memdir config 读取配置。"""
    global _runner
    _runner = ExtractMemoriesRunner()


def get_runner() -> ExtractMemoriesRunner:
    """获取提取器实例。"""
    global _runner
    if _runner is None:
        raise RuntimeError("ExtractMemoriesRunner not initialized. Call init_extract_memories(main_agent) first.")
    return _runner


async def execute_extract_memories(
    messages: List[BaseMessage],
    append_system_message: Optional[AppendSystemMessageFn] = None,
) -> None:
    """在 query loop 结束时运行记忆提取。"""
    runner = get_runner()
    await runner.execute(messages, append_system_message)


async def drain_pending_extraction(timeout_ms: int = 60000) -> None:
    """等待所有进行中的提取完成。"""
    runner = get_runner()
    await runner.drain(timeout_ms)


from utils.logging_utils import get_session_logger

# 记忆提取专用的日志基础目录
_EXTRACT_LOG_BASE_DIR = "logs/extract_memory"


def _get_extract_memory_logger(session_id: str) -> logging.Logger:
    """获取会话级别的记忆提取日志记录器"""
    return get_session_logger("extract_memories", session_id)


def _debug_log(message: str, session_id: Optional[str] = None) -> None:
    """调试日志，写入会话级别的日志文件"""
    if not session_id:
        return
    logger = _get_extract_memory_logger(session_id)
    logger.debug(message)