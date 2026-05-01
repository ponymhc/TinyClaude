"""
Prompt Builder - 负责融合静态和动态 Prompt

职责：
1. 静态部分：可全局缓存（与工具集合相关）
2. 动态部分：会话级缓存（与用户配置/会话状态相关）
3. 最终融合：在 builder 中组装为完整的消息列表
"""

from typing import List, Optional
from langchain_core.messages import SystemMessage, BaseMessage

from .static_sections import build_static_messages
from .dynamic_sections import DynamicSectionContext, build_dynamic_messages


# ============================================================================
# 全局缓存的静态 messages
# ============================================================================
_cached_static_messages: Optional[List[SystemMessage]] = None


def get_cached_static_messages() -> List[SystemMessage]:
    """
    获取缓存的静态 SystemMessage 列表

    Returns:
        静态 SystemMessage 列表
    """
    global _cached_static_messages

    if _cached_static_messages is None:
        _cached_static_messages = build_static_messages()

    return _cached_static_messages


def invalidate_static_cache() -> None:
    """使静态 prompt 缓存失效"""
    global _cached_static_messages
    _cached_static_messages = None


# ============================================================================
# System Prompt 构建器
# ============================================================================
class SystemPromptBuilder:
    """
    System Prompt 构建器

    融合静态和动态部分，生成完整的 SystemMessage 列表

    使用示例：
        ctx = DynamicSectionContext(cwd="/project", shell="bash")
        builder = SystemPromptBuilder()
        messages = builder.build(ctx)

        # 直接用于 LangChain
        llm.invoke(messages)
    """

    def __init__(self, custom_static: Optional[List[SystemMessage]] = None):
        """
        初始化构建器

        Args:
            custom_static: 可选的自定义静态 SystemMessage 列表
        """
        self._custom_static = custom_static

    def build(self, ctx: DynamicSectionContext) -> List[SystemMessage]:
        """
        构建完整的 system prompt 消息列表

        Args:
            ctx: 动态 section 上下文

        Returns:
            完整的 SystemMessage 列表，可直接用于 LangChain
        """
        # 静态部分
        if self._custom_static:
            static_messages = self._custom_static
        else:
            static_messages = get_cached_static_messages()

        # 动态部分
        dynamic_messages = build_dynamic_messages(ctx)

        # 融合
        return self._merge(static_messages, dynamic_messages)

    def _merge(
        self,
        static: List[SystemMessage],
        dynamic: List[SystemMessage],
    ) -> List[SystemMessage]:
        """
        融合静态和动态 messages

        Args:
            static: 静态 SystemMessage 列表
            dynamic: 动态 SystemMessage 列表

        Returns:
            融合后的 SystemMessage 列表
        """
        # 简单的拼接策略
        # 如果需要更复杂的合并策略，可以在这里扩展
        return static + dynamic


# ============================================================================
# 便捷接口
# ============================================================================
def get_system_messages(ctx: DynamicSectionContext) -> List[SystemMessage]:
    """
    获取完整的 system prompt 消息列表

    Args:
        ctx: 动态 section 上下文

    Returns:
        SystemMessage 列表，可直接用于 LangChain
    """
    builder = SystemPromptBuilder()
    return builder.build(ctx)


def get_system_prompt_text(ctx: DynamicSectionContext) -> str:
    """
    获取完整的 system prompt（字符串格式，用于日志/调试）

    Args:
        ctx: 动态 section 上下文

    Returns:
        完整的 system prompt 字符串
    """
    messages = get_system_messages(ctx)
    return "\n\n".join(msg.content for msg in messages)
