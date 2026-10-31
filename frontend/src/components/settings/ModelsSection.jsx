import { api } from "../../lib/api";
import Icon from "../Icon.jsx";
import { MODEL_TASK_FILTERS } from "./constants.js";
import { useSettings } from "./SettingsContext.js";

/** Settings → "models" section. State lives in SettingsPanel (see SettingsContext). */
export default function ModelsSection() {
  const {
    config,
    setConfig,
    models,
    modelsError,
    hardware,
    modelTaskFilter,
    setModelTaskFilter,
    pullName,
    setPullName,
    pullBusy,
    pullStatus,
    pullPct,
    createForm,
    setCreateForm,
    createBusy,
    createStatus,
    handlePull,
    handleCreate,
    handleDeleteModel,
  } = useSettings();

  return (
    <section className="settings-section">
      <h3 className="settings-section-title">Installed models</h3>
      <p className="settings-section-desc">
        Everything below is running locally on your Ollama. No data leaves your machine.
      </p>
      {hardware && (
        <div className="hw-summary">
          <span>{hardware.hardware.cpu_cores} CPU cores</span>
          <span>{hardware.hardware.ram_gb ?? "?"} GB RAM</span>
          <span>
            {hardware.hardware.gpu
              ? `${hardware.hardware.gpu.name}${hardware.hardware.gpu.vram_gb ? ` (${hardware.hardware.gpu.vram_gb} GB VRAM)` : ""}`
              : "No GPU detected — running on CPU"}
          </span>
        </div>
      )}
      <ul className="model-list">
        {models.map((m) => {
          const hw = hardware?.installed.find((x) => x.name === m.name);
          return (
            <li key={m.name}>
              <span className="model-name">{m.name}</span>
              <span className="model-roles">
                {m.roles?.map((r) => (
                  <span key={r} className="role-chip" data-role={r}>
                    {r}
                  </span>
                ))}
                {m.agent_eval?.total > 0 && (
                  <span
                    className={`fit-chip ${m.agent_eval.passed / m.agent_eval.total >= 0.8 ? "fit-chip-comfortable" : "fit-chip-tight"}`}
                    title="Agent eval on this machine (python -m evals agent)"
                  >
                    agent {m.agent_eval.passed}/{m.agent_eval.total}
                  </span>
                )}
                {hw && hw.fit !== "unknown" && (
                  <span className={`fit-chip fit-chip-${hw.fit}`} title="Estimated fit for your hardware">
                    {hw.fit === "comfortable" ? "fits well" : hw.fit === "tight" ? "tight fit" : "will struggle"}
                  </span>
                )}
                <button
                  className="model-delete-btn"
                  onClick={() => handleDeleteModel(m.name)}
                  title="Delete model from Ollama"
                  aria-label={`Delete model ${m.name} from Ollama`}
                >
                  <Icon name="x" size={13} />
                </button>
              </span>
            </li>
          );
        })}
        {models.length === 0 && !modelsError && <li className="model-empty">Loading…</li>}
      </ul>

      {hardware?.recommended.length > 0 && (
        <>
          <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
            Recommended for your hardware
          </h3>
          <p className="settings-section-desc">
            Sized to what {hardware.budget_gb ? `~${hardware.budget_gb} GB` : "this machine"} can
            actually run well — best fit first. All run locally on your Ollama.
          </p>
          <div
            role="group"
            aria-label="Filter recommended models by task"
            style={{ display: "flex", flexWrap: "wrap", gap: "6px", margin: "8px 0 12px" }}
          >
            {MODEL_TASK_FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                onClick={() => setModelTaskFilter(f.key)}
                aria-pressed={modelTaskFilter === f.key}
                style={{
                  fontSize: "0.75rem",
                  padding: "4px 10px",
                  borderRadius: "999px",
                  border: "1px solid var(--bg-inset)",
                  background: modelTaskFilter === f.key ? "var(--signal-general, #4a6cf7)" : "var(--bg-panel-raised, transparent)",
                  color: modelTaskFilter === f.key ? "#fff" : "var(--text-secondary)",
                  cursor: "pointer",
                }}
              >
                {f.label}
              </button>
            ))}
          </div>
          <ul className="model-list">
            {hardware.recommended
              .filter((m) => modelTaskFilter === "all" || m.role === modelTaskFilter)
              .map((m) => (
              <li key={m.name}>
                <span className="model-name" style={{ flex: 1 }}>
                  {m.name}
                  <span style={{ display: "block", fontSize: "0.75em", color: "var(--text-tertiary)" }}>
                    {m.note}
                  </span>
                </span>
                <span className={`fit-chip fit-chip-${m.fit}`}>
                  {m.fit === "comfortable" ? "fits well" : m.fit === "tight" ? "tight fit" : "will struggle"}
                </span>
                <button
                  className="text-btn"
                  onClick={() => {
                    setPullName(m.name);
                    handlePull(m.name);
                  }}
                >
                  Pull
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
        Cloud model options
      </h3>
      <div className="setting-row">
        <div className="setting-meta">
          <span className="setting-label">Show cloud model options</span>
          <span className="setting-hint">
            Larger models than your hardware can run, hosted by Ollama, requires an
            ollama.com account. Nothing else in Zenith calls out to the internet without
            this being explicitly on.
          </span>
        </div>
        <button
          className={`switch ${config?.show_cloud_model_suggestions ? "switch-on" : ""}`}
          onClick={async () =>
            setConfig(
              await api.patchConfig({
                show_cloud_model_suggestions: !config?.show_cloud_model_suggestions,
              })
            )
          }
          role="switch"
          aria-checked={!!config?.show_cloud_model_suggestions}
        >
          <span className="switch-thumb" />
        </button>
      </div>

      {config?.show_cloud_model_suggestions && hardware?.cloud_recommended?.length > 0 && (
        <div
          style={{
            marginTop: "8px",
            padding: "12px",
            border: "1px dashed color-mix(in srgb, #7c5cff 45%, transparent)",
            borderRadius: "var(--radius-sm)",
            background: "color-mix(in srgb, #7c5cff 6%, transparent)",
          }}
        >
          <p className="settings-section-desc">
            These do <strong>not</strong> run on this machine — they run on Ollama's own
            servers. Pulling one requires signing into an ollama.com account outside of
            Zenith; Zenith does not manage that sign-in, it only helps you pick a model.
          </p>
          <div
            role="group"
            aria-label="Filter cloud models by task"
            style={{ display: "flex", flexWrap: "wrap", gap: "6px", margin: "8px 0 12px" }}
          >
            {MODEL_TASK_FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                onClick={() => setModelTaskFilter(f.key)}
                aria-pressed={modelTaskFilter === f.key}
                style={{
                  fontSize: "0.75rem",
                  padding: "4px 10px",
                  borderRadius: "999px",
                  border: "1px solid var(--bg-inset)",
                  background: modelTaskFilter === f.key ? "var(--signal-general, #4a6cf7)" : "var(--bg-panel-raised, transparent)",
                  color: modelTaskFilter === f.key ? "#fff" : "var(--text-secondary)",
                  cursor: "pointer",
                }}
              >
                {f.label}
              </button>
            ))}
          </div>
          <ul className="model-list">
            {hardware.cloud_recommended
              .filter((m) => modelTaskFilter === "all" || m.role === modelTaskFilter)
              .map((m) => (
              <li key={m.name}>
                <span className="model-name" style={{ flex: 1 }}>
                  {m.name}
                  <span style={{ display: "block", fontSize: "0.75em", color: "var(--text-tertiary)" }}>
                    {m.note}
                  </span>
                </span>
                <span
                  title="Runs on Ollama's servers, not this machine"
                  style={{
                    fontSize: "10px",
                    padding: "2px 8px",
                    borderRadius: "999px",
                    textTransform: "uppercase",
                    letterSpacing: "0.03em",
                    whiteSpace: "nowrap",
                    background: "color-mix(in srgb, #7c5cff 22%, transparent)",
                    color: "#7c5cff",
                    fontWeight: 600,
                  }}
                >
                  Cloud
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
        Pull a model
      </h3>
      <p className="settings-section-desc">
        Download a model from the Ollama registry — no CLI needed. Try{" "}
        <code>llama3.2</code>, <code>qwen2.5-coder</code>, or <code>llava</code>.
      </p>
      <div className="settings-row">
        <input
          className="settings-input"
          placeholder="model name, e.g. llama3.2:3b"
          aria-label="Model name to pull"
          value={pullName}
          onChange={(e) => setPullName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handlePull()}
          disabled={pullBusy}
        />
        <button className="settings-btn-primary" onClick={() => handlePull()} disabled={pullBusy || !pullName.trim()}>
          {pullBusy ? "Pulling…" : "Pull"}
        </button>
      </div>
      {pullStatus && (
        <div className="model-progress">
          <span className="setting-hint">
            {pullStatus}
            {pullPct != null ? ` — ${pullPct}%` : ""}
          </span>
          {pullPct != null && (
            <div className="model-progress-bar">
              <div className="model-progress-fill" style={{ width: `${pullPct}%` }} />
            </div>
          )}
        </div>
      )}

      <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
        Create a variant / apply an adapter
      </h3>
      <p className="settings-section-desc">
        Make a new model from an existing one — bake in a system prompt, or apply a
        fine-tuned LoRA adapter (point <code>adapter</code> at a GGUF adapter file Ollama
        can read).
      </p>
      <div className="setting-row setting-row-stack" style={{ gap: "0.5rem" }}>
        <input
          className="settings-input"
          placeholder="New model name, e.g. my-assistant"
          aria-label="New model name"
          value={createForm.name}
          onChange={(e) => setCreateForm((f) => ({ ...f, name: e.target.value }))}
        />
        <input
          className="settings-input"
          placeholder="Base model (from), e.g. llama3.2:3b"
          aria-label="Base model"
          value={createForm.from}
          onChange={(e) => setCreateForm((f) => ({ ...f, from: e.target.value }))}
        />
        <input
          className="settings-input"
          placeholder="System prompt (optional)"
          aria-label="System prompt"
          value={createForm.system}
          onChange={(e) => setCreateForm((f) => ({ ...f, system: e.target.value }))}
        />
        <input
          className="settings-input"
          placeholder="Adapter path (optional, for LoRA)"
          aria-label="Adapter path"
          value={createForm.adapter}
          onChange={(e) => setCreateForm((f) => ({ ...f, adapter: e.target.value }))}
        />
        <button
          className="settings-btn-primary"
          onClick={handleCreate}
          disabled={createBusy || !createForm.name.trim() || !createForm.from.trim()}
        >
          {createBusy ? "Creating…" : "Create"}
        </button>
        {createStatus && <span className="setting-hint">{createStatus}</span>}
      </div>
    </section>
  );
}
