"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { RotateCcw } from "lucide-react";
import PhoneFrame from "./PhoneFrame";
import SMSHeader from "./SMSHeader";
import SMSBubble from "./SMSBubble";
import SMSTypingIndicator from "./SMSTypingIndicator";
import SMSInputBar from "./SMSInputBar";
import { sendMessage, WorkflowState } from "@/lib/chatApi";

// ── Types ───────────────────────────────────────────────────────────────────

interface ChatMessage {
  id: string;
  sender: "clinic" | "patient";
  text: string;
}

function makeId(): string {
  return typeof crypto !== "undefined"
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);
}

// ── Component ───────────────────────────────────────────────────────────────

const ConversationSimulator = () => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chatState, setChatState] = useState<WorkflowState | null>(null);
  const [isTyping, setIsTyping] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sessionId = useRef<string>(makeId());
  /** After Restart, first user message forces server-side new-thread sanitization. */
  const newConversationFirstSend = useRef(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const msgCounter = useRef(0);

  const nextId = () => {
    msgCounter.current += 1;
    return `msg-${msgCounter.current}`;
  };

  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, isTyping, scrollToBottom]);

  // ── API call helper ──────────────────────────────────────────────────────

  const callApi = useCallback(
    async (userText: string, isOpening = false) => {
      setIsTyping(true);
      setError(null);
      try {
        const flagNew = newConversationFirstSend.current;
        if (flagNew) {
          newConversationFirstSend.current = false;
        }
        const data = await sendMessage({
          session_id: sessionId.current,
          message: userText,
          // Opening must never echo prior workflow state (avoids stale React closure).
          state: isOpening ? null : chatState,
          is_session_opening: isOpening,
          new_conversation: flagNew && !isOpening,
        });

        setChatState(data.state);

        // The reply may be multi-line; render it as one bubble
        setMessages((prev) => [
          ...prev,
          { id: nextId(), sender: "clinic", text: data.reply },
        ]);
      } catch (err) {
        const msg =
          err instanceof Error ? err.message : "Something went wrong.";
        setError(msg);
        setMessages((prev) => [
          ...prev,
          {
            id: nextId(),
            sender: "clinic",
            text: "Sorry, I'm having trouble connecting right now. Please try again in a moment.",
          },
        ]);
      } finally {
        setIsTyping(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [chatState]
  );

  // ── Opening SMS on mount ─────────────────────────────────────────────────

  useEffect(() => {
    callApi("", true);
    // Run once on mount only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── User sends a message ─────────────────────────────────────────────────

  const handleSend = (text: string) => {
    if (isTyping) return;

    // Append the patient bubble immediately
    setMessages((prev) => [
      ...prev,
      { id: nextId(), sender: "patient", text },
    ]);

    callApi(text);
  };

  // ── Restart ──────────────────────────────────────────────────────────────

  const handleReset = () => {
    setMessages([]);
    setChatState(null);
    setError(null);
    setIsTyping(false);
    msgCounter.current = 0;
    sessionId.current = makeId();
    newConversationFirstSend.current = true;

    // Small delay so state is cleared before the opening call fires
    setTimeout(() => callApi("", true), 100);
  };

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <>
      <button
        type="button"
        onClick={handleReset}
        disabled={isTyping}
        className="fixed top-3 right-3 z-50 flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium
                   bg-background/90 text-muted-foreground shadow-sm border border-border/60 backdrop-blur-sm
                   hover:bg-muted hover:text-foreground disabled:opacity-40 transition-colors"
        aria-label="Restart conversation"
      >
        <RotateCcw className="h-3.5 w-3.5" />
        Restart
      </button>

      <PhoneFrame>
        <SMSHeader />

        {/* Thread — only this div scrolls */}
        <div
          ref={scrollRef}
          className="flex-1 min-h-0 overflow-y-auto py-2 space-y-[2px]"
          style={
            {
              scrollBehavior: "smooth",
              WebkitOverflowScrolling: "touch",
            } as React.CSSProperties
          }
        >
          <div className="text-center text-[10px] text-sms-timestamp font-medium mb-2">
            Today {new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </div>

          {messages.map((msg) => (
            <SMSBubble key={msg.id} text={msg.text} sender={msg.sender} />
          ))}

          {isTyping && <SMSTypingIndicator />}

          {error && (
            <p className="text-center text-[11px] text-destructive px-4 py-1">
              {error}
            </p>
          )}
        </div>

        <SMSInputBar onSend={handleSend} disabled={isTyping} />
      </PhoneFrame>
    </>
  );
};

export default ConversationSimulator;
