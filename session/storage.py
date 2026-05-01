"""
会话存储抽象层
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from utils.token import TokenUsage


@dataclass
class SessionMetadata:
    """会话元数据"""
    session_id: str
    created_at: datetime
    updated_at: datetime
    turn_count: int = 0
    title: Optional[str] = None
    tags: List[str] = None
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self):
        if self.tags is None:
            self.tags = []


@dataclass
class StoredMessage:
    """序列化后的消息"""
    type: str  # human, ai, tool
    content: str
    turn_id: int = 0  # 会话轮次 ID，同一轮的所有消息共享相同的 turn_id
    tool_calls: Optional[List[dict]] = None
    tool_call_id: Optional[str] = None
    additional_kwargs: Optional[dict] = None
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


class SessionStorage(ABC):
    """会话存储抽象基类"""

    @abstractmethod
    async def save_message(self, session_id: str, message: StoredMessage) -> None:
        """保存单条消息"""

    @abstractmethod
    async def get_messages(self, session_id: str) -> List[StoredMessage]:
        """获取会话的所有消息"""

    @abstractmethod
    async def get_messages_tail(self, session_id: str, limit: int) -> List[StoredMessage]:
        """获取最近 N 条消息"""

    @abstractmethod
    async def save_metadata(self, metadata: SessionMetadata) -> None:
        """保存会话元数据"""

    @abstractmethod
    async def get_metadata(self, session_id: str) -> Optional[SessionMetadata]:
        """获取会话元数据"""

    @abstractmethod
    async def list_sessions(self) -> List[SessionMetadata]:
        """列出所有会话"""

    @abstractmethod
    async def delete_session(self, session_id: str) -> None:
        """删除会话"""

    @abstractmethod
    async def close(self) -> None:
        """关闭存储连接"""

    async def update_token_stats(self, session_id: str, token_usage) -> None:
        """
        更新会话的 token 统计

        Args:
            session_id: 会话 ID
            token_usage: Token 使用统计 (TokenUsage 对象或兼容的 dict)
        """
        from session import TokenUsage  # 延迟导入避免循环
        metadata = await self.get_metadata(session_id)
        if metadata:
            if isinstance(token_usage, TokenUsage):
                metadata.total_tokens = token_usage.total
                metadata.input_tokens = token_usage.input_tokens
                metadata.output_tokens = token_usage.output_tokens
            else:
                # 兼容 dict 格式
                metadata.total_tokens = token_usage.get("total", 0)
                metadata.input_tokens = token_usage.get("input_tokens", 0)
                metadata.output_tokens = token_usage.get("output_tokens", 0)
            metadata.updated_at = datetime.now()
            await self.save_metadata(metadata)
