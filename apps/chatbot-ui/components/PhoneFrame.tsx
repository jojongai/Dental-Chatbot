import { ReactNode } from "react";

interface PhoneFrameProps {
  children: ReactNode;
}

/**
 * Fits the full device (thread + keyboard) in the viewport without page scroll.
 * Width is the limiting dimension for both short and narrow viewports.
 */
const PhoneFrame = ({ children }: PhoneFrameProps) => {
  return (
    <div
      className="relative mx-auto rounded-[50px] bg-phone-bezel p-[12px] shadow-2xl shrink-0"
      style={{
        aspectRatio: "375 / 812",
        width:
          "min(375px, calc(100vw - 0.5rem), calc((100dvh - 0.5rem) * 375 / 812))",
        height: "auto",
      }}
    >
      {/* Notch */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[160px] h-[34px] bg-phone-bezel rounded-b-[18px] z-20" />

      {/* Screen */}
      <div className="relative w-full h-full rounded-[40px] bg-phone-screen overflow-hidden flex flex-col min-h-0">
        {children}
      </div>

      {/* Home indicator */}
      <div className="absolute bottom-[18px] left-1/2 -translate-x-1/2 w-[134px] h-[5px] bg-foreground/20 rounded-full" />
    </div>
  );
};

export default PhoneFrame;
