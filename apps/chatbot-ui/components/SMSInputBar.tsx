"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Send, Globe, Delete } from "lucide-react";

interface SMSInputBarProps {
  onSend: (text: string) => void;
  disabled?: boolean;
}

const rows = [
  ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"],
  ["A", "S", "D", "F", "G", "H", "J", "K", "L"],
  ["Z", "X", "C", "V", "B", "N", "M"],
];

const numRows = [
  ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
  ["-", "/", ":", ";", "(", ")", "$", "&", "@", '"'],
  [".", ",", "?", "!", "'"],
];

const SMSInputBar = ({ onSend, disabled }: SMSInputBarProps) => {
  const [inputText, setInputText] = useState("");
  const [shift, setShift] = useState(true);
  const [numMode, setNumMode] = useState(false);

  const hiddenInputRef = useRef<HTMLInputElement>(null);

  const focusInput = useCallback(() => {
    if (!disabled) hiddenInputRef.current?.focus();
  }, [disabled]);

  useEffect(() => {
    focusInput();
  }, [focusInput]);

  const handleKey = (key: string) => {
    if (disabled) return;
    const char = shift && /^[A-Z]$/.test(key) ? key : key.toLowerCase();
    setInputText((prev) => prev + char);
    setShift(false);
    focusInput();
  };

  const handleDelete = () => {
    setInputText((prev) => prev.slice(0, -1));
    focusInput();
  };

  const handleSpace = () => {
    if (!disabled) {
      setInputText((prev) => prev + " ");
      focusInput();
    }
  };

  const handleSend = () => {
    const trimmed = inputText.trim();
    if (trimmed && !disabled) {
      onSend(trimmed);
      setInputText("");
      setShift(true);
      focusInput();
    }
  };

  const handlePhysicalKeyboard = (e: React.ChangeEvent<HTMLInputElement>) => {
    setInputText(e.target.value);
    setShift(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleSend();
    }
  };

  const display = (k: string) => (shift ? k : k.toLowerCase());

  return (
    <div className="bg-phone-input-bg border-t border-border/50" onClick={focusInput}>
      {/* Hidden input for physical keyboard capture */}
      <input
        ref={hiddenInputRef}
        value={inputText}
        onChange={handlePhysicalKeyboard}
        onKeyDown={handleKeyDown}
        className="absolute opacity-0 w-0 h-0 pointer-events-none"
        tabIndex={-1}
        disabled={disabled}
        autoFocus
      />

      {/* Text field row */}
      <div className="flex items-center gap-2 px-3 py-[6px] bg-phone-header">
        <div
          onClick={focusInput}
          className="flex-1 flex items-center bg-phone-input-bg rounded-[18px] border border-border/60 px-3 py-[6px] min-h-[34px] cursor-text"
        >
          <span
            className={`text-[15px] leading-tight ${
              inputText ? "text-foreground" : "text-muted-foreground"
            }`}
          >
            {inputText || "Text Message"}
          </span>
          {!disabled && (
            <span className="inline-block w-[2px] h-[16px] bg-primary ml-[1px] animate-pulse" />
          )}
        </div>
        <button
          onClick={handleSend}
          disabled={!inputText.trim() || disabled}
          className="w-[28px] h-[28px] rounded-full bg-primary flex items-center justify-center flex-shrink-0 disabled:opacity-30 transition-opacity"
        >
          <Send className="w-[13px] h-[13px] text-primary-foreground ml-[-1px] mt-[1px]" />
        </button>
      </div>

      {/* On-screen keyboard */}
      {!disabled && (
        <div className="px-[3px] pt-[6px] pb-5">
          {numMode ? (
            <>
              <div className="flex justify-center gap-[5px] mb-[8px]">
                {numRows[0].map((k) => (
                  <button
                    key={k}
                    onClick={() => handleKey(k)}
                    className="w-[32px] h-[42px] rounded-[5px] bg-card shadow-sm active:bg-muted flex items-center justify-center transition-colors"
                  >
                    <span className="text-[20px] font-light text-foreground leading-none">{k}</span>
                  </button>
                ))}
              </div>
              <div className="flex justify-center gap-[5px] mb-[8px]">
                {numRows[1].map((k) => (
                  <button
                    key={k}
                    onClick={() => handleKey(k)}
                    className="w-[32px] h-[42px] rounded-[5px] bg-card shadow-sm active:bg-muted flex items-center justify-center transition-colors"
                  >
                    <span className="text-[20px] font-light text-foreground leading-none">{k}</span>
                  </button>
                ))}
              </div>
              <div className="flex justify-center gap-[5px] mb-[8px] items-center">
                <button className="w-[40px] h-[42px] rounded-[5px] bg-muted shadow-sm flex items-center justify-center">
                  <span className="text-[13px] text-foreground">#+=</span>
                </button>
                {numRows[2].map((k) => (
                  <button
                    key={k}
                    onClick={() => handleKey(k)}
                    className="w-[32px] h-[42px] rounded-[5px] bg-card shadow-sm active:bg-muted flex items-center justify-center transition-colors"
                  >
                    <span className="text-[20px] font-light text-foreground leading-none">{k}</span>
                  </button>
                ))}
                <button
                  onClick={handleDelete}
                  className="w-[40px] h-[42px] rounded-[5px] bg-muted shadow-sm active:bg-border flex items-center justify-center transition-colors"
                >
                  <Delete className="w-[18px] h-[18px] text-foreground" />
                </button>
              </div>
              <div className="flex justify-center gap-[5px] items-center">
                <button
                  onClick={() => setNumMode(false)}
                  className="w-[40px] h-[42px] rounded-[5px] bg-muted shadow-sm flex items-center justify-center"
                >
                  <span className="text-[15px] text-foreground">ABC</span>
                </button>
                <button className="w-[32px] h-[42px] rounded-[5px] bg-muted shadow-sm flex items-center justify-center">
                  <Globe className="w-[16px] h-[16px] text-foreground" />
                </button>
                <button
                  onClick={handleSpace}
                  className="flex-1 h-[42px] rounded-[5px] bg-card shadow-sm active:bg-muted flex items-center justify-center transition-colors"
                >
                  <span className="text-[15px] text-foreground">space</span>
                </button>
                <button
                  onClick={handleSend}
                  className="w-[72px] h-[42px] rounded-[5px] bg-muted shadow-sm flex items-center justify-center"
                >
                  <span className="text-[15px] text-foreground">return</span>
                </button>
              </div>
            </>
          ) : (
            <>
              <div className="flex justify-center gap-[5px] mb-[8px]">
                {rows[0].map((k) => (
                  <button
                    key={k}
                    onClick={() => handleKey(k)}
                    className="w-[32px] h-[42px] rounded-[5px] bg-card shadow-sm active:bg-muted flex items-center justify-center transition-colors"
                  >
                    <span className="text-[20px] font-light text-foreground leading-none">
                      {display(k)}
                    </span>
                  </button>
                ))}
              </div>
              <div className="flex justify-center gap-[5px] mb-[8px]">
                {rows[1].map((k) => (
                  <button
                    key={k}
                    onClick={() => handleKey(k)}
                    className="w-[32px] h-[42px] rounded-[5px] bg-card shadow-sm active:bg-muted flex items-center justify-center transition-colors"
                  >
                    <span className="text-[20px] font-light text-foreground leading-none">
                      {display(k)}
                    </span>
                  </button>
                ))}
              </div>
              <div className="flex justify-center gap-[5px] mb-[8px] items-center">
                <button
                  onClick={() => setShift(!shift)}
                  className={`w-[40px] h-[42px] rounded-[5px] shadow-sm flex items-center justify-center transition-colors
                    ${shift ? "bg-card ring-1 ring-foreground/20" : "bg-muted"}`}
                >
                  <span className="text-[14px] text-foreground">⇧</span>
                </button>
                {rows[2].map((k) => (
                  <button
                    key={k}
                    onClick={() => handleKey(k)}
                    className="w-[32px] h-[42px] rounded-[5px] bg-card shadow-sm active:bg-muted flex items-center justify-center transition-colors"
                  >
                    <span className="text-[20px] font-light text-foreground leading-none">
                      {display(k)}
                    </span>
                  </button>
                ))}
                <button
                  onClick={handleDelete}
                  className="w-[40px] h-[42px] rounded-[5px] bg-muted shadow-sm active:bg-border flex items-center justify-center transition-colors"
                >
                  <Delete className="w-[18px] h-[18px] text-foreground" />
                </button>
              </div>
              <div className="flex justify-center gap-[5px] items-center">
                <button
                  onClick={() => setNumMode(true)}
                  className="w-[40px] h-[42px] rounded-[5px] bg-muted shadow-sm flex items-center justify-center"
                >
                  <span className="text-[15px] text-foreground">123</span>
                </button>
                <button className="w-[32px] h-[42px] rounded-[5px] bg-muted shadow-sm flex items-center justify-center">
                  <Globe className="w-[16px] h-[16px] text-foreground" />
                </button>
                <button
                  onClick={handleSpace}
                  className="flex-1 h-[42px] rounded-[5px] bg-card shadow-sm active:bg-muted flex items-center justify-center transition-colors"
                >
                  <span className="text-[15px] text-foreground">space</span>
                </button>
                <button
                  onClick={handleSend}
                  className="w-[72px] h-[42px] rounded-[5px] bg-muted shadow-sm flex items-center justify-center"
                >
                  <span className="text-[15px] text-foreground">return</span>
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
};

export default SMSInputBar;
