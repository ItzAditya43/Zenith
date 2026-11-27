import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { confirmDialog } from "../../lib/dialogs.js";
import Select from "../Select.jsx";

function when(ts) {
  return ts ? new Date(ts * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "never";
}

/** Settings → Data → API keys: for scripts and other apps. */
export default function ApiKeys() {
  const [keys, setKeys] = useState([]);
  const [name, setName] = useState("");
  const [scope, setScope] = useState("read");
  const [fresh, setFresh] = useState(null);
  const [error, setError] = useState("");

  const load = () => api.listApiKeys().then(setKeys).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  const create = async () => {
    try { setFresh(await api.createApiKey(name.trim() || "API key", scope)); setName(""); load(); } catch (e) { setError(e.message); }
  };
  const rotate = async (k) => {
    if (!(await confirmDialog({ title: `Rotate “${k.name}”?`, message: "You get a new key; the old one stops working right away.", confirmLabel: "Rotate" }))) return;
    setFresh(await api.rotateApiKey(k.id)); load();
  };
  const revoke = async (k) => {
    if (!(await confirmDialog({ title: `Revoke “${k.name}”?`, message: "Anything using it stops working.", confirmLabel: "Revoke", danger: true }))) return;
    await api.revokeApiKey(k.id); load();
  };
  const active = keys.filter((k) => !k.revoked_at);

  return (
    <>
      <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>API keys</h3>
      <p className="settings-section-desc">
        For scripts and other apps that use Zenith's API (see <code>docs/API.md</code> and the reference at <code>/docs</code>).
        A read key can only look; a write key can do anything the app can. Keys work from other devices and while the lock is on.
      </p>
      <div className="settings-row">
        <input className="settings-input" placeholder="What it's for, e.g. home-assistant" value={name} onChange={(e) => setName(e.target.value)} />
        <Select className="settings-select" value={scope} onChange={(e) => setScope(e.target.value)} aria-label="Key scope">
          <option value="read">Read only</option>
          <option value="write">Read and write</option>
        </Select>
        <button className="settings-btn-primary" onClick={create}>Create key</button>
      </div>
      {fresh && (
        <div className="wf-alert review" style={{ marginTop: "0.75rem" }}>
          <strong>Copy it now — it won't be shown again.</strong>
          <p><code className="apikey-value">{fresh.key}</code></p>
          <div>
            <button className="wf-btn primary" onClick={() => navigator.clipboard?.writeText(fresh.key)}>Copy</button>
            <button className="wf-btn" onClick={() => setFresh(null)}>Done</button>
          </div>
        </div>
      )}
      {error && <p className="settings-error">{error}</p>}
      <ul className="model-list" style={{ marginTop: "0.75rem" }}>
        {active.map((k) => (
          <li key={k.id}>
            <span className="model-name" style={{ flex: 1 }}>
              {k.name} <span className="lib-chip">{k.scope}</span>
              <span className="setting-hint" style={{ display: "block" }}>zk_{k.id}_… · created {when(k.created_at)} · last used {when(k.last_used_at)}</span>
            </span>
            <span className="settings-row" style={{ gap: "0.5rem" }}>
              <button className="text-btn" onClick={() => rotate(k)}>Rotate</button>
              <button className="text-btn" onClick={() => revoke(k)}>Revoke</button>
            </span>
          </li>
        ))}
        {active.length === 0 && <li className="model-empty">No keys yet.</li>}
      </ul>
    </>
  );
}
