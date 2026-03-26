"use client";

import { motion } from "framer-motion";

const SMSTypingIndicator = () => {
  return (
    <div className="flex justify-start px-3 mb-[3px]">
      <div className="bg-sms-incoming rounded-[18px] rounded-bl-[4px] px-4 py-3 flex items-center gap-[5px]">
        {[0, 1, 2].map((i) => (
          <motion.div
            key={i}
            className="w-[7px] h-[7px] rounded-full bg-sms-incoming-foreground/40"
            animate={{ opacity: [0.3, 1, 0.3] }}
            transition={{
              duration: 1,
              repeat: Infinity,
              delay: i * 0.2,
            }}
          />
        ))}
      </div>
    </div>
  );
};

export default SMSTypingIndicator;
