import asyncio
import os
from dataclasses import dataclass
from typing import List, Optional

from .memory_scan import scan_memory_files, MemoryHeader
from .memory_age import memory_age
from .paths import (
    get_auto_mem_path,
    AUTO_MEM_ENTRYPOINT_NAME,
    MAX_ENTRYPOINT_LINES,
    MAX_ENTRYPOINT_BYTES,
)

@dataclass
class MemoryMetadata:
    """记忆元数据（不含内容）。"""
    filename: str
    file_path: str
    memory_type: Optional[str]
    description: Optional[str]
    age: str
    # frontmatter 其他字段
    name: Optional[str] = None


@dataclass
class MemdirIndex:
    """MEMORY.md 索引内容。"""
    content: str
    line_count: int
    byte_count: int
    was_truncated: bool


@dataclass
class MemdirContext:
    """记忆上下文（索引 + 元数据列表）。"""
    index: Optional[MemdirIndex]
    memories: List[MemoryMetadata]
    total_count: int

def _convert_index_paths_to_absolute(content: str, memory_dir: str) -> str:
    """
    将 MEMORY.md 索引中的相对路径转换为绝对路径。

    MEMORY.md 格式：- [Title](file.md) — one-line hook
    转换后：[Title](/absolute/path/to/file.md) — one-line hook
    """
    lines = content.split("\n")
    result_lines = []

    for line in lines:
        # 匹配 Markdown 链接格式: [Title](filename.md)
        # 使用正则表达式找到 (file.md 或 (*.md)
        import re
        # 匹配 [...]](xxx.md) 模式，xxx.md 是相对路径
        def replace_path(match):
            title = match.group(1)  # 链接标题
            filename = match.group(2)  # 文件名
            # 转换为绝对路径
            abs_path = os.path.join(memory_dir, filename)
            return f"[{title}]({abs_path})"

        # 匹配 markdown 链接: [任意内容](相对路径.md)
        pattern = r'\[([^\]]+)\]\(([^)]+\.md)\)'
        new_line = re.sub(pattern, replace_path, line)
        result_lines.append(new_line)

    return "\n".join(result_lines)


def read_memory_md(memory_dir: str) -> Optional[MemdirIndex]:
    """
    读取 MEMORY.md 入口文件（索引文件）。

    MEMORY.md 是索引文件，格式为：
    - [Title](file.md) — one-line hook

    返回时已将相对路径转换为绝对路径。
    """
    entrypoint_path = os.path.join(memory_dir, AUTO_MEM_ENTRYPOINT_NAME)

    if not os.path.exists(entrypoint_path):
        return None

    try:
        with open(entrypoint_path, "r", encoding="utf-8") as f:
            raw = f.read()

        trimmed = raw.strip()
        lines = trimmed.split("\n")
        line_count = len(lines)
        byte_count = len(trimmed.encode("utf-8"))

        was_truncated = line_count > MAX_ENTRYPOINT_LINES or byte_count > MAX_ENTRYPOINT_BYTES

        # 截断
        if was_truncated:
            if line_count > MAX_ENTRYPOINT_LINES:
                lines = lines[:MAX_ENTRYPOINT_LINES]
            content = "\n".join(lines)
            if len(content.encode("utf-8")) > MAX_ENTRYPOINT_BYTES:
                truncated_bytes = content.encode("utf-8")[:MAX_ENTRYPOINT_BYTES]
                cut_at = content.rfind("\n", 0, len(truncated_bytes))
                if cut_at <= 0:
                    cut_at = MAX_ENTRYPOINT_BYTES - 1
                content = content[:cut_at]
        else:
            content = trimmed

        # 将相对路径转换为绝对路径
        content = _convert_index_paths_to_absolute(content, memory_dir)

        return MemdirIndex(
            content=content,
            line_count=line_count,
            byte_count=byte_count,
            was_truncated=was_truncated,
        )
    except (OSError, IOError):
        return None


async def scan_memory_metadata(
    memory_dir: str,
    signal: Optional["asyncio.Event"] = None,
) -> List[MemoryMetadata]:
    """
    扫描记忆目录，只提取 frontmatter 元数据。

    只读取每个文件的前 30 行（frontmatter）用于获取：
    - filename
    - file_path
    - memory_type
    - description
    - name

    不读取正文内容。
    """
    # 使用已有的 scan_memory_files 函数（已只读取 frontmatter）
    headers = await scan_memory_files(memory_dir, signal)

    memories = []
    for h in headers:
        # 计算年龄
        age = memory_age(h.mtime_ms)

        memories.append(MemoryMetadata(
            filename=h.filename,
            file_path=h.file_path,
            memory_type=h.memory_type.value if h.memory_type else None,
            description=h.description,
            name=h.description,  # frontmatter.name 通常和 description 类似
            age=age,
        ))

    return memories

async def load_memdir_context(
    memory_dir: Optional[str] = None,
    signal: Optional["asyncio.Event"] = None,
) -> MemdirContext:
    """
    加载完整的记忆上下文（索引 + 元数据）。

    参数:
        memory_dir: 记忆目录路径（默认为 get_auto_mem_path()）
        signal: 可选的 asyncio.Event 用于中断

    返回:
        MemdirContext 对象，包含 MEMORY.md 索引和所有记忆的元数据
    """
    if memory_dir is None:
        memory_dir = get_auto_mem_path()

    # 1. 读取 MEMORY.md 索引（同步，因为需要截断逻辑）
    index = read_memory_md(memory_dir)

    # 2. 扫描其他记忆文件的 frontmatter（异步）
    memories = await scan_memory_metadata(memory_dir, signal)

    return MemdirContext(
        index=index,
        memories=memories,
        total_count=len(memories),
    )


def format_memdir_context(context: MemdirContext) -> str:
    """
    将记忆上下文格式化为文本，用于插入到 messages 中。

    格式：
    <system-reminder>
    # Memory Index

    ## MEMORY.md (index)
    - [Title](file.md) — hook
    - ...

    ## Available Memories (X files)
    - [1] [type] /absolute/path/to/file.md — saved X days ago
    - Description: ...
    ...
    </system-reminder>
    """
    sections = []

    sections.append("# Memory Index\n")

    # MEMORY.md 索引内容
    if context.index:
        sections.append("## MEMORY.md (index)")
        sections.append("")
        # 注意：MEMORY.md 索引中的路径保持相对路径，由 Read 工具处理
        sections.append(context.index.content)

        if context.index.was_truncated:
            sections.append("")
            sections.append(
                f"> [Truncated: {context.index.line_count} lines, "
                f"showing first {MAX_ENTRYPOINT_LINES} lines]"
            )
        sections.append("")
    else:
        sections.append("## MEMORY.md (index)")
        sections.append("")
        sections.append("No index file found.")
        sections.append("")

    # 记忆文件清单 - 使用完整路径
    if context.memories:
        sections.append(f"## Available Memories ({len(context.memories)} files)")
        sections.append("")
        sections.append(
            "Use the Read tool to access the full content of any memory file below."
        )
        sections.append("")

        for i, mem in enumerate(context.memories, 1):
            type_tag = f"[{mem.memory_type}] " if mem.memory_type else ""
            desc = f" — {mem.description}" if mem.description else ""
            # 使用 file_path（完整路径）而不是 filename
            file_path = mem.file_path if mem.file_path else mem.filename

            sections.append(f"- [{i}] {type_tag}{file_path} — saved {mem.age}{desc}")
    else:
        sections.append("## Available Memories")
        sections.append("")
        sections.append("No memory files found.")

    return "\n".join(sections)


def format_memdir_as_system_reminder(context: MemdirContext) -> str:
    """
    将记忆上下文包装在 <system-reminder> 标签中。
    """
    content = format_memdir_context(context)
    return f"<system-reminder>\n{content}\n</system-reminder>"


async def load_all_memories_for_context(
    memory_dir: Optional[str] = None,
    include_reminder_wrapper: bool = True,
    signal: Optional["asyncio.Event"] = None,
) -> List:
    """
    加载所有记忆并格式化为 LangChain HumanMessage。

    返回的 messages 结构：
    [HumanMessage(content="<system-reminder>...</system-reminder>", additional_kwargs={"is_meta": True})]

    参数:
        memory_dir: 记忆目录路径
        include_reminder_wrapper: 是否包装在 <system-reminder> 中
        signal: 可选的 asyncio.Event 用于中断

    返回:
        包含单个 HumanMessage 的列表，准备插入到 system prompt 之后
    """
    from langchain_core.messages import HumanMessage
    
    context = await load_memdir_context(memory_dir, signal)

    if include_reminder_wrapper:
        content = format_memdir_as_system_reminder(context)
    else:
        content = format_memdir_context(context)

    return [
        HumanMessage(
            content=content,
            additional_kwargs={"is_meta": True},  # 标记为元数据
        )
    ]

async def get_memory_summary(
    memory_dir: Optional[str] = None,
    signal: Optional["asyncio.Event"] = None,
) -> str:
    """
    获取记忆摘要（索引预览 + 文件列表）。

    用于快速检查记忆数量和新鲜度。
    """
    context = await load_memdir_context(memory_dir, signal)

    lines = [f"# Memory Summary"]
    lines.append(f"Total memory files: {context.total_count}")
    lines.append("")

    if context.index:
        index_lines = context.index.content.strip().split("\n")
        lines.append(f"## MEMORY.md Index ({len(index_lines)} entries)")
        # 只显示前 10 条
        for entry in index_lines[:10]:
            lines.append(entry)
        if len(index_lines) > 10:
            lines.append(f"... and {len(index_lines) - 10} more entries")
    else:
        lines.append("## MEMORY.md Index")
        lines.append("(no index file)")

    lines.append("")

    if context.memories:
        lines.append(f"## Memory Files ({len(context.memories)})")
        for i, mem in enumerate(context.memories[:10], 1):
            type_tag = f"[{mem.memory_type}] " if mem.memory_type else ""
            desc = f" — {mem.description}" if mem.description else ""
            lines.append(f"{i}. {type_tag}{mem.filename} — {mem.age}{desc}")
        if len(context.memories) > 10:
            lines.append(f"... and {len(context.memories) - 10} more files")
    else:
        lines.append("## Memory Files")
        lines.append("(no memory files)")

    return "\n".join(lines)
