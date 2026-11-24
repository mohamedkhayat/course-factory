import { useState } from "react";
import { cn } from "@/lib/utils";

/** A learner's question in a conversation. A long paste (an exercise, notes) folds to eight lines so the answer stays in view. */
export function AskedText({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.split("\n").length > 8 || text.length > 600;
  return (
    <>
      <p className={cn("whitespace-pre-wrap [overflow-wrap:anywhere]", long && !open && "line-clamp-8")}>{text}</p>
      {long && <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}
                       className="mt-1 rounded text-xs font-medium text-primary underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring">
        {open ? "Show less" : "Show all"}</button>}
    </>
  );
}
