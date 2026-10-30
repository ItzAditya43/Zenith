
/** Settings → "about" section. State lives in SettingsPanel (see SettingsContext). */
export default function AboutSection() {
  return (
    <section className="settings-section about-section">
      <img src="/icon-192.png" alt="Zenith" className="about-logo" />
      <h3 className="settings-section-title">Zenith</h3>
      <p className="settings-section-desc">
        A local-first AI cockpit — chat, agent tools, email, calendar, notes, research,
        and multi-device sync, all running on your own machine. No cloud, no accounts.
      </p>
      <p className="setting-hint">Version 0.10.0 · built on Ollama</p>
    </section>
  );
}
