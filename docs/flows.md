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

### 5. New Patient Registration 🔧 Stub

**Trigger phrases:** "I'm a new patient", "I'd like to register", "First time here"

**Fields collected (in order):**

| Field | Example |
|-------|---------|
| Full name | "My name is Sarah Chen" |
| Phone number | "(416) 555-1234" |
| Date of birth | "March 14, 1985" |
| Insurance name | "Sun Life" / "I don't have insurance" |
| Appointment type | "cleaning", "checkup", "new patient exam" |
| Preferred date | "next Tuesday", "sometime next week" |

**Optional fields (extracted if mentioned):** preferred time of day

**Flow:**
1. Chatbot greets new patient and asks for each field in order.
2. Fields are extracted from free-text via regex/keyword extractors (no LLM).
3. When all fields are collected → confirmation summary shown.
4. Patient confirms → `create_patient` tool called.
5. *(Next step — stub pending):* `search_slots` called to find available times.

**Tools:** `create_patient` → `search_slots` → `book_appointment`
**Requires confirmation before tool call: yes**

---

### 6. Patient Verification 🔧 Stub

*Used standalone and as a sub-workflow for flows 7–10.*

**Trigger phrases:** "I'm an existing patient", "I need to book an appointment"

**Fields collected:**

| Field | Example |
|-------|---------|
| Last name | "Thompson" |
| Date of birth | "1985-03-14" |

**Optional fields:** phone number (raises match confidence), first name

**Flow:**
1. Chatbot asks for last name + DOB.
2. `lookup_patient` called — returns `found: true/false` + patient record.
3. On success: resumes pending parent workflow (book / reschedule / cancel).
4. On failure: offers new-patient registration.

**Tool:** `lookup_patient`

---

### 7. Book Appointment 🔧 Stub

**Trigger phrases:** "I want to book a cleaning", "Schedule an appointment", "Can I come in next week?"

**Requires:** patient identity (auto-runs flow 6 first if not verified)

**Fields collected:**

| Field | Example |
|-------|---------|
| Appointment type | "cleaning", "general checkup", "emergency" |
| Preferred date | "next Monday", "April 15th" |

**Optional fields:** preferred time of day (morning / afternoon / after school)

**Flow:**
1. Verify patient identity (sub-workflow 6).
2. Ask for appointment type + preferred date.
3. `search_slots` returns up to 5 available slots.
4. Patient selects a slot → `book_appointment` called.
5. Confirmation with date, time, and provider name.

**Tools:** `lookup_patient` → `search_slots` → `book_appointment`

**Appointment types supported:**

| Code | Shown as |
|------|----------|
| `cleaning` | Teeth Cleaning |
| `general_checkup` | General Check-up |
| `new_patient_exam` | New Patient Exam |
| `emergency` | Emergency Visit (→ triggers flow 10) |

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
| `lookup_patient` | 6 · 7 · 8 · 9 · 11 | 🔧 Stub |
| `create_patient` | 5 | 🔧 Stub |
| `search_slots` | 5 · 7 · 8 · 10 | 🔧 Stub |
| `book_appointment` | 5 · 7 · 10 | 🔧 Stub |
| `reschedule_appointment` | 8 | 🔧 Stub |
| `cancel_appointment` | 9 | 🔧 Stub |
| `book_family_appointments` | 11 | 🔧 Stub |
| `create_staff_notification` | 10 · 12 | 🔧 Stub |
