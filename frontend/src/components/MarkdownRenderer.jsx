import { lazy, Suspense } from "react";
import Icon from "./Icon.jsx";

// Heavy libs loaded lazily — split into separate chunks, then fetched while
// idle so the first reply renders as markdown instead of the plain fallback.
const loadMarkdown = () => import("react-markdown");
const ReactMarkdown = lazy(loadMarkdown);
if (typeof window !== "undefined") {
  (window.requestIdleCallback || ((cb) => setTimeout(cb, 1200)))(() => {
    loadMarkdown().catch(() => {});
    import("../lib/highlighter.js").catch(() => {});
  });
}
const SyntaxHighlighter = lazy(() =>
  import("../lib/highlighter.js")
);

// Small-ish deps loaded eagerly (just plugin functions, not component trees).
import remarkGfm from "remark-gfm";
import { atomDark } from "react-syntax-highlighter/dist/esm/styles/prism";

function CodeBlock({ className, children, onOpenEditor }) {
  const match = /language-(\w+)/.exec(className || "");
  const lang = match?.[1] || "text";
  const text = String(children).replace(/\n$/, "");
  return (
    <div className="code-block-wrap">
      {onOpenEditor && text.length > 20 && (
        <button className="code-block-open-btn" onClick={() => onOpenEditor(text, lang)} title="Open in live editor">
          <Icon name="pencil" size={12} /> Open in editor
        </button>
      )}
      <Suspense fallback={<pre className="code-fallback">{children}</pre>}>
        <SyntaxHighlighter
          style={atomDark}
          language={lang}
          PreTag="div"
          customStyle={{
            borderRadius: "var(--radius-md)",
            fontSize: "var(--text-sm)",
            margin: "var(--space-2) 0",
          }}
        >
          {text}
        </SyntaxHighlighter>
      </Suspense>
    </div>
  );
}

export default function MarkdownRenderer({ content, onOpenEditor }) {
  return (
    <Suspense fallback={<div className="md-fallback">{content}</div>}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // react-markdown v10 dropped the `inline` flag: a fenced block has a
          // language class or spans lines; anything else is inline code.
          code({ className, children, ...props }) {
            if (!className && !String(children).includes("\n")) {
              return (
                <code className="inline-code" {...props}>
                  {children}
                </code>
              );
            }
            return <CodeBlock className={className} onOpenEditor={onOpenEditor}>{children}</CodeBlock>;
          },
        }}
      >
        {content || ""}
      </ReactMarkdown>
    </Suspense>
  );
}