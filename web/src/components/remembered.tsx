import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { send } from "@/lib/api";

export type Remembered = { id: number; text: string };

/** "Remembered: …" under the answer that saved a Learner memory fact, with the Undo that deletes it. */
export function RememberedLine({ fact }: { fact: Remembered }) {
  const qc = useQueryClient();
  const [gone, setGone] = useState(false);
  const [error, setError] = useState("");
  if (gone) return null;
  return (
    <p className="mt-2 flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground" role="status">
      <span>Remembered: {fact.text}</span>
      <button type="button" className="underline hover:text-foreground"
        onClick={() => send(`/api/memory/${fact.id}`, undefined, "DELETE").then(() => { setGone(true); qc.invalidateQueries({ queryKey: ["memory"] }); }, (e) => setError(String(e.message)))}>Undo</button>
      {error && <span className="text-destructive">{error}</span>}
    </p>
  );
}
