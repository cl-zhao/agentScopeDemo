from pathlib import Path

from agentscope.tool import Toolkit

AGENT_SKILL_INSTRUCTION = (
    "# Agent Skills\n"
    "The agent skills are folders of instructions and resources that improve "
    "performance on specialized tasks. Each registered skill has a "
    "`SKILL.md` file that defines how to use it.\n"
    "If a user's request matches a registered skill, you must call "
    "`read_agent_skill_file` first and read the full `SKILL.md` before "
    "using that skill. Do not guess or paraphrase unread skill content."
)

ENABLED_SKILL_DIRS = ("quantity_skill", "intelligent_dispatching","Text2Sql_skill")


def register_agent_skills(toolkit: Toolkit) -> None:
    """注册当前智能体可用的生产技能。"""
    base_path = Path(__file__).parent
    for directory_name in ENABLED_SKILL_DIRS:
        toolkit.register_agent_skill(str(base_path / directory_name))
