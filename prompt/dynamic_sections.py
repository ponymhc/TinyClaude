"""
Dynamic Sections - 动态 Prompt 部分

这些部分与会话状态相关，仅在会话级缓存。
包括：session_guidance, env_info, language
"""

from typing import List, Optional
from dataclasses import dataclass

from langchain_core.messages import SystemMessage
import os


@dataclass
class DynamicSectionContext:
    """动态 section 的上下文信息"""
    cwd: Optional[str] = None
    shell: str = "bash"
    language: str = "auto"  # auto, en, zh, etc.
    has_agent_tool: bool = False
    has_skill_tool: bool = False
    available_skills: Optional[List[str]] = None


def _build_session_guidance(ctx: DynamicSectionContext) -> SystemMessage | None:
    """会话特定指导"""
    sections = []

    # Agent 工具指导
    if ctx.has_agent_tool:
        sections.append("""## Agent Tool (Sub-agents)

You may use the Agent tool to spawn sub-agents for specialized tasks. Use sparingly - direct tool use is usually more efficient.
- Keep the task description focused and specific
- Sub-agents operate in the same project context
- Results are returned to you and should be presented to the user""")

    # Skill 工具指导
    if ctx.has_skill_tool and ctx.available_skills:
        skills_list = ", ".join(f"`{s}`" for s in ctx.available_skills)
        sections.append(f"""## User Skills

The user has access to the following skills:
- {skills_list}

Use the Skill tool when the user explicitly asks for a skill, or when you recognize that a specific skill would be helpful for the current task.""")

    if not sections:
        return None

    return SystemMessage(content="\n\n".join(sections))


def _build_env_info(ctx: DynamicSectionContext) -> SystemMessage:
    """环境信息"""
    if os.path.exists(ctx.cwd): 
        env_lines = [
            f"- Working directory: {ctx.cwd or '/unknown'}",
            f"- Shell: {ctx.shell}"
        ]
    else:
        raise ValueError(f"Working directory {ctx.cwd} does not exist")

    return SystemMessage(content=f"""# Environment

You have been invoked in the following environment:
{chr(10).join(env_lines)}""")


def _build_language(ctx: DynamicSectionContext) -> SystemMessage:
    """语言偏好设置"""
    if ctx.language == "auto":
        content = """# Language

Detect the user's language from their input and respond in that language. Default to English if the language cannot be determined."""
    else:
        content = f"""# Language

Respond in {ctx.language} when the user writes in {ctx.language}."""

    return SystemMessage(content=content)


def build_dynamic_messages(ctx: DynamicSectionContext) -> List[SystemMessage]:
    """
    构建所有动态 sections 为 SystemMessage 列表

    Args:
        ctx: 动态 section 上下文

    Returns:
        动态 SystemMessage 列表
    """
    messages: List[SystemMessage] = []

    session_guidance = _build_session_guidance(ctx)
    if session_guidance:
        messages.append(session_guidance)

    messages.append(_build_env_info(ctx))

    messages.append(_build_language(ctx))

    return messages
