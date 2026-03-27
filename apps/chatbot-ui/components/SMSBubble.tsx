"use client";

import { motion } from "framer-motion";

interface SMSBubbleProps {
  text: string;
  sender: "clinic" | "patient";
  timestamp?: string;
  showTail?: boolean;
}

const SMSBubble = ({ text, sender, timestamp, showTail = true }: SMSBubbleProps) => {
  const isClinic = sender === "clinic";

  return (
    <motion.div
      initial={{ opacity: 0, y: 12, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className={`flex ${isClinic ? "justify-start" : "justify-end"} px-3 mb-[3px]`}
    >
      <div className="flex flex-col max-w-[75%]">
        <div
          className={`
            px-3 py-[7px] text-[15px] leading-[20px] whitespace-pre-line
            ${
              isClinic
                ? `bg-sms-incoming text-sms-incoming-foreground ${
                    showTail ? "rounded-[18px] rounded-bl-[4px]" : "rounded-[18px]"
                  }`
                : `bg-sms-outgoing text-sms-outgoing-foreground ${
                    showTail ? "rounded-[18px] rounded-br-[4px]" : "rounded-[18px]"
                  }`
            }
          `}
        >
          {text}
        </div>
        {timestamp && (
          <span
            className={`text-[11px] text-sms-timestamp mt-[2px] ${
              isClinic ? "ml-1" : "mr-1 text-right"
            }`}
          >
            {timestamp}
          </span>
        )}
      </div>
    </motion.div>
  );
};

export default SMSBubble;
