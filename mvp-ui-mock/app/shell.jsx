// Sidebar + Topbar components

function Topbar({ route, setRoute, endpoint }) {
  return (
    <div className="topbar">
      <div className="topbar-brand">
        <span className="topbar-brand-glyph">sd</span>
        sd-chisel
      </div>
      <div className="topbar-nav">
        <button
          className={route.page === 'workspace' ? 'is-active' : ''}
          onClick={() => setRoute({ page: 'workspace' })}
        >Workspace</button>
        <button
          className={route.page === 'library' ? 'is-active' : ''}
          onClick={() => setRoute({ page: 'library', tab: 'loras' })}
        >Library</button>
      </div>
      <div className="topbar-spacer" />
      <div className="topbar-right">
        <span className={'topbar-endpoint' + (endpoint.connected ? '' : ' is-off')} title="LMStudio endpoint">
          <span className="dot" />
          {endpoint.base_url}
        </span>
        <span className="topbar-endpoint" title="Models in use">
          VL · {endpoint.vl_model}
        </span>
      </div>
    </div>
  );
}

function Sidebar({ projects, sessions, activeSessionId, onSelect, onNewSession, onNewProject }) {
  const [open, setOpen] = React.useState(() => {
    const o = {}; projects.forEach(p => { o[p.id] = true }); return o;
  });
  const sessionCount = (pid) => sessions.filter(s => s.project_id === pid).length;

  return (
    <div className="sidebar">
      <div className="sidebar-head">
        <span className="sidebar-head-title">Projects</span>
        <button className="ds-icon-btn" title="New project" onClick={onNewProject}>
          <Icon name="Plus" />
        </button>
      </div>
      <div className="sidebar-scroll">
        {projects.map(p => (
          <div key={p.id} className="proj-group">
            <button
              className={'proj-row ' + (open[p.id] ? 'is-open' : '')}
              onClick={() => setOpen({ ...open, [p.id]: !open[p.id] })}
            >
              <span className="chev"><Icon name="ChevronRight" size={10} /></span>
              <span className="proj-name">{p.name}</span>
              <span className="proj-count">{sessionCount(p.id)}</span>
            </button>
            {open[p.id] && (
              <div className="session-list">
                {sessions.filter(s => s.project_id === p.id).map(s => (
                  <button
                    key={s.id}
                    onClick={() => onSelect(s.id)}
                    className={'session-row ' + (s.id === activeSessionId ? 'is-active ' : '') + (s.source_image_path ? 'has-result' : '')}
                  >
                    <span className="ses-dot" />
                    <span className="ses-name">{s.name}</span>
                  </button>
                ))}
                {sessionCount(p.id) === 0 && (
                  <div style={{ fontSize: 11, color: 'var(--text-subtle)', padding: '4px 10px', fontStyle: 'italic' }}>
                    empty
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        <button className="sidebar-new" onClick={onNewSession}>
          <Icon name="Plus" size={12} />
          New session
        </button>
      </div>
      <div className="sidebar-foot">
        <span>Quarry · v0.3</span>
        <button className="sidebar-foot-btn" title="Settings"><Icon name="Settings" size={12} /></button>
      </div>
    </div>
  );
}

Object.assign(window, { Topbar, Sidebar });
