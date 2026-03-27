"""
Gemini-powered receptionist response generator.

Takes structured clinic data (FAQ entries + settings + pricing) retrieved
deterministically from the database and generates a warm, concise answer
in a dental-receptionist tone.

Channel context
---------------
This chatbot is delivered via SMS as an auto-response to a missed call.
The patient just tried to reach the clinic and got no answer — they may be
frustrated, anxious, or in pain. All generated text must be:

  - Plain text only (no markdown — asterisks and hashes render as symbols in SMS)
  - Short (2–3 sentences max per reply)
  - Warm and reassuring — acknowledge that we missed their call

Design principle
----------------
Gemini's job here is purely *presentation* — it never invents facts.
All authoritative data (hours, addresses, plan lists, prices) comes from
the DB via get_clinic_info / get_pricing_options before Gemini is called.
If Gemini is unavailable the router falls back to a plain-text formatter.
"""

from __future__ import annotations

import logging
import re

from schemas.tools import GetClinicInfoOutput

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System persona
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are Maya, a dental receptionist at Bright Smile Dental, replying via SMS.
Your role is to answer using ONLY the clinic information provided — never invent facts or prices.

Missed-call SMS context:
- The patient could not reach us by phone; do NOT push them to call back just to hear basic prices
  when dollar amounts are already listed in the clinic information below. Share those numbers here.
- When the context includes pricing options or FAQ answers with fees, quote them clearly (e.g. cleaning $140,
  membership $399/year). Reserve the phone number for things that truly need staff (complex treatment plans,
  insurance predetermination), not for repeating prices that are already in this message.

Conversation threading (critical):
- The patient already received an opening text from Maya. Do NOT start replies with a full re-introduction
  like "Hi, this is Maya from Bright Smile Dental" or "Hi there, Maya from..." on every turn. Sound like you are
  continuing the same text thread.
- Do NOT end every message with a signature line like "- Maya" or "Anything else? - Maya." Use a short closing
  question only when it fits (e.g. "Anything else I can help with?") and without repeating your name each time.
  Reserve signing off as "- Maya" for a natural closing or goodbye, not after every answer.

SMS formatting rules (strictly enforced):
- Plain text only. No asterisks, no pound signs, no bullet symbols, no markdown of any kind.
- Numbers are fine for lists (1. 2. 3.) but keep lists to 3 items maximum.
- Keep the entire reply to 3 sentences or fewer for simple questions.
- Never use em-dashes (—) or special Unicode characters that may not render on all phones.

Tone rules:
- Warm, reassuring, and professional — many callers are anxious about dental visits.
- If something is not in the provided context, say so briefly; you may still offer the clinic phone for
  complex cases, but do not use "please call for pricing" as a default when prices are in the context above.

Handling unclear or nonsensical messages:
- If the patient sends something vague like "idk", "idk lol", "hmm" — respond naturally and
  lightheartedly, like a real person texting. Example: "Haha no worries! Just let me know if
  anything comes up — I'm here to help."
- If the patient sends gibberish or random characters like "asdfghjkl", "aaa", "????" — respond
  casually, like: "Haha I didn't quite catch that! But if you need anything just let me know."
- Never be robotic or repeat the exact same "How can I help you?" phrasing — vary your responses.\
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def answer_general_inquiry(
    user_message: str,
    clinic_data: GetClinicInfoOutput,
    pricing_options: list | None = None,
    is_first_message: bool = False,
    *,
    inquiry_followup: str | None = None,
    inquiry_category: str | None = None,
) -> str:
    """
    Generate an SMS-appropriate receptionist answer to a general inquiry.

    Parameters
    ----------
    user_message:
        The patient's raw question or first message.
    clinic_data:
        Structured output from get_clinic_info — FAQ entries + settings.
    pricing_options:
        Optional list of PricingOption ORM objects for self-pay questions.
    is_first_message:
        When True, this is the first reply you generate after the canned opening SMS (patient may say "yes" etc.).
        The model is told not to repeat the full Maya intro from that opening text.
    inquiry_followup:
        When ``affirm`` or ``negate``, the patient is answering a yes/no follow-up
        (e.g. more details on payment). The model must respond to that intent, not generic small talk.
    inquiry_category:
        FAQ category for the follow-up (``payment``, ``hours``, etc.).

    Returns
    -------
    A plain-text reply string, SMS-safe.  Falls back to a plain-text summary if
    the Gemini API is unavailable or raises an exception.
    """
    from config import get_settings

    if not get_settings().use_llm:
        logger.debug("USE_LLM=false — skipping Gemini, using plain fallback.")
        return _plain_fallback(
            clinic_data,
            pricing_options,
            is_first_message,
            user_message,
            inquiry_followup=inquiry_followup,
            inquiry_category=inquiry_category,
        )

    context = _build_context(clinic_data, pricing_options)
    prompt = _build_prompt(
        user_message,
        context,
        is_first_message,
        inquiry_followup=inquiry_followup,
        inquiry_category=inquiry_category,
    )

    try:
        from llm.gemini import generate

        return generate(prompt)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gemini unavailable, falling back to plain formatter: %s", exc)
        return _plain_fallback(
            clinic_data,
            pricing_options,
            is_first_message,
            user_message,
            inquiry_followup=inquiry_followup,
            inquiry_category=inquiry_category,
        )


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------


def _build_context(
    data: GetClinicInfoOutput,
    pricing_options: list | None,
) -> str:
    """Serialize clinic data into a compact text block for the prompt."""
    lines: list[str] = []

    if data.settings:
        s = data.settings
        lines.append(f"Clinic name: {s.location_name}")
        lines.append(f"Address: {s.address}")
        if s.phone_number:
            lines.append(f"Phone: {s.phone_number}")
        lines.append(f"Hours: {s.hours_summary}")
        flags = []
        if s.accepts_major_insurance:
            flags.append("accepts all major dental insurance plans")
        if s.self_pay_available:
            flags.append("offers self-pay options")
        if s.membership_available:
            flags.append("offers an in-house membership plan")
        if s.financing_available:
            flags.append("offers third-party financing")
        if flags:
            lines.append("Payment: " + ", ".join(flags))

    if pricing_options:
        lines.append("\nPricing options:")
        for p in pricing_options:
            price_str = f" — ${p.base_price:.0f}" if p.base_price else ""
            lines.append(f"  • {p.name} ({p.pricing_type}){price_str}: {p.description}")

    if data.faq_entries:
        lines.append("\nFAQ:")
        for faq in data.faq_entries:
            lines.append(f"  Q: {faq.question}")
            lines.append(f"  A: {faq.answer}")

    return "\n".join(lines)


_PATIENT_TYPE_ONLY_RE = re.compile(
    r"^\s*(i'?m\s+(a\s+)?|i\s+am\s+(a\s+)?)?(new|existing)\s+(patient|here|customer)?\s*$",
    re.IGNORECASE,
)


def _is_patient_type_only(message: str) -> bool:
    """Return True when the message is only a patient-type signal with no action intent."""
    return bool(_PATIENT_TYPE_ONLY_RE.match(message.strip()))


_GIBBERISH_RE = re.compile(r"^[^a-zA-Z]*$|^(.)\1{3,}$")
_VAGUE_PHRASES = frozenset({
    "idk", "i don't know", "i dont know", "dunno", "not sure", "no idea",
    "hmm", "hm", "hmmmm", "meh", "lol", "haha", "ok", "k", "idk lol",
    "bruh", "nvm", "nevermind", "never mind", "nm",
})


def _has_vowels(text: str) -> bool:
    """Check if text has a reasonable vowel ratio for English."""
    alpha = [c for c in text.lower() if c.isalpha()]
    if not alpha:
        return False
    vowels = sum(1 for c in alpha if c in "aeiou")
    return vowels / len(alpha) >= 0.15


def _is_nonsensical(message: str) -> bool:
    """Return True for gibberish, random characters, or 'idk'-style vague input."""
    stripped = message.strip().lower()
    if not stripped:
        return True
    if stripped in _VAGUE_PHRASES:
        return True
    if _GIBBERISH_RE.match(stripped):
        return True
    words = stripped.split()
    alpha_only = re.sub(r"[^a-z]", "", stripped)
    if len(alpha_only) >= 5 and len(words) <= 2 and not _has_vowels(alpha_only):
        return True
    # Long single "word" with consonant clusters → keyboard mashing
    if len(words) == 1 and len(alpha_only) >= 8 and re.search(r"[bcdfghjklmnpqrstvwxyz]{4,}", alpha_only):
        return True
    return False


def _build_prompt(
    user_message: str,
    context: str,
    is_first_message: bool = False,
    *,
    inquiry_followup: str | None = None,
    inquiry_category: str | None = None,
) -> str:
    opening_note = (
        "This is your first reply in this SMS thread. The opening text already introduced Maya from "
        "Bright Smile Dental and mentioned the missed call — do NOT repeat that full introduction. "
        "If their message is short or vague (e.g. yes, hi, ok), acknowledge in one short phrase and ask "
        "how you can help. Otherwise answer directly. Do not sign with '- Maya' at the end.\n\n"
        if is_first_message
        else (
            "Ongoing conversation: answer the question directly in a warm tone. No greeting that re-states "
            "your name and clinic. No '- Maya' signature unless you are naturally closing the conversation. "
            "If the message is unclear, gibberish, or off-topic, respond naturally like a real person texting.\n\n"
        )
    )
    patient_type_note = (
        "The patient has only identified themselves as new or existing — they have NOT yet "
        "stated what they need. Do NOT dump clinic information. Simply acknowledge them warmly "
        "and ask how you can help today (one sentence).\n\n"
        if _is_patient_type_only(user_message)
        else ""
    )
    nonsensical_note = (
        "The patient's message is vague, gibberish, or unclear. Respond casually and "
        "lightheartedly like a real person texting — don't be robotic. Let them know you're "
        "here if they need anything. Keep it to 1 sentence. Do NOT dump clinic info.\n\n"
        if _is_nonsensical(user_message) and not patient_type_note
        else ""
    )
    followup_note = ""
    if inquiry_followup == "affirm" and inquiry_category:
        followup_note = (
            f"IMPORTANT: The patient just AGREED (e.g. said yes) to hearing MORE DETAIL about "
            f"\"{inquiry_category}\" — for example after you asked if they want more details on "
            "payment, membership, or financing. Use the clinic information below to give "
            "concrete, helpful specifics (names of options, how to enroll, or next steps). "
            "Do NOT reply with only \"What can I help you with?\" — they are answering your "
            "offer for more detail.\n\n"
        )
    elif inquiry_followup == "negate" and inquiry_category:
        followup_note = (
            f"IMPORTANT: The patient DECLINED more detail on \"{inquiry_category}\". Thank them "
            "briefly and invite them to text anytime if they change their mind or have another "
            "question. Keep it short.\n\n"
        )
    return (
        f"{_SYSTEM_PROMPT}\n\n"
        f"{opening_note}"
        f"{patient_type_note}"
        f"{nonsensical_note}"
        f"{followup_note}"
        f"=== CLINIC INFORMATION ===\n{context}\n"
        f"=== END OF CLINIC INFORMATION ===\n\n"
        f"Patient message: {user_message}\n\n"
        f"Reply (plain text, SMS-safe, 3 sentences max):"
    )


# ---------------------------------------------------------------------------
# Plain-text fallback (no LLM required)
# ---------------------------------------------------------------------------


def _plain_fallback(
    data: GetClinicInfoOutput,
    pricing_options: list | None,
    is_first_message: bool = False,
    user_message: str = "",
    *,
    inquiry_followup: str | None = None,
    inquiry_category: str | None = None,
) -> str:
    """Return a plain-text, SMS-safe answer when Gemini is unavailable."""
    parts: list[str] = []

    if is_first_message:
        parts.append("Hey, this is Maya from Bright Smile Dental - sorry we missed your call!")

    if user_message and _is_patient_type_only(user_message):
        parts.append("How can I help you today?")
        return "\n".join(parts)

    if user_message and _is_nonsensical(user_message):
        parts.append("Haha no worries! Just let me know if anything comes up — I'm here to help.")
        return "\n".join(parts)

    if inquiry_followup == "affirm" and inquiry_category == "payment" and pricing_options:
        parts.append(
            "Happy to share more. Here are the options we have on file — I can also have "
            "someone call you to walk through them."
        )
    elif inquiry_followup == "negate" and inquiry_category:
        parts.append("No problem at all. Text us anytime if you have other questions.")
        return "\n".join(parts) if parts else "No problem — we're here if you need anything."

    if data.settings:
        s = data.settings
        if data.faq_entries:
            # Use the FAQ answer directly — it is already plain text
            for faq in data.faq_entries[:2]:
                parts.append(faq.answer)
        else:
            # Fall back to assembling from settings fields
            parts.append(f"Hours: {s.hours_summary}")
            if s.accepts_major_insurance:
                parts.append("We accept all major dental insurance plans.")
            if s.self_pay_available or s.membership_available or s.financing_available:
                options = []
                if s.self_pay_available:
                    options.append("self-pay rates")
                if s.membership_available:
                    options.append("a membership plan")
                if s.financing_available:
                    options.append("financing options")
                parts.append("No insurance? We offer " + ", ".join(options) + ".")

    if pricing_options:
        for i, p in enumerate(pricing_options[:3], 1):
            price_str = f" (${p.base_price:.0f})" if p.base_price else ""
            parts.append(f"{i}. {p.name}{price_str}: {p.description}")

    phone = data.settings.phone_number if data.settings else "(416) 555-0100"
    if is_first_message:
        parts.append(f"Anything else I can help with? You can also call us at {phone}. - Maya")
    else:
        parts.append(f"Anything else I can help with? Call us at {phone} if you prefer.")

    return "\n".join(parts)
