// Image panes — Source with VL summary, Result placeholder

function SourceImagePane({ session, onUpload, onAnalyze, analyzing, onClear }) {
  const [over, setOver] = React.useState(false);
  const [showSummary, setShowSummary] = React.useState(true);
  const hasImg = !!session?.source_image_path;

  return (
    <div className="pane">
      <div className="pane-head">
        <span className="pane-title">Source</span>
        {hasImg && session?.vl_summary && (
          <span className="pane-sub">· VL-analyzed</span>
        )}
        <div className="spacer" />
        {hasImg && (
          <>
            <button className="ds-icon-btn" title={showSummary ? 'Hide VL summary' : 'Show VL summary'} onClick={() => setShowSummary(!showSummary)}>
              <Icon name="Chat" size={12} />
            </button>
            <button className="ds-icon-btn" title="Re-analyze" onClick={onAnalyze}>
              <Icon name="Spark" size={12} />
            </button>
            <button className="ds-icon-btn" title="Clear" onClick={onClear}>
              <Icon name="Trash" size={12} />
            </button>
          </>
        )}
      </div>
      <div className="pane-body">
        <div className="img-pane-body">
          {hasImg ? (
            <>
              <div className="img-pane-frame">
                <img src={session.source_image_path} alt="source" />
                <div className="img-meta">
                  <span>source.jpg</span>
                  <span style={{ color: 'rgba(255,255,255,0.5)' }}>·</span>
                  <span>900 × 1200</span>
                </div>
              </div>
              {analyzing && (
                <div className="vl-summary">
                  <div className="vl-summary-head">
                    <span>VL analyzing…</span>
                    <div className="ds-spinner" style={{ width: 12, height: 12, borderWidth: 1.5 }} />
                  </div>
                  <div style={{ color: 'var(--text-muted)', fontSize: 11.5 }}>
                    qwen2-vl-7b describes composition, lighting, objects, mood…
                  </div>
                </div>
              )}
              {!analyzing && showSummary && session.vl_summary && (
                <div className="vl-summary">
                  <div className="vl-summary-head">
                    <span>VL summary</span>
                    <button className="ds-icon-btn" onClick={() => setShowSummary(false)} style={{ width: 16, height: 16 }}>
                      <Icon name="X" size={10} />
                    </button>
                  </div>
                  {session.vl_summary}
                </div>
              )}
            </>
          ) : (
            <div
              className={'img-drop' + (over ? ' is-over' : '')}
              onDragOver={e => { e.preventDefault(); setOver(true); }}
              onDragLeave={() => setOver(false)}
              onDrop={e => { e.preventDefault(); setOver(false); onUpload(); }}
            >
              <Icon name="Image" size={28} />
              <div className="img-drop-title">Drop source image</div>
              <div className="img-drop-sub">or choose a file. VL describes the image in terms useful for i2i — that becomes the spine of every prompt.</div>
              <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                <Button variant="primary" size="sm" onClick={onUpload}>Choose file</Button>
                <Button variant="ghost" size="sm" onClick={onUpload}>Paste clipboard</Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ResultImagePane({ session }) {
  return (
    <div className="pane pane-result">
      <div className="pane-head">
        <span className="pane-title">Result</span>
        <span className="pane-sub">· ComfyUI paste-back</span>
        <div className="spacer" />
        <button className="ds-icon-btn" title="Upload result" disabled style={{ opacity: 0.5 }}>
          <Icon name="Plus" size={12} />
        </button>
      </div>
      <div className="pane-body">
        <div className="img-pane-body">
          <div className="img-drop">
            <Icon name="Image" size={28} />
            <div className="img-drop-title" style={{ color: 'var(--text-subtle)' }}>No result yet</div>
            <div className="img-drop-sub">
              Run the prompt in ComfyUI, then paste the generated image here to have VL critique it (step 6, coming soon).
            </div>
            <Badge variant="warning">Post-MVP</Badge>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { SourceImagePane, ResultImagePane });
