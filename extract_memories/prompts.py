"""
记忆提取提示模板。

这些模板用于构建后台提取 Agent 的提示。
"""

MEMORY_FRONTMATTER_EXAMPLE = '''---
title: "Memory Title"
type: <memory_type>
created: <ISO 8601 timestamp>
updated: <ISO 8601 timestamp>
---

Brief description of what this memory captures.'''

TYPES_SECTION_INDIVIDUAL = """## Memory Types

Save memories using one of these types:

- **preference**: How the user likes something done (formatting, naming, workflow preferences)
- **pattern**: A repeated behavior, habit, or recurring situation
- **rule**: Explicit instruction, policy, or constraint the user has given
- **fact**: Factual information about the user or their environment
- **skill**: User's demonstrated expertise or special capability
- **context**: Current project state, active work, or ongoing situation
- **learning**: What the user has recently learned or been told

Pick the most specific type that fits. When multiple types apply, prefer the more specific one."""


WHAT_NOT_TO_SAVE_SECTION = """## What NOT to save

Do NOT save as memory:
- Trivial details that can be inferred from context
- One-off comments that don't reflect ongoing preferences
- Information the user is clearly testing or experimenting with
- Content the user explicitly says they want to forget
- Sensitive information (passwords, keys, personal data)"""


def _build_opener(new_message_count: int, existing_memories: str) -> str:
    """构建提示开头部分。"""
    manifest = ""
    if existing_memories:
        manifest = f"""

## Existing memory files

{existing_memories}

Check this list before writing — update an existing file rather than creating a duplicate."""

    tools_note = (
        "Read, Grep, Glob, and read-only Bash (ls/find/cat/stat/wc/head/tail) are always permitted. "
        "Edit/Write are only allowed for paths inside the memory directory. "
        "All other tools will be denied. "
        "IMPORTANT: If a tool returns an error message (starts with 'Error:'), read it carefully and retry with the corrected path or command. Do NOT stop if you see errors — fix and retry."
    )

    turn_strategy = (
        "You have a limited turn budget. CRITICAL: Edit requires a RECENT Read of the same file. "
        "If you read a file early in your response, you MUST re-read it before editing. "
        "DO NOT stop after seeing an error message — analyze it, fix the path/command, and RETRY. "
        "Your job is NOT done until you have successfully read MEMORY.md and updated it. "
        "Recommended: turn 1 — Read MEMORY.md; turn 2 — Write memory files; turn 3 — Edit MEMORY.md index."
    )

    constraint = (
        f"You MUST only use content from the last ~{new_message_count} messages to update your persistent memories. "
        "Do not waste any turns attempting to investigate or verify that content further — "
        "no grepping source files, no reading code to confirm a pattern exists, no git commands."
    )

    return f"""You are now acting as the memory extraction subagent. Analyze the most recent ~{new_message_count} messages above and use them to update your persistent memory systems.

{tools_note}

{turn_strategy}

{constraint}{manifest}"""


def build_extract_auto_only_prompt(
    new_message_count: int,
    existing_memories: str,
    skip_index: bool = False,
) -> str:
    """
    构建自动提取提示。

    Args:
        new_message_count: 自上次提取以来的新消息数量
        existing_memories: 现有记忆文件列表（manifest）
        skip_index: 是否跳过 MEMORY.md 索引更新

    Returns:
        格式化的提示字符串
    """
    if skip_index:
        how_to_save = f"""## How to save memories

Write each memory to its own file (e.g., `user_role.md`, `feedback_testing.md`) using this frontmatter format:

{MEMORY_FRONTMATTER_EXAMPLE}

- Organize memory semantically by topic, not chronologically
- Update or remove memories that turn out to be wrong or outdated
- Do not write duplicate memories. First check if there is an existing memory you can update before writing a new one."""
    else:
        how_to_save = f"""## How to save memories

Saving a memory is a two-step process:

**Step 1** — write the memory to its own file (e.g., `user_role.md`, `feedback_testing.md`) using this frontmatter format:

{MEMORY_FRONTMATTER_EXAMPLE}

**Step 2** — add a pointer to that file in `MEMORY.md`. `MEMORY.md` is an index, not a memory — each entry should be one line, under ~150 characters: `- [Title](file.md) — one-line hook`. It has no frontmatter. Never write memory content directly into `MEMORY.md`.

- `MEMORY.md` is always loaded into your conversation context — lines after 200 will be truncated, so keep the index concise
- Organize memory semantically by topic, not chronologically
- Update or remove memories that turn out to be wrong or outdated
- Do not write duplicate memories. First check if there is an existing memory you can update before writing a new one."""

    opener = _build_opener(new_message_count, existing_memories)

    return f"""{opener}

If the user explicitly asks you to remember something, save it immediately as whichever type fits best. If they ask you to forget something, find and remove the relevant entry.

{TYPES_SECTION_INDIVIDUAL}

{WHAT_NOT_TO_SAVE_SECTION}

{how_to_save}"""
