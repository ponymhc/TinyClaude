"""
Skill Tool - 调用预定义技能

技能工具实现，允许模型调用 skills/ 目录下的技能。
技能通过 SKILL.md 文件定义，包含 YAML frontmatter 和提示内容。

使用方法：
    skill: 技能名称（如 "docx"）
    args: 可选参数，替换提示中的 $ARGUMENTS 占位符
"""

from pathlib import Path
from typing import Type, Optional, ClassVar

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from utils.skill_loader import load_skill_prompt, scan_skills


class SkillInput(BaseModel):
    skill: str = Field(description="要调用的技能名称（如 'docx', 'pdf_to_markdown'）")
    args: Optional[str] = Field(default=None, description="可选参数，替换提示中的 $ARGUMENTS 占位符")


class SkillTool(BaseTool):
    name: str = "Skill"
    description: str = (
        "调用预定义技能。技能是存储在 skills/ 目录下的提示模板，"
        "用于执行特定任务（如文档处理、内容生成等）。"
    )
    args_schema: Type[BaseModel] = SkillInput
    base_dir: Path = Path(__file__).parent.parent  # 项目根目录

    def _run(self, skill: str, args: Optional[str] = None) -> str:
        """
        执行技能调用
        """
        # 验证技能是否存在
        skills = scan_skills(self.base_dir)
        skill_names = [s.name for s in skills]
        if skill not in skill_names:
            return f"❌ 未知技能: {skill}。可用技能: {', '.join(skill_names)}"

        # 加载技能提示
        prompt = load_skill_prompt(skill, self.base_dir, args or "")
        if prompt is None:
            return f"❌ 无法加载技能 {skill} 的提示内容"

        # 返回技能提示，作为工具输出
        # 注意：理想情况下，技能提示应作为消息注入上下文，但当前版本先作为输出返回
        return prompt

    async def _arun(self, skill: str, args: Optional[str] = None) -> str:
        """异步版本"""
        return self._run(skill, args)


def create_skill_tool(base_dir: Optional[Path] = None) -> SkillTool:
    """
    创建技能工具实例
    """
    if base_dir is None:
        base_dir = Path(__file__).parent.parent
    return SkillTool(base_dir=base_dir)