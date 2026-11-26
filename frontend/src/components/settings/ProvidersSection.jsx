import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { confirmDialog } from "../../lib/dialogs.js";
import Icon from "../Icon.jsx";
import Select from "../Select.jsx";
import { useSettings } from "./SettingsContext.js";

const EMPTY = { id: "", name: "", kind: "openai", base_url: "", api_key: "", models: "" };

/** Settings → "Providers": API models next to Ollama (OpenAI, Claude, Gemini, OpenRouter, local servers…). */
export default function ProvidersSection() {
  const { refreshModels } = useSettings();
  const [list, setList] = useState(null);
  const [presets, setPresets] = useState([]);
  const [form, setForm] = useState(null); // null = closed; {…, editing: bool}
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [tests, setTests] = useState({}); // id -> {ok, error, count}

  const load = () =>
    api.listProviders().then((r) => setList(r.providers)).catch((err) => setError(err.message));

  useEffect(() => {
    load();
    api.providerPresets().then((r) => setPresets(r.presets)).catch(() => {});
  }, []);

  const startAdd = (presetId) => {
    const p = presets.find((x) => x.id === presetId);
    const taken = new Set((list || []).map((x) => x.id));
    let id = p ? p.id : "custom";
    for (let n = 2; taken.has(id); n++) id = `${p ? p.id : "custom"}${n}`;
    setError(null);
    setForm({ ...EMPTY, id, name: p?.name || "", kind: p?.kind || "openai", base_url: p?.base_url || "", preset: p || null, editing: false });
  };

  const startEdit = (prov) => {
    setError(null);
    setForm({ ...EMPTY, ...prov, api_key: "", models: (prov.models || []).join("\n"), preset: presets.find((x) => x.id === prov.id) || null, editing: true });
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const saved = await api.saveProvider({
        id: form.id.trim().toLowerCase(),
        name: form.name.trim() || form.id,
        kind: form.kind,
        base_url: form.base_url.trim(),
        api_key: form.api_key.trim() || null,
        models: form.models.split(/[\n,]/).map((s) => s.trim()).filter(Boolean),
        enabled: form.enabled ?? true,
      });
      setForm(null);
      await load();
      test(saved.id);
      refreshModels?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  // Guided check: address → reach → key → models → a real reply (+ tools and
  // embeddings when thorough). Results render as a step list with fixes.
  const test = async (id, thorough = true) => {
    setTests((t) => ({ ...t, [id]: { running: true } }));
    try {
      const r = await api.checkProvider({ id, thorough });
      setTests((t) => ({ ...t, [id]: r }));
    } catch (err) {
      setTests((t) => ({ ...t, [id]: { ok: false, steps: [{ id: "x", label: "Check", ok: false, detail: err.message }] } }));
    }
  };
  const [formCheck, setFormCheck] = useState(null);
  const checkForm = async () => {
    setFormCheck({ running: true });
    try {
      setFormCheck(await api.checkProvider({
        id: form.editing ? form.id : undefined, name: form.name || form.id, kind: form.kind,
        base_url: form.base_url.trim(), api_key: form.api_key.trim() || null, thorough: true,
      }));
    } catch (err) { setFormCheck({ ok: false, steps: [{ id: "x", label: "Check", ok: false, detail: err.message }] }); }
  };

  const toggle = async (prov) => {
    await api.saveProvider({ ...prov, api_key: null, enabled: !prov.enabled });
    await load();
    refreshModels?.();
  };

  const remove = async (prov) => {
    if (!(await confirmDialog({ title: `Remove ${prov.name}?`, message: "Its models disappear from Zenith and its saved API key is deleted.", confirmLabel: "Remove", danger: true }))) return;
    await api.deleteProvider(prov.id);
    await load();
    refreshModels?.();
  };

  const needsKey = form ? (form.preset ? form.preset.needs_key : !/localhost|127\.0\.0\.1/.test(form.base_url)) : false;

  return (
    <section className="settings-section">
      <h3 className="settings-section-title">Providers</h3>
      <p className="settings-section-desc">
        Use models from APIs next to your Ollama ones: OpenAI, Claude, Gemini, OpenRouter, Groq and
        others, or local servers like LM Studio. Their models appear in every model picker as
        <code> provider::model</code>.
      </p>
      <p className="settings-notice settings-notice-warn">
        API models run on that company's servers and are billed to your account there. Zenith never
        picks them automatically unless you turn on cloud models in Model routing; it only uses them
        when you choose one. Keys are encrypted on this machine and never shown again.
      </p>

      {list?.length > 0 && (
        <ul className="prov-list">
          {list.map((p) => {
            const t = tests[p.id];
            return (
              <li key={p.id} className={`prov-item ${p.enabled ? "" : "is-off"}`}>
                <span className="prov-icon" aria-hidden="true">{p.name[0]?.toUpperCase()}</span>
                <div className="prov-meta">
                  <strong>
                    {p.name}
                    <span className={`lib-chip ${p.local ? "" : "lib-chip-cloud"}`}>{p.local ? "local" : "api"}</span>
                    {p.kind === "anthropic" && <span className="lib-chip">claude</span>}
                  </strong>
                  <span className="setting-hint">{p.base_url}{p.has_key ? " · key saved" : p.local ? "" : " · no key"}</span>
                  {t && <CheckResult result={t} />}
                </div>
                <div className="prov-actions">
                  <button className="text-btn" onClick={() => test(p.id)} disabled={t?.running}>{t?.running ? "Checking…" : "Check"}</button>
                  <button className="text-btn" onClick={() => startEdit(p)}>Edit</button>
                  <button
                    className={`switch ${p.enabled ? "switch-on" : ""}`}
                    onClick={() => toggle(p)}
                    role="switch"
                    aria-checked={p.enabled}
                    aria-label={`${p.enabled ? "Disable" : "Enable"} ${p.name}`}
                  >
                    <span className="switch-thumb" />
                  </button>
                  <button className="model-delete-btn" onClick={() => remove(p)} aria-label={`Remove ${p.name}`}>
                    <Icon name="x" size={13} />
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {list?.length === 0 && !form && <p className="setting-hint">No providers yet. Add one below.</p>}

      {!form && (
        <div className="prov-presets">
          {presets.map((p) => (
            <button key={p.id} className="lib-cat" onClick={() => startAdd(p.id)}>
              <Icon name="plus" size={11} /> {p.name}
            </button>
          ))}
          <button className="lib-cat" onClick={() => startAdd(null)}>
            <Icon name="plus" size={11} /> Other (OpenAI-compatible)
          </button>
        </div>
      )}

      {form && (
        <div className="prov-form">
          <h4>{form.editing ? `Edit ${form.name || form.id}` : form.preset ? `Add ${form.preset.name}` : "Add a provider"}</h4>
          <div className="prov-grid">
            <label>
              <span>Name</span>
              <input className="settings-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </label>
            <label>
              <span>ID (used in model names)</span>
              <input className="settings-input" value={form.id} disabled={form.editing} onChange={(e) => setForm({ ...form, id: e.target.value })} />
            </label>
            <label>
              <span>Type</span>
              <Select className="settings-input" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })} aria-label="Provider type">
                <option value="openai">OpenAI-compatible API</option>
                <option value="anthropic">Anthropic (Claude)</option>
              </Select>
            </label>
            <label>
              <span>Base URL</span>
              <input className="settings-input" value={form.base_url} placeholder="https://api.example.com/v1" onChange={(e) => setForm({ ...form, base_url: e.target.value })} />
            </label>
            <label className="prov-wide">
              <span>
                API key {form.editing && form.has_key ? "(leave empty to keep the saved one)" : needsKey ? "" : "(not needed for local servers)"}
                {form.preset?.key_url && (
                  <a href={form.preset.key_url} target="_blank" rel="noreferrer"> · get a key</a>
                )}
              </span>
              <input className="settings-input" type="password" autoComplete="off" value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })} />
            </label>
            <label className="prov-wide">
              <span>Only these models (optional, one per line). Empty = everything the provider lists.</span>
              <textarea className="settings-input" rows={3} value={form.models} placeholder={form.preset?.default_models?.join("\n") || "gpt-4.1\ngpt-4.1-mini"} onChange={(e) => setForm({ ...form, models: e.target.value })} />
            </label>
          </div>
          {error && <p className="settings-notice settings-notice-error" role="alert">{error}</p>}
          {formCheck && <CheckResult result={formCheck} />}
          <div className="prov-form-actions">
            <button className="settings-btn-secondary" onClick={() => { setForm(null); setFormCheck(null); }}>Cancel</button>
            <button className="settings-btn-secondary" onClick={checkForm} disabled={formCheck?.running || !form.base_url.trim()}>
              {formCheck?.running ? "Checking…" : "Check connection"}
            </button>
            <button className="settings-btn-primary" onClick={save} disabled={busy || !form.id.trim() || !form.base_url.trim() || (!form.editing && needsKey && !form.api_key.trim())}>
              {busy ? "Saving…" : "Save and test"}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

/** The guided check's steps: a tick, a cross with the fix, or a note. */
function CheckResult({ result }) {
  if (result.running) return <p className="setting-hint">Checking the address, key, models and a real reply…</p>;
  return (
    <div className={`prov-check ${result.ok ? "is-ok" : "is-bad"}`}>
      <ol>
        {(result.steps || []).map((s) => (
          <li key={s.id} className={s.ok === true ? "ok" : s.ok === false ? "bad" : "note"}>
            <span className="prov-check-mark">{s.ok === true ? "✓" : s.ok === false ? "✕" : "–"}</span>
            <span><b>{s.label}</b>{s.detail && <> · {s.detail}</>}{s.fix && <em>{s.fix}</em>}</span>
          </li>
        ))}
      </ol>
      {result.next && <p className="prov-check-next">{result.next}</p>}
      {result.models?.length > 0 && (
        <details>
          <summary>{result.models.length} model{result.models.length === 1 ? "" : "s"} and what they can likely do</summary>
          <ul className="prov-check-models">
            {result.models.slice(0, 80).map((m) => (
              <li key={m.name}><code>{m.name}</code>{m.caps.map((c) => <span key={c} className="lib-chip">{c}</span>)}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

