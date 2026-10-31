import { useState } from "react";
import { api } from "../lib/api";
import { useEscapeToClose } from "../hooks/useEscapeToClose";
import Icon from "./Icon.jsx";

const MODES = ["", "manual", "semi", "full", "plan"];

/** Project as a workspace: its folder, default persona for new chats,
 * standing instructions, and agent autonomy. Memories tagged to the
 * project already stay inside it. */
export default function ProjectDialog({ project, personas, onClose, onSaved }) {
  useEscapeToClose(onClose);
  const [form, setForm] = useState({
    name: project.name || "",
    workdir: project.workdir || "",
    persona_id: project.persona_id || "",
    instructions: project.instructions || "",
    agent_mode: project.agent_mode || "",
  });
  const [error, setError] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const save = async () => {
    setError(null);
    try {
      const { agent_mode, ...fields } = form;
      const updated = await api.updateProject(project.id, fields);
      if ((agent_mode || null) !== (project.agent_mode || null)) await api.setProjectAgentMode(project.id, agent_mode || null);
      onSaved({ ...updated, agent_mode: agent_mode || null });
      onClose();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="notes-overlay" onClick={onClose}>
      <div className="notes-modal project-dialog" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Project settings">
        <div className="notes-header">
          <h2><Icon name="folder" size={14} /> {project.name}</h2>
          <button className="icon-btn" onClick={onClose} title="Close" aria-label="Close"><Icon name="x" size={14} /></button>
        </div>
        <div className="project-form">
          <label>Name<input className="settings-input" value={form.name} onChange={set("name")} /></label>
          <label>
            Folder <span className="setting-hint">agent mode works here</span>
            <input className="settings-input" value={form.workdir} onChange={set("workdir")} placeholder="/path/to/project" />
          </label>
          <label>
            Default persona <span className="setting-hint">for new chats in this project</span>
            <select className="settings-input" value={form.persona_id} onChange={set("persona_id")}>
              <option value="">None</option>
              {personas.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
          <label>
            Instructions <span className="setting-hint">added to every reply in this project</span>
            <textarea className="settings-input" rows={4} value={form.instructions} onChange={set("instructions")} placeholder="e.g. This is a Rust codebase; prefer small diffs." />
          </label>
          <label>
            Agent autonomy
            <select className="settings-input" value={form.agent_mode} onChange={set("agent_mode")}>
              {MODES.map((m) => <option key={m} value={m}>{m || "Global default"}</option>)}
            </select>
          </label>
          {error && <p className="setting-hint" role="alert">{error}</p>}
          <div className="project-actions">
            <button className="settings-btn" onClick={onClose}>Cancel</button>
            <button className="settings-btn settings-btn-primary" onClick={save}>Save</button>
          </div>
        </div>
      </div>
    </div>
  );
}
