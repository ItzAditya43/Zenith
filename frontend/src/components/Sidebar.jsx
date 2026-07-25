function groupByDate(conversations) {
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000;
  const day = 86400;
  const buckets = [
    { label: "Today", items: [], from: startOfToday },
    { label: "Yesterday", items: [], from: startOfToday - day },
    { label: "Previous 7 days", items: [], from: startOfToday - 7 * day },
    { label: "Previous 30 days", items: [], from: startOfToday - 30 * day },
    { label: "Older", items: [], from: -Infinity },
  ];
  for (const c of conversations) {
    const ts = c.updated_at || c.created_at || 0;
    const bucket = buckets.find((b) => ts >= b.from);
    (bucket || buckets[buckets.length - 1]).items.push(c);
  }
  return buckets.filter((b) => b.items.length > 0);
}

function ConversationItem({ c, active, collapsed, showDelete, onSelect, onDelete }) {
  return (
    <div
      className={`conversation-item ${active ? "conversation-item-active" : ""}`}
      onClick={() => onSelect(c.id)}
    >
      <span className="conversation-title">
        {collapsed ? c.title[0]?.toUpperCase() : c.title}
      </span>
      {!collapsed && showDelete && (
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
  );
}

export default function Sidebar({
  conversations,
  activeId,
  onSelect,
  onCreate,
  onDelete,
  onOpenSettings,
  collapsed,
  onToggleCollapse,
  searchQuery,
  onSearch,
  searchResults,
}) {
  const showSearchResults = searchResults !== null;
  const list = showSearchResults ? searchResults : conversations;
  const groups = showSearchResults || collapsed ? null : groupByDate(list);

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

      {!collapsed && (
        <div className="sidebar-search-wrap">
          <input
            id="sidebar-search"
            className="sidebar-search"
            type="search"
            placeholder="Search conversations…  (⌘K)"
            value={searchQuery}
            onChange={(e) => onSearch(e.target.value)}
          />
          {showSearchResults && (
            <button className="sidebar-search-clear" onClick={() => onSearch("")} title="Clear">
              ×
            </button>
          )}
        </div>
      )}

      <nav className="conversation-list">
        {showSearchResults && (
          <p className="search-results-label">
            {searchResults.length} result{searchResults.length === 1 ? "" : "s"}
          </p>
        )}
        {groups
          ? groups.map((group) => (
              <div className="conversation-group" key={group.label}>
                <p className="conversation-group-label">{group.label}</p>
                {group.items.map((c) => (
                  <ConversationItem
                    key={c.id}
                    c={c}
                    active={c.id === activeId}
                    collapsed={collapsed}
                    showDelete={!showSearchResults}
                    onSelect={onSelect}
                    onDelete={onDelete}
                  />
                ))}
              </div>
            ))
          : list.map((c) => (
              <ConversationItem
                key={c.id}
                c={c}
                active={c.id === activeId}
                collapsed={collapsed}
                showDelete={!showSearchResults}
                onSelect={onSelect}
                onDelete={onDelete}
              />
            ))}
        {list.length === 0 && !collapsed && (
          <p className="conversation-empty">
            {showSearchResults ? "No matches." : "No conversations yet — start one above."}
          </p>
        )}
      </nav>

      <button className="settings-btn" onClick={onOpenSettings}>
        <span className="settings-icon" aria-hidden="true" />
        {!collapsed && <span>Settings</span>}
      </button>
    </aside>
  );
}