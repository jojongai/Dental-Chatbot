# Dental Office Chatbot — Project Documentation

**Jojo Ngai**

This document describes a working prototype of an SMS-style dental office assistant: it answers common questions, guides patients through booking and related tasks, and integrates a staff-facing schedule view. It is written for evaluators who need a clear picture of scope, architecture, and how to run the software locally.

---

## 1. Project Overview

The chatbot helps patients interact with a fictional practice (**Bright Smile Dental**) through natural language: hours, location, insurance, booking, rescheduling, cancellations, new-patient registration, family booking, emergencies, and handoff to staff. The backend combines **structured workflows** (a state machine) with an **LLM** (Google Gemini) for flexible wording, so replies feel conversational while actions remain predictable.

**Problem it addresses.** Phone lines and front-desk staff are often overloaded. A chat interface can answer routine questions 24/7, collect structured data before an appointment, and escalate urgent cases—reducing friction for patients and clarifying intent for the clinic.

**Prototype scope.** This is a **functional prototype**, not a production product. It uses a local SQLite database, real LLM calls, and a browser-based “SMS” UI plus an employee dashboard backed by the same API. Features are implemented to demo end-to-end paths.

---

## 2. Working Prototype

### Capabilities

The chatbot supports multiple **workflows** driven by intent detection and a workflow state machine. In practice, evaluators can try:

- **General inquiry** — Hours, location, insurance, pricing, payment, and FAQ-style answers pulled from the database, with natural-language replies when the LLM is enabled.
- **Booking** — New vs existing patient flows, slot search, slot selection, and appointment creation in the database.
- **Reschedule / cancel** — Verification-style flows with appointment selection and tool calls to update or cancel records.
- **New patient registration** — Collecting identity fields and creating a patient record.
- **Family booking** — Multi-step collection for scheduling multiple family members.
- **Emergency triage** — Escalation messaging, staff notifications, optional urgent slot offers, and booking when slots exist.
- **Staff handoff** — Callback-oriented flow when the patient asks for a human.

The **employee dashboard** (`/employee` in the web app) loads schedule data from the API for a selected day, including appointment rows and emergency highlights, when the API and database are running with seeded data.

### How to test (access instructions)

1. **Clone the repository** and follow **Section 6** (setup) so dependencies and `.env` are in place.
2. **Seed the database** (recommended for a realistic schedule):

   ```bash
   cd apps/api
   python seed.py --reset
   ```

   SQLite path defaults to `apps/api/data/app.db` unless `DATABASE_URL` overrides it.

3. **Start the stack** from the repo root:

   ```bash
   npm run dev
   ```

4. Open the **chat UI** at `http://localhost:3000` and the **API docs** at `http://localhost:8000/docs`.

5. **LLM behavior:** With `USE_LLM=false` (default in `.env.example`), the system avoids live Gemini calls and uses deterministic fallbacks—suitable for CI and quick testing. Set `USE_LLM=true` and add a valid `GEMINI_API_KEY` to exercise full natural-language behavior.

### Assumptions and limitations

- **Single practice / demo data** — Seeded content represents one location and fixed providers; multi-tenant production behavior is out of scope.
- **Gemini** — Optional; without a key or with `USE_LLM=false`, responses are simpler but flows still run.
- **REST stubs (`501`)** — Some routers (`appointments`, `patients`, `clinic`) expose **planned** REST endpoints with Pydantic models and Swagger entries; the handlers are placeholders (`TODO: delegate to tools.…`). The working logic lives in **`tools/`** and is invoked from **`POST /chat`**, which was built first. The stubs remain as a **roadmap** for staff apps or third-party clients—not accidental clutter. For demos, use **chat** and routes that are fully wired (e.g. employee schedule).
- **Security** — Prototype only: no hardened auth model for patients; treat as local demonstration.

---

## 3. Architecture Overview

The system is a **monorepo** with clear separation between UI, API, and shared contracts.

**Browser → Next.js (`apps/chatbot-ui`).** The frontend implements the SMS-style chat and the employee dashboard. It calls the FastAPI backend over HTTP (`NEXT_PUBLIC_API_URL`, typically `http://localhost:8000`).

**API → FastAPI (`apps/api`).** HTTP routes under `/chat` run the **workflow state machine** (`state_machine/`), which decides which fields to collect and when to call **tools** (`tools/`)—scheduling, patient lookup/create, clinic info, notifications, etc. An **interpreter** layer (`llm/interpreter.py`) uses Gemini when enabled to extract structured fields from free text; otherwise keyword/regex fallbacks apply.

**Database → SQLAlchemy + SQLite (or Postgres).** Models cover practices, locations, patients, appointments, slots, staff, conversations, and notifications. **Seed data** (`seed.py`) populates a demo world for local testing.

**LLM / inference.** Google **Gemini** is invoked from the API for intent classification and interpretation, gated by `USE_LLM` and `GEMINI_API_KEY`. This keeps all inference server-side and avoids exposing keys in the browser.

**State and workflows.** Long-running chat behavior is not stored only in the LLM: the **state machine** (`workflow`, `step`, `collected_fields`, slot options) persists per session so the same patient journey can be resumed and tested reliably.

---

## 4. Technologies Used

| Technology | Role | Why it was chosen |
|------------|------|-------------------|
| **Next.js** (React, TypeScript) | Web app | Fast iteration, good ecosystem, easy deployment story. |
| **Tailwind CSS** | Styling | Rapid UI work consistent with a prototype. |
| **FastAPI** | REST API | Clear request/response typing with Pydantic, async-friendly, auto OpenAPI docs. |
| **Pydantic** | Validation | Shared contracts between tools, routers, and DB boundaries. |
| **SQLAlchemy** | ORM | Portable SQLite for dev; Postgres for production-like runs. |
| **Google Gemini** | LLM | Strong general-purpose model for classification and paraphrasing; configurable via env. |
| **uv** | Python env & deps | Reproducible installs and lockfile for the API. |
| **npm workspaces + Turbo** | Monorepo scripts | One command to run frontend and backend together. |

---

## 5. Design Decisions and Rationale

**State machine + LLM, not LLM-only.** Relying entirely on an LLM for booking would be fragile (hallucinated fields, inconsistent states). The prototype **fixes** workflow transitions and field requirements in code, while the LLM **fills** natural-language gaps. That tradeoff favors reliability for a demo and easier testing.

**Tools as explicit actions.** Booking, search, and patient create are **named tools** with typed inputs. The model suggests field values; the engine validates and executes. That makes behavior auditable and aligns with “chatbot as orchestrator” patterns.

**SQLite by default.** Zero setup for graders and teammates; switching to Postgres is a configuration change for anyone who wants a production-like test.

**Optional LLM.** Tests and laptops without API keys still run the same flows with fallbacks, which keeps CI cheap and demos reproducible.

**Employee schedule via API.** The dashboard shares the same source of truth as the chatbot’s scheduling logic, reducing drift between “what staff see” and “what the bot books.”

---

## 6. Setup and Usage Instructions

**Prerequisites:** Node.js 20+, npm 10+, and Python **3.12+**. For the API you can use **[uv](https://docs.astral.sh/uv/)** (what the repo scripts prefer) or a normal **virtual environment + pip**.

1. **Install JavaScript dependencies** (repository root):

   ```bash
   npm install
   ```

2. **Install Python dependencies** (`apps/api`). Pick **one** approach.

   **Option A — uv (fastest, matches CI):**

   ```bash
   cd apps/api
   uv sync --group dev
   cd ../..
   ```

   **Option B — venv + pip (no uv required):**

   ```bash
   cd apps/api
   python3 -m venv .venv
   source .venv/bin/activate          # Windows: .venv\Scripts\activate
   pip install --upgrade pip
   pip install -e .
   pip install alembic httpx pytest ruff
   cd ../..
   ```

   The API dev script (`apps/api/scripts/dev.sh`) uses `uv run` when `uv` is installed; otherwise it runs **`python -m uvicorn`** using `apps/api/.venv` if that folder exists, so Option B works for local runs.

3. **Environment file.** Copy the template and edit as needed:

   ```bash
   cp .env.example .env
   ```

   Minimum for local UI + API: `NEXT_PUBLIC_API_URL`, `CORS_ORIGINS`, `DATABASE_URL`. For Gemini: `GEMINI_API_KEY` and `USE_LLM=true`.

4. **Database seed (optional but recommended):**

   From `apps/api`, with the same Python you use for the API (activate the venv first if you use Option B):

   ```bash
   cd apps/api && python seed.py --reset && cd ../..
   ```

5. **Run development servers** (root):

   ```bash
   npm run dev
   ```

   - Chat UI: `http://localhost:3000`  
   - Employee dashboard: `http://localhost:3000/employee`  
   - API + Swagger: `http://localhost:8000/docs`

6. **Tests** (root): `npm run test` runs workspace tests (including API pytest via Turbo).

---

## 7. Code Repository Notes

**Organization.** The repo uses standard **app** and **package** boundaries:

- `apps/chatbot-ui` — Frontend.  
- `apps/api` — Backend, models, tests, `seed.py`.  
- `packages/shared-types` — Shared TypeScript/Zod-style contracts.  
- `packages/prompts` — Prompt text.  
- `docs/` — Architecture and flow notes (`architecture.md`, `flows.md`).  
- **`SUBMISSION_DOCUMENTATION.md`** (repository root) — Full project write-up (this document).

**Commit history.** Evaluators should use a **clear, incremental commit history** (feature branches, descriptive messages). *[If your course requires a specific commit message or branch policy, add it here.]*

**README and environment template.** The **root `README.md`** is a short overview and points here; **`.env.example`** lists important variables—copy to `.env` and never commit secrets.

---

## 8. Conclusion

This project delivers a **working, testable** dental chatbot prototype: structured workflows, database-backed scheduling and patient records, optional Gemini-powered language understanding, and a staff schedule view tied to the same API. With the steps in Section 6, an evaluator can run the stack locally, seed demo data, and walk through representative patient journeys. The design prioritizes **clarity and repeatability** for a classroom or review setting while leaving a clear path to hardening for production.

---

*End of submission documentation.*
