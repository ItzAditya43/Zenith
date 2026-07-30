import Icon from "./Icon.jsx";

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
          <Icon name="x" size={13} />
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
  onOpenMemory,
  collapsed,
  onToggleCollapse,
  searchQuery,
  onSearch,
  searchResults,
}) {
  const showSearchResults = searchResults !== null;
  const convResults = showSearchResults ? searchResults.conversations || [] : conversations;
  const docResults = showSearchResults ? searchResults.documents || [] : [];
  const memResults = showSearchResults ? searchResults.memories || [] : [];
  const totalResults = convResults.length + docResults.length + memResults.length;
  const groups = showSearchResults || collapsed ? null : groupByDate(conversations);

  return (
    <aside className={`sidebar ${collapsed ? "sidebar-collapsed" : ""}`}>
      <div className="sidebar-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          {!collapsed && <span className="brand-name">Cortex</span>}
        </div>
        <button className="icon-btn" onClick={onToggleCollapse} title="Toggle sidebar">
          <Icon name={collapsed ? "chevron-right" : "chevron-left"} size={15} />
        </button>
      </div>

      <button className="new-chat-btn" onClick={onCreate}>
        <span className="new-chat-plus"><Icon name="plus" size={15} /></span>
        {!collapsed && <span>New chat</span>}
      </button>

      {!collapsed && (
        <div className="sidebar-search-wrap">
          <input
            id="sidebar-search"
            className="sidebar-search"
            type="search"
            placeholder="Search chats, docs, memories…"
            value={searchQuery}
            onChange={(e) => onSearch(e.target.value)}
          />
          {showSearchResults && (
            <button className="sidebar-search-clear" onClick={() => onSearch("")} title="Clear">
              <Icon name="x" size={13} />
            </button>
          )}
        </div>
      )}

      <nav className="conversation-list">
        {showSearchResults ? (
          <>
            {convResults.length > 0 && (
              <div className="conversation-group">
                <p className="conversation-group-label">Conversations</p>
                {convResults.map((c) => (
                  <ConversationItem
                    key={c.conversation_id || c.id}
                    c={{ id: c.conversation_id || c.id, title: c.title }}
                    active={(c.conversation_id || c.id) === activeId}
                    collapsed={collapsed}
                    showDelete={false}
                    onSelect={onSelect}
                    onDelete={onDelete}
                  />
                ))}
              </div>
            )}
            {docResults.length > 0 && (
              <div className="conversation-group">
                <p className="conversation-group-label">Documents</p>
                {docResults.map((d) => (
                  <button
                    key={d.id}
                    className="search-result-item"
                    onClick={() => d.conversation_id && onSelect(d.conversation_id)}
                    disabled={!d.conversation_id}
                    title={d.snip || d.filename}
                  >
                    <Icon name="file-text" size={14} />
                    <span className="search-result-text">{d.filename}</span>
                  </button>
                ))}
              </div>
            )}
            {memResults.length > 0 && (
              <div className="conversation-group">
                <p className="conversation-group-label">Memories</p>
                {memResults.map((m) => (
                  <button
                    key={m.id}
                    className="search-result-item"
                    onClick={() => onOpenMemory?.()}
                    title={m.content}
                  >
                    <Icon name="layers" size={14} />
                    <span className="search-result-text">{m.content}</span>
                  </button>
                ))}
              </div>
            )}
            {totalResults === 0 && !collapsed && (
              <p className="conversation-empty">No matches.</p>
            )}
          </>
        ) : (
          <>
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
                        showDelete
                        onSelect={onSelect}
                        onDelete={onDelete}
                      />
                    ))}
                  </div>
                ))
              : conversations.map((c) => (
                  <ConversationItem
                    key={c.id}
                    c={c}
                    active={c.id === activeId}
                    collapsed={collapsed}
                    showDelete
                    onSelect={onSelect}
                    onDelete={onDelete}
                  />
                ))}
            {conversations.length === 0 && !collapsed && (
              <p className="conversation-empty">No conversations yet — start one above.</p>
            )}
          </>
        )}
      </nav>

      <button className="settings-btn" onClick={onOpenSettings}>
        <span className="settings-icon" aria-hidden="true" />
        {!collapsed && <span>Settings</span>}
      </button>
    </aside>
  );
}