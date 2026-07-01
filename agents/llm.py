"""DeepSeek LLM wrapper (litellm)."""

from litellm import completion
from config import DEEPSEEK_KEY, DEEPSEEK_MODEL


def chat(system: str, user: str, temperature: float = 0.9, max_tokens: int = 4096) -> str:
    resp = completion(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        api_key=DEEPSEEK_KEY,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return resp.choices[0].message.content
