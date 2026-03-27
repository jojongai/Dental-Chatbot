import { ChevronLeft } from "lucide-react";

const SMSHeader = () => {
  return (
    <div className="relative bg-zinc-300 pt-10 pb-1.5 px-3 flex flex-col items-center border-b border-zinc-400/40 shrink-0">
      {/* Status bar */}
      <div className="absolute top-0 left-0 right-0 pt-2 px-6 flex justify-between items-center text-[11px] font-semibold text-zinc-800 z-10">
        <span>2:34</span>
        <div className="flex items-center gap-1">
          <div className="flex gap-[2px] items-end">
            <div className="w-[3px] h-[4px] bg-zinc-800 rounded-[1px]" />
            <div className="w-[3px] h-[6px] bg-zinc-800 rounded-[1px]" />
            <div className="w-[3px] h-[8px] bg-zinc-800 rounded-[1px]" />
            <div className="w-[3px] h-[10px] bg-zinc-800/35 rounded-[1px]" />
          </div>
          <span className="text-[10px] ml-0.5">5G</span>
          <div className="w-[25px] h-[11px] border border-zinc-800 rounded-[3px] relative ml-1">
            <div className="absolute inset-[1.5px] right-[6px] bg-zinc-800 rounded-[1px]" />
            <div className="absolute right-[-3px] top-[2.5px] w-[1.5px] h-[5px] bg-zinc-800 rounded-r-[1px]" />
          </div>
        </div>
      </div>

      {/* Navigation row */}
      <div className="w-full flex items-center justify-between mb-0.5 mt-0.5">
        <ChevronLeft className="w-4 h-4 text-zinc-700" />
        <div className="flex-1" />
      </div>

      {/* Contact avatar + name */}
      <div className="w-9 h-9 rounded-full bg-zinc-400/80 flex items-center justify-center mb-0.5">
        <span className="text-sm font-semibold text-zinc-700">BS</span>
      </div>
      <span className="text-[11px] font-semibold text-zinc-900 leading-tight">
        Bright Smile Dental
      </span>
    </div>
  );
};

export default SMSHeader;
