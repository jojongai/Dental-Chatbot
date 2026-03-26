# Chat Flows

All chatbot conversation flows supported by Bright Smile Dental.
Each entry lists: the trigger phrases that start the flow, the fields collected,
the tool called, and its current implementation status.

---

## Status legend

| Symbol | Meaning |
|--------|---------|
| ✅ Live | Fully implemented — DB query + Gemini response |
| 🔧 Stub | State machine + schema complete; tool body returns `NotImplementedError` |
| 📋 Planned | Not yet started |

---

## Static / General Inquiry flows

These flows require **no patient identity** and are answered instantly from
the database via `get_clinic_info` + the Gemini receptionist (`llm/receptionist.py`).

### 1. Hours ✅ Live

**Trigger phrases:** "What are your hours?", "When are you open?", "Are you open Saturday?"

**Flow:**
1. User asks any hours-related question.
2. State machine detects `general_inquiry` intent → calls `get_clinic_info(category="hours")`.
3. FAQ rows + `LocationHours` from DB are passed to Gemini receptionist.
4. Warm natural-language reply is returned.

**Tool:** `get_clinic_info`
**No fields collected.**

---

### 2. Location ✅ Live

**Trigger phrases:** "Where are you located?", "What is your address?", "How do I get there?", "Is there parking?"

**Flow:**
1. State machine → `get_clinic_info(category="location")`.
2. Address, city, postal code, transit directions pulled from `Location` table + FAQ.
3. Gemini formats a concise directions reply.

**Tool:** `get_clinic_info`
**No fields collected.**

---

### 3. Insurance ✅ Live

**Trigger phrases:** "Do you take insurance?", "Do you accept Sun Life?", "What plans do you accept?"

**Flow:**
1. State machine → `get_clinic_info(category="insurance")`.
2. `ClinicSettings.accepts_major_insurance` flag + insurance FAQ entries returned.
3. Gemini answers confirming accepted plans and recommends calling to verify coverage.

**Tool:** `get_clinic_info`
**No fields collected.**

---

### 4. No Insurance / Self-Pay / Financing ✅ Live

**Trigger phrases:** "I don't have insurance", "What if I can't afford it?", "Do you offer payment plans?", "How much does a cleaning cost?"

**Flow:**
1. State machine → `get_clinic_info(category="payment")` + `get_pricing_options()`.
2. Returns self-pay rates, Bright Smile Membership details, and PayBright financing info.
3. Gemini presents the options in a clear, reassuring tone.

**Tool:** `get_clinic_info` + `get_pricing_options`
**No fields collected.**

---

## Scheduling flows

These flows collect patient information before calling a scheduling tool.
Flows that require a `patient_id` automatically pivot to **Patient Verification** as
a sub-workflow first, then resume the original flow.

### 5. New Patient Booking ✅ Live

**Trigger phrases:** "I'm a new patient", "I'd like to register", "First time here", "Never been before"

**Fields collected (in order):**

| Field | Example | Extractor |
|-------|---------|-----------|
| Full name | "My name is Sarah Chen" | `extract_full_name` |
| Phone number | "(416) 555-1234" | `extract_phone` |
| Date of birth | "March 14, 1985" | `extract_dob` |
| Insurance name | "Sun Life" / "I don't have insurance" | `extract_insurance` |
| Appointment type | "cleaning", "checkup", "new patient exam" | `extract_appointment_type` |
| Preferred date | "next Tuesday", "sometime next week" | `extract_preferred_date` |

**Optional fields (extracted if mentioned):** preferred time of day (`morning` / `afternoon` / `any`)

**Flow:**
```
Opening SMS
    │
    ▼
User: "I'm a new patient"
    │
    ▼
Collect fields (one prompt per missing field, extracted inline if volunteered)
    │
    ▼  all fields present
create_patient ──► validates phone (10-digit NANP)
                ► validates DOB (must be in the past, realistic age)
                ► checks for duplicate phone number
                ► fuzzy-links InsurancePlan if insurance_name matches a known carrier
                ► patient status set to "lead"
    │
    ▼  patient created
search_slots (same turn, auto)
    │
    ├─ No slots found → ask for different date / time
    │
    ▼  slots found
Present up to 3 options:
  "1. Mon Apr 14, 10:00 AM
   2. Tue Apr 15, 11:00 AM
   3. Wed Apr 16, 2:00 PM"
    │
    ▼  user replies "1" / "first" / "option 2"
book_appointment ──► locks slot (SELECT FOR UPDATE equivalent)
                 ► creates Appointment (status="booked", booked_via="chatbot")
                 ► returns confirmation message
    │
    ▼
"You're all set! See you Mon Apr 14 at 10:00 AM. Reply CANCEL to cancel."
```

**Validation / normalisation enforced:**

| Check | Behaviour on failure |
|-------|---------------------|
| Phone format | Re-ask with specific error ("That phone number doesn't look right — 10 digits, please") |
| DOB in the past | Re-ask ("Date of birth must be a past date") |
| Duplicate phone | Return error ("A patient with that phone is already registered — are you an existing patient?") |
| Appointment type | Fuzzy-mapped to canonical code; unknown type → re-ask |
| Slot taken between search and book | Remove from options, re-present remaining slots |

**Tools called:** `create_patient` → `search_slots` (auto-chained, same turn) → `book_appointment` (after slot selection)

---

### 6. Patient Verification ✅ Live

*Used standalone and as a sub-workflow for flows 7–9 and 11.*

**Trigger phrases:** "I'm an existing patient", "I've been here before"

**Fields collected:**

| Field | Required? | Example |
|-------|-----------|---------|
| Last name | Required | "Thompson" |
| Date of birth | Required | "March 14 1985" |
| First name | Optional | "Alice" — used for disambiguation only |
| Phone number | Optional | "(416) 555-0201" — boosts match confidence to 1.0 |

**Confidence levels:**

| Scenario | `match_confidence` |
|----------|--------------------|
| Phone-only match | 0.8 |
| Last name + DOB match | 0.7 |
| Last name + DOB + phone match | 1.0 |
| Last name + DOB + first name disambiguation | 0.9 |

**Flow:**
```
User: "existing patient" (or any booking intent without patient_id)
    │
    ▼
Ask: "Could you tell me your last name and date of birth?"
    │
    ▼  fields collected
lookup_patient
    │
    ├─ found (conf ≥ 0.7) ──────────────► set patient_id → resume pending workflow
    │
    ├─ multiple_matches ────────────────► "Found more than one patient with that
    │                                      name and date of birth. Could you also
    │  user replies with first name        share your first name?"
    │       │                              step = "disambiguating"
    │       ▼
    │  retry lookup_patient (with first_name)
    │       │
    │       └─ resolved ────────────────► resume pending workflow
    │       └─ still ambiguous ─────────► "Please call (416) 555-0100"
    │
    ├─ low confidence (phone match       ► "I found a record for that number
    │  but name mismatch, conf < 0.7)      but couldn't fully verify it.
    │                                      Could you confirm your last name
    │  user replies with name + DOB        and date of birth?"
    │       │                              step = "reconfirming"
    │       ▼
    │  retry lookup_patient
    │
    └─ not found ───────────────────────► clear name fields, offer retry
           │  (_lookup_retry = True)       or new-patient registration
           └─ still not found ──────────► "I still wasn't able to match…
                                           Please call us or register as new"
```

**Tool:** `lookup_patient`

---

### 7. Existing Patient Appointment Booking ✅ Live

**Trigger phrases:** "I want to book a cleaning", "Schedule an appointment", "Can I come in next week?", "I need a check-up"

**Requires:** patient identity — state machine automatically runs flow 6 first if `patient_id` is absent.

**Fields collected (after verification):**

| Field | Example |
|-------|---------|
| Appointment type | "cleaning", "general checkup", "emergency" |
| Preferred date | "next Monday", "April 15th" |

**Optional fields:** preferred time of day (morning / afternoon / any)

**Flow:**
```
User: "I want to book a cleaning next week"
    │
    ├─ patient_id present ──────────────────────────┐
    │                                               │
    └─ no patient_id ──► run flow 6 (verification)  │
           │  verified                              │
           └────────────────────────────────────────┘
                │
                ▼
    Collect: appointment type + preferred date
                │
                ▼  all fields collected
    search_slots (date window: requested date + 14 days)
                │
                ├─ No slots → ask for different date / time of day
                │
                ▼  slots found
    Present up to 3 options (same UI as flow 5)
                │
                ▼  user selects
    book_appointment ──► confirmation
```

**Appointment types supported:**

| Code | Shown as | Note |
|------|----------|------|
| `cleaning` | Teeth Cleaning | |
| `general_checkup` | General Check-up | |
| `new_patient_exam` | New Patient Exam | |
| `emergency` | Emergency Visit | Triggers flow 10 (staff notification) |

**Tools called:** `lookup_patient` (if unverified) → `search_slots` → `book_appointment`

**Re-used helpers:** `_search_and_present_slots`, `_handle_slot_selection` — identical to flow 5

---

### 8. Reschedule Appointment 🔧 Stub

**Trigger phrases:** "I need to reschedule", "Can I change my appointment?", "Move my booking"

**Requires:** patient identity + existing appointment

**Fields collected:**

| Field | Example |
|-------|---------|
| Preferred new date | "next Friday", "sometime in April" |

**Optional fields:** preferred time of day

**Flow:**
1. Verify patient identity (sub-workflow 6).
2. Show patient's upcoming appointments; patient selects which to reschedule.
3. Ask for preferred new date.
4. `search_slots` finds available times.
5. Patient selects → `reschedule_appointment` called.
6. Old slot is freed; new slot is confirmed.

**Tools:** `lookup_patient` → `search_slots` → `reschedule_appointment`

---

### 9. Cancel Appointment 🔧 Stub

**Trigger phrases:** "Cancel my appointment", "I need to cancel", "I can't make it"

**Requires:** patient identity + existing appointment

**Fields collected:**

| Field | Example |
|-------|---------|
| Cancel reason | "I'm feeling better", "scheduling conflict" |

**Flow:**
1. Verify patient identity (sub-workflow 6).
2. Show upcoming appointments; patient selects one to cancel.
3. Ask for reason (optional but collected for records).
4. Confirmation prompt — patient confirms.
5. `cancel_appointment` called; slot is freed.

**Tools:** `lookup_patient` → `cancel_appointment`
**Requires confirmation before tool call: yes**

---

### 10. Emergency Triage 🔧 Stub

**Trigger phrases:** "I'm in severe pain", "Broken tooth", "Dental emergency", "I need urgent help"

**Fields collected:**

| Field | Example |
|-------|---------|
| First name | "James" |
| Phone number | "(416) 555-9999" |
| Emergency summary | "Severe toothache, pain 9/10, started this morning" |

**Flow:**
1. Chatbot immediately acknowledges the emergency and expresses concern.
2. Collects name, phone, and a brief description of the emergency — no confirmation delay.
3. `create_staff_notification` called with `priority="urgent"` and emergency summary.
4. Patient is told staff will contact them shortly.
5. *(Next step — stub pending):* attempt to book a same-day emergency slot.

**Tool:** `create_staff_notification` (urgent) → `search_slots` → `book_appointment`
**No confirmation pause — staff are notified immediately.**

---

### 11. Family Booking 🔧 Stub

**Trigger phrases:** "Book for my whole family", "I need appointments for my kids", "Can we all come in the same day?"

**Requires:** patient identity (primary account holder)

**Fields collected:**

| Field | Example |
|-------|---------|
| Family count | "3 people", "my two kids and me" |
| Appointment type | "cleanings for everyone" |
| Preferred date | "Saturday morning" |

**Optional fields:** group preference (back-to-back / same-day / same-provider), preferred time of day

**Coordination options:**

| Preference | Behaviour |
|------------|-----------|
| `back_to_back` | Consecutive slots, same provider if possible |
| `same_day` | All on the same day, any available times |
| `same_provider` | All with the same dentist |
| *(none)* | Best available slots independently |

**Flow:**
1. Verify primary account holder identity (sub-workflow 6).
2. Ask how many people + what type of appointment each needs.
3. Ask for preferred date and coordination preference.
4. Confirmation summary shown for all members.
5. `book_family_appointments` called atomically.

**Tool:** `lookup_patient` → `book_family_appointments`
**Requires confirmation before tool call: yes**

---

## Staff / Escalation flows

### 12. Staff Handoff 🔧 Stub

**Trigger phrases:** "I'd like to speak to someone", "Let me talk to a human", "Can I speak to the receptionist?"

**Fields collected:**

| Field | Example |
|-------|---------|
| Phone number | "(416) 555-1111" |

**Optional fields:** first name

**Flow:**
1. Chatbot acknowledges and collects phone number.
2. `create_staff_notification` called (priority: normal, type: callback_request).
3. Patient is told a team member will call back.

**Tool:** `create_staff_notification`

---

## Flow detection — how the chatbot decides which flow to start

The `detect_intent` function in `state_machine/machine.py` uses keyword matching
to route to the correct workflow at the start of each conversation.
The order below is the priority — a message matching multiple categories uses the
first match:

1. Emergency keywords → Emergency Triage
2. Family / kids keywords → Family Booking
3. Cancel keywords → Cancel Appointment
4. Reschedule keywords → Reschedule Appointment
5. Register / new patient keywords → New Patient Registration
6. Book / appointment / schedule keywords → Book Appointment (triggers verification)
7. Speak to human / receptionist → Staff Handoff
8. *(anything else)* → General Inquiry

---

## Tool map

| Tool | Called by flow(s) | Status |
|------|-------------------|--------|
| `get_clinic_info` | 1 · 2 · 3 · 4 | ✅ Live |
| `lookup_patient` | 6 · 7 · 8 · 9 · 11 | ✅ Live |
| `create_patient` | 5 | ✅ Live |
| `search_slots` | 5 · 7 · 8 · 10 | ✅ Live |
| `book_appointment` | 5 · 7 · 10 | ✅ Live |
| `reschedule_appointment` | 8 | 🔧 Stub |
| `cancel_appointment` | 9 | 🔧 Stub |
| `book_family_appointments` | 11 | 🔧 Stub |
| `create_staff_notification` | 10 · 12 | 🔧 Stub |

---

## Shared helpers (code reuse)

Both flows 5 and 7 share the same slot-selection pipeline — no duplicated logic:

| Helper | Location | Used by |
|--------|----------|---------|
| `_search_and_present_slots` | `routers/chat.py` | Flows 5 and 7 (and 8/10 when implemented) |
| `_handle_slot_selection` | `routers/chat.py` | Flows 5 and 7 — parses "1" / "first" / "option 2" → `book_appointment` |
| `_resume_pending_workflow` | `routers/chat.py` | Flow 6 — resumes whichever workflow triggered verification |
| `_apply_verification_retry` | `routers/chat.py` | Flow 6 — handles disambiguation and re-confirm retry turns |
| `normalize_appointment_type` | `tools/validators.py` | Flows 5 and 7 — maps free text to canonical codes |
| `normalize_phone` | `tools/validators.py` | Flow 5 — validates and normalises phone before `create_patient` |
