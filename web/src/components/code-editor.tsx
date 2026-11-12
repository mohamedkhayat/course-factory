import { useEffect, useRef } from "react";
import { basicSetup, EditorView } from "codemirror";
import { keymap } from "@codemirror/view";
import { Prec } from "@codemirror/state";
import { indentWithTab } from "@codemirror/commands";
import { python } from "@codemirror/lang-python";
import { HighlightStyle, StreamLanguage, indentUnit, syntaxHighlighting } from "@codemirror/language";
import { shell } from "@codemirror/legacy-modes/mode/shell";
import { dockerFile } from "@codemirror/legacy-modes/mode/dockerfile";
import { yaml } from "@codemirror/legacy-modes/mode/yaml";
import { standardSQL } from "@codemirror/legacy-modes/mode/sql";
import { json } from "@codemirror/legacy-modes/mode/javascript";
import { http } from "@codemirror/legacy-modes/mode/http";
import { tags as t } from "@lezer/highlight";

const theme = EditorView.theme({
  "&": { backgroundColor: "color-mix(in oklab, var(--muted) 50%, transparent)", color: "var(--foreground)", fontSize: "0.875rem" },
  "&.cm-focused": { outline: "2px solid var(--ring)" },
  ".cm-content": { fontFamily: "var(--font-mono, ui-monospace, monospace)", caretColor: "var(--foreground)", minHeight: "6rem" },
  ".cm-gutters": { backgroundColor: "transparent", color: "var(--muted-foreground)", border: "none" },
  ".cm-activeLine, .cm-activeLineGutter": { backgroundColor: "color-mix(in oklab, var(--accent) 60%, transparent)" },
});

const colors = HighlightStyle.define([ // theme tokens, so both themes keep their contrast
  { tag: [t.keyword, t.controlKeyword, t.definitionKeyword, t.operatorKeyword], color: "var(--primary)", fontWeight: "600" },
  { tag: [t.string, t.special(t.string)], color: "var(--ok)" },
  { tag: [t.number, t.bool, t.null], color: "var(--warn)" },
  { tag: [t.comment, t.lineComment], color: "var(--muted-foreground)", fontStyle: "italic" },
  { tag: [t.function(t.variableName), t.function(t.definition(t.variableName))], color: "var(--foreground)", fontWeight: "600" },
]);

const MODES = { bash: shell, shell, sh: shell, dockerfile: dockerFile, yaml, yml: yaml, sql: standardSQL, json, http };
const lang = (l: string) => l === "python" ? [python()] : l in MODES ? [StreamLanguage.define(MODES[l as keyof typeof MODES])] : [];

/** A code editor (CodeMirror 6): Python, or a shell, Dockerfile, YAML, SQL, JSON or HTTP mode. Tab indents; Shift+Enter runs the cell, like Jupyter. */
export function CodeEditor({ value, onChange, onRun, label, language = "python" }: { value: string; onChange: (v: string) => void; onRun?: () => void; label: string; language?: string }) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const cb = useRef({ onChange, onRun });
  cb.current = { onChange, onRun };
  useEffect(() => {
    const v = new EditorView({
      parent: host.current!,
      doc: value,
      extensions: [
        Prec.highest(keymap.of([{ key: "Shift-Enter", run: () => { cb.current.onRun?.(); return !!cb.current.onRun; } }])),
        basicSetup, keymap.of([indentWithTab]), indentUnit.of("    "), ...lang(language.toLowerCase()), theme, syntaxHighlighting(colors),
        EditorView.contentAttributes.of({ "aria-label": label }),
        EditorView.updateListener.of((u) => { if (u.docChanged) cb.current.onChange(u.state.doc.toString()); }),
      ],
    });
    view.current = v;
    return () => v.destroy();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- created once; later value changes come from the editor itself
  useEffect(() => { // outside changes (a reset to the starter) replace the document
    const v = view.current;
    if (v && v.state.doc.toString() !== value) v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: value } });
  }, [value]);
  return <>
    <div ref={host} className="mt-3 overflow-hidden rounded-md border border-input" />
    <p className="mt-1 text-xs text-muted-foreground">Tab indents, Shift+Tab unindents · Ctrl+/ comments a line · Ctrl+F finds · Alt+↑↓ moves a line{onRun && " · Shift+Enter runs"} · Esc then Tab leaves the editor</p>
  </>;
}
