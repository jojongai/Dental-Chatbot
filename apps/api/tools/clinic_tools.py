"""
Clinic tools — get_clinic_info.

Called during the general_inquiry workflow to answer questions about:
- Insurance and payment options
- Location and hours
- New patient process
- Self-pay / membership / financing
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from schemas.tools import GetClinicInfoInput, GetClinicInfoOutput


def get_clinic_info(
    db: Session,
    payload: GetClinicInfoInput,
    practice_id: str,
) -> GetClinicInfoOutput:
    """
    Fetch FAQ entries and clinic settings for a given category.

    Steps:
    1. Query faq_entries WHERE practice_id=practice_id AND is_active=True.
       If payload.category is provided, filter by category.
       If payload.question_hint is provided, optionally rank results by
       simple keyword overlap (future: vector similarity).
    2. Query clinic_settings + locations for ClinicSettingsOut.
    3. Build hours_summary from location_hours rows (e.g. "Mon–Fri 8am–6pm, Sat 9am–2pm").
    4. Return GetClinicInfoOutput.

    Supported categories: insurance | payment | hours | location | new_patient

    TODO: implement.
    """
    raise NotImplementedError("get_clinic_info not yet implemented")
