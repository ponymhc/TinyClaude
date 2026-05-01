"""
Prompt 模块 - 管理 System Prompt 的生成与组装

设计原则：
- static_sections.py: 只返回静态 SystemMessage
- dynamic_sections.py: 只返回动态 SystemMessage
- builder.py: 负责融合两者，输出最终消息列表

使用示例：
    from prompt import DynamicSectionContext, get_system_messages

    ctx = DynamicSectionContext(cwd="/project", shell="bash")
    messages = get_system_messages(ctx)

    # 直接用于 LangChain
    llm.invoke(messages)
"""

from .static_sections import (
    get_simple_intro_section,
    get_simple_system_section,
    get_simple_doing_tasks_section,
    get_actions_section,
    get_using_your_tools_section,
    build_static_messages,
)

from .dynamic_sections import (
    DynamicSectionContext,
    build_dynamic_messages,
)

from .builder import (
    SystemPromptBuilder,
    get_cached_static_messages,
    invalidate_static_cache,
    get_system_messages,
    get_system_prompt_text,
)

# 导出 LangChain 类型
from langchain_core.messages import SystemMessage, BaseMessage

__all__ = [
    # LangChain 类型
    "SystemMessage",
    "BaseMessage",
    # 动态部分
    "DynamicSectionContext",
    "build_dynamic_messages",
    # 静态部分
    "get_simple_intro_section",
    "get_simple_system_section",
    "get_simple_doing_tasks_section",
    "get_actions_section",
    "get_using_your_tools_section",
    "build_static_messages",
    # 构建器
    "SystemPromptBuilder",
    "get_cached_static_messages",
    "invalidate_static_cache",
    "get_system_messages",
    "get_system_prompt_text",
]
