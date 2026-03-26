/**
 * Typed client for POST /chat.
 *
 * The backend is stateless per request: every turn the client echoes back
 * the `state` object from the previous response so the server can resume
 * the workflow without a DB read.
 */

// ── Subset of the backend WorkflowState we need on the client ──────────────

export interface WorkflowState {
  workflow: string;
  step: string;
  patient_id: string | null;
  appointment_id: string | null;
  collected_fields: Record<string, unknown>;
  missing_fields: string[];
  slot_options: { id: string; label: string }[];
  selected_slot_id: string | null;
  appointment_options: { id: string; label: string }[];
}

// ── Request / Response shapes ───────────────────────────────────────────────

export interface ChatRequest {
  session_id: string;
  message: string;
  /** Omit or null for opening / fresh thread — never send a stale workflow here. */
  state?: WorkflowState | null;
  is_session_opening?: boolean;
  /**
   * When true, server drops prior-thread intent (booking prefs, emergency text, slots,
   * pending workflows) and keeps only identity fields + patient_id for demographic pre-fill.
   */
  new_conversation?: boolean;
}

export interface ChatResponse {
  reply: string;
  state: WorkflowState;
  tools_called: string[];
  actions: unknown[];
}

// ── API client ──────────────────────────────────────────────────────────────

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function sendMessage(req: ChatRequest): Promise<ChatResponse> {
  const res = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`API ${res.status}: ${text}`);
  }

  return res.json() as Promise<ChatResponse>;
}
