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
        {list.map((c) => (
          <div
            key={c.id}
            className={`conversation-item ${c.id === activeId ? "conversation-item-active" : ""}`}
            onClick={() => onSelect(c.id)}
          >
            <span className="conversation-title">
              {collapsed ? c.title[0]?.toUpperCase() : c.title}
            </span>
            {!collapsed && !showSearchResults && (
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