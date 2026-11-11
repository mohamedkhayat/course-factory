/** Faded practice on a worked example: stage 0 shows every step; stage 1 hides the last step; stage 2 hides every step
 * after the first. Returns the indices of the hidden steps. */
export function fadedSteps(n: number, stage: number): number[] {
  if (stage <= 0 || n === 0) return [];
  if (stage === 1 || n === 1) return [n - 1];
  return Array.from({ length: n - 1 }, (_, i) => i + 1);
}

/** The last stage that hides something new for n steps. */
export const lastStage = (n: number) => (n > 2 ? 2 : n > 0 ? 1 : 0);

export const LIKELIHOOD = {
  high: { label: "Likely in the exam", cls: "bg-destructive/12 text-destructive" },
  medium: { label: "Sometimes in the exam", cls: "bg-warn/15 text-warn" },
  low: { label: "Rarely in the exam", cls: "bg-muted text-muted-foreground" },
} as const;
