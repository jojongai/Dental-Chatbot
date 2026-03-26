"""
Clinic tools — get_clinic_info.

Queries faq_entries, clinic_settings, locations, and location_hours to answer
static questions about hours, location, insurance, and payment options.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.content import ClinicSettings, FaqEntry, PricingOption
from models.practice import Location, LocationHours, Practice
from schemas.tools import (
    ClinicSettingsOut,
    FaqEntryOut,
    GetClinicInfoInput,
    GetClinicInfoOutput,
)

# Maps category keywords from the input to DB category values
_CATEGORY_ALIASES: dict[str, list[str]] = {
    "hours": ["hours"],
    "insurance": ["insurance"],
    "payment": ["payment"],
    "location": ["location"],
    "new_patient": ["new_patient"],
}

# Day-of-week labels (0 = Sunday, matching LocationHours.day_of_week)
_DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def get_practice_display_name(db: Session, practice_id: str) -> str:
    """Display name for SMS / Maya intros (falls back if practice missing)."""
    if not practice_id:
        return "Bright Smile Dental"
    row = db.get(Practice, practice_id)
    if row:
        return row.display_name or row.name
    return "Bright Smile Dental"


def get_clinic_info(
    db: Session,
    payload: GetClinicInfoInput,
    practice_id: str,
) -> GetClinicInfoOutput:
    """
    Return FAQ entries and clinic settings for a given category.

    If payload.category is None, returns all active FAQ entries.
    If payload.question_hint is provided, filters to entries whose question
    or answer contains any keyword from the hint (simple keyword overlap).
    """
    # --- FAQ entries ---
    stmt = select(FaqEntry).where(FaqEntry.is_active == True)  # noqa: E712
    if practice_id:
        stmt = stmt.where(FaqEntry.practice_id == practice_id)

    if payload.category:
        db_cats = _CATEGORY_ALIASES.get(payload.category, [payload.category])
        stmt = stmt.where(FaqEntry.category.in_(db_cats))

    stmt = stmt.order_by(FaqEntry.sort_order)
    rows = db.execute(stmt).scalars().all()

    # Optional keyword re-ranking when a question hint is provided
    if payload.question_hint:
        hint_words = {w.lower() for w in payload.question_hint.split() if len(w) > 3}
        rows = sorted(
            rows,
            key=lambda r: -sum(
                1
                for w in hint_words
                if w in r.question.lower() or w in r.answer.lower()
            ),
        )

    faq_entries = [
        FaqEntryOut(category=r.category, question=r.question, answer=r.answer)
        for r in rows
    ]

    # --- Clinic settings + location ---
    settings_row = (
        db.execute(
            select(ClinicSettings).where(
                ClinicSettings.practice_id == practice_id if practice_id else True  # type: ignore[arg-type]
            )
        )
        .scalars()
        .first()
    )

    clinic_settings: ClinicSettingsOut | None = None
    if settings_row:
        loc = db.get(Location, settings_row.default_location_id)
        hours_summary = _build_hours_summary(db, settings_row.default_location_id)

        clinic_settings = ClinicSettingsOut(
            accepts_major_insurance=settings_row.accepts_major_insurance,
            self_pay_available=settings_row.self_pay_available,
            membership_available=settings_row.membership_available,
            financing_available=settings_row.financing_available,
            emergency_escalation_enabled=settings_row.emergency_escalation_enabled,
            location_name=loc.name if loc else "Bright Smile Dental",
            address=(
                f"{loc.address_line_1}, {loc.city} {loc.province} {loc.postal_code}"
                if loc
                else ""
            ),
            phone_number=loc.phone_number if loc else None,
            hours_summary=hours_summary,
        )

    return GetClinicInfoOutput(faq_entries=faq_entries, settings=clinic_settings)


def get_pricing_options(
    db: Session,
    practice_id: str,
    pricing_type: str | None = None,
) -> list[PricingOption]:
    """Return active pricing options, optionally filtered by type."""
    stmt = select(PricingOption).where(PricingOption.is_active == True)  # noqa: E712
    if practice_id:
        stmt = stmt.where(PricingOption.practice_id == practice_id)
    if pricing_type:
        stmt = stmt.where(PricingOption.pricing_type == pricing_type)
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_hours_summary(db: Session, location_id: str | None) -> str:
    """Build a human-readable hours string from location_hours rows."""
    if not location_id:
        return "Mon–Fri 8:00 AM – 6:00 PM, Sat 9:00 AM – 2:00 PM"

    rows = (
        db.execute(
            select(LocationHours)
            .where(LocationHours.location_id == location_id)
            .order_by(LocationHours.day_of_week)
        )
        .scalars()
        .all()
    )

    if not rows:
        return "Mon–Fri 8:00 AM – 6:00 PM, Sat 9:00 AM – 2:00 PM"

    # Group consecutive days with the same hours into ranges
    open_rows = [r for r in rows if not r.is_closed and r.open_time and r.close_time]
    closed_rows = [r for r in rows if r.is_closed]

    parts: list[str] = []
    if open_rows:
        # Group by time range
        groups: dict[str, list[int]] = {}
        for r in open_rows:
            key = f"{_fmt_time(r.open_time)}–{_fmt_time(r.close_time)}"
            groups.setdefault(key, []).append(r.day_of_week)

        for time_range, days in groups.items():
            days_sorted = sorted(days)
            if len(days_sorted) >= 3 and days_sorted == list(
                range(days_sorted[0], days_sorted[-1] + 1)
            ):
                parts.append(f"{_DOW[days_sorted[0]]}–{_DOW[days_sorted[-1]]} {time_range}")
            else:
                day_labels = "/".join(_DOW[d] for d in days_sorted)
                parts.append(f"{day_labels} {time_range}")

    if closed_rows:
        closed_labels = "/".join(_DOW[r.day_of_week] for r in closed_rows)
        parts.append(f"{closed_labels} closed")

    return ", ".join(parts)


def _fmt_time(t: object) -> str:
    """Format a time object as '8:00 AM'."""
    from datetime import time as dt_time

    if not isinstance(t, dt_time):
        return str(t)
    hour = t.hour
    minute = t.minute
    period = "AM" if hour < 12 else "PM"
    display = hour if hour <= 12 else hour - 12
    if display == 0:
        display = 12
    return f"{display}:{minute:02d} {period}"
