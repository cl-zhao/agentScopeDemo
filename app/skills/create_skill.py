import os


def main():
    os.makedirs("sample_skill", exist_ok=True)
    with open("sample_skill/SKILL.md", "w", encoding="utf-8") as f:
        f.write(
            """
---
name: sample_skill
description: 用于演示的示例智能体技能
---

# 示例技能
这是一个示例技能，什么都不会做
"""
            ,
        )


if __name__ == "__main__":
    main()
