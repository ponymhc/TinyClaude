"""
Skill Loader - 加载技能目录并构建上下文消息

技能加载器实现模式：
1. 扫描 skills/ 目录获取技能元数据（名称、描述）
2. 动态构建技能列表消息，注入为 system-reminder
3. 提供按需加载技能完整内容的函数
"""

import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

# 尝试导入 HumanMessage，如果失败则使用模拟类
try:
    from langchain_core.messages import HumanMessage
except ImportError:
    # 定义模拟的 HumanMessage 类
    class HumanMessage:
        def __init__(self, content: str, additional_kwargs: dict = None):
            self.content = content
            self.additional_kwargs = additional_kwargs or {}


def safe_read_text(filepath: Path) -> str:
    """安全读取文本文件，忽略编码错误"""
    try:
        return filepath.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        # 尝试其他编码
        for encoding in ['latin-1', 'cp1252', 'gbk', 'gb2312']:
            try:
                return filepath.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        # 如果所有编码都失败，返回空字符串
        return ""


class SkillDefinition:
    """技能定义，包含名称、描述和内容"""
    def __init__(self, name: str, description: str, content: str, directory: Path):
        self.name = name
        self.description = description
        self.content = content  # SKILL.md 的完整内容（包括 YAML frontmatter）
        self.directory = directory
    
    def get_prompt(self) -> str:
        """返回技能的提示文本（不含 YAML frontmatter），类似 getPromptForCommand"""
        # 如果内容以 --- 开头，则去除 YAML frontmatter
        if self.content.startswith("---"):
            parts = self.content.split("---", 2)
            if len(parts) >= 3:
                return parts[2].strip()
        return self.content.strip()
    
    def format_metadata(self) -> str:
        """格式化技能元数据，用于技能列表"""
        # 限制描述长度，避免单个技能占用过多空间
        max_desc_length = 80
        if len(self.description) > max_desc_length:
            short_desc = self.description[:max_desc_length] + "..."
        else:
            short_desc = self.description
        return f"- **/{self.name}**: {short_desc}"


def scan_skills(base_dir: Path) -> List[SkillDefinition]:
    """
    扫描 skills/ 目录，返回技能定义列表
    
    Args:
        base_dir: 项目基目录（包含 skills/ 子目录）
    
    Returns:
        技能定义列表
    """
    skills_dir = base_dir / "skills"
    if not skills_dir.exists():
        return []
    
    skills = []
    for skill_md in sorted(skills_dir.rglob("SKILL.md")):
        try:
            content = safe_read_text(skill_md)
            # 解析 YAML frontmatter
            meta = {}
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    meta = yaml.safe_load(parts[1]) or {}
            
            name = meta.get("name", skill_md.parent.name)
            description = meta.get("description", "")
            
            skill = SkillDefinition(
                name=name,
                description=description,
                content=content,
                directory=skill_md.parent
            )
            skills.append(skill)
        except Exception as e:
            print(f"⚠️ 加载技能 {skill_md} 时出错: {e}")
    
    return skills


def build_skills_listing(skills: List[SkillDefinition]) -> str:
    """
    构建技能列表字符串（只包含元数据，不包含完整内容）
    技能列表消息
    
    Args:
        skills: 技能定义列表
    
    Returns:
        格式化的技能列表字符串
    """
    if not skills:
        return ""
    
    lines = ["# 可用技能"]
    lines.append("")
    lines.append("以下是所有可用技能的列表。当用户请求相关功能时，可以使用对应的技能。")
    lines.append("")
    
    for skill in skills:
        lines.append(skill.format_metadata())
    
    return "\n".join(lines)


def load_skill_prompt(skill_name: str, base_dir: Optional[Path] = None, args: str = "") -> Optional[str]:
    """
    动态加载指定技能的完整提示内容，类似 getPromptForCommand
    
    Args:
        skill_name: 技能名称
        base_dir: 项目基目录，如果为 None 则使用当前文件的父目录的父目录
        args: 技能参数
    
    Returns:
        格式化后的技能提示内容，或 None 如果技能未找到
    """
    if base_dir is None:
        base_dir = Path(__file__).parent.parent
    
    skills = scan_skills(base_dir)
    for skill in skills:
        if skill.name == skill_name:
            # 获取技能提示文本
            prompt = skill.get_prompt()
            
            # TODO: 实现参数替换，类似 substituteArguments
            # TODO: 实现环境变量替换，如 ${CLAUDE_SKILL_DIR}
            # TODO: 实现 shell 命令执行，类似 executeShellCommandsInPrompt
            
            # 简单参数替换示例
            if args:
                prompt = prompt.replace("$ARGUMENTS", args)
            
            # 添加技能标题
            formatted = f"# 技能: {skill.name}\n\n{prompt}"
            
            return formatted
    
    return None


def load_skills_context(base_dir: Optional[Path] = None) -> List[HumanMessage]:
    """
    加载技能上下文并返回 HumanMessage 列表
    只包含技能列表，不包含完整内容
    
    Args:
        base_dir: 项目基目录，如果为 None 则使用当前文件的父目录的父目录
    
    Returns:
        HumanMessage 列表，包含包装在 <system-reminder> 中的技能列表
    """
    if base_dir is None:
        base_dir = Path(__file__).parent.parent
    
    skills = scan_skills(base_dir)
    if not skills:
        return []
    
    # 构建技能列表
    listing_text = build_skills_listing(skills)
    
    # 包装在 <system-reminder> 中
    wrapped = f"<system-reminder>\n{listing_text}\n</system-reminder>"
    
    # 返回 HumanMessage，标记为元数据
    return [HumanMessage(
        content=wrapped,
        additional_kwargs={"is_meta": True}
    )]
