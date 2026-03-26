"""
Notification tools — create_staff_notification.

Called automatically by book_appointment when is_emergency=True,
and directly by the orchestration layer when a conversation needs
manual review or escalation.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from schemas.tools import CreateStaffNotificationInput, CreateStaffNotificationOutput


def create_staff_notification(
    db: Session,
    payload: CreateStaffNotificationInput,
    practice_id: str,
) -> CreateStaffNotificationOutput:
    """
    Create a StaffNotification row visible in the staff dashboard.

    Behaviour by notification_type:
    - 'emergency'          → priority forced to 'urgent'; also creates a WorkQueueItem
                             of type 'escalation'.
    - 'manual_review'      → priority='high'; WorkQueueItem type='manual_review'.
    - 'callback_request'   → priority='normal'; WorkQueueItem type='call_back'.
    - 'verification_issue' → priority='normal'; no WorkQueueItem.
    - 'family_scheduling_complexity' → priority='normal'; WorkQueueItem type='family_coordination'.

    Steps:
    1. Insert StaffNotification row.
    2. If notification_type in ('emergency', 'manual_review', 'callback_request',
       'family_scheduling_complexity'): insert WorkQueueItem.
    3. Emit domain_event: notification_created.
    4. Return notification_id.

    TODO: implement.
    """
    raise NotImplementedError("create_staff_notification not yet implemented")
