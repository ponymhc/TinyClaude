from typing import List, AsyncGenerator, Any, Tuple, Dict, Optional
from langgraph.graph import StateGraph, add_messages
from langgraph.prebuilt import ToolNode
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, AIMessageChunk, ToolMessage
from langchain_core.tools import BaseTool
from langchain_litellm import ChatLiteLLM
from typing import TypedDict, Annotated
from datetime import datetime
import sys

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

class ChunkParser:

    @staticmethod
    def parse(chunk: AIMessageChunk) -> Tuple[str, bool]:
        text_parts = []
        is_thinking = False
        if isinstance(chunk.content, str):
            text_parts.append(chunk.content)
            is_thinking = False
        elif isinstance(chunk.content, list):
            for block in chunk.content:
                if isinstance(block, dict):
                    if block.get("type") == "thinking":
                        text_parts.append(block.get("thinking", ""))
                        is_thinking = True
                    elif block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                        is_thinking = False
                    else:
                        text_parts.append(str(block))
                        is_thinking = False
                else:
                    text_parts.append(str(block))
                    is_thinking = False
        else:
            text_parts.append(str(chunk.content))
            is_thinking = False
        return "".join(text_parts), is_thinking


class EventProcessor:
    def __init__(self):
        self.tools_just_finished = False
        self.full_response = ""
        self.final_messages = None
        self._emitted_tool_starts = set()

    async def process(self, event: Dict[str, Any]) -> AsyncGenerator[Dict[str, Any], None]:
        kind = event["event"]
        handler = getattr(self, f"_handle_{kind}", None)
        if handler is None:
            return
        async for out_event in handler(event):
            yield out_event

    async def _handle_on_chat_model_stream(self, event: Dict[str, Any]) -> AsyncGenerator[Dict[str, Any], None]:
        
        chunk = event["data"]["chunk"]

        tool_call_chunks = getattr(chunk, "tool_call_chunks", None)
        if tool_call_chunks:
            for tc_chunk in tool_call_chunks:
                if tc_chunk.get("name"):
                    yield {
                        "type": "tool_call_name",
                        "tool": tc_chunk["name"]
                    }
                if tc_chunk.get("args"):
                    yield {
                        "type": "tool_call_args",
                        "args": tc_chunk["args"]
                    }
            return

        if getattr(chunk, "tool_calls", None):
            return
        text, is_thinking = ChunkParser.parse(chunk)
        if not text:
            return
        if self.tools_just_finished:
            yield {"type": "new_response"}
            self.tools_just_finished = False
        self.full_response += text

        yield {"type": "token", "content": text, "thinking": is_thinking}

    async def _handle_on_tool_start(self, event: Dict[str, Any]) -> AsyncGenerator[Dict[str, Any], None]:
        yield {
            "type": "tool_start",
            "tool": event.get("name"),
            "input": str(event["data"].get("input")),
        }

    async def _handle_on_tool_end(self, event: Dict[str, Any]) -> AsyncGenerator[Dict[str, Any], None]:
        yield {
            "type": "tool_end",
            "tool": event.get("name"),
            "output": str(event["data"].get("output")),
        }
        self.tools_just_finished = True

    async def _handle_on_chain_end(self, event: Dict[str, Any]) -> AsyncGenerator[Dict[str, Any], None]:
        """LangGraph 的 astream_events 会发出 on_tool_start/on_tool_end 事件。
        这里只提取最终消息列表，不发送 tool_start/tool_end（已由其他 handler 处理）。"""
        output = event.get("data", {}).get("output")
        if not output or "messages" not in output:
            return
        
        messages = output["messages"]
        self.final_messages = messages
        return
        yield  # 使函数成为 async generator（永不执行）

    def get_full_response(self) -> str:
        return self.full_response

    def get_final_messages(self):
        return self.final_messages


class AgentLoop:

    def __init__(
        self,
        llm: ChatLiteLLM,
        tools: List[BaseTool],
        model_name: Optional[str] = None,
        max_turns: int = 50,
    ):
        self.llm = llm.bind_tools(tools) if hasattr(llm, "bind_tools") else llm
        self.tools = tools
        self.model_name = model_name
        self.max_turns = max_turns
        self.graph = self._build_graph()

    def _should_continue(self, state: AgentState) -> str:

        last_message = state["messages"][-1]

        if not isinstance(last_message, AIMessage):
            return "__end__"
        
        has_tool_calls = bool(
            getattr(last_message, "tool_calls", []) or 
            getattr(last_message, "invalid_tool_calls", [])
        )
        
        if has_tool_calls:
            return "tools"
        else:
            return "__end__"
            
    def _parse_message(self, msg: AIMessage) -> AIMessage:
        reasoning_content = msg.additional_kwargs.get('reasoning_content', '')
        msg.reasoning_content = reasoning_content
        
        final_content = ""
        if isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, str):
                    final_content = block
        
        if final_content:
            msg.content = final_content
        else:
            msg.content = reasoning_content
            
        return msg

    async def _acall_model(self, state: AgentState):
        
        messages = state['messages']
        msg_count = len(messages)
        last_msg_type = type(messages[-1]).__name__ if messages else "none"
        
        tool_call_ids = set()
        tool_msg_ids = set()
        for msg in messages:
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_call_ids.add(tc.get('id'))
            if isinstance(msg, ToolMessage):
                tool_msg_ids.add(msg.tool_call_id)
        
        missing = tool_call_ids - tool_msg_ids
        if missing:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [_acall_model] WARNING: missing ToolMessage for ids={missing}", file=sys.stderr)
        

        response = await self.llm.ainvoke(state['messages'])
        cleaned_response = self._parse_message(response)
        return {"messages": [cleaned_response]}

    def _build_graph(self):
        workflow = StateGraph(AgentState)

        workflow.add_node("agent", self._acall_model)
        workflow.add_node("tools", ToolNode(self.tools))

        workflow.set_entry_point("agent")
        workflow.add_conditional_edges("agent", self._should_continue)
        workflow.add_edge("tools", "agent")

        return workflow.compile()

    async def astream(
        self,
        message: str,
        history: list[BaseMessage] = [],
        max_turns: Optional[int] = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        messages = history + [HumanMessage(content=message)]
        processor = EventProcessor()
        
        turns_limit = max_turns if max_turns is not None else self.max_turns
        recursion_limit = turns_limit

        async for event in self.graph.astream_events(
            {"messages": messages},
            version="v2",
            config={"recursion_limit": recursion_limit},
        ):
            async for out_event in processor.process(event):
                yield out_event

        yield {
            "type": "done",
            "content": processor.get_full_response(),
            "messages": processor.get_final_messages()
        }
