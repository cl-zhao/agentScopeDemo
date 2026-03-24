"""已注册智能体技能文件的受限读取器。"""

from __future__ import annotations

from pathlib import Path

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse


class SkillFileReader:
    """仅允许读取已注册技能对应的完整 `SKILL.md` 内容。"""

    def __init__(self, skill_dirs: dict[str, str | Path]) -> None:
        """将已注册技能目录规范化为解析后的 Path 对象。"""
        self._skill_dirs = {
            skill_name: Path(skill_dir).resolve()
            for skill_name, skill_dir in skill_dirs.items()
        }

    async def read_agent_skill_file(self, skill_name: str) -> ToolResponse:
        """返回已注册技能的完整 Markdown 内容。"""
        skill_dir = self._skill_dirs.get(skill_name)
        if skill_dir is None:
            return self._error_response(
                f"未知的智能体技能：{skill_name}。请使用已注册的技能名称之一。",
            )

        skill_md = (skill_dir / "SKILL.md").resolve()
        try:
            skill_md.relative_to(skill_dir)
        except ValueError:
            return self._error_response("请求的技能路径无效。")

        if not skill_md.is_file():
            return self._error_response(
                f"已注册技能 {skill_name} 缺少 SKILL.md 文件。",
            )

        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=skill_md.read_text(encoding="utf-8"),
                ),
            ],
        )

    def _error_response(self, message: str) -> ToolResponse:
        """为技能文件读取失败构造纯文本工具响应。"""
        return ToolResponse(content=[TextBlock(type="text", text=message)])
