"""DeepSeek LLM wrapper (litellm) — with retry, validation, timeout."""

import logging
from litellm import completion
from config import DEEPSEEK_KEY, DEEPSEEK_MODEL

logger = logging.getLogger(__name__)


def _validate_response(resp) -> str:
    """Extract content from LLM response, raising on empty/missing."""
    if not resp or not resp.choices:
        raise ValueError("LLM returned empty response (no choices)")
    content = resp.choices[0].message.content
    if not content or not content.strip():
        raise ValueError("LLM returned empty content")
    return content


def chat(
    system: str,
    user: str,
    temperature: float = 0.9,
    max_tokens: int = 4096,
    max_retries: int = 3,
    timeout: int = 60,
) -> str:
    """Call DeepSeek via litellm with retry on failure.

    Args:
        system: system prompt
        user: user message
        temperature: sampling temperature
        max_tokens: max output tokens
        max_retries: retry count on failure (exponential backoff 1s/2s/4s)
        timeout: request timeout in seconds

    Returns:
        LLM response text

    Raises:
        ValueError: after all retries exhausted with empty/invalid response
    """
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = completion(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                api_key=DEEPSEEK_KEY,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
            )
            return _validate_response(resp)
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                wait_s = 2 ** (attempt - 1)  # 1, 2, 4 seconds
                logger.warning(
                    "LLM call failed (attempt %d/%d, retrying in %ds): %s",
                    attempt, max_retries, wait_s, e,
                )
                import time
                time.sleep(wait_s)
            else:
                logger.error(
                    "LLM call failed after %d attempts: %s", max_retries, e,
                )

    raise ValueError(f"LLM call failed after {max_retries} retries: {last_error}")
