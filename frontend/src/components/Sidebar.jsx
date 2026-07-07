export default function Sidebar({
  conversations,
  activeId,
  onSelect,
  onCreate,
  onDelete,
  onOpenSettings,
  collapsed,
  onToggleCollapse,
}) {
  return (
    <aside className={`sidebar ${collapsed ? "sidebar-collapsed" : ""}`}>
      <div className="sidebar-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          {!collapsed && <span className="brand-name">Cortex</span>}
        </div>
        <button className="icon-btn" onClick={onToggleCollapse} title="Toggle sidebar">
          {collapsed ? "»" : "«"}
        </button>
      </div>

      <button className="new-chat-btn" onClick={onCreate}>
        <span className="new-chat-plus">+</span>
        {!collapsed && <span>New chat</span>}
      </button>

      <nav className="conversation-list">
        {conversations.map((c) => (
          <div
            key={c.id}
            className={`conversation-item ${c.id === activeId ? "conversation-item-active" : ""}`}
            onClick={() => onSelect(c.id)}
          >
            <span className="conversation-title">{collapsed ? c.title[0]?.toUpperCase() : c.title}</span>
            {!collapsed && (
              <button
                className="conversation-delete"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(c.id);
                }}
                title="Delete conversation"
              >
                ×
              </button>
            )}
          </div>
        ))}
        {conversations.length === 0 && !collapsed && (
          <p className="conversation-empty">No conversations yet — start one above.</p>
        )}
      </nav>

      <button className="settings-btn" onClick={onOpenSettings}>
        <span className="settings-icon" aria-hidden="true" />
        {!collapsed && <span>Settings</span>}
      </button>
    </aside>
  );
}
