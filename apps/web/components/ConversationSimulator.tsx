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
  const [choices, setChoices] = useState<string[]>([]);
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
        } else if (step?.patientChoices) {
          setChoices(step.patientChoices);
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
    setChoices([]);

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
    setChoices([]);
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
    <div className="relative">
      <PhoneFrame>
        <SMSHeader />

        {/* Messages area */}
        <div
          ref={scrollRef}
          className="flex-1 min-h-0 overflow-y-auto py-3 space-y-[2px]"
          style={{ scrollBehavior: "smooth", WebkitOverflowScrolling: "touch" } as React.CSSProperties}
        >
          {/* iMessage-style date header */}
          <div className="text-center text-[11px] text-sms-timestamp font-medium mb-3">
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

        {/* Quick-reply chips (above keyboard) */}
        {choices.length > 0 && !isEnded && (
          <div className="px-3 py-2 flex flex-wrap gap-2 border-t border-border/30 bg-phone-screen">
            {choices.map((choice) => (
              <button
                key={choice}
                onClick={() => handleSend(choice)}
                disabled={isTyping}
                className="px-3 py-1.5 rounded-full border border-primary text-primary text-[13px]
                           bg-transparent hover:bg-primary/10 active:bg-primary/20
                           disabled:opacity-40 transition-colors"
              >
                {choice}
              </button>
            ))}
          </div>
        )}

        <SMSInputBar onSend={handleSend} disabled={isEnded || isTyping} />
      </PhoneFrame>

      {/* Restart button below the phone */}
      <button
        onClick={handleReset}
        className="absolute -bottom-16 left-1/2 -translate-x-1/2 flex items-center gap-2 px-4 py-2 rounded-full
                   bg-foreground/5 hover:bg-foreground/10 text-foreground/60 hover:text-foreground/80
                   text-sm font-medium transition-colors"
      >
        <RotateCcw className="w-4 h-4" />
        Restart conversation
      </button>
    </div>
  );
};

export default ConversationSimulator;
