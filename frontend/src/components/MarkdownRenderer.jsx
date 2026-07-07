import { lazy, Suspense, useMemo } from "react";

// Heavy libs loaded lazily — split into separate chunks.
const ReactMarkdown = lazy(() => import("react-markdown"));
const SyntaxHighlighter = lazy(() =>
  import("react-syntax-highlighter").then((m) => ({ default: m.Prism }))
);

// Small-ish deps loaded eagerly (just plugin functions, not component trees).
import remarkGfm from "remark-gfm";
import { atomDark } from "react-syntax-highlighter/dist/esm/styles/prism";

function CodeBlock({ className, children }) {
  const match = /language-(\w+)/.exec(className || "");
  return (
    <Suspense fallback={<pre className="code-fallback">{children}</pre>}>
      <SyntaxHighlighter
        style={atomDark}
        language={match?.[1] || "text"}
        PreTag="div"
        customStyle={{
          borderRadius: "var(--radius-md)",
          fontSize: "var(--text-sm)",
          margin: "var(--space-2) 0",
        }}
      >
        {String(children).replace(/\n$/, "")}
      </SyntaxHighlighter>
    </Suspense>
  );
}

export default function MarkdownRenderer({ content }) {
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
            return <CodeBlock className={className}>{children}</CodeBlock>;
          },
        }}
      >
        {content || ""}
      </ReactMarkdown>
    </Suspense>
  );
}