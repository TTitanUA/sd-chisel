// Primitives — buttons, inputs, badges, slider, etc.
// All use CSS variables from tokens.css so they reskin per-theme.

const { useState } = React;

// ─── Button ────────────────────────────────────────────────────────────
function Button({ variant = 'primary', size = 'md', children, icon, ...p }) {
  return (
    <button className={`ds-btn ds-btn-${variant} ds-btn-${size}`} {...p}>
      {icon && <span className="ds-btn-icon">{icon}</span>}
      {children}
    </button>
  );
}

// ─── Input ─────────────────────────────────────────────────────────────
function Input({ label, hint, error, ...p }) {
  return (
    <label className="ds-field">
      {label && <span className="ds-field-label">{label}</span>}
      <input className="ds-input" {...p} />
      {hint && !error && <span className="ds-field-hint">{hint}</span>}
      {error && <span className="ds-field-error">{error}</span>}
    </label>
  );
}

function Textarea({ label, rows = 4, ...p }) {
  return (
    <label className="ds-field">
      {label && <span className="ds-field-label">{label}</span>}
      <textarea className="ds-textarea" rows={rows} {...p} />
    </label>
  );
}

// ─── Select (custom look) ─────────────────────────────────────────────
function Select({ label, options = [], value, onChange }) {
  return (
    <label className="ds-field">
      {label && <span className="ds-field-label">{label}</span>}
      <div className="ds-select">
        <select value={value} onChange={(e) => onChange?.(e.target.value)}>
          {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <svg width="10" height="10" viewBox="0 0 10 10"><path d="M2 4l3 3 3-3" stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinecap="round"/></svg>
      </div>
    </label>
  );
}

// ─── Badge / Chip ──────────────────────────────────────────────────────
function Badge({ variant = 'neutral', children, icon, dot }) {
  return (
    <span className={`ds-badge ds-badge-${variant}`}>
      {dot && <span className="ds-badge-dot" />}
      {icon && <span className="ds-badge-icon">{icon}</span>}
      {children}
    </span>
  );
}

function Chip({ children, removable, onRemove }) {
  return (
    <span className="ds-chip">
      {children}
      {removable && (
        <button className="ds-chip-x" onClick={onRemove} aria-label="remove">
          <svg width="8" height="8" viewBox="0 0 8 8"><path d="M1 1l6 6M7 1l-6 6" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/></svg>
        </button>
      )}
    </span>
  );
}

// ─── Slider (for LoRA weight) ─────────────────────────────────────────
function Slider({ label, min = -2, max = 2, step = 0.05, value, onChange, unit = '' }) {
  const [v, setV] = useState(value ?? 0.8);
  const cur = value ?? v;
  const pct = ((cur - min) / (max - min)) * 100;
  const zeroPct = ((0 - min) / (max - min)) * 100;
  return (
    <div className="ds-slider">
      {label && (
        <div className="ds-slider-row">
          <span className="ds-slider-label">{label}</span>
          <span className="ds-slider-value">{cur.toFixed(2)}{unit}</span>
        </div>
      )}
      <div className="ds-slider-track">
        <div className="ds-slider-tick" style={{ left: `${zeroPct}%` }} />
        <div className="ds-slider-fill" style={{
          left: `${Math.min(zeroPct, pct)}%`,
          width: `${Math.abs(pct - zeroPct)}%`
        }} />
        <input
          type="range" min={min} max={max} step={step} value={cur}
          onChange={(e) => { const n = +e.target.value; setV(n); onChange?.(n); }}
        />
        <div className="ds-slider-thumb" style={{ left: `${pct}%` }} />
      </div>
    </div>
  );
}

// ─── Toggle ────────────────────────────────────────────────────────────
function Toggle({ checked, onChange, label }) {
  const [on, setOn] = useState(checked ?? false);
  const v = checked ?? on;
  return (
    <label className="ds-toggle">
      <button
        className={`ds-toggle-track ${v ? 'is-on' : ''}`}
        role="switch" aria-checked={v}
        onClick={() => { const n = !v; setOn(n); onChange?.(n); }}
      >
        <span className="ds-toggle-thumb" />
      </button>
      {label && <span className="ds-toggle-label">{label}</span>}
    </label>
  );
}

// ─── Chat bubble ───────────────────────────────────────────────────────
function ChatBubble({ role = 'user', children, streaming, meta }) {
  return (
    <div className={`ds-chat ds-chat-${role}`}>
      {role === 'assistant' && (
        <div className="ds-chat-avatar">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M3 11L7 3L11 11L7 8.5L3 11Z" fill="currentColor" />
          </svg>
        </div>
      )}
      <div className="ds-chat-body">
        {meta && <div className="ds-chat-meta">{meta}</div>}
        <div className="ds-chat-content">
          {children}
          {streaming && <span className="ds-chat-cursor" />}
        </div>
      </div>
    </div>
  );
}

// ─── Table row ─────────────────────────────────────────────────────────
function DataRow({ name, tags = [], family, weight, trigger }) {
  return (
    <div className="ds-row">
      <div className="ds-row-main">
        <div className="ds-row-name">{name}</div>
        <div className="ds-row-meta">
          {trigger && <code className="ds-code">{trigger}</code>}
        </div>
      </div>
      <div className="ds-row-tags">
        {tags.map((t) => <Chip key={t}>{t}</Chip>)}
      </div>
      <div className="ds-row-family"><Badge variant="neutral">{family}</Badge></div>
      <div className="ds-row-weight">{weight}</div>
    </div>
  );
}

// ─── Section wrapper for canvas ────────────────────────────────────────
function Panel({ title, subtitle, children, width, minHeight }) {
  return (
    <div className="ds-panel" style={{ width, minHeight }}>
      <div className="ds-panel-header">
        <div className="ds-panel-title">{title}</div>
        {subtitle && <div className="ds-panel-subtitle">{subtitle}</div>}
      </div>
      <div className="ds-panel-body">{children}</div>
    </div>
  );
}

Object.assign(window, {
  Button, Input, Textarea, Select, Badge, Chip,
  Slider, Toggle, ChatBubble, DataRow, Panel,
});
