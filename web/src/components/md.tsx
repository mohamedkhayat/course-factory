import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import katex from "katex";
import { cn } from "@/lib/utils";

/** Markdown with $inline$ and $$display$$ math. Raw HTML is never rendered. */
export function Md({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cn("prose-cf", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>{children}</ReactMarkdown>
    </div>
  );
}

export function Tex({ latex, display = true }: { latex: string; display?: boolean }) {
  const html = katex.renderToString(latex, { displayMode: display, throwOnError: false });
  return <span className="block overflow-x-auto" dangerouslySetInnerHTML={{ __html: html }} />;
}
