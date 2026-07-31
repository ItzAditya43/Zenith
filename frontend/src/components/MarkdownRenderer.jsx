import { lazy, Suspense } from "react";
import Icon from "./Icon.jsx";

// Heavy libs loaded lazily — split into separate chunks.
const ReactMarkdown = lazy(() => import("react-markdown"));
const SyntaxHighlighter = lazy(() =>
  import("react-syntax-highlighter").then((m) => ({ default: m.Prism }))
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
          code({ inline, className, children, ...props }) {
            if (inline) {
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