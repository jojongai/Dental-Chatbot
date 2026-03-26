"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { RotateCcw } from "lucide-react";
import PhoneFrame from "./PhoneFrame";
import SMSHeader from "./SMSHeader";
import SMSBubble from "./SMSBubble";
import SMSTypingIndicator from "./SMSTypingIndicator";
import SMSInputBar from "./SMSInputBar";
import { conversationSteps, Message } from "@/data/conversationFlows";

interface DisplayMessage extends Message {
  stepId: string;
}

const ConversationSimulator = () => {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [currentStepId, setCurrentStepId] = useState("start");
  const [isTyping, setIsTyping] = useState(false);
  const [isEnded, setIsEnded] = useState(false);
  const [pendingMessages, setPendingMessages] = useState<{
    msgs: Message[];
    stepId: string;
  } | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  const msgCounter = useRef(0);

  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, isTyping, scrollToBottom]);

  // Deliver pending messages one at a time with a typing delay
  useEffect(() => {
    if (!pendingMessages || pendingMessages.msgs.length === 0) return;

    const [next, ...rest] = pendingMessages.msgs;
    const delay = next.delay ?? 800;

    setIsTyping(true);

    const timer = setTimeout(() => {
      setIsTyping(false);
      msgCounter.current += 1;
      const displayMsg: DisplayMessage = {
        ...next,
        id: `msg-${msgCounter.current}`,
        stepId: pendingMessages.stepId,
      };
      setMessages((prev) => [...prev, displayMsg]);

      if (rest.length > 0) {
        setPendingMessages({ msgs: rest, stepId: pendingMessages.stepId });
      } else {
        setPendingMessages(null);
        const step = conversationSteps[pendingMessages.stepId];
        if (step?.isEnd) {
          setIsEnded(true);
        }
      }
    }, delay);

    return () => clearTimeout(timer);
  }, [pendingMessages]);

  // Kick off the opening message
  useEffect(() => {
    const step = conversationSteps["start"];
    if (step) {
      setPendingMessages({ msgs: step.messages, stepId: "start" });
    }
  }, []);

  const handleSend = (text: string) => {
    if (isEnded || isTyping) return;

    msgCounter.current += 1;
    const patientMsg: DisplayMessage = {
      id: `msg-${msgCounter.current}`,
      sender: "patient",
      text,
      timestamp: "",
      stepId: currentStepId,
    };
    setMessages((prev) => [...prev, patientMsg]);

    const currentStep = conversationSteps[currentStepId];
    let nextStepId = currentStep?.nextStep;

    if (currentStep?.nextStepMap) {
      nextStepId =
        currentStep.nextStepMap[text] ?? Object.values(currentStep.nextStepMap)[0];
    }

    if (nextStepId && conversationSteps[nextStepId]) {
      setCurrentStepId(nextStepId);
      setPendingMessages({
        msgs: conversationSteps[nextStepId].messages,
        stepId: nextStepId,
      });
    }
  };

  const handleReset = () => {
    setMessages([]);
    setCurrentStepId("start");
    setIsTyping(false);
    setIsEnded(false);
    setPendingMessages(null);
    msgCounter.current = 0;

    setTimeout(() => {
      const step = conversationSteps["start"];
      if (step) {
        setPendingMessages({ msgs: step.messages, stepId: "start" });
      }
    }, 300);
  };

  return (
    <>
      <button
        type="button"
        onClick={handleReset}
        className="fixed top-3 right-3 z-50 flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium
                   bg-background/90 text-muted-foreground shadow-sm border border-border/60 backdrop-blur-sm
                   hover:bg-muted hover:text-foreground transition-colors"
        aria-label="Restart conversation"
      >
        <RotateCcw className="h-3.5 w-3.5" />
        Restart
      </button>

      <PhoneFrame>
        <SMSHeader />

        {/* Messages area — scrolls inside the thread only, not the page */}
        <div
          ref={scrollRef}
          className="flex-1 min-h-0 overflow-y-auto py-2 space-y-[2px]"
          style={{ scrollBehavior: "smooth", WebkitOverflowScrolling: "touch" } as React.CSSProperties}
        >
          <div className="text-center text-[10px] text-sms-timestamp font-medium mb-2">
            Today 2:34 PM
          </div>

          {messages.map((msg) => (
            <SMSBubble
              key={msg.id}
              text={msg.text}
              sender={msg.sender}
              timestamp={msg.timestamp || undefined}
            />
          ))}

          {isTyping && <SMSTypingIndicator />}
        </div>

        <SMSInputBar onSend={handleSend} disabled={isEnded || isTyping} />
      </PhoneFrame>
    </>
  );
};

export default ConversationSimulator;
