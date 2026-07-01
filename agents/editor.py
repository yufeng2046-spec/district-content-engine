"""Editor agent: compliance review + de-AI polish."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.llm import chat

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load_prompt(name: str) -> str:
    path = PROMPT_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def edit(script: str, research_brief: str) -> str:
    """Review and polish a script for compliance, AI-voice, and factual accuracy."""
    system = load_prompt("editor.txt")
    user = f"""请审核以下脚本，确保合规、去AI味、事实准确。

## 研究简报（事实来源）
{research_brief[:3000]}

## 待审核脚本
{script}
"""
    return chat(system, user, temperature=0.7, max_tokens=4096)
