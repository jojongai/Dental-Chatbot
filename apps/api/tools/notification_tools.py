"""
Notification tools — create_staff_notification.

Called automatically for dental emergencies and escalations.
Writes to StaffNotification + (for actionable types) WorkQueueItem.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from models.notification import StaffNotification, WorkQueueItem
from schemas.tools import CreateStaffNotificationInput, CreateStaffNotificationOutput

logger = logging.getLogger(__name__)

# Notification types that also create a work-queue item for staff follow-up
_QUEUE_TYPES: dict[str, str] = {
    "emergency": "escalation",
    "manual_review": "manual_review",
    "callback_request": "call_back",
    "family_scheduling_complexity": "family_coordination",
}

# Force urgent priority for emergencies regardless of what caller passed
_FORCED_PRIORITY: dict[str, str] = {
    "emergency": "urgent",
}


def create_staff_notification(
    db: Session,
    payload: CreateStaffNotificationInput,
    practice_id: str,
) -> CreateStaffNotificationOutput:
    """
    Create a StaffNotification row (and optionally a WorkQueueItem) so that
    staff are immediately aware of the patient's situation.

    Behaviour by notification_type:
    - 'emergency'                       → priority forced to 'urgent'; WorkQueueItem type='escalation'
    - 'manual_review'                   → priority='high'; WorkQueueItem type='manual_review'
    - 'callback_request'                → priority='normal'; WorkQueueItem type='call_back'
    - 'verification_issue'              → priority='normal'; no WorkQueueItem
    - 'family_scheduling_complexity'    → priority='normal'; WorkQueueItem type='family_coordination'
    """
    try:
        resolved_practice_id = payload.practice_id or practice_id
        notification_type = payload.notification_type
        priority = _FORCED_PRIORITY.get(notification_type, payload.priority or "normal")

        notification = StaffNotification(
            practice_id=resolved_practice_id,
            patient_id=payload.patient_id,
            appointment_id=payload.appointment_id,
            conversation_id=payload.conversation_id,
            notification_type=notification_type,
            priority=priority,
            title=payload.title,
            body=payload.body,
            status="open",
        )
        db.add(notification)
        db.flush()  # get notification.id before the work-queue item references it

        queue_type = _QUEUE_TYPES.get(notification_type)
        if queue_type:
            item = WorkQueueItem(
                practice_id=resolved_practice_id,
                queue_type=queue_type,
                related_patient_id=payload.patient_id,
                related_appointment_id=payload.appointment_id,
                related_conversation_id=payload.conversation_id,
                status="open",
                summary=payload.title,
                details={
                    "notification_id": notification.id,
                    "body": payload.body,
                    "priority": priority,
                },
            )
            db.add(item)

        db.commit()
        logger.info(
            "Staff notification created: id=%s type=%s priority=%s",
            notification.id,
            notification_type,
            priority,
        )
        return CreateStaffNotificationOutput(success=True, notification_id=notification.id)

    except Exception as exc:
        db.rollback()
        logger.exception("create_staff_notification failed: %s", exc)
        return CreateStaffNotificationOutput(success=False, error=str(exc))
