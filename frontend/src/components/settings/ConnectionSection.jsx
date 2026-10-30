import { api } from "../../lib/api";
import Icon from "../Icon.jsx";
import { useState } from "react";
import { useSettings } from "./SettingsContext.js";

/** Settings → "connection" section. State lives in SettingsPanel (see SettingsContext). */
export default function ConnectionSection() {
  const {
    config,
    setConfig,
    modelsError,
    host,
    setHost,
    saving,
    lockEnabled,
    saveHost,
  } = useSettings();
  const [searchTest, setSearchTest] = useState(null);
  const runSearchTest = async () => {
    setSearchTest({ pending: true });
    try {
      setSearchTest(await api.webSearchTest());
    } catch (err) {
      setSearchTest({ ok: false, error: err.message });
    }
  };

  return (
    <section className="settings-section">
      <h3 className="settings-section-title">Ollama connection</h3>
      <p className="settings-section-desc">
        Zenith talks to a local Ollama instance. Point it at the host it's running on.
      </p>
      <div className="setting-row setting-row-stack">
        <label className="setting-label" htmlFor="ollama-host">
          Ollama host
        </label>
        <div className="settings-row">
          <input
            id="ollama-host"
            className="settings-input"
            value={host}
            onChange={(e) => setHost(e.target.value)}
            placeholder="http://localhost:11434"
          />
          <button className="settings-btn-primary" onClick={saveHost} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
        {modelsError && (
          <p className="settings-error">
            {modelsError} — check the host above and that Ollama is running.
          </p>
        )}
      </div>

      <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
        Image generation
      </h3>
      <p className="settings-section-desc">
        Optional. Point this at a local Stable Diffusion server with its API enabled
        (AUTOMATIC1111 / Forge / SD.Next started with <code>--api</code>). Once set, an{" "}
        <strong>Image</strong> mode appears in the composer. Leave blank to keep it off.
      </p>
      <div className="settings-row">
        <input
          className="settings-input"
          placeholder="http://localhost:7860"
          aria-label="Image generation server URL"
          defaultValue={config?.image_gen_url || ""}
          onBlur={async (e) => {
            const updated = await api.patchConfig({ image_gen_url: e.target.value.trim() });
            setConfig(updated);
          }}
        />
      </div>

      <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
        Multi-device access
      </h3>
      <p className="settings-section-desc">
        Let other devices on your network (or Tailscale) reach Zenith — open it from a
        phone at <code>http://&lt;this-machine-ip&gt;:5173</code>. The backend must also listen
        on the network (<code>ZENITH_BIND=0.0.0.0</code>), and other devices are refused until a
        passcode is set (Data section). Takes effect after a backend restart. See MULTIDEVICE.md.
      </p>
      {config?.cors_allow_lan && !lockEnabled && (
        <p className="setting-hint" role="alert">
          <Icon name="alert-triangle" size={13} /> No passcode is set — other devices will get
          "Remote access is off" until you set one under Data.
        </p>
      )}
      <div className="setting-row">
        <div className="setting-meta">
          <span className="setting-label">Allow LAN / Tailscale access</span>
          <span className="setting-hint">
            Accepts requests from private-network and <code>*.ts.net</code> origins.
          </span>
        </div>
        <button
          className={`switch ${config?.cors_allow_lan ? "switch-on" : ""}`}
          onClick={async () => {
            const updated = await api.patchConfig({ cors_allow_lan: !config?.cors_allow_lan });
            setConfig(updated);
          }}
          role="switch"
          aria-checked={!!config?.cors_allow_lan}
        >
          <span className="switch-thumb" />
        </button>
      </div>
      <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
        Web search
      </h3>
      <p className="settings-section-desc">
        DuckDuckGo needs no setup but is scraped from an unofficial page and can break. A
        self-hosted SearXNG (<code>docker compose --profile search up</code>) is stabler; if it
        fails, Zenith falls back to DuckDuckGo.
      </p>
      <div className="setting-row">
        <div>
          <strong>Search backend</strong>
        </div>
        <select
          className="settings-input"
          aria-label="Search backend"
          value={config?.web_search_backend || "duckduckgo"}
          onChange={async (e) => setConfig(await api.patchConfig({ web_search_backend: e.target.value }))}
        >
          <option value="duckduckgo">DuckDuckGo</option>
          <option value="searxng">SearXNG (self-hosted)</option>
        </select>
      </div>
      {config?.web_search_backend === "searxng" && (
        <div className="setting-row">
          <div>
            <strong>SearXNG URL</strong>
            <span className="setting-hint">e.g. http://localhost:8080 (JSON format must be enabled)</span>
          </div>
          <input
            className="settings-input"
            aria-label="SearXNG URL"
            defaultValue={config?.searxng_url || ""}
            onBlur={async (e) => {
              const v = e.target.value.trim();
              if (v !== (config?.searxng_url || "")) setConfig(await api.patchConfig({ searxng_url: v }));
            }}
          />
        </div>
      )}
      <div className="setting-row">
        <button className="icon-btn" onClick={runSearchTest} disabled={searchTest?.pending}>
          {searchTest?.pending ? "Testing…" : "Test search"}
        </button>
        {searchTest && !searchTest.pending && (
          <span className="setting-hint" role="status">
            {searchTest.ok ? `OK — ${searchTest.results} results via ${searchTest.backend}.` : "No results."}
            {searchTest.error ? ` ${searchTest.error}` : ""}
          </span>
        )}
      </div>
    </section>
  );
}
