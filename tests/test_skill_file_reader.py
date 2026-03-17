from __future__ import annotations

from pathlib import Path

import pytest

from app.tools.skill_file_reader import SkillFileReader


def _skill_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "app" / "skills" / "quantity_skill"


def _text_from_response(response: object) -> str:
    first_block = response.content[0]
    if isinstance(first_block, dict):
        return str(first_block["text"])
    return str(first_block.text)


@pytest.mark.asyncio
async def test_read_agent_skill_file_returns_registered_skill_markdown() -> None:
    reader = SkillFileReader(
        {"order_complete_quantity_query": _skill_dir()},
    )

    response = await reader.read_agent_skill_file("order_complete_quantity_query")
    text = _text_from_response(response)

    assert text.startswith("---")
    assert "order_complete_quantity_query" in text
    assert "工具使用顺序" in text


@pytest.mark.asyncio
async def test_read_agent_skill_file_rejects_unknown_skill() -> None:
    reader = SkillFileReader(
        {"order_complete_quantity_query": _skill_dir()},
    )

    response = await reader.read_agent_skill_file("../quantity_skill")
    text = _text_from_response(response)

    assert "Unknown agent skill" in text
