const ROLE_LABEL = {
  general: "General",
  small_fast: "Quick",
  vision: "Vision",
  code: "Code",
  reasoning: "Reasoning",
};

export default function ModelBadge({ model, role, reason }) {
  if (!model) return null;
  return (
    <div className="model-badge" data-role={role} title={reason}>
      <span className="model-badge-dot" />
      <span className="model-badge-role">{ROLE_LABEL[role] || role}</span>
      <span className="model-badge-name">{model}</span>
    </div>
  );
}
