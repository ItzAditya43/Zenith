import { api } from "../../lib/api";
import { POPULAR_MCP_SERVERS } from "./constants.js";
import { useSettings } from "./SettingsContext.js";

/** Settings → "agent" section. State lives in SettingsPanel (see SettingsContext). */
export default function AgentSection() {
  const {
    config,
    setConfig,
    mcpServers,
    mcpError,
    newMcpName,
    setNewMcpName,
    newMcpCommand,
    setNewMcpCommand,
    newMcpArgs,
    setNewMcpArgs,
    mcpToolsChecking,
    mcpToolsResult,
    checkCommand,
    setCheckCommand,
    addMcpServer,
    removeMcpServer,
    toggleMcpServer,
    checkMcpTools,
    toggleAgentEnabled,
    setAgentMode,
    saveCheckCommand,
    toggleAutoCheck,
    toggleNativeTools,
  } = useSettings();

  return (
    <section className="settings-section">
      <h3 className="settings-section-title">Agent tools</h3>
      <p className="settings-section-desc">
        Off by default. When on, Zenith can run shell commands and read/write files
        across multiple steps to complete a request — not just answer from context.
        This runs with the same permissions as the backend process, on whatever
        filesystem it can see (the container's, unless you've bind-mounted your real
        host into docker-compose.yml). Only enable this if you understand what that
        means.
      </p>

      <div className="setting-row">
        <div className="setting-meta">
          <span className="setting-label">Enable agent tools</span>
          <span className="setting-hint">
            Master switch. Off = the Agent composer toggle does nothing.
          </span>
        </div>
        <button
          className={`switch ${config?.agent_enabled ? "switch-on" : ""}`}
          onClick={() => toggleAgentEnabled(!config?.agent_enabled)}
          role="switch"
          aria-checked={!!config?.agent_enabled}
        >
          <span className="switch-thumb" />
        </button>
      </div>

      <div className="setting-row setting-row-stack">
        <label className="setting-label" htmlFor="agent-mode">
          Autonomy
        </label>
        <select
          id="agent-mode"
          className="settings-select"
          value={config?.agent_mode || "manual"}
          onChange={(e) => setAgentMode(e.target.value)}
          disabled={!config?.agent_enabled}
        >
          <option value="manual">Manual — approve every action</option>
          <option value="semi">Semi-auto — auto-run reads, confirm writes</option>
          <option value="full">Full-auto — no confirmation</option>
          <option value="plan">Plan-first — approve a plan, then it runs unattended</option>
        </select>
        <span className="setting-hint">
          {config?.agent_mode === "full"
            ? "Nothing pauses for approval. Only as safe as your prompts."
            : config?.agent_mode === "semi"
            ? "Read-only calls (read/list/search) run immediately; writes and shell commands with side effects still ask first."
            : config?.agent_mode === "plan"
            ? "Zenith drafts a step-by-step plan and waits for your approval; once approved, it executes the whole plan without pausing at each step."
            : "Every tool call — even a plain file read — shows up in chat for you to approve or deny."}
        </span>
      </div>

      <p className="settings-hint-note">
        Small models (roughly under ~4B parameters) often skip the tool-calling
        protocol entirely and answer from guesswork instead of actually using a tool —
        this isn't a bug in Zenith, it's a real limitation of small local models. Pin
        the "general" role to a larger model in Model routing for agent turns to work
        reliably.
      </p>

      <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
        Test / lint checks
      </h3>
      <p className="settings-section-desc">
        A command the agent can run to verify its own edits — e.g.{" "}
        <code>pytest -q</code> or <code>npm test</code>. It runs in the conversation's
        working directory. The agent can call it any time via its <code>run_checks</code>{" "}
        tool; turn on auto-check to have it run automatically after every file edit.
      </p>
      <div className="settings-row">
        <input
          className="settings-input"
          placeholder="e.g. pytest -q"
          aria-label="Check command"
          value={checkCommand}
          onChange={(e) => setCheckCommand(e.target.value)}
          onBlur={(e) => saveCheckCommand(e.target.value.trim())}
        />
      </div>
      <div className="setting-row" style={{ marginTop: "0.75rem" }}>
        <div>
          <strong>Auto-run after edits</strong>
          <span className="setting-hint">
            After each successful file edit, run the check command and feed the pass/fail
            back to the agent so it fixes breakage on its own.
          </span>
        </div>
        <button
          className={`switch ${config?.agent_auto_check ? "switch-on" : ""}`}
          onClick={() => toggleAutoCheck(!config?.agent_auto_check)}
          disabled={!config?.agent_enabled}
          role="switch"
          aria-checked={!!config?.agent_auto_check}
        >
          <span className="switch-thumb" />
        </button>
      </div>

      <div className="setting-row" style={{ marginTop: "0.75rem" }}>
        <div>
          <strong>Native tool calling</strong>
          <span className="setting-hint">
            Use Ollama&apos;s built-in tool API on models that support it (fewer format slips on
            small models). Other models keep the JSON protocol.
          </span>
        </div>
        <button
          className={`switch ${config?.agent_native_tools !== false ? "switch-on" : ""}`}
          onClick={() => toggleNativeTools(config?.agent_native_tools === false)}
          disabled={!config?.agent_enabled}
          role="switch"
          aria-checked={config?.agent_native_tools !== false}
          aria-label="Native tool calling"
        >
          <span className="switch-thumb" />
        </button>
      </div>

      <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
        Sandbox
      </h3>
      <p className="settings-section-desc">
        Run the agent's shell commands (bash, checks, background shells) in a throwaway
        Docker container that sees only this conversation's working directory, with no
        network by default. File tools are confined to the same folder. Needs Docker on this
        machine; not available inside the Docker deployment, which is already isolated.
      </p>
      <div className="setting-row">
        <div>
          <strong>Run commands in a container</strong>
          <span className="setting-hint">
            Off: commands run as your user with full access to your files.
          </span>
        </div>
        <button
          className={`switch ${config?.agent_sandbox === "docker" ? "switch-on" : ""}`}
          onClick={async () =>
            setConfig(await api.patchConfig({ agent_sandbox: config?.agent_sandbox === "docker" ? "off" : "docker" }))
          }
          role="switch"
          aria-checked={config?.agent_sandbox === "docker"}
        >
          <span className="switch-thumb" />
        </button>
      </div>
      {config?.agent_sandbox === "docker" && (
        <>
          <div className="setting-row">
            <div>
              <strong>Image</strong>
              <span className="setting-hint">Any image with <code>sh</code>; add the tools your project needs.</span>
            </div>
            <input
              className="settings-input"
              defaultValue={config?.agent_sandbox_image || ""}
              aria-label="Sandbox image"
              onBlur={async (e) => {
                const v = e.target.value.trim();
                if (v && v !== config?.agent_sandbox_image) setConfig(await api.patchConfig({ agent_sandbox_image: v }));
              }}
            />
          </div>
          <div className="setting-row">
            <div>
              <strong>Network access</strong>
              <span className="setting-hint">Needed for <code>pip install</code> / <code>npm install</code> inside the sandbox.</span>
            </div>
            <button
              className={`switch ${config?.agent_sandbox_network === "bridge" ? "switch-on" : ""}`}
              onClick={async () =>
                setConfig(await api.patchConfig({ agent_sandbox_network: config?.agent_sandbox_network === "bridge" ? "none" : "bridge" }))
              }
              role="switch"
              aria-checked={config?.agent_sandbox_network === "bridge"}
            >
              <span className="switch-thumb" />
            </button>
          </div>
        </>
      )}

      <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
        MCP servers
      </h3>
      <p className="settings-section-desc">
        Connect external MCP (Model Context Protocol) tool servers — email, calendar,
        Notion, whatever's published — instead of Zenith hand-building each
        integration. Runs as a local subprocess over stdio, same free-by-construction
        posture as everything else here. Their tools appear in agent mode's tool list
        automatically, prefixed <code>mcp__servername__</code>, and go through the same
        approval gate as bash/write_file (external tools are unknown behavior, so
        they're always classified risky).
      </p>

      <p className="setting-hint" style={{ marginBottom: "0.4rem" }}>
        Popular servers (keyless, run locally via npx — click to fill in the form below,
        then adjust and add):
      </p>
      <div className="mcp-popular-list">
        {POPULAR_MCP_SERVERS.map((s) => (
          <button
            key={s.name}
            className="mcp-popular-chip"
            onClick={() => {
              setNewMcpName(s.name);
              setNewMcpCommand(s.command);
              setNewMcpArgs(s.args);
            }}
            title={s.description}
          >
            {s.name}
          </button>
        ))}
      </div>

      <div className="settings-row">
        <input
          className="settings-input"
          placeholder="Name"
          aria-label="MCP server name"
          value={newMcpName}
          onChange={(e) => setNewMcpName(e.target.value)}
          style={{ flex: "0 0 120px" }}
        />
        <input
          className="settings-input"
          placeholder="Command, e.g. npx or /path/to/python"
          aria-label="MCP server command"
          value={newMcpCommand}
          onChange={(e) => setNewMcpCommand(e.target.value)}
        />
        <input
          className="settings-input"
          placeholder="Args (space-separated)"
          aria-label="MCP server args"
          value={newMcpArgs}
          onChange={(e) => setNewMcpArgs(e.target.value)}
        />
        <button className="settings-btn-primary" onClick={addMcpServer}>
          Add
        </button>
      </div>
      {mcpError && <p className="settings-error">{mcpError}</p>}

      <ul className="model-list" style={{ marginTop: "0.75rem" }}>
        {mcpServers.map((s) => (
          <li key={s.id} style={{ flexDirection: "column", alignItems: "stretch", opacity: s.enabled ? 1 : 0.5 }}>
            <div className="settings-row settings-row-space-between">
              <span className="model-name" style={{ flex: 1 }}>
                {s.name}
                <span className="setting-hint" style={{ display: "block", fontFamily: "var(--font-mono)" }}>
                  {s.command} {s.args.join(" ")}
                </span>
              </span>
              <span className="settings-row" style={{ gap: "0.5rem" }}>
                <button className="text-btn" onClick={() => checkMcpTools(s.id)}>
                  {mcpToolsChecking === s.id ? "Checking…" : "Test connection"}
                </button>
                <button className="text-btn" onClick={() => toggleMcpServer(s.id, !s.enabled)}>
                  {s.enabled ? "On" : "Off"}
                </button>
                <button className="icon-btn" onClick={() => removeMcpServer(s.id)} title="Remove" aria-label="Remove server">
                  ×
                </button>
              </span>
            </div>
            {mcpToolsResult[s.id] && (
              <div className="tool-call-body" style={{ padding: "0.5rem 0 0" }}>
                {mcpToolsResult[s.id].error ? (
                  <span className="settings-error">{mcpToolsResult[s.id].error}</span>
                ) : mcpToolsResult[s.id].length === 0 ? (
                  <span className="setting-hint">Connected, but no tools advertised.</span>
                ) : (
                  mcpToolsResult[s.id].map((t) => (
                    <pre key={t.name} className="tool-call-result" style={{ marginBottom: "0.3rem" }}>
                      {t.name}: {t.description}
                    </pre>
                  ))
                )}
              </div>
            )}
          </li>
        ))}
        {mcpServers.length === 0 && !mcpError && (
          <li className="model-empty">No MCP servers configured.</li>
        )}
      </ul>
    </section>
  );
}
