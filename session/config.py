"""
会话配置模块

使用统一配置 (config/config.py)。

导入方式:
    from config.config import get_session_config
    from session.config import SessionManagerConfig, get_config  # 向后兼容
"""

import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from config.config import (
    SessionConfig as UnifiedSessionConfig,
    StorageConfig as UnifiedStorageConfig,
    TokenBudgetConfig as UnifiedTokenBudgetConfig,
    AgentConfig as UnifiedAgentConfig,
    get_session_config as _get_unified_session_config,
    reload_all_config as _reload_unified_config,
)


# =============================================================================
# 向后兼容的配置模型
# =============================================================================

class TokenBudgetConfig(BaseModel):
    """Token 预算配置"""
    max_tokens: int = Field(default=200_000, ge=0)
    warning_threshold: float = Field(default=0.8, ge=0, le=1)
    auto_compact_threshold: float = Field(default=0.9, ge=0, le=1)


class StorageConfig(BaseModel):
    """存储配置"""
    base_dir: str  # 由 create_session_manager 传入
    dirname: str
    max_messages_in_memory: int = 100

    @property
    def storage_dir(self) -> str:
        base = self.base_dir
        if base.startswith("~/"):
            base = str(Path.home() / base[2:])
        return str(Path(base) / self.dirname)


class AgentConfig(BaseModel):
    """Agent 配置（向后兼容别名）"""
    model: str = "qwen3_8b"
    dirname: str = "workspace"  # 与 base_dir 拼接
    shell: str = "bash"
    language: str = "auto"
    has_agent_tool: bool = False
    has_skill_tool: bool = False
    available_skills: list[str] = []


class SessionManagerConfig(BaseModel):
    """SessionManager 配置"""
    storage: StorageConfig
    token_budget: TokenBudgetConfig
    max_turns: Optional[int] = None
    agent: Optional[AgentConfig] = None


# =============================================================================
# 配置访问（代理到统一配置）
# =============================================================================

def get_config() -> SessionManagerConfig:
    """获取会话配置（使用统一配置）"""
    from config.config import load_unified_config
    unified = _get_unified_session_config()
    config = load_unified_config()
    return SessionManagerConfig(
        storage=StorageConfig(
            base_dir=config.base_dir,
            dirname=unified.storage.dirname,
            max_messages_in_memory=unified.storage.max_messages_in_memory,
        ),
        token_budget=TokenBudgetConfig(
            max_tokens=unified.token_budget.max_tokens,
            warning_threshold=unified.token_budget.warning_threshold,
            auto_compact_threshold=unified.token_budget.auto_compact_threshold,
        ),
        max_turns=unified.max_turns,
    )


def reload_config() -> SessionManagerConfig:
    """重新加载配置"""
    _reload_unified_config()
    return get_config()
