// Session settings drawer + new session/project modals

function SessionDrawer({ session, lorasByName, models, onClose, onSave }) {
  const [draft, setDraft] = React.useState(() => ({
    name: session.name,
    model_name: session.model_name,
    use_negative: session.use_negative,
    pinned: [...(session.pinned || [])],
    vl_endpoint: { base_url: 'http://localhost:1234/v1', model: 'qwen2-vl-7b-instruct' },
    prompt_endpoint: { base_url: 'http://localhost:1234/v1', model: 'mistral-nemo-12b' },
  }));
  const [addingLora, setAddingLora] = React.useState(false);
  const [loraSearch, setLoraSearch] = React.useState('');

  const availableLoras = Object.values(lorasByName).filter(l =>
    !draft.pinned.includes(l.name) &&
    (l.name + ' ' + (l.tags || []).join(' ')).toLowerCase().includes(loraSearch.toLowerCase())
  );

  const togglePin = (name) => {
    setDraft(d => ({
      ...d,
      pinned: d.pinned.includes(name) ? d.pinned.filter(n => n !== name) : [...d.pinned, name]
    }));
  };

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer-panel" onClick={e => e.stopPropagation()}>
        <div className="drawer-head">
          <div>
            <div className="ds-label-caps">SESSION SETTINGS</div>
            <div style={{ fontSize: 16, fontWeight: 600, marginTop: 4, fontFamily: 'var(--font-display)' }}>
              {draft.name}
            </div>
          </div>
          <button className="ds-icon-btn" onClick={onClose}><Icon name="X" /></button>
        </div>
        <div className="drawer-body">
          <Input label="Session name" value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} />

          <Select
            label="Base model"
            value={draft.model_name}
            onChange={v => setDraft({ ...draft, model_name: v })}
            options={models.map(m => ({ value: m.name, label: `${m.display_name} · ${m.family_id.toUpperCase()}` }))}
          />

          <div>
            <div className="drawer-section-lbl">
              <span>Pinned LoRAs</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-subtle)' }}>
                {draft.pinned.length} selected
              </span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {draft.pinned.map(n => {
                const meta = lorasByName[n];
                return (
                  <div key={n} className="pin-row">
                    <Icon name="Pin" size={12} />
                    <span className="pin-name">{n}</span>
                    <span className="weight-mini">{(meta?.recommended_weight ?? 0.8).toFixed(2)}</span>
                    <button className="ds-icon-btn" onClick={() => togglePin(n)}><Icon name="X" size={10} /></button>
                  </div>
                );
              })}
              {draft.pinned.length === 0 && (
                <div style={{ fontSize: 11.5, color: 'var(--text-subtle)', padding: '4px 0', fontStyle: 'italic' }}>
                  No pinned LoRAs. Pinned LoRAs are always included in retrieval.
                </div>
              )}
            </div>
            {!addingLora ? (
              <Button variant="ghost" size="sm" icon={<Icon name="Plus" size={10} />} onClick={() => setAddingLora(true)}>
                Add LoRA
              </Button>
            ) : (
              <div className="add-lora-pop">
                <div className="search">
                  <Icon name="Search" size={12} />
                  <input
                    autoFocus placeholder="Search LoRA…"
                    value={loraSearch} onChange={e => setLoraSearch(e.target.value)}
                  />
                  <button className="ds-icon-btn" onClick={() => { setAddingLora(false); setLoraSearch(''); }}>
                    <Icon name="X" size={10} />
                  </button>
                </div>
                {availableLoras.slice(0, 8).map(l => (
                  <button key={l.name} className="item" onClick={() => { togglePin(l.name); setLoraSearch(''); }}>
                    <span>{l.name}</span>
                    <span className="fam">{l.family_compat[0]}</span>
                  </button>
                ))}
                {availableLoras.length === 0 && (
                  <div style={{ padding: 10, fontSize: 11.5, color: 'var(--text-subtle)' }}>No matches</div>
                )}
              </div>
            )}
          </div>

          <Toggle
            checked={draft.use_negative}
            onChange={v => setDraft({ ...draft, use_negative: v })}
            label="Use negative prompt"
          />

          <div className="ds-divider" />

          <div className="drawer-section-lbl">Endpoints</div>
          <Input label="VL · base_url"
            value={draft.vl_endpoint.base_url}
            onChange={e => setDraft({ ...draft, vl_endpoint: { ...draft.vl_endpoint, base_url: e.target.value } })} />
          <Input label="VL · model"
            value={draft.vl_endpoint.model}
            onChange={e => setDraft({ ...draft, vl_endpoint: { ...draft.vl_endpoint, model: e.target.value } })} />
          <Input label="Prompt · model"
            value={draft.prompt_endpoint.model}
            onChange={e => setDraft({ ...draft, prompt_endpoint: { ...draft.prompt_endpoint, model: e.target.value } })} />
        </div>
        <div className="drawer-foot">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={() => onSave(draft)}>Save changes</Button>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { SessionDrawer });
