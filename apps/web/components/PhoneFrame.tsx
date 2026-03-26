import { ReactNode } from "react";

interface PhoneFrameProps {
  children: ReactNode;
}

const PhoneFrame = ({ children }: PhoneFrameProps) => {
  return (
    <div className="relative mx-auto w-[375px] h-[812px] rounded-[50px] bg-phone-bezel p-[12px] shadow-2xl">
      {/* Notch */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[160px] h-[34px] bg-phone-bezel rounded-b-[18px] z-20" />

      {/* Screen */}
      <div className="relative w-full h-full rounded-[40px] bg-phone-screen overflow-hidden flex flex-col">
        {children}
      </div>

      {/* Home indicator */}
      <div className="absolute bottom-[18px] left-1/2 -translate-x-1/2 w-[134px] h-[5px] bg-foreground/20 rounded-full" />
    </div>
  );
};

export default PhoneFrame;
