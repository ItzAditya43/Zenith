import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { atomDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import ModelBadge from "./ModelBadge";

const KIND_ICON = { image: "🖼", video: "🎬", document: "📄", audio: "🎙" };

export default function MessageBubble({ message }) {
  const isUser = message.role === "user";

  return (
    <div className={`msg-row ${isUser ? "msg-row-user" : "msg-row-assistant"}`}>
      <div className={`msg-bubble ${isUser ? "msg-bubble-user" : "msg-bubble-assistant"}`}>
        {!isUser && message.model && (
          <ModelBadge model={message.model} role={message.route_role} reason={message.route_reason} />
        )}

        {message.attachments?.length > 0 && (
          <div className="msg-attachments">
            {message.attachments.map((a) => (
              <span className="msg-attachment-chip" key={a.id}>
                {KIND_ICON[a.kind] || "📎"} {a.name}
              </span>
            ))}
          </div>
        )}

        <div className="msg-content">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              code({ inline, className, children, ...props }) {
                const match = /language-(\w+)/.exec(className || "");
                if (inline) {
                  return (
                    <code className="inline-code" {...props}>
                      {children}
                    </code>
                  );
                }
                return (
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
                );
              },
            }}
          >
            {message.content || (message.streaming ? "" : "")}
          </ReactMarkdown>
          {message.streaming && <span className="cursor-blink" data-role={message.route_role} />}
        </div>
      </div>
    </div>
  );
}
