import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import katex from "katex";
import { cn } from "@/lib/utils";

type MdNode = { type: string; position?: { start: { offset?: number } }; data?: object; children?: MdNode[] };

/** remark-math renders $$x$$ written on one line as inline math; the Catalogue (and the render checks) mean display. */
function displayDoubleDollar() {
  return (tree: MdNode, file: { value: unknown }) => {
    const src = String(file.value);
    const visit = (n: MdNode) => {
      if (n.type === "inlineMath" && src.startsWith("$$", n.position?.start.offset ?? -1))
        n.data = { ...n.data, hProperties: { className: ["language-math", "math-display"] } };
      n.children?.forEach(visit);
    };
    visit(tree);
  };
}

/** Markdown with $inline$ and $$display$$ math. Raw HTML is never rendered. */
export function Md({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cn("prose-cf", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath, displayDoubleDollar]} rehypePlugins={[rehypeKatex]}>{children}</ReactMarkdown>
    </div>
  );
}

/** One line of Markdown with math, for titles, names and table headers (no wrapping paragraph). */
export function MdLine({ children }: { children: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} components={{ p: ({ children }) => <>{children}</> }}>
      {children}
    </ReactMarkdown>
  );
}

export function Tex({ latex, display = true }: { latex: string; display?: boolean }) {
  const html = katex.renderToString(latex, { displayMode: display, throwOnError: false });
  return <span className="block overflow-x-auto" dangerouslySetInnerHTML={{ __html: html }} />;
}
