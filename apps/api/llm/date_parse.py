"""
Optional LLM fallback for messy natural-language dates (birthdays, etc.).

Used only when regex extractors cannot parse the text and USE_LLM is true.
"""

from __future__ import annotations

import logging
import re
from datetime import date

logger = logging.getLogger(__name__)


def parse_birth_date_via_llm(text: str) -> date | None:
    """
    Ask Gemini for a single YYYY-MM-DD birth date, or return None on failure / when LLM is off.
    """
    from config import get_settings

    if not get_settings().use_llm:
        return None

    raw = (text or "").strip()
    if len(raw) < 3:
        return None

    try:
        from llm.gemini import generate
    except Exception as exc:
        logger.debug("Gemini not available for date parse: %s", exc)
        return None

    prompt = (
        "You extract ONE calendar date meant as a person's date of birth from SMS-style text. "
        "The message may have typos, missing spaces, or informal month names.\n"
        "Reply with exactly one line: YYYY-MM-DD\n"
        "If there is no interpretable date, reply with exactly: NONE\n\n"
        f"Text: {raw!r}"
    )
    try:
        out = generate(prompt).strip()
    except Exception as exc:
        logger.warning("LLM birth-date parse failed: %s", exc)
        return None

    first_line = out.splitlines()[0].strip() if out else ""
    if not first_line or first_line.upper() == "NONE":
        return None
    # Allow model to wrap in markdown or extra words
    iso_match = re.search(r"(19\d{2}|20\d{2})-(\d{2})-(\d{2})", first_line)
    if not iso_match:
        return None
    try:
        y, mo, d = int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))
        return date(y, mo, d)
    except ValueError:
        return None
