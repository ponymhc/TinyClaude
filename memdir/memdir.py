import os
from dataclasses import dataclass
from typing import List, Optional

from .memory_types import (
    MEMORY_FRONTMATTER_EXAMPLE,
    TYPES_SECTION_INDIVIDUAL,
    TRUSTING_RECALL_SECTION,
    WHAT_NOT_TO_SAVE_SECTION,
    WHEN_TO_ACCESS_SECTION,
)
from .paths import (
    MAX_ENTRYPOINT_BYTES,
    MAX_ENTRYPOINT_LINES,
    AUTO_MEM_ENTRYPOINT_NAME,
    get_auto_mem_path,
    is_auto_memory_enabled,
)


# =============================================================================
# 类型定义
# =============================================================================


@dataclass
class EntrypointTruncation:
    """截断结果。"""
    content: str
    line_count: int
    byte_count: int
    was_line_truncated: bool
    was_byte_truncated: bool


# =============================================================================
# 常量
# =============================================================================

AUTO_MEM_DISPLAY_NAME = "auto memory"
DIR_EXISTS_GUIDANCE = (
    "This directory already exists — write to it directly with the Write tool "
    "(do not run mkdir or check for its existence)."
)
DIRS_EXIST_GUIDANCE = (
    "Both directories already exist — write to them directly with the Write tool "
    "(do not run mkdir or check for their existence)."
)


# =============================================================================
# 截断逻辑
# =============================================================================


def truncate_entrypoint_content(raw: str) -> EntrypointTruncation:
    """
    截断 MEMORY.md 内容到行数和字节数上限，
    追加一个警告说明触发了哪个限制。

    先按行截断（自然边界），然后在最后一个换行符处字节截断，
    这样不会在行中间切断。
    """
    trimmed = raw.strip()
    content_lines = trimmed.split("\n")
    line_count = len(content_lines)
    byte_count = len(trimmed.encode("utf-8"))

    was_line_truncated = line_count > MAX_ENTRYPOINT_LINES
    # 检查原始字节数 — 长行是字节上限的失败模式
    was_byte_truncated = byte_count > MAX_ENTRYPOINT_BYTES

    if not was_line_truncated and not was_byte_truncated:
        return EntrypointTruncation(
            content=trimmed,
            line_count=line_count,
            byte_count=byte_count,
            was_line_truncated=False,
            was_byte_truncated=False,
        )

    truncated = (
        "\n".join(content_lines[:MAX_ENTRYPOINT_LINES])
        if was_line_truncated
        else trimmed
    )

    if len(truncated.encode("utf-8")) > MAX_ENTRYPOINT_BYTES:
        # 在最后一个换行符处截断
        truncated_bytes = truncated.encode("utf-8")[:MAX_ENTRYPOINT_BYTES]
        cut_at = truncated.rfind("\n", 0, len(truncated_bytes))
        if cut_at <= 0:
            cut_at = MAX_ENTRYPOINT_BYTES - 1
        truncated = truncated[:cut_at]

    reason = (
        f"{_format_file_size(byte_count)} (limit: {_format_file_size(MAX_ENTRYPOINT_BYTES)}) — index entries are too long"
        if was_byte_truncated and not was_line_truncated
        else (
            f"{line_count} lines (limit: {MAX_ENTRYPOINT_LINES})"
            if was_line_truncated and not was_byte_truncated
            else f"{line_count} lines and {_format_file_size(byte_count)}"
        )
    )

    return EntrypointTruncation(
        content=(
            truncated
            + f"\n\n> WARNING: {AUTO_MEM_ENTRYPOINT_NAME} is {reason}. "
            "Only part of it was loaded. Keep index entries to one line under ~200 chars; "
            "move detail into topic files."
        ),
        line_count=line_count,
        byte_count=byte_count,
        was_line_truncated=was_line_truncated,
        was_byte_truncated=was_byte_truncated,
    )


def _format_file_size(size_bytes: int) -> str:
    """格式化文件大小。"""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    return f"{size_bytes / (1024 * 1024):.1f}MB"


# =============================================================================
# 目录操作
# =============================================================================


async def ensure_memory_dir_exists(memory_dir: str) -> None:
    """
    确保记忆目录存在。幂等 — 每个会话调用一次，
    这样模型可以始终直接写入而不先检查存在性。
    os.makedirs 是递归的，已经处理 EEXIST。
    
    同时确保 MEMORY.md 入口文件存在。
    """
    try:
        os.makedirs(memory_dir, exist_ok=True)
        
        # 确保 MEMORY.md 存在（如果不存在则创建空文件）
        from .paths import get_auto_mem_entrypoint_name
        entrypoint_name = get_auto_mem_entrypoint_name()
        memory_md_path = os.path.join(memory_dir, entrypoint_name)
        
        if not os.path.exists(memory_md_path):
            with open(memory_md_path, "w", encoding="utf-8") as f:
                f.write("# Memory Index\n\n")
    except OSError as e:
        # EEXIST 由 os.makedirs 内部处理。
        # 到达这里的是真正的问题 (EACCES/EPERM/EROFS)。
        # TODO: 日志记录
        pass


# =============================================================================
# 提示构建
# =============================================================================


def build_memory_lines(
    display_name: str,
    memory_dir: str,
    extra_guidelines: Optional[List[str]] = None,
    skip_index: bool = False,
) -> str:
    """
    构建记忆行为指令（不含 MEMORY.md 内容）。

    将记忆限制为封闭的四类型分类 (user / feedback / project / reference) —
    可以从当前项目状态推导的内容（代码模式、架构、git 历史）被明确排除。
    """
    if skip_index:
        how_to_save = f"""\
## How to save memories

Write each memory to its own file (e.g., `user_role.md`, `feedback_testing.md`) using this frontmatter format:

{MEMORY_FRONTMATTER_EXAMPLE}

- Keep the name, description, and type fields in memory files up-to-date with the content
- Organize memory semantically by topic, not chronologically
- Update or remove memories that turn out to be wrong or outdated
- Do not write duplicate memories. First check if there is an existing memory you can update before writing a new one."""
    else:
        how_to_save = f"""\
## How to save memories

Saving a memory is a two-step process:

**Step 1** — write the memory to its own file (e.g., `user_role.md`, `feedback_testing.md`) using this frontmatter format:

{MEMORY_FRONTMATTER_EXAMPLE}

**Step 2** — add a pointer to that file in `{AUTO_MEM_ENTRYPOINT_NAME}`. `{AUTO_MEM_ENTRYPOINT_NAME}` is an index, not a memory — each entry should be one line, under ~150 characters: `- [Title](file.md) — one-line hook`. It has no frontmatter. Never write memory content directly into `{AUTO_MEM_ENTRYPOINT_NAME}`.

- `{AUTO_MEM_ENTRYPOINT_NAME}` is always loaded into your conversation context — lines after {MAX_ENTRYPOINT_LINES} will be truncated, so keep the index concise
- Keep the name, description, and type fields in memory files up-to-date with the content
- Organize memory semantically by topic, not chronologically
- Update or remove memories that turn out to be wrong or outdated
- Do not write duplicate memories. First check if there is an existing memory you can update before writing a new one."""

    lines = f"""\
# {display_name}

You have a persistent, file-based memory system at `{memory_dir}`. {DIR_EXISTS_GUIDANCE}

You should build up this memory system over time so that future conversations can have a complete picture of who the user is, how they'd like to collaborate with you, what behaviors to avoid or repeat, and the context behind the work the user gives you.

If the user explicitly asks you to remember something, save it immediately as whichever type fits best. If they ask you to forget something, find and remove the relevant entry.

{TYPES_SECTION_INDIVIDUAL}

{WHAT_NOT_TO_SAVE_SECTION}

{how_to_save}

{WHEN_TO_ACCESS_SECTION}

{TRUSTING_RECALL_SECTION}

## Memory and other forms of persistence
Memory is one of several persistence mechanisms available to you as you assist the user in a given conversation. The distinction is often that memory can be recalled in future conversations and should not be used for persisting information that is only useful within the scope of the current conversation.
- When to use or update a plan instead of memory: If you are about to start a non-trivial implementation task and you'd like to reach alignment with the user on your approach you should use a Plan rather than saving this information to memory. Similarly, if you already have a plan within the conversation and you have changed your approach persist that change by updating the plan rather than saving a memory.
- When to use or update tasks instead of memory: When you need to break your work in current conversation into discrete steps or keep track of your progress use tasks instead of saving to memory. Tasks are great for persisting information about the work that needs to be done in the current conversation, but memory should be reserved for information that will be useful in future conversations.

"""

    if extra_guidelines:
        lines += "\n".join(extra_guidelines) + "\n\n"

    return lines


# =============================================================================
# 主入口函数
# =============================================================================


async def load_memory_prompt(
    skip_index: bool = False,
    extra_guidelines: Optional[List[str]] = None,
) -> Optional[str]:
    """
    加载统一的记忆提示以包含在系统提示中。

    当自动记忆被禁用时返回 None。
    """
    if not is_auto_memory_enabled():
        return None

    auto_dir = get_auto_mem_path()

    # 确保目录存在
    await ensure_memory_dir_exists(auto_dir)

    return build_memory_lines(
        AUTO_MEM_DISPLAY_NAME,
        auto_dir,
        extra_guidelines,
        skip_index,
    )
