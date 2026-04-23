// Prompt pane — positive / negative / LoRA list / string / debug

function PromptPane({ session, lorasByName, onCopyToast, onRegen, regenerating, onUpdateLora, onPin, onUnpin }) {
  const [showDebug, setShowDebug] = React.useState(false);
  const [editable, setEditable] = React.useState({ positive: null, negative: null });
  const prompt = session?.lastPrompt;

  const positive = editable.positive ?? prompt?.positive ?? '';
  const negative = editable.negative ?? prompt?.negative ?? '';
  const loras = prompt?.loras ?? [];

  const loraString = React.useMemo(
    () => loras.map(l => `<lora:${l.name}:${l.weight.toFixed(2)}>`).join(' '),
    [loras]
  );

  const copy = async (text, label) => {
    try { await navigator.clipboard.writeText(text); onCopyToast(label); } catch {}
  };

  if (!session) {
    return (
      <div className="pane">
        <div className="pane-head"><span className="pane-title">Prompt</span></div>
        <div className="pane-body"><div style={{padding:24, color:'var(--text-subtle)', fontSize:12}}>No session.</div></div>
      </div>
    );
  }

  if (!prompt) {
    return (
      <div className="pane">
        <div className="pane-head">
          <span className="pane-title">Prompt</span>
          <div className="spacer" />
        </div>
        <div className="pane-body">
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
            <div style={{ textAlign: 'center', maxWidth: 280 }}>
              <Icon name="Spark" size={28} />
              <div style={{ fontFamily: 'var(--font-display)', fontWeight: 600, fontSize: 14, marginTop: 10 }}>
                No prompt yet
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 6, lineHeight: 1.55 }}>
                Chat about what you want, then click <b>Generate prompt</b>. Two-step: intents → retrieval → composition.
              </div>
              <Button variant="primary" size="sm" onClick={onRegen} disabled={!session.source_image_path || regenerating}
                style={{ marginTop: 14 }} icon={<Icon name="Spark" size={12} />}>
                {regenerating ? 'Generating…' : 'Generate prompt'}
              </Button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="pane">
      <div className="pane-head">
        <span className="pane-title">Prompt</span>
        <span className="pane-sub">· {loras.length} LoRAs</span>
        <div className="spacer" />
        <button className="ds-icon-btn" title="Regenerate" onClick={onRegen} disabled={regenerating}>
          <Icon name="Spark" size={12} />
        </button>
      </div>
      <div className="pane-body">
        <div className="prompt-scroll">
          <PromptSection
            label="Positive"
            count={`${positive.length} chars`}
            onCopy={() => copy(positive, 'Positive copied')}
          >
            <textarea
              className="pp-ta"
              value={positive}
              onChange={e => setEditable(s => ({ ...s, positive: e.target.value }))}
            />
          </PromptSection>

          {session.use_negative && (
            <PromptSection
              label="Negative"
              count={`${negative.length} chars`}
              onCopy={() => copy(negative, 'Negative copied')}
            >
              <textarea
                className="pp-ta"
                value={negative}
                onChange={e => setEditable(s => ({ ...s, negative: e.target.value }))}
              />
            </PromptSection>
          )}

          <PromptSection label="LoRAs" count={`${loras.length}`} onCopy={() => copy(loraString, 'LoRA string copied')} copyLabel="Copy string">
            <div className="pp-lora-list">
              {loras.length === 0 && (
                <div className="pp-lora-empty">No LoRAs picked.</div>
              )}
              {loras.map((l, i) => {
                const meta = lorasByName[l.name];
                return (
                  <LoraRow
                    key={l.name}
                    lora={l}
                    meta={meta}
                    onWeightChange={(w) => onUpdateLora(i, { ...l, weight: w })}
                    onTogglePin={() => (l.kind === 'pinned' ? onUnpin(l.name) : onPin(l.name))}
                  />
                );
              })}
              <div className="pp-string" style={{ marginTop: 4 }}>{loraString || '—'}</div>
            </div>
          </PromptSection>

          <div className="pp-debug">
            <button className="pp-debug-head" onClick={() => setShowDebug(!showDebug)}>
              <Icon name={showDebug ? 'ChevronDown' : 'ChevronRight'} size={10} />
              Debug · intents & retrieval
            </button>
            {showDebug && (
              <div className="pp-debug-body">
                <div className="ds-label-caps">Intents ({prompt.intents.length})</div>
                {prompt.intents.map((it, i) => {
                  const hits = prompt.retrieved.find(r => r.intent === i)?.loras || [];
                  return (
                    <div key={i} className="pp-debug-intent">
                      <span className="kind">{it.kind}</span>
                      <span className="q">{it.query}</span>
                      <span className="hits">{hits.length} hits</span>
                    </div>
                  );
                })}
                <div className="ds-divider" />
                <div className="ds-label-caps">Top retrieval</div>
                {prompt.retrieved.map((r, i) => (
                  <div key={i} style={{ fontSize: 11.5, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                    <span style={{ color: 'var(--accent)' }}>#{i}</span>{' '}
                    {r.loras.map(([n, s]) => `${n}·${s.toFixed(2)}`).join('  ·  ')}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
        <div className="pp-generate">
          <span className="chat-hint">
            prompt_id · <code style={{fontFamily:'var(--font-mono)'}}>#{session.id.slice(-3)}-{loras.length}</code>
          </span>
          <div className="spacer" />
          <Button variant="ghost" size="sm" onClick={() => copy(positive + (session.use_negative ? '\n\nNEG: ' + negative : '') + '\n\n' + loraString, 'All copied')}>
            Copy all
          </Button>
          <Button variant="primary" size="sm" onClick={onRegen} disabled={regenerating}
            icon={<Icon name="Spark" size={12} />}>
            {regenerating ? 'Regenerating…' : 'Regenerate'}
          </Button>
        </div>
      </div>
    </div>
  );
}

function PromptSection({ label, count, onCopy, copyLabel, children }) {
  const [done, setDone] = React.useState(false);
  const click = () => { onCopy(); setDone(true); setTimeout(() => setDone(false), 1200); };
  return (
    <div className="pp-section">
      <div className="pp-section-head">
        <span className="lbl">{label}</span>
        <span className="count">· {count}</span>
        <div className="spacer" />
        <button className={'copy-btn' + (done ? ' is-done' : '')} onClick={click}>
          <Icon name={done ? 'Check' : 'Copy'} size={10} />
          {done ? 'Copied' : (copyLabel || 'Copy')}
        </button>
      </div>
      {children}
    </div>
  );
}

function LoraRow({ lora, meta, onWeightChange, onTogglePin }) {
  const isUnknown = !meta;
  const kindClass = isUnknown ? 'is-unknown' : (lora.kind === 'pinned' ? 'is-pinned' : 'is-retrieved');
  const kindLabel = isUnknown ? '⚠ unknown' : (lora.kind === 'pinned' ? 'Pinned' : 'Picked');
  const triggers = meta?.trigger_words || [];

  return (
    <div className="pp-lora-row">
      <div className="pp-lora-row-top">
        <button className={'pin-btn' + (lora.kind === 'pinned' ? ' is-on' : '')} onClick={onTogglePin} title={lora.kind === 'pinned' ? 'Unpin' : 'Pin'}>
          <Icon name="Pin" size={12} />
        </button>
        <span className="pp-lora-name" style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {lora.name}
        </span>
        <span className={'pp-lora-tag ' + kindClass}>{kindLabel}</span>
        <button className="ds-icon-btn" title="Remove" style={{ flexShrink: 0 }}><Icon name="X" size={10} /></button>
      </div>
      {triggers.length > 0 && null}
      <div style={{ paddingLeft: 24, paddingRight: 4 }}>
        <Slider label={`weight`} value={lora.weight} min={-1} max={2} step={0.05} onChange={onWeightChange} />
      </div>
    </div>
  );
}

Object.assign(window, { PromptPane });
