"""
统一配置加载模块

集中管理所有子模块配置：
- 自动记忆 (automemory)
- 会话管理 (session)
- Session Memory (session_memory)
- LLM 模型 (models)

配置文件位置：
- config/settings.yaml - 统一配置
- config/models.yaml - 模型配置
- config/.env - API 密钥
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field
from tools import get_all_tools_list

# =============================================================================
# 配置路径解析
# =============================================================================

def _get_project_root() -> Path:
    """获取项目根目录"""
    current_file = Path(__file__).resolve()
    # config/config.py -> 项目根目录
    return current_file.parent.parent


def find_settings_file() -> str:
    """
    查找配置文件。
    优先级：环境变量 > config/settings.yaml
    """
    # 1. 环境变量指定
    env_path = os.environ.get("TINY_ClAUDE_CONFIG_PATH")
    if env_path and os.path.isfile(env_path):
        return os.path.abspath(env_path)

    # 2. 默认路径: config/settings.yaml
    default_path = _get_project_root() / "config" / "settings.yaml"
    if default_path.is_file():
        return str(default_path)

    return None


def find_models_file() -> str:
    """
    查找模型配置文件。
    优先级：环境变量 > config/models.yaml
    """
    # 1. 环境变量指定
    env_path = os.environ.get("TINY_ClAUDE_MODELS_CONFIG_PATH")
    if env_path and os.path.isfile(env_path):
        return os.path.abspath(env_path)

    # 2. 默认路径: config/models.yaml
    default_path = _get_project_root() / "config" / "models.yaml"
    if default_path.is_file():
        return str(default_path)

    return None


# =============================================================================
# Pydantic 配置模型
# =============================================================================

class AutoMemoryConfig(BaseModel):
    """自动记忆功能配置"""
    enabled: bool = Field(default=True, description="是否启用自动记忆功能")
    dirname: str = Field(default="memory", description="记忆子目录名称（与 base_dir 拼接）")
    entrypoint_name: str = Field(default="MEMORY.md", description="入口点文件名")
    max_entrypoint_lines: int = Field(default=200, description="入口点最大行数")
    max_entrypoint_bytes: int = Field(default=25000, description="入口点最大字节数")
    logs_subdir: str = Field(default="logs", description="日志子目录名称")
    max_memory_files: int = Field(default=200, description="最大记忆文件数")
    max_frontmatter_lines: int = Field(default=30, description="frontmatter 最大行数")
    exclude_patterns: list[str] = Field(
        default_factory=lambda: ["MEMORY.md", ".git", "__pycache__", "*.pyc"],
        description="扫描时排除的文件模式"
    )
    extraction_model: Optional[str] = Field(default="qwen3_8b", description="记忆提取专用模型名称")


class TokenBudgetConfig(BaseModel):
    """Token 预算配置"""
    max_tokens: int = Field(default=200_000, ge=0, description="最大 token 数")
    warning_threshold: float = Field(default=0.8, ge=0, le=1, description="警告阈值")
    auto_compact_threshold: float = Field(default=0.9, ge=0, le=1, description="自动压缩阈值")


class StorageConfig(BaseModel):
    """存储配置"""
    dirname: str = Field(default="session_storage", description="会话子目录名称（与 base_dir 拼接）")
    max_messages_in_memory: int = Field(default=100, ge=1, description="内存缓存的最大消息数")


class AgentConfig(BaseModel):
    """Agent 配置"""
    model: str = Field(default="qwen3_8b", description="使用的模型名称")
    dirname: str = Field(default="workspace", description="工作目录（与 base_dir 拼接）")
    shell: str = Field(default="bash", description="shell 类型")
    python_path: str = Field(default='python', description='python解释器路径')
    language: str = Field(default="auto", description="语言偏好")
    has_agent_tool: bool = Field(default=False, description="是否启用 Agent 工具")
    has_skill_tool: bool = Field(default=False, description="是否启用 Skill 工具")
    available_skills: list[str] = Field(default_factory=list, description="可用技能列表")
    tools: Optional[list[str]] = Field(default=None, description="启用的工具列表，None 表示全部")


class SessionConfig(BaseModel):
    """会话管理配置"""
    storage: StorageConfig = Field(default_factory=StorageConfig, description="存储配置")
    token_budget: TokenBudgetConfig = Field(default_factory=TokenBudgetConfig, description="Token 预算配置")
    max_turns: Optional[int] = Field(default=None, ge=1, description="最大轮次限制")
    agent: AgentConfig = Field(default_factory=AgentConfig, description="Agent 配置")
    session_memory: "SessionMemoryConfig" = Field(default_factory=lambda: SessionMemoryConfig(), description="Session Memory 配置")


class SessionMemoryConfig(BaseModel):
    """Session Memory 配置"""
    enabled: bool = Field(default=True, description="是否启用")
    minimum_message_tokens_to_init: int = Field(default=1000, description="初始化阈值")
    minimum_tokens_between_update: int = Field(default=500, description="更新间隔阈值")
    tool_calls_between_updates: int = Field(default=3, description="工具调用更新间隔")
    max_turns: int = Field(default=50, description="子代理最大循环次数")
    model_name: Optional[str] = Field(default="qwen3_8b", description="子代理使用的模型名称")
    max_section_length: int = Field(default=2000, description="每个部分的最大 token 数")
    max_total_tokens: int = Field(default=12000, description="总最大 token 数")


class LLMModelConfig(BaseModel):
    """LLM 模型配置"""
    provider: str = Field(description="provider name")
    model: str = Field(description="model name")
    api_key: str = Field(description="api key 环境变量名")
    base_url: Optional[str] = Field(default=None, description="base url 环境变量名")
    temperature: float = Field(default=0.7, description="temperature")
    streaming: bool = Field(default=True, description="streaming")
    reasoning_effort: Optional[str] = Field(default=None, description="reasoning effort")
    timeout: Optional[int] = Field(default=None, description="request timeout in seconds")


class ModelsConfig(BaseModel):
    """所有 LLM 模型配置"""
    deepseek_chat: Optional[LLMModelConfig] = None
    deepseek_reasoner: Optional[LLMModelConfig] = None
    qwen3_8b: Optional[LLMModelConfig] = None
    deepseek_r1_distill_qwen_7b: Optional[LLMModelConfig] = None

    class Config:
        extra = "allow"  # 允许额外字段


class UnifiedConfig(BaseModel):
    """统一配置根模型"""
    base_dir: str = Field(default="~/workspace/research/agent/TinyClaude", description="全局基础目录")
    automemory: AutoMemoryConfig = Field(default_factory=AutoMemoryConfig, description="自动记忆配置")
    session: SessionConfig = Field(default_factory=SessionConfig, description="会话管理配置")
    models_config_path: str = Field(default="config/models.yaml", description="模型配置文件路径")


# =============================================================================
# 配置加载
# =============================================================================

def _load_yaml(path: str) -> dict[str, Any]:
    """从 YAML 文件加载配置"""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def load_unified_config() -> UnifiedConfig:
    """加载统一配置"""
    settings_path = find_settings_file()

    if settings_path and os.path.isfile(settings_path):
        try:
            config_dict = _load_yaml(settings_path)
            return UnifiedConfig(**config_dict)
        except Exception as e:
            print(f"[config] Warning: failed to load config from {settings_path}: {e}")

    return UnifiedConfig()


@lru_cache(maxsize=1)
def load_models_config() -> ModelsConfig:
    """加载模型配置"""
    models_path = find_models_file()

    if models_path and os.path.isfile(models_path):
        try:
            config_dict = _load_yaml(models_path)
            return ModelsConfig(**config_dict)
        except Exception as e:
            print(f"[config] Warning: failed to load models config from {models_path}: {e}")

    return ModelsConfig()


def reload_all_config() -> None:
    """重新加载所有配置（清除缓存）"""
    load_unified_config.cache_clear()
    load_models_config.cache_clear()


# =============================================================================
# 便捷访问函数
# =============================================================================

def _get_base_dir() -> str:
    """获取展开后的全局 base_dir"""
    base = load_unified_config().base_dir
    if base.startswith("~/"):
        base = os.path.join(Path.home(), base[2:])
    return base


def _get_cwd_from_config(agent_config: Optional[AgentConfig] = None) -> str:
    """从 agent 配置获取完整工作目录（base_dir + dirname）"""
    if agent_config is None:
        agent_config = get_session_config().agent
    base = _get_base_dir()
    return os.path.join(base, agent_config.dirname)

def get_config() -> UnifiedConfig:
    """获取统一配置"""
    return load_unified_config()


def get_automemory_config() -> AutoMemoryConfig:
    """获取自动记忆配置"""
    return load_unified_config().automemory


def get_session_config() -> SessionConfig:
    """获取会话管理配置"""
    return load_unified_config().session


def get_session_memory_config() -> SessionMemoryConfig:
    """获取 Session Memory 配置"""
    return load_unified_config().session.session_memory


def get_models_config() -> ModelsConfig:
    """获取模型配置"""
    return load_models_config()


def get_model_config(model_name: str) -> Optional[LLMModelConfig]:
    """获取指定模型配置"""
    models = load_models_config()
    return getattr(models, model_name, None)


def is_auto_memory_enabled() -> bool:
    """检查自动记忆功能是否启用"""
    return get_automemory_config().enabled


def is_session_memory_enabled() -> bool:
    """检查 Session Memory 功能是否启用"""
    return get_session_memory_config().enabled


def get_memory_base_dir() -> str:
    """获取记忆存储完整目录（base_dir + dirname）"""
    base = load_unified_config().base_dir
    if base.startswith("~/"):
        base = os.path.join(Path.home(), base[2:])
    dirname = get_automemory_config().dirname
    return os.path.join(base, dirname)


def get_session_storage_dir() -> str:
    """获取会话存储目录（base_dir + dirname）"""
    config = load_unified_config()
    base = config.base_dir
    if base.startswith("~/"):
        base = os.path.join(Path.home(), base[2:])
    dirname = config.session.storage.dirname
    return os.path.join(base, dirname)


def get_session_memory_dir() -> str:
    """获取 Session Memory 目录（使用 session.storage.dirname）"""
    config = load_unified_config()
    base = config.base_dir
    if base.startswith("~/"):
        base = os.path.join(Path.home(), base[2:])
    dirname = config.session.storage.dirname
    return os.path.join(base, dirname)


# =============================================================================
# 工厂方法
# =============================================================================

def create_agent(
    agent_config: Optional[AgentConfig] = None,
    tools: Optional[list] = None,
) -> "AgentLoop":
    """
    从配置创建 AgentLoop 实例

    Args:
        agent_config: Agent 配置，为 None 时使用默认配置
        tools: 额外的工具列表，为 None 时根据配置启用默认工具

    Returns:
        AgentLoop 实例
    """
    from langchain_core.messages import SystemMessage
    from agent.agent_factory import AgentLoop as _AgentLoop
    from agent.model.llm_factory import LLMFactory

    if agent_config is None:
        agent_config = get_session_config().agent

    # 创建 LLM
    llm = LLMFactory.create_llm(agent_config.model)

    # 获取工具列表
    if tools is None:
        
        cwd = _get_cwd_from_config(agent_config)
        tools = get_all_tools_list(
            cwd, 
            python_path=agent_config.python_path, 
            has_skill_tool=agent_config.has_skill_tool
        )

    # 创建 Agent
    return _AgentLoop(llm=llm, tools=tools)


def create_system_messages(
    agent_config: Optional[AgentConfig] = None,
) -> "list":
    """
    从配置创建 SystemMessage 列表

    Args:
        agent_config: Agent 配置，为 None 时使用默认配置

    Returns:
        SystemMessage 列表
    """
    from langchain_core.messages import SystemMessage
    from prompt import DynamicSectionContext, get_system_messages

    if agent_config is None:
        agent_config = get_session_config().agent

    cwd = _get_cwd_from_config(agent_config)

    # 动态扫描可用技能（如果启用了技能工具且未指定技能列表）
    available_skills = agent_config.available_skills
    if agent_config.has_skill_tool and not available_skills:
        try:
            from utils.skill_loader import scan_skills
            from pathlib import Path
            # 项目根目录是 cwd 的父目录（cwd 是 workspace 目录）
            project_root = Path(cwd).parent
            skills = scan_skills(project_root)
            available_skills = [skill.name for skill in skills]
        except Exception as e:
            print(f"[config] Warning: failed to scan skills: {e}")
            available_skills = []

    ctx = DynamicSectionContext(
        cwd=cwd,
        shell=agent_config.shell,
        language=agent_config.language,
        has_agent_tool=agent_config.has_agent_tool,
        has_skill_tool=agent_config.has_skill_tool,
        available_skills=available_skills,
    )

    return get_system_messages(ctx)


def create_session_manager(
    session_config: Optional["SessionConfig"] = None,
    agent_config: Optional[AgentConfig] = None,
    tools: Optional[list] = None,
    system_messages: Optional["list"] = None,
) -> "SessionManager":
    """
    从配置创建完整的 SessionManager 实例

    一站式创建：自动初始化 Agent、Storage、TokenBudget

    Args:
        session_config: 会话配置，为 None 时使用默认配置
        agent_config: Agent 配置，为 None 时使用 session_config.agent
        tools: 额外的工具列表
        system_messages: 自定义 SystemMessage 列表，为 None 时根据 agent_config 生成

    Returns:
        SessionManager 实例（未创建会话，需调用 create_session）
    """
    from session.session import SessionManager
    from session.config import SessionManagerConfig as SMConfig
    from session.config import StorageConfig as SMStorageConfig, TokenBudgetConfig as SMTBConfig
    from utils.token import TokenBudget

    if session_config is None:
        session_config = get_session_config()

    # 创建 Agent
    if agent_config is None:
        agent_config = session_config.agent

    agent = create_agent(agent_config, tools)

    # 创建 System Messages
    if system_messages is None:
        system_messages = create_system_messages(agent_config)

    # 转换配置
    sm_config = SMConfig(
        storage=SMStorageConfig(
            base_dir=_get_base_dir(),
            dirname=session_config.storage.dirname,
            max_messages_in_memory=session_config.storage.max_messages_in_memory,
        ),
        token_budget=SMTBConfig(
            max_tokens=session_config.token_budget.max_tokens,
            warning_threshold=session_config.token_budget.warning_threshold,
            auto_compact_threshold=session_config.token_budget.auto_compact_threshold,
        ),
        max_turns=session_config.max_turns,
    )

    # 计算日志目录
    base_dir = _get_base_dir()
    logs_dir = os.path.join(base_dir, "logs", "session_memory")

    # 创建 SessionManager
    return SessionManager.from_config(agent, sm_config, system_messages=system_messages, logs_dir=logs_dir)


def get_default_session_config() -> SessionConfig:
    """获取默认会话配置"""
    return get_session_config()
