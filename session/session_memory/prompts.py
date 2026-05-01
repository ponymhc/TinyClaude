"""
Session Memory 提示模板模块
"""

import os
from typing import Dict

# 模板常量
MAX_SECTION_LENGTH = 2000
MAX_TOTAL_SESSION_MEMORY_TOKENS = 12000


# 默认模板
DEFAULT_SESSION_MEMORY_TEMPLATE = """
# 会话标题
_简短且有特色的 5-10 个词描述性标题。信息密集，无废话_

# 当前状态
_当前正在积极处理什么？尚未完成的待处理任务。立即的下一步行动_

# 任务说明
_用户要求构建什么？任何设计决策或其他解释性上下文_

# 文件和函数
_有哪些重要文件？简要说明它们包含什么以及为什么相关？_

# 工作流程
_通常按什么顺序运行哪些 bash 命令？如何解释它们的输出（如果不太明显）？_

# 错误与修正
_遇到的错误以及如何修复。用户纠正了什么？哪些方法失败了不应再尝试？_

# 代码库和系统文档
_有哪些重要的系统组件？它们如何工作/如何组合在一起？_

# 经验总结
_什么效果好？什么不好？应该避免什么？不要重复其他部分的内容_

# 关键结果
_如果用户要求特定的输出（如问题的答案、表格或其他文档），在此重复准确的结果_

# 工作日志
_一步一步，尝试了什么，做了什么？每一步非常简洁的总结_
"""


def get_default_update_prompt() -> str:
    """获取默认的更新提示"""
    return """重要提示：此消息及其中的指令不是实际用户对话的一部分。请勿在笔记内容中包含任何关于"记笔记"、"会话笔记提取"或这些更新指令的引用。

请根据上述用户对话（不包括此记笔记指令消息、系统提示条目或任何过去的会话摘要）来更新会话笔记文件。

文件 {notes_path} 已为您读取。以下是它的当前内容：
<current_notes_content>
{current_notes}
</current_notes_content>

您的唯一任务是使用 Edit 工具更新笔记文件，然后停止。您可以进行多次编辑（在需要时更新每个部分）——在一条消息中并行发出所有 Edit 工具调用。不要调用任何其他工具。

编辑的关键规则：
- 文件必须保持其精确结构，所有部分、标题和斜体描述保持完整
- 永远不要修改、删除或添加章节标题（以 '#' 开头的行，如 # 任务说明）
- 永远不要修改或删除斜体的 _章节描述_ 行（这些是紧接在每个标题后面的斜体行——它们以下划线开头和结尾）
- 斜体的 _章节描述_ 是模板指令，必须原样保留——它们指导每个部分应包含什么内容
- 只更新出现在每个现有部分的斜体 _章节描述_ 下方的实际内容
- 不要在现有结构之外添加任何新部分、摘要或信息
- 不要在笔记中引用此记笔记过程或指令
- 如果某个部分没有实质性的新见解，可以跳过更新。不要添加"No info yet"等填充内容，如果合适的话可以留空或不做编辑
- 为每个部分编写详细的、信息密集的内容——包括文件路径、函数名、错误消息、确切命令、技术细节等具体信息
- 对于"关键结果"，请包含用户请求的完整准确输出（例如完整表格、完整答案等）
- 每个部分保持在约 {max_section_length} 个 token/词以内——如果某个部分接近此限制，请通过删除不太重要的细节来精简它，同时保留最关键的信息
- 专注于可操作的、具体的信息，这些信息可以帮助他人理解或重现对话中讨论的工作
- 重要提示：始终更新"当前状态"以反映最近的工作——这对于压缩后的连续性至关重要

请使用 file_path 为 {notes_path} 的 Edit 工具

结构保持提醒：
每个部分都有两个必须完全按照当前文件中显示的方式保留的部分：
1. 章节标题（以 # 开头的行）
2. 斜体描述行（紧接在标题后面的 _斜体文本_ ——这是模板指令）

您只需要更新这两个保留行之后的实际内容。以下划线开头和结尾的斜体描述行是模板结构的一部分，不是要编辑或删除的内容。

编辑工具的关键规则（防止文件损坏）：
- 使用 Edit 工具时，old_string 必须只包含实际内容行——永远不要使用章节标题或斜体描述行作为 old_string
- 永远不要复制、移动或重复任何以 '#' 开头的行（章节标题）或两端都包含 '_' 的行（斜体描述）
- 如果您不小心在 old_string 中包含了标题/描述行，内容将被放错位置并损坏文件结构
- 只编辑包含实际笔记内容的行（斜体描述下方 的常规文本）

记住：并行使用 Edit 工具然后停止。编辑后不要继续。只包含来自实际用户对话的见解，永远不要来自这些记笔记指令。不要删除或更改章节标题或斜体的 _章节描述_。""".format(
        notes_path="{{notes_path}}",
        current_notes="{{current_notes}}",
        max_section_length=MAX_SECTION_LENGTH,
    )


def _get_template_dir() -> str:
    """获取模板目录（使用 session/memory 目录）"""
    from pathlib import Path
    return str(Path(__file__).parent)


def load_template() -> str:
    """加载模板（支持自定义模板）"""
    # 尝试从配置文件加载自定义模板
    template_path = os.path.join(
        _get_template_dir(),
        "template.md",
    )
    
    if os.path.exists(template_path):
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            pass
    
    return DEFAULT_SESSION_MEMORY_TEMPLATE


def load_update_prompt() -> str:
    """加载更新提示（支持自定义提示）"""
    prompt_path = os.path.join(
        _get_template_dir(),
        "prompt.md",
    )
    
    if os.path.exists(prompt_path):
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            pass
    
    return get_default_update_prompt()


def _rough_token_count(text: str) -> int:
    """粗略估算 token 数"""
    if not text:
        return 0
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - chinese_chars
    return int(chinese_chars * 2 + other_chars * 0.25)


def analyze_section_sizes(content: str) -> Dict[str, int]:
    """分析各部分的 token 数"""
    sections: Dict[str, int] = {}
    lines = content.split('\n')
    current_section = ''
    current_content: list = []

    for line in lines:
        if line.startswith('# '):
            if current_section and current_content:
                section_content = '\n'.join(current_content).strip()
                sections[current_section] = _rough_token_count(section_content)
            current_section = line
            current_content = []
        else:
            current_content.append(line)

    if current_section and current_content:
        section_content = '\n'.join(current_content).strip()
        sections[current_section] = _rough_token_count(section_content)

    return sections


def generate_section_reminders(section_sizes: Dict[str, int], total_tokens: int) -> str:
    """生成超长部分的提醒"""
    over_budget = total_tokens > MAX_TOTAL_SESSION_MEMORY_TOKENS
    
    oversized_sections = [
        f'- "{section}" 约 {tokens} tokens（限制：{MAX_SECTION_LENGTH}）'
        for section, tokens in section_sizes.items()
        if tokens > MAX_SECTION_LENGTH
    ]
    oversized_sections.sort(key=lambda x: int(x.split('约 ')[1].split(' ')[0]), reverse=True)

    if not oversized_sections and not over_budget:
        return ''

    parts = []
    
    if over_budget:
        parts.append(
            f"\n\n关键提醒：会话记忆文件当前约 {total_tokens} tokens，"
            f"超过了 {MAX_TOTAL_SESSION_MEMORY_TOKENS} tokens 的最大值。 "
            f"您必须精简文件以符合此预算。 "
            f"积极缩短过大篇幅的部分，删除不太重要的细节，"
            f"合并相关内容，并总结较早的条目。 "
            f'请优先保持"当前状态"和"错误与修正"的准确性和详细性。'
        )
    
    if oversized_sections:
        parts.append(
            f"\n\n{'关键提醒：' if over_budget else '重要提示：'}以下部分超过了每个部分的限制，必须精简：\n" + '\n'.join(oversized_sections)
        )
    
    return ''.join(parts)


def build_session_memory_update_prompt(current_notes: str, notes_path: str) -> str:
    """构建 Session Memory 更新提示"""
    prompt_template = load_update_prompt()
    
    # 分析部分大小
    section_sizes = analyze_section_sizes(current_notes)
    total_tokens = _rough_token_count(current_notes)
    section_reminders = generate_section_reminders(section_sizes, total_tokens)
    
    # 替换变量
    prompt = prompt_template.replace("{{notes_path}}", notes_path)
    prompt = prompt.replace("{{current_notes}}", current_notes)
    
    # 添加部分大小提醒
    return prompt + section_reminders


def is_session_memory_empty(content: str) -> bool:
    """检查 Session Memory 内容是否为空（只有模板）"""
    template = load_template()
    return content.strip() == template.strip()


def truncate_session_memory_for_compact(content: str) -> tuple:
    """
    截断过长的 Session Memory 章节。

    用于压缩时防止 Session Memory 消耗过多 token 预算。

    Returns:
        (截断后的内容, 是否被截断)
    """
    lines = content.split('\n')
    # 粗略估算：每 token 约 4 字符
    max_chars_per_section = MAX_SECTION_LENGTH * 4
    output_lines: list = []
    current_section_lines: list = []
    current_section_header = ''
    was_truncated = False

    for line in lines:
        if line.startswith('# '):
            # 处理上一个章节
            result = _flush_session_section(
                current_section_header,
                current_section_lines,
                max_chars_per_section,
            )
            output_lines.extend(result["lines"])
            was_truncated = was_truncated or result["was_truncated"]

            current_section_header = line
            current_section_lines = []
        else:
            current_section_lines.append(line)

    # 处理最后一个章节
    result = _flush_session_section(
        current_section_header,
        current_section_lines,
        max_chars_per_section,
    )
    output_lines.extend(result["lines"])
    was_truncated = was_truncated or result["was_truncated"]

    return '\n'.join(output_lines), was_truncated


def _flush_session_section(
    section_header: str,
    section_lines: list,
    max_chars: int,
) -> dict:
    """刷新一个章节，必要时截断"""
    if not section_header:
        return {"lines": section_lines, "was_truncated": False}

    section_content = '\n'.join(section_lines)
    if len(section_content) <= max_chars:
        return {"lines": [section_header] + section_lines, "was_truncated": False}

    # 在接近限制处截断
    kept_lines = [section_header]
    char_count = 0
    for line in section_lines:
        if char_count + len(line) + 1 > max_chars:
            break
        kept_lines.append(line)
        char_count += len(line) + 1

    kept_lines.append('\n[... 章节因过长被截断 ...]')
    return {"lines": kept_lines, "was_truncated": True}
