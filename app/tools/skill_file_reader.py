"""Restricted reader for registered agent skill files."""

from __future__ import annotations

from pathlib import Path

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse


class SkillFileReader:
    """Read the full SKILL.md content for registered agent skills only."""

    def __init__(self, skill_dirs: dict[str, str | Path]) -> None:
        self._skill_dirs = {
            skill_name: Path(skill_dir).resolve()
            for skill_name, skill_dir in skill_dirs.items()
        }

    async def read_agent_skill_file(self, skill_name: str) -> ToolResponse:
        """Return the full markdown content for a registered skill."""
        skill_dir = self._skill_dirs.get(skill_name)
        if skill_dir is None:
            return self._error_response(
                f"Unknown agent skill: {skill_name}. Use one of the registered skill names.",
            )

        skill_md = (skill_dir / "SKILL.md").resolve()
        try:
            skill_md.relative_to(skill_dir)
        except ValueError:
            return self._error_response("The requested skill path is invalid.")

        if not skill_md.is_file():
            return self._error_response(
                f"SKILL.md not found for registered skill: {skill_name}.",
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
        return ToolResponse(content=[TextBlock(type="text", text=message)])
