import re
from typing import Pattern


_INTERJECTION_PATTERN: Pattern[str] = re.compile(
    r"\b(?:a+h+|o+h+|u+h+|u+m+|e+r+m+|e+r+|h+m+|ge+e+|go+sh+|eh+|hu+h+)\b(?:\s*[,\.\!\?…—–-]*)",
    flags=re.IGNORECASE,
)


def sanitize_agent_output(text: str) -> str:
    """Remove conversational filler interjections like 'Ah', 'Oh', 'Um', 'Uh', etc.

    Rules:
    - Removes standalone interjections (with repeated letters) regardless of case
    - Also removes immediately following light punctuation (commas, ellipses, etc.)
    - Collapses extra whitespace and tidies spaces around punctuation
    """
    if not text:
        return text

    # Remove interjections globally
    cleaned = _INTERJECTION_PATTERN.sub(" ", text)

    # Collapse repeated whitespace
    cleaned = re.sub(r"\s{2,}", " ", cleaned)

    # Remove spaces before punctuation
    cleaned = re.sub(r"\s+([,\.\!\?;:\)…\]\}])", r"\1", cleaned)

    # Trim leading/trailing whitespace
    return cleaned.strip()


