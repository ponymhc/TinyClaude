import json
import uuid
import shutil
from pathlib import Path
from datetime import datetime
from typing import List, Optional, AsyncGenerator

from .storage import SessionStorage, SessionMetadata, StoredMessage

class FileSessionStorage(SessionStorage):
    """
    基于文件的会话存储

    目录结构:
        storage_dir/
        ├── {session_id}/
        │   ├── metadata.json
        │   └── messages.jsonl
        └── ...

    使用 JSONL 格式追加写入消息，适合高频写入场景
    """

    def __init__(
        self,
        storage_dir: str = "session_storage",
        max_messages_in_memory: int = 100,
        logs_dir: Optional[str] = None,
    ):
        self.storage_dir = Path(storage_dir).expanduser().resolve()
        self.max_messages_in_memory = max_messages_in_memory
        self.logs_dir = Path(logs_dir).expanduser().resolve() if logs_dir else None
        # 自动计算 extract_memories 日志目录
        if self.logs_dir:
            self.extract_logs_dir = self.logs_dir.parent / "extract_memories"
        else:
            self.extract_logs_dir = None
        self._memory_cache: dict[str, List[StoredMessage]] = {}

    def _ensure_dirs(self) -> None:
        """确保目录存在"""
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _get_session_dir(self, session_id: str) -> Path:
        return self.storage_dir / session_id

    def _get_messages_path(self, session_id: str) -> Path:
        return self._get_session_dir(session_id) / "messages.jsonl"

    def _get_metadata_path(self, session_id: str) -> Path:
        return self._get_session_dir(session_id) / "metadata.json"

    def _serialize_message(self, message: StoredMessage) -> str:
        """序列化消息为 JSONL 行"""
        data = {
            "type": message.type,
            "content": message.content,
            "turn_id": message.turn_id,
            "tool_calls": message.tool_calls,
            "tool_call_id": message.tool_call_id,
            "additional_kwargs": message.additional_kwargs,
            "created_at": message.created_at.isoformat(),
        }
        return json.dumps(data, ensure_ascii=False)

    def _deserialize_message(self, line: str) -> StoredMessage:
        """从 JSONL 行反序列化消息"""
        data = json.loads(line)
        return StoredMessage(
            type=data["type"],
            content=data["content"],
            turn_id=data.get("turn_id", 0),
            tool_calls=data.get("tool_calls"),
            tool_call_id=data.get("tool_call_id"),
            additional_kwargs=data.get("additional_kwargs"),
            created_at=datetime.fromisoformat(data["created_at"]),
        )

    async def create_session(self, title: Optional[str] = None) -> str:
        """创建新会话，返回 session_id"""
        self._ensure_dirs()
        session_id = str(uuid.uuid4())
        session_dir = self._get_session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)

        metadata = SessionMetadata(
            session_id=session_id,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            title=title or f"会话 {session_id[:8]}",
        )
        await self.save_metadata(metadata)
        return session_id

    async def save_message(self, session_id: str, message: StoredMessage) -> None:
        """追加保存消息到文件"""
        self._ensure_dirs()
        messages_path = self._get_messages_path(session_id)

        line = self._serialize_message(message) + "\n"
        with open(messages_path, "a", encoding="utf-8") as f:
            f.write(line)

        # 更新缓存
        if session_id not in self._memory_cache:
            self._memory_cache[session_id] = []
        self._memory_cache[session_id].append(message)

        # 截断缓存
        if len(self._memory_cache[session_id]) > self.max_messages_in_memory:
            self._memory_cache[session_id] = self._memory_cache[session_id][-self.max_messages_in_memory:]

        # 更新元数据的 updated_at
        metadata = await self.get_metadata(session_id)
        if metadata:
            metadata.updated_at = datetime.now()
            metadata.turn_count += 1
            await self.save_metadata(metadata)

    async def get_messages(self, session_id: str) -> List[StoredMessage]:
        """获取所有消息"""
        if session_id in self._memory_cache:
            return self._memory_cache[session_id]

        messages_path = self._get_messages_path(session_id)
        if not messages_path.exists():
            return []

        messages = []
        with open(messages_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    messages.append(self._deserialize_message(line))

        self._memory_cache[session_id] = messages[-self.max_messages_in_memory:]
        return messages

    async def get_messages_tail(self, session_id: str, limit: int) -> List[StoredMessage]:
        """获取最近 N 条消息"""
        messages = await self.get_messages(session_id)
        return messages[-limit:] if messages else []

    async def save_metadata(self, metadata: SessionMetadata) -> None:
        """保存元数据"""
        self._ensure_dirs()
        metadata_path = self._get_metadata_path(metadata.session_id)

        data = {
            "session_id": metadata.session_id,
            "created_at": metadata.created_at.isoformat(),
            "updated_at": metadata.updated_at.isoformat(),
            "turn_count": metadata.turn_count,
            "title": metadata.title,
            "tags": metadata.tags,
            "total_tokens": metadata.total_tokens,
            "input_tokens": metadata.input_tokens,
            "output_tokens": metadata.output_tokens,
        }

        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    async def get_metadata(self, session_id: str) -> Optional[SessionMetadata]:
        """获取元数据"""
        metadata_path = self._get_metadata_path(session_id)
        if not metadata_path.exists():
            return None

        with open(metadata_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return SessionMetadata(
            session_id=data["session_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            turn_count=data.get("turn_count", 0),
            title=data.get("title"),
            tags=data.get("tags", []),
            total_tokens=data.get("total_tokens", 0),
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
        )

    async def list_sessions(self) -> List[SessionMetadata]:
        """列出所有会话"""
        self._ensure_dirs()
        sessions = []

        if not self.storage_dir.exists():
            return sessions

        for session_dir in self.storage_dir.iterdir():
            if session_dir.is_dir():
                metadata = await self.get_metadata(session_dir.name)
                if metadata:
                    sessions.append(metadata)

        return sorted(sessions, key=lambda x: x.updated_at, reverse=True)

    async def delete_session(self, session_id: str) -> None:
        """删除会话及关联的所有日志"""
        # 删除会话目录
        session_dir = self._get_session_dir(session_id)
        if session_dir.exists():
            shutil.rmtree(session_dir)

        # 删除 session_memory 日志
        if self.logs_dir and self.logs_dir.exists():
            log_file = self.logs_dir / f"{session_id}.log"
            if log_file.exists():
                log_file.unlink()

        # 删除 extract_memories 日志
        if self.extract_logs_dir and self.extract_logs_dir.exists():
            extract_log_file = self.extract_logs_dir / f"{session_id}.log"
            if extract_log_file.exists():
                extract_log_file.unlink()

        # 清除内存缓存
        if session_id in self._memory_cache:
            del self._memory_cache[session_id]

    async def close(self) -> None:
        """关闭存储"""
        self._memory_cache.clear()
