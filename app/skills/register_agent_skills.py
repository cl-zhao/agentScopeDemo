from pathlib import Path

from agentscope.tool import Toolkit


def register_agent_skills(toolkit: Toolkit):
    """Register agent skills."""
    base_path = Path(__file__).parent
    path = str(base_path) + "/sample_skill"
    toolkit.register_agent_skill(path)
    path = str(base_path) + "/quantity_skill"
    toolkit.register_agent_skill(path)

    agent_skill_prompt = toolkit.get_agent_skill_prompt()
    print("智能体技能提示词:")
    print(agent_skill_prompt)
