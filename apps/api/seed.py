"""
Demo seed script — populates all must-have tables with realistic sample data.

Usage (from apps/api/):
    uv run python seed.py              # create tables if missing, then seed
    uv run python seed.py --reset      # SQLite only: drop all tables, recreate, seed
    python seed.py                     # if .venv is activated

Without --reset, re-running on an already-seeded DB will usually fail (duplicate rows).
For a clean SQLite DB, either delete the file (e.g. data/app.db) or use --reset.
"""

import argparse
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Ensure apps/api is on sys.path when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from database import SessionLocal, engine, init_db
from models.base import Base
from models import (
    Appointment,
    AppointmentSlot,
    AppointmentType,
    ClinicSettings,
    Conversation,
    ConversationMessage,
    ConversationStateSnapshot,
    FamilyGroup,
    FamilyGroupMember,
    FaqEntry,
    InsurancePlan,
    Location,
    LocationHours,
    Operatory,
    Patient,
    PatientAddress,
    PatientInsurancePolicy,
    PatientResponsibleParty,
    Practice,
    PricingOption,
    Provider,
    ProviderScheduleTemplate,
    ResponsibleParty,
    StaffUser,
)

TZ = ZoneInfo("America/Toronto")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def local_dt(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


def today_local() -> date:
    return datetime.now(TZ).date()


def _next_march_27_30_window() -> tuple[date, date]:
    """
    Next March 27 (Fri) and March 30 (Mon) pair where March 30 is still on or after today.
    Used to place demo appointments on those weekdays.
    """
    t = today_local()
    for y in range(t.year, t.year + 3):
        mon = date(y, 3, 30)
        if mon >= t:
            return date(y, 3, 27), mon
    y = t.year + 1
    return date(y, 3, 27), date(y, 3, 30)


def _slots_on_day(slots: list[AppointmentSlot], d: date) -> list[AppointmentSlot]:
    return sorted(
        [s for s in slots if s.starts_at.astimezone(TZ).date() == d],
        key=lambda s: s.starts_at,
    )


def _slot_on_day(slots: list[AppointmentSlot], d: date, index: int) -> AppointmentSlot:
    day = _slots_on_day(slots, d)
    if len(day) <= index:
        raise RuntimeError(
            f"Seed: need slot index {index} on {d}, found {len(day)} slots. "
            "Increase generate_slots days or fix demo dates."
        )
    return day[index]


def generate_slots(
    location_id: str,
    provider_id: str,
    appt_type_id: str,
    start_date: date,
    days: int = 14,
) -> list[AppointmentSlot]:
    """
    Generate 1-hour available slots for the next `days` calendar days.
    Mon–Fri: 8 AM – 6 PM  (10 slots/day)
    Sat:     9 AM – 2 PM  ( 5 slots/day)
    Sun:     closed
    """
    slots = []
    for offset in range(days):
        day = start_date + timedelta(days=offset)
        weekday = day.weekday()  # 0=Mon … 6=Sun
        if weekday == 6:  # Sunday closed
            continue
        hour_range = range(9, 14) if weekday == 5 else range(8, 18)  # Sat 9–14, else 8–18
        for hour in hour_range:
            starts = datetime(day.year, day.month, day.day, hour, 0, tzinfo=TZ)
            ends = starts + timedelta(hours=1)
            slots.append(
                AppointmentSlot(
                    location_id=location_id,
                    provider_id=provider_id,
                    appointment_type_id=appt_type_id,
                    starts_at=starts,
                    ends_at=ends,
                    slot_status="available",
                    capacity=1,
                )
            )
    return slots


def reset_database() -> None:
    """Drop all tables and recreate (SQLite only)."""
    from config import get_settings

    if not get_settings().database_url.startswith("sqlite"):
        print(
            "Error: --reset only supports SQLite DATABASE_URL. "
            "For Postgres or others, use alembic or drop the DB manually.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    Base.metadata.drop_all(bind=engine)
    init_db()


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------


def seed(*, reset: bool = False) -> None:
    if reset:
        reset_database()
    else:
        init_db()
    db = SessionLocal()

    try:
        # ------------------------------------------------------------------
        # Practice
        # ------------------------------------------------------------------
        practice = Practice(
            name="bright_smile_dental",
            display_name="Bright Smile Dental",
            timezone="America/Toronto",
            phone_number="(416) 555-0100",
            email="hello@brightsmile.example.com",
            website_url="https://brightsmile.example.com",
            is_active=True,
        )
        db.add(practice)
        db.flush()

        # ------------------------------------------------------------------
        # Location
        # ------------------------------------------------------------------
        location = Location(
            practice_id=practice.id,
            name="Downtown Toronto Office",
            address_line_1="123 King Street West",
            address_line_2="Suite 400",
            city="Toronto",
            province="ON",
            postal_code="M5H 1J9",
            country_code="CA",
            phone_number="(416) 555-0100",
            email="downtown@brightsmile.example.com",
            is_primary=True,
            is_active=True,
        )
        db.add(location)
        db.flush()

        # ------------------------------------------------------------------
        # Location hours  (Mon–Fri 8am–6pm, Sat 9am–2pm, Sun closed)
        # ------------------------------------------------------------------
        # day_of_week: 0=Sun, 1=Mon … 6=Sat
        location_schedule = [
            (0, True, None, None),  # Sun — closed
            (1, False, time(8, 0), time(18, 0)),  # Mon 8–6
            (2, False, time(8, 0), time(18, 0)),  # Tue 8–6
            (3, False, time(8, 0), time(18, 0)),  # Wed 8–6
            (4, False, time(8, 0), time(18, 0)),  # Thu 8–6
            (5, False, time(8, 0), time(18, 0)),  # Fri 8–6
            (6, False, time(9, 0), time(14, 0)),  # Sat 9–2
        ]
        for dow, closed, open_t, close_t in location_schedule:
            db.add(
                LocationHours(
                    location_id=location.id,
                    day_of_week=dow,
                    is_closed=closed,
                    open_time=open_t,
                    close_time=close_t,
                )
            )

        # ------------------------------------------------------------------
        # Operatories
        # ------------------------------------------------------------------
        op1 = Operatory(location_id=location.id, name="Operatory 1", chair_code="OP1")
        op2 = Operatory(location_id=location.id, name="Operatory 2", chair_code="OP2")
        db.add_all([op1, op2])
        db.flush()

        # ------------------------------------------------------------------
        # Staff users
        # ------------------------------------------------------------------
        receptionist = StaffUser(
            practice_id=practice.id,
            location_id=location.id,
            first_name="Sarah",
            last_name="Chen",
            email="sarah.chen@brightsmile.example.com",
            role="receptionist",
        )
        dentist_user = StaffUser(
            practice_id=practice.id,
            location_id=location.id,
            first_name="Dr. James",
            last_name="Patel",
            email="james.patel@brightsmile.example.com",
            role="dentist",
        )
        hygienist_user = StaffUser(
            practice_id=practice.id,
            location_id=location.id,
            first_name="Maria",
            last_name="Santos",
            email="maria.santos@brightsmile.example.com",
            role="hygienist",
        )
        db.add_all([receptionist, dentist_user, hygienist_user])
        db.flush()

        # ------------------------------------------------------------------
        # Providers
        # ------------------------------------------------------------------
        dentist_provider = Provider(
            staff_user_id=dentist_user.id,
            location_id=location.id,
            provider_type="dentist",
            display_name="Dr. James Patel",
            license_number="DDS-ON-12345",
            is_bookable=True,
        )
        hygienist_provider = Provider(
            staff_user_id=hygienist_user.id,
            location_id=location.id,
            provider_type="hygienist",
            display_name="Maria Santos RDH",
            license_number="RDH-ON-67890",
            is_bookable=True,
        )
        db.add_all([dentist_provider, hygienist_provider])
        db.flush()

        # ------------------------------------------------------------------
        # Provider schedule templates (Mon-Fri)
        # ------------------------------------------------------------------
        for dow in range(1, 6):
            db.add(
                ProviderScheduleTemplate(
                    provider_id=dentist_provider.id,
                    location_id=location.id,
                    day_of_week=dow,
                    start_time=time(9, 0),
                    end_time=time(17, 0),
                )
            )
            db.add(
                ProviderScheduleTemplate(
                    provider_id=hygienist_provider.id,
                    location_id=location.id,
                    day_of_week=dow,
                    start_time=time(8, 0),
                    end_time=time(16, 0),
                )
            )

        # ------------------------------------------------------------------
        # Appointment types
        # ------------------------------------------------------------------
        at_cleaning = AppointmentType(
            practice_id=practice.id,
            code="cleaning",
            display_name="Teeth Cleaning",
            default_duration_minutes=60,
            requires_provider_type="hygienist",
            is_emergency=False,
        )
        at_checkup = AppointmentType(
            practice_id=practice.id,
            code="general_checkup",
            display_name="General Check-up",
            default_duration_minutes=60,
            requires_provider_type="dentist",
            is_emergency=False,
        )
        at_emergency = AppointmentType(
            practice_id=practice.id,
            code="emergency",
            display_name="Emergency Visit",
            default_duration_minutes=60,
            requires_provider_type="dentist",
            is_emergency=True,
        )
        at_new_patient = AppointmentType(
            practice_id=practice.id,
            code="new_patient_exam",
            display_name="New Patient Exam",
            default_duration_minutes=90,
            requires_provider_type="dentist",
            is_emergency=False,
        )
        db.add_all([at_cleaning, at_checkup, at_emergency, at_new_patient])
        db.flush()

        # ------------------------------------------------------------------
        # Appointment slots — wide enough to include demo days Mar 27 (Fri) & Mar 30 (Mon)
        # ------------------------------------------------------------------
        demo_fri, demo_mon = _next_march_27_30_window()
        start_date = min(today_local(), demo_fri)
        days_needed = max(14, (demo_mon - start_date).days + 1)
        slots_dentist = generate_slots(
            location.id, dentist_provider.id, at_checkup.id, start_date, days=days_needed
        )
        slots_hygienist = generate_slots(
            location.id, hygienist_provider.id, at_cleaning.id, start_date, days=days_needed
        )
        # Parallel "emergency" slots (same time grid as dentist check-ups) for demo bookings.
        slots_emergency = generate_slots(
            location.id, dentist_provider.id, at_emergency.id, start_date, days=days_needed
        )
        db.add_all(slots_dentist + slots_hygienist + slots_emergency)
        db.flush()

        # ------------------------------------------------------------------
        # Insurance plans — Canadian and US major carriers
        # ------------------------------------------------------------------

        # Helper so we don't repeat practice_id on every row
        def plan(carrier: str, plan_name: str, plan_code: str | None = None, notes: str | None = None) -> InsurancePlan:
            return InsurancePlan(
                practice_id=practice.id,
                carrier_name=carrier,
                plan_name=plan_name,
                plan_code=plan_code,
                acceptance_status="accepted",
                notes=notes,
            )

        canadian_plans = [
            # Sun Life Financial — also administers the federal CDCP
            plan("Sun Life Financial", "Sun Life Personal Health Insurance (PHI)", "SL-PHI"),
            plan("Sun Life Financial", "Sun Life FollowMe Dental", "SL-FM"),
            plan(
                "Sun Life Financial",
                "Canadian Dental Care Plan (CDCP)",
                "SL-CDCP",
                "Government-subsidised plan for uninsured residents with household income < $90 000. "
                "Administered by Sun Life. Launched 2024, expanding 2025–2026.",
            ),
            # Manulife
            plan("Manulife", "Manulife Flexcare Dental", "MAN-FLEX"),
            plan("Manulife", "Manulife FollowMe Dental", "MAN-FM"),
            # Green Shield Canada
            plan("Green Shield Canada (GSC)", "GreenShield ZONE", "GSC-ZONE"),
            plan("Green Shield Canada (GSC)", "GreenShield LINK", "GSC-LINK"),
            # Canada Life (formerly Great-West Life)
            plan("Canada Life", "Freedom to Choose Health & Dental", "CL-FTC"),
            plan("Canada Life", "Canada Life Group Dental", "CL-GRP"),
            # Medavie Blue Cross / Pacific Blue Cross
            plan("Medavie Blue Cross", "Medavie Blue Cross Dental", "MBC-DNTL"),
            plan("Pacific Blue Cross", "Pacific Blue Cross Dental", "PBC-DNTL"),
            # Desjardins
            plan("Desjardins Insurance", "Desjardins Basic Dental", "DJ-BASIC"),
            plan("Desjardins Insurance", "Desjardins Enhanced Dental", "DJ-ENH"),
            # RBC Insurance
            plan("RBC Insurance", "RBC Dental Care Insurance", "RBC-DNTL"),
            plan("RBC Insurance", "RBC Group Benefits Dental", "RBC-GRP"),
            # GMS (Group Medical Services)
            plan("GMS (Group Medical Services)", "GMS BasicPlan Dental", "GMS-BASIC"),
            plan("GMS (Group Medical Services)", "GMS ExtendaPlan Dental", "GMS-EXT"),
            plan("GMS (Group Medical Services)", "GMS OmniPlan Dental", "GMS-OMNI"),
        ]

        us_plans = [
            plan("Delta Dental", "Delta Dental PPO", "DD-PPO"),
            plan("Delta Dental", "Delta Dental Premier", "DD-PREMIER"),
            plan("MetLife", "MetLife Preferred Dentist Program (PDP)", "MET-PDP"),
            plan("Cigna Dental", "Cigna Dental 1500", "CIG-1500"),
            plan("Cigna Dental", "Cigna Dental 3000", "CIG-3000"),
            plan("UnitedHealthcare", "UHC Dental Gold", "UHC-GOLD"),
            plan("UnitedHealthcare", "UHC Dental Silver", "UHC-SILV"),
            plan("Guardian Life Insurance", "Guardian DentalGuard Preferred", "GRD-PREF"),
            plan("Humana", "Humana Extend 2500", "HUM-EXT"),
            plan("Humana", "Humana Complete Dental", "HUM-COMP"),
            plan("Ameritas", "Ameritas PrimeStar Dental", "AMR-PS"),
            plan("United Concordia", "United Concordia Flex Plan", "UC-FLEX"),
            plan("Aetna", "Aetna Dental Direct", "AET-DRTL"),
            plan("Aetna", "Aetna Vital Savings", "AET-VS"),
            plan("Aflac", "Aflac Dental Supplement", "AFL-SUPP"),
        ]

        db.add_all(canadian_plans + us_plans)
        db.flush()

        # ------------------------------------------------------------------
        # Sample patients
        # ------------------------------------------------------------------
        patient_existing = Patient(
            practice_id=practice.id,
            primary_location_id=location.id,
            first_name="Alice",
            last_name="Thompson",
            date_of_birth=date(1985, 3, 14),
            phone_number="(416) 555-2001",
            email="alice.thompson@example.com",
            preferred_contact_method="email",
            is_existing_patient=True,
            status="active",
        )
        patient_new = Patient(
            practice_id=practice.id,
            primary_location_id=location.id,
            first_name="Ben",
            last_name="Kowalski",
            date_of_birth=date(1990, 7, 22),
            phone_number="(416) 555-2002",
            email="ben.k@example.com",
            preferred_contact_method="phone",
            is_existing_patient=False,
            status="lead",
        )
        patient_child = Patient(
            practice_id=practice.id,
            primary_location_id=location.id,
            first_name="Emma",
            last_name="Thompson",
            date_of_birth=date(2015, 9, 5),
            phone_number="(416) 555-2001",
            is_existing_patient=True,
            status="active",
        )
        patient_maria = Patient(
            practice_id=practice.id,
            primary_location_id=location.id,
            first_name="Maria",
            last_name="Gonzalez",
            date_of_birth=date(1978, 11, 2),
            phone_number="(416) 555-2010",
            email="maria.gonzalez@example.com",
            preferred_contact_method="phone",
            is_existing_patient=True,
            status="active",
        )
        patient_james = Patient(
            practice_id=practice.id,
            primary_location_id=location.id,
            first_name="James",
            last_name="Chen",
            date_of_birth=date(1992, 4, 18),
            phone_number="(416) 555-2011",
            email="james.chen@example.com",
            preferred_contact_method="email",
            is_existing_patient=True,
            status="active",
        )
        patient_priya = Patient(
            practice_id=practice.id,
            primary_location_id=location.id,
            first_name="Priya",
            last_name="Sharma",
            date_of_birth=date(1988, 8, 30),
            phone_number="(416) 555-2012",
            email="priya.sharma@example.com",
            preferred_contact_method="email",
            is_existing_patient=True,
            status="active",
        )
        patient_david = Patient(
            practice_id=practice.id,
            primary_location_id=location.id,
            first_name="David",
            last_name="Kim",
            date_of_birth=date(2001, 1, 25),
            phone_number="(416) 555-2013",
            email="david.kim@example.com",
            preferred_contact_method="text",
            is_existing_patient=True,
            status="active",
        )
        db.add_all(
            [
                patient_existing,
                patient_new,
                patient_child,
                patient_maria,
                patient_james,
                patient_priya,
                patient_david,
            ]
        )
        db.flush()

        # Addresses
        db.add(
            PatientAddress(
                patient_id=patient_existing.id,
                address_line_1="456 Queen Street East",
                city="Toronto",
                province="ON",
                postal_code="M4M 1R6",
                is_primary=True,
            )
        )

        # Insurance policy for existing patient — Sun Life PHI
        sun_life_phi = canadian_plans[0]  # "Sun Life Personal Health Insurance (PHI)"
        db.add(
            PatientInsurancePolicy(
                patient_id=patient_existing.id,
                insurance_plan_id=sun_life_phi.id,
                provider_name="Sun Life Financial",
                member_id="SL-887766",
                group_number="GRP-4455",
                policy_holder_name="Alice Thompson",
                policy_holder_relationship="self",
                is_primary=True,
                verification_status="verified",
            )
        )

        # Responsible party (parent for child patient)
        guardian = ResponsibleParty(
            practice_id=practice.id,
            first_name="Alice",
            last_name="Thompson",
            phone_number="(416) 555-2001",
            email="alice.thompson@example.com",
            relationship_to_patient="parent",
        )
        db.add(guardian)
        db.flush()

        db.add(
            PatientResponsibleParty(
                patient_id=patient_child.id,
                responsible_party_id=guardian.id,
                relationship_type="parent",
                is_primary_contact=True,
                can_schedule=True,
                can_receive_billing=True,
            )
        )

        # Family group (Thompson household)
        family = FamilyGroup(
            practice_id=practice.id,
            name="Thompson Household",
            primary_contact_patient_id=patient_existing.id,
        )
        db.add(family)
        db.flush()

        db.add(
            FamilyGroupMember(
                family_group_id=family.id,
                patient_id=patient_existing.id,
                member_role="parent",
            )
        )
        db.add(
            FamilyGroupMember(
                family_group_id=family.id,
                patient_id=patient_child.id,
                member_role="child",
            )
        )

        # ------------------------------------------------------------------
        # Sample appointments (mix of statuses and channels)
        # ------------------------------------------------------------------
        def book_demo_appointment(
            slot: AppointmentSlot,
            patient: Patient,
            *,
            provider_id: str,
            appointment_type_id: str,
            status: str,
            booked_via: str = "chatbot",
            reason: str | None = None,
            is_emergency: bool = False,
            emergency_summary: str | None = None,
        ) -> None:
            slot.slot_status = "booked"
            db.add(
                Appointment(
                    patient_id=patient.id,
                    slot_id=slot.id,
                    location_id=location.id,
                    provider_id=provider_id,
                    appointment_type_id=appointment_type_id,
                    status=status,
                    booked_via=booked_via,
                    scheduled_starts_at=slot.starts_at,
                    scheduled_ends_at=slot.ends_at,
                    reason_for_visit=reason,
                    is_emergency=is_emergency,
                    emergency_summary=emergency_summary,
                )
            )

        # Demo appointments: Friday March 27 and Monday March 30 (same calendar year as demo_mon)
        book_demo_appointment(
            _slot_on_day(slots_dentist, demo_fri, 0),
            patient_existing,
            provider_id=dentist_provider.id,
            appointment_type_id=at_checkup.id,
            status="booked",
            reason="Annual check-up",
        )
        book_demo_appointment(
            _slot_on_day(slots_hygienist, demo_fri, 0),
            patient_maria,
            provider_id=hygienist_provider.id,
            appointment_type_id=at_cleaning.id,
            status="confirmed",
            booked_via="phone",
            reason="Routine cleaning",
        )
        book_demo_appointment(
            _slot_on_day(slots_dentist, demo_fri, 1),
            patient_james,
            provider_id=dentist_provider.id,
            appointment_type_id=at_checkup.id,
            status="completed",
            booked_via="staff",
            reason="Follow-up exam",
        )
        book_demo_appointment(
            _slot_on_day(slots_hygienist, demo_mon, 0),
            patient_priya,
            provider_id=hygienist_provider.id,
            appointment_type_id=at_cleaning.id,
            status="checked_in",
            booked_via="chatbot",
            reason="Cleaning",
        )
        book_demo_appointment(
            _slot_on_day(slots_dentist, demo_mon, 0),
            patient_new,
            provider_id=dentist_provider.id,
            appointment_type_id=at_checkup.id,
            status="booked",
            booked_via="chatbot",
            reason="New patient exam",
        )
        book_demo_appointment(
            _slot_on_day(slots_emergency, demo_mon, 1),
            patient_david,
            provider_id=dentist_provider.id,
            appointment_type_id=at_emergency.id,
            status="confirmed",
            booked_via="phone",
            reason="Emergency visit",
            is_emergency=True,
            emergency_summary="Severe tooth pain (lower left)",
        )
        db.flush()

        # ------------------------------------------------------------------
        # Sample conversation + messages + state snapshot
        # ------------------------------------------------------------------
        conv = Conversation(
            practice_id=practice.id,
            location_id=location.id,
            patient_id=patient_existing.id,
            session_token="demo-session-alice-001",
            channel="web_chat",
            current_workflow="book_appointment",
            conversation_status="completed",
        )
        db.add(conv)
        db.flush()

        db.add(
            ConversationMessage(
                conversation_id=conv.id,
                sender_type="user",
                message_text="Hi, I'd like to book a general check-up.",
            )
        )
        db.add(
            ConversationMessage(
                conversation_id=conv.id,
                sender_type="assistant",
                message_text=(
                    "Of course! I can help you book a general check-up with Dr. Patel. "
                    "Would morning or afternoon work better for you?"
                ),
            )
        )
        db.add(
            ConversationStateSnapshot(
                conversation_id=conv.id,
                version_number=1,
                workflow="book_appointment",
                collected_fields={
                    "appointment_type": "general_checkup",
                    "patient_id": patient_existing.id,
                },
                missing_fields={"preferred_time": None, "date_range": None},
                next_recommended_action="ask_time_preference",
            )
        )

        # ------------------------------------------------------------------
        # Clinic settings
        # ------------------------------------------------------------------
        db.add(
            ClinicSettings(
                practice_id=practice.id,
                default_location_id=location.id,
                accepts_major_insurance=True,
                self_pay_available=True,
                membership_available=True,
                financing_available=True,
                emergency_escalation_enabled=True,
            )
        )

        # ------------------------------------------------------------------
        # FAQ entries
        # ------------------------------------------------------------------
        faq_data = [
            (
                "insurance",
                1,
                "Do you accept my dental insurance?",
                "We accept most major insurance plans including Sun Life, Manulife, Great-West Life, "
                "and Desjardins. Contact us with your plan details and we will confirm coverage before "
                "your appointment.",
            ),
            (
                "insurance",
                2,
                "What if I don't have insurance?",
                "You can pay as you go: a routine cleaning is $140 self-pay. Our Bright Smile Membership is "
                "$399 per year and includes 2 cleanings, 2 exams, 1 set of X-rays, and 10% off other "
                "treatment. For larger plans, PayBright offers 0% interest for 6 months on amounts over "
                "$500 (subject to credit approval).",
            ),
            (
                "payment",
                3,
                "What payment methods do you accept?",
                "We take Visa, Mastercard, Amex, Interac debit, cash, and direct insurance billing. "
                "Example self-pay: cleaning $140. Membership: $399/year. PayBright financing on plans "
                "over $500: 0% for 6 months where approved.",
            ),
            (
                "hours",
                4,
                "What are your office hours?",
                "We are open Monday to Friday 8:00 AM – 6:00 PM and Saturday 9:00 AM – 2:00 PM. "
                "We are closed on Sundays and statutory holidays.",
            ),
            (
                "hours",
                5,
                "Do you offer emergency appointments?",
                "Yes. We reserve same-day slots for dental emergencies. If you are in severe pain or have "
                "a broken tooth, call us immediately at (416) 555-0100 and we will do our best to see you "
                "the same day.",
            ),
            (
                "location",
                6,
                "Where are you located?",
                "Our Downtown Toronto office is at 123 King Street West, Suite 400, Toronto ON M5H 1J9. "
                "We are a short walk from King subway station (Line 1).",
            ),
            (
                "location",
                7,
                "Is parking available?",
                "Street parking is available on nearby side streets. The Green P parking lot at "
                "Adelaide and York is a 3-minute walk from our office.",
            ),
            (
                "new_patient",
                8,
                "What happens at a new patient exam?",
                "Your first visit (approximately 90 minutes) includes a comprehensive oral exam, "
                "digital X-rays, a periodontal assessment, and a cleaning if time allows. "
                "Please arrive 10 minutes early to complete your intake paperwork.",
            ),
            (
                "new_patient",
                9,
                "How do I register as a new patient?",
                "You can register right here in this chat — I will walk you through it step by step "
                "(name, phone, date of birth, insurance if any, and what kind of visit you need). "
                "If you would rather talk to someone, you can always try calling us another time. "
                "Would you like to register now?",
            ),
        ]
        for category, sort_order, question, answer in faq_data:
            db.add(
                FaqEntry(
                    practice_id=practice.id,
                    location_id=location.id,
                    category=category,
                    question=question,
                    answer=answer,
                    sort_order=sort_order,
                    is_active=True,
                )
            )

        # ------------------------------------------------------------------
        # Pricing options
        # ------------------------------------------------------------------
        db.add_all(
            [
                PricingOption(
                    practice_id=practice.id,
                    location_id=location.id,
                    name="Self-Pay Cleaning",
                    pricing_type="self_pay",
                    description=(
                        "Routine adult cleaning (scaling and polishing), uninsured. "
                        "New patient exam and X-rays if needed: typically $95–$180 depending on imaging."
                    ),
                    base_price=140.00,
                    is_active=True,
                ),
                PricingOption(
                    practice_id=practice.id,
                    location_id=location.id,
                    name="Bright Smile Membership",
                    pricing_type="membership",
                    description=(
                        "$399/year: includes 2 cleanings ($140 value each), 2 exams ($95 each), "
                        "1 set of bitewing X-rays ($45), plus 10% off fillings and other treatment."
                    ),
                    base_price=399.00,
                    is_active=True,
                ),
                PricingOption(
                    practice_id=practice.id,
                    location_id=location.id,
                    name="PayBright Financing",
                    pricing_type="financing",
                    description=(
                        "Split larger balances: 0% APR for 6 months on approved plans over $500 "
                        "(example: $1,200 treatment ≈ $200/month for 6 months). Subject to credit approval."
                    ),
                    base_price=None,
                    is_active=True,
                ),
            ]
        )

        db.commit()
        print("✓ Seed complete.")
        print(f"  Practice:          {practice.display_name} ({practice.id})")
        print(f"  Location:          {location.name} ({location.id})")
        print(f"  Providers:         {dentist_provider.display_name}, {hygienist_provider.display_name}")
        print("  Appointment types: cleaning, general_checkup, emergency, new_patient_exam")
        total_slots = len(slots_dentist) + len(slots_hygienist) + len(slots_emergency)
        print(f"  Slots seeded:      {total_slots}")
        print(
            "  Patients:          7 demo (Alice, Ben, Emma, Maria G., James C., Priya S., David K.)"
        )
        print(
            f"  Appointments:      6 demo on Fri Mar {demo_fri.day} & Mon Mar {demo_mon.day} "
            f"({demo_fri.year}) — check-ups, cleanings, 1 emergency"
        )
        print(f"  FAQ entries:       {len(faq_data)}")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the database with demo data.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="SQLite only: drop all tables, recreate, then seed.",
    )
    args = parser.parse_args()
    seed(reset=args.reset)
