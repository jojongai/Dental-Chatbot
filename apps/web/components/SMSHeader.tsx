import { ChevronLeft } from "lucide-react";

const SMSHeader = () => {
  return (
    <div className="bg-phone-header pt-14 pb-2 px-4 flex flex-col items-center border-b border-border/50">
      {/* Status bar */}
      <div className="absolute top-0 left-0 right-0 pt-[14px] px-8 flex justify-between items-center text-[12px] font-semibold text-foreground z-10">
        <span>2:34</span>
        <div className="flex items-center gap-1">
          {/* Signal bars */}
          <div className="flex gap-[2px] items-end">
            <div className="w-[3px] h-[4px] bg-foreground rounded-[1px]" />
            <div className="w-[3px] h-[6px] bg-foreground rounded-[1px]" />
            <div className="w-[3px] h-[8px] bg-foreground rounded-[1px]" />
            <div className="w-[3px] h-[10px] bg-foreground/30 rounded-[1px]" />
          </div>
          <span className="text-[11px] ml-1">5G</span>
          {/* Battery */}
          <div className="w-[25px] h-[11px] border border-foreground rounded-[3px] relative ml-1">
            <div className="absolute inset-[1.5px] right-[6px] bg-foreground rounded-[1px]" />
            <div className="absolute right-[-3px] top-[2.5px] w-[1.5px] h-[5px] bg-foreground rounded-r-[1px]" />
          </div>
        </div>
      </div>

      {/* Navigation row */}
      <div className="w-full flex items-center justify-between mb-1">
        <ChevronLeft className="w-5 h-5 text-primary" />
        <div className="flex-1" />
      </div>

      {/* Contact avatar + name */}
      <div className="w-12 h-12 rounded-full bg-muted flex items-center justify-center mb-1">
        <span className="text-lg font-semibold text-muted-foreground">BS</span>
      </div>
      <span className="text-[13px] font-semibold text-foreground">Bright Smile Dental</span>
      <span className="text-[11px] text-muted-foreground mb-1">(416) 555-0100</span>
    </div>
  );
};

export default SMSHeader;
