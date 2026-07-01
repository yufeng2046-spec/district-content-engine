"""Writer agent: generates video scripts from research briefs."""

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


def write_track_a(research_brief: str) -> str:
    """Generate Track A script (community tour)."""
    system = load_prompt("track_a.txt")
    user = f"""根据以下研究简报，写一条杨凌小区探盘视频脚本（90-120秒）。

{research_brief}

严格按简报里的数据写，不要编造任何数字。每个部分都必须带 [画面：xxx] 的B-roll提示。"""
    return chat(system, user, temperature=0.9, max_tokens=4096)


def write_track_b(research_brief: str) -> str:
    """Generate Track B script (region commentary)."""
    system = load_prompt("track_b.txt")
    user = f"""根据以下研究简报，写一条杨凌区域房产口播脚本（60-90秒）。

{research_brief}

严格按简报里的数据写，不要编造。给不同预算的人具体的购房建议。"""
    return chat(system, user, temperature=0.9, max_tokens=4096)
