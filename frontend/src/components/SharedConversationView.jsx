import { useEffect, useState } from "react";
import { api } from "../lib/api";

/** Public, read-only view for a shared conversation link
 * (#/share/<token>). Deliberately minimal — no sidebar, no composer, no
 * app chrome — this is what gets opened by someone who doesn't have (or
 * need) an account. */
export default function SharedConversationView({ token }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.getSharedConversation(token).then(setData).catch((err) => setError(err.message));
  }, [token]);

  if (error) {
    return (
      <div className="shared-view">
        <p className="shared-view-error">{error}</p>
      </div>
    );
  }
  if (!data) {
    return <div className="shared-view" />;
  }

  return (
    <div className="shared-view">
      <div className="shared-view-header">
        <span className="brand-name">Zenith</span>
        <span className="shared-view-badge">Shared conversation (read-only)</span>
      </div>
      <h1 className="shared-view-title">{data.title}</h1>
      <div className="shared-view-messages">
        {data.messages.map((m, i) => (
          <div key={i} className={`shared-view-msg shared-view-msg-${m.role}`}>
            <div className="shared-view-msg-role">{m.role === "user" ? "You" : m.model || "Assistant"}</div>
            <div className="shared-view-msg-content">{m.content}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
