// Library variants — 4 different approaches to replace the original LibraryTable.
// All share the same dataset; each solves browse/search/filter differently.

const LORA_DATA = [
  { name: 'add_detail_xl',           family: 'SDXL',        tags: ['detail','texture'],          triggers: ['detail enhancer','fine detail'], weight: 0.65, author: 'kohya',    updated: '3d' },
  { name: 'cinematic_lighting_v2',   family: 'SDXL',        tags: ['light','mood','style'],      triggers: ['cinematic','rim light'],         weight: 0.85, author: 'civitai',  updated: '1w' },
  { name: 'character_redhead_v3',    family: 'Illustrious', tags: ['character'],                 triggers: ['red hair','long hair'],          weight: 1.00, author: 'you',      updated: '4h' },
  { name: 'anime_ink_style',         family: 'Pony',        tags: ['style','ink','linework'],    triggers: ['ink','linework','sumi-e'],       weight: 0.70, author: 'nerdy',    updated: '2w' },
  { name: 'studio_portrait_v1',      family: 'SDXL',        tags: ['portrait','studio','light'], triggers: ['studio portrait','softbox'],     weight: 0.80, author: 'you',      updated: '1mo' },
  { name: 'moody_atmosphere',        family: 'Flux',        tags: ['mood','atmospheric'],        triggers: ['moody','fog','overcast'],        weight: 0.60, author: 'civitai',  updated: '5d' },
  { name: 'painterly_brush_v4',      family: 'SDXL',        tags: ['style','painterly'],         triggers: ['oil paint','impasto'],           weight: 0.75, author: 'you',      updated: '2d' },
  { name: 'crisp_line_art',          family: 'Illustrious', tags: ['linework','ink'],            triggers: ['clean lineart'],                 weight: 0.90, author: 'nerdy',    updated: '3w' },
  { name: 'dramatic_shadow',         family: 'SDXL',        tags: ['light','mood'],              triggers: ['dramatic shadow','chiaroscuro'], weight: 0.80, author: 'civitai',  updated: '6d' },
  { name: 'face_restoration_pony',   family: 'Pony',        tags: ['detail','face'],             triggers: ['face detail'],                   weight: 0.55, author: 'kohya',    updated: '1mo' },
  { name: 'film_grain_warm',         family: 'Flux',        tags: ['texture','film'],            triggers: ['grain','kodachrome'],            weight: 0.40, author: 'you',      updated: '2d' },
  { name: 'character_elf_archer',    family: 'Illustrious', tags: ['character','fantasy'],       triggers: ['elf','archer','pointed ears'],   weight: 0.95, author: 'civitai',  updated: '5d' },
];

// Count tags for facets
function countFacets(items, key) {
  const m = new Map();
  items.forEach(it => {
    const v = it[key];
    if (Array.isArray(v)) v.forEach(x => m.set(x, (m.get(x) || 0) + 1));
    else m.set(v, (m.get(v) || 0) + 1);
  });
  return [...m.entries()].sort((a, b) => b[1] - a[1]);
}

// ═════════════════════════════════════════════════════════════════════════
// Variant 1 — LIST + DETAIL (master-detail, Linear-style)
// ═════════════════════════════════════════════════════════════════════════
function LibraryListDetail() {
  const [selected, setSelected] = React.useState('cinematic_lighting_v2');
  const item = LORA_DATA.find(x => x.name === selected) || LORA_DATA[0];

  return (
    <div className="lib-md">
      {/* Left: dense list */}
      <div className="lib-md-list">
        <div className="lib-md-list-head">
          <div className="ds-search" style={{ flex: 1 }}>
            <Icon name="Search" />
            <input placeholder="Search 143 LoRAs…" />
            <span className="ds-kbd">/</span>
          </div>
        </div>
        <div className="lib-md-list-sub">
          <span className="ds-label-caps">All · 143</span>
          <div className="ds-hstack" style={{ gap: 6 }}>
            <button className="lib-chip-mini is-active">name ↓</button>
            <button className="lib-chip-mini">updated</button>
          </div>
        </div>
        <div className="lib-md-list-scroll">
          {LORA_DATA.map(r => (
            <button
              key={r.name}
              onClick={() => setSelected(r.name)}
              className={'lib-md-row' + (r.name === selected ? ' is-selected' : '')}
            >
              <div className="lib-md-row-main">
                <span className="lib-md-row-name">{r.name}</span>
                <span className="lib-md-row-family">{r.family}</span>
              </div>
              <div className="lib-md-row-meta">
                <span>{r.tags.slice(0, 2).join(' · ')}</span>
                <span className="lib-md-row-dot">·</span>
                <span>{r.updated}</span>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Right: full detail */}
      <div className="lib-md-detail">
        <div className="lib-md-detail-head">
          <div>
            <div className="ds-label-caps" style={{ marginBottom: 6 }}>LoRA</div>
            <h2 style={{ margin: 0, fontFamily: 'var(--font-mono)', fontSize: 22, fontWeight: 500, letterSpacing: '-0.01em', color: 'var(--text)' }}>
              {item.name}
            </h2>
          </div>
          <div className="ds-hstack" style={{ gap: 8 }}>
            <Button variant="ghost" size="sm" icon={<Icon name="Copy" />}>Copy ref</Button>
            <Button variant="secondary" size="sm" icon={<Icon name="Edit" />}>Edit</Button>
          </div>
        </div>

        <div className="lib-md-detail-meta">
          <div><span className="ds-label-caps">Family</span><Badge variant="neutral">{item.family}</Badge></div>
          <div><span className="ds-label-caps">Weight</span><code className="ds-code">{item.weight.toFixed(2)}</code></div>
          <div><span className="ds-label-caps">Author</span><span style={{ fontSize: 13, color: 'var(--text-muted)' }}>{item.author}</span></div>
          <div><span className="ds-label-caps">Updated</span><span style={{ fontSize: 13, color: 'var(--text-muted)' }}>{item.updated} ago</span></div>
        </div>

        <div className="lib-md-detail-block">
          <div className="ds-label-caps">Trigger words</div>
          <div className="ds-hstack" style={{ gap: 6, flexWrap: 'wrap' }}>
            {item.triggers.map(t => <code key={t} className="ds-code">{t}</code>)}
          </div>
        </div>

        <div className="lib-md-detail-block">
          <div className="ds-label-caps">Tags</div>
          <div className="ds-hstack" style={{ gap: 6, flexWrap: 'wrap' }}>
            {item.tags.map(t => <Chip key={t}>{t}</Chip>)}
          </div>
        </div>

        <div className="lib-md-detail-block">
          <div className="ds-label-caps">Description</div>
          <div style={{ fontSize: 13, lineHeight: 1.6, color: 'var(--text-muted)' }}>
            Усиливает деталь и микроконтраст. Не комбинируется с другими detail-LoRA.
            Веса 0.4–0.8 для портретов, 0.6–1.0 для сцен. Работает лучше всего в
            связке с cinematic lighting или painterly brush.
          </div>
        </div>
      </div>
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════
// Variant 2 — FACET-FIRST (Jira/Algolia sidebar)
// ═════════════════════════════════════════════════════════════════════════
function LibraryFacet() {
  const [activeFamily, setActiveFamily] = React.useState('SDXL');
  const [activeTags, setActiveTags] = React.useState(new Set(['light']));

  const families = countFacets(LORA_DATA, 'family');
  const tags = countFacets(LORA_DATA, 'tags');
  const authors = countFacets(LORA_DATA, 'author');

  const filtered = LORA_DATA.filter(r =>
    (!activeFamily || r.family === activeFamily) &&
    (activeTags.size === 0 || [...activeTags].every(t => r.tags.includes(t)))
  );

  const toggleTag = (t) => {
    const next = new Set(activeTags);
    next.has(t) ? next.delete(t) : next.add(t);
    setActiveTags(next);
  };

  return (
    <div className="lib-facet">
      {/* Sidebar */}
      <aside className="lib-facet-side">
        <div className="ds-search" style={{ marginBottom: 14 }}>
          <Icon name="Search" />
          <input placeholder="Filter…" />
        </div>

        <FacetGroup label="Family">
          <FacetRow label="All" count={LORA_DATA.length} active={!activeFamily} onClick={() => setActiveFamily(null)} />
          {families.map(([f, n]) => (
            <FacetRow key={f} label={f} count={n} active={activeFamily === f} onClick={() => setActiveFamily(f)} />
          ))}
        </FacetGroup>

        <FacetGroup label="Tags">
          {tags.slice(0, 8).map(([t, n]) => (
            <FacetRow key={t} label={t} count={n} active={activeTags.has(t)} onClick={() => toggleTag(t)} kind="check" />
          ))}
        </FacetGroup>

        <FacetGroup label="Author">
          {authors.map(([a, n]) => (
            <FacetRow key={a} label={a} count={n} />
          ))}
        </FacetGroup>
      </aside>

      {/* Results */}
      <div className="lib-facet-main">
        <div className="lib-facet-toolbar">
          <div className="ds-hstack" style={{ gap: 6 }}>
            <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>
              <strong style={{ color: 'var(--text)' }}>{filtered.length}</strong> of {LORA_DATA.length}
            </span>
            {activeFamily && <Chip removable>{activeFamily}</Chip>}
            {[...activeTags].map(t => <Chip key={t} removable>{t}</Chip>)}
          </div>
          <Button variant="primary" size="sm" icon={<Icon name="Plus" />}>New LoRA</Button>
        </div>
        <div className="lib-facet-results">
          {filtered.map(r => (
            <div key={r.name} className="lib-card">
              <div className="lib-card-head">
                <span className="lib-card-name">{r.name}</span>
                <Badge variant="neutral">{r.family}</Badge>
              </div>
              <div className="lib-card-triggers">
                {r.triggers.map(t => <code key={t} className="ds-code">{t}</code>)}
              </div>
              <div className="lib-card-foot">
                <div className="ds-hstack" style={{ gap: 4, flexWrap: 'wrap' }}>
                  {r.tags.map(t => <Chip key={t}>{t}</Chip>)}
                </div>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-subtle)' }}>
                  w {r.weight.toFixed(2)} · {r.updated}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function FacetGroup({ label, children }) {
  return (
    <div className="lib-facet-group">
      <div className="lib-facet-group-label">{label}</div>
      {children}
    </div>
  );
}

function FacetRow({ label, count, active, onClick, kind }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={'lib-facet-row' + (active ? ' is-active' : '')}
    >
      {kind === 'check' && (
        <span className={'lib-facet-check' + (active ? ' is-on' : '')}>
          {active && <Icon name="Check" size={10} />}
        </span>
      )}
      <span className="lib-facet-row-label">{label}</span>
      <span className="lib-facet-row-count">{count}</span>
    </button>
  );
}

// ═════════════════════════════════════════════════════════════════════════
// Variant 3 — COMMAND PALETTE / GREP-MODE (Raycast-style)
// ═════════════════════════════════════════════════════════════════════════
function LibraryPalette() {
  const [q, setQ] = React.useState('light');
  const [expanded, setExpanded] = React.useState('cinematic_lighting_v2');

  // Filter + highlight logic
  const matches = LORA_DATA.filter(r =>
    q === '' ||
    r.name.includes(q) ||
    r.tags.some(t => t.includes(q)) ||
    r.triggers.some(t => t.includes(q))
  );

  const highlight = (text, query) => {
    if (!query) return text;
    const idx = text.toLowerCase().indexOf(query.toLowerCase());
    if (idx < 0) return text;
    return (
      <>
        {text.slice(0, idx)}
        <mark className="lib-hl">{text.slice(idx, idx + query.length)}</mark>
        {text.slice(idx + query.length)}
      </>
    );
  };

  return (
    <div className="lib-palette">
      <div className="lib-palette-input">
        <Icon name="Search" size={16} />
        <input
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder="grep name, tag, trigger…"
          autoFocus
        />
        <span className="ds-kbd">esc</span>
      </div>

      <div className="lib-palette-meta">
        <span>{matches.length} matches</span>
        <div className="ds-hstack" style={{ gap: 12, color: 'var(--text-subtle)', fontSize: 11 }}>
          <span><span className="ds-kbd">↑↓</span> move</span>
          <span><span className="ds-kbd">↵</span> expand</span>
          <span><span className="ds-kbd">⌘E</span> edit</span>
        </div>
      </div>

      <div className="lib-palette-results">
        {matches.map((r, i) => {
          const isExpanded = expanded === r.name;
          return (
            <div key={r.name} className={'lib-palette-row' + (isExpanded ? ' is-expanded' : '')}>
              <button
                onClick={() => setExpanded(isExpanded ? null : r.name)}
                className="lib-palette-row-btn"
              >
                <span className="lib-palette-row-glyph">
                  {isExpanded ? <Icon name="ChevronDown" size={10} /> : <Icon name="ChevronRight" size={10} />}
                </span>
                <span className="lib-palette-row-name">{highlight(r.name, q)}</span>
                <span className="lib-palette-row-family">{r.family}</span>
                <span className="lib-palette-row-tags">
                  {r.tags.map(t => <span key={t} className={'lib-palette-tag' + (t === q ? ' is-hit' : '')}>{highlight(t, q)}</span>)}
                </span>
                <span className="lib-palette-row-weight">{r.weight.toFixed(2)}</span>
              </button>
              {isExpanded && (
                <div className="lib-palette-expand">
                  <div className="lib-palette-expand-row">
                    <span className="ds-label-caps">triggers</span>
                    <div className="ds-hstack" style={{ gap: 6, flexWrap: 'wrap' }}>
                      {r.triggers.map(t => <code key={t} className="ds-code">{highlight(t, q)}</code>)}
                    </div>
                  </div>
                  <div className="lib-palette-expand-row">
                    <span className="ds-label-caps">meta</span>
                    <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                      {r.author} · updated {r.updated} ago · weight {r.weight.toFixed(2)}
                    </span>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════
// Variant 4 — GROUPED STACK (accordion by family, inventory view)
// ═════════════════════════════════════════════════════════════════════════
function LibraryGrouped() {
  const [open, setOpen] = React.useState(new Set(['SDXL', 'Illustrious']));
  const toggle = (f) => {
    const n = new Set(open);
    n.has(f) ? n.delete(f) : n.add(f);
    setOpen(n);
  };

  const groups = {};
  LORA_DATA.forEach(r => {
    (groups[r.family] ||= []).push(r);
  });

  return (
    <div className="lib-grouped">
      <div className="lib-grouped-toolbar">
        <div className="ds-search" style={{ flex: 1 }}>
          <Icon name="Search" />
          <input placeholder="Search 143 LoRAs…" />
          <span className="ds-kbd">/</span>
        </div>
        <div className="ds-hstack" style={{ gap: 6 }}>
          <button className="lib-chip-mini is-active">by family</button>
          <button className="lib-chip-mini">by tag</button>
          <button className="lib-chip-mini">by author</button>
        </div>
        <Button variant="primary" size="sm" icon={<Icon name="Plus" />}>New</Button>
      </div>

      {Object.entries(groups).map(([family, items]) => {
        const isOpen = open.has(family);
        return (
          <div key={family} className="lib-group">
            <button onClick={() => toggle(family)} className="lib-group-head">
              <span className="lib-group-chev">
                {isOpen ? <Icon name="ChevronDown" size={10} /> : <Icon name="ChevronRight" size={10} />}
              </span>
              <span className="lib-group-name">{family}</span>
              <span className="lib-group-count">{items.length}</span>
              <span className="lib-group-rule" />
              <span className="lib-group-sum">
                avg w {(items.reduce((a, b) => a + b.weight, 0) / items.length).toFixed(2)} · tags {
                  [...new Set(items.flatMap(i => i.tags))].length
                }
              </span>
            </button>
            {isOpen && (
              <div className="lib-group-body">
                {items.map(r => (
                  <div key={r.name} className="lib-group-row">
                    <span className="lib-group-row-name">{r.name}</span>
                    <span className="lib-group-row-triggers">
                      {r.triggers.slice(0, 2).map(t => <code key={t} className="ds-code">{t}</code>)}
                    </span>
                    <span className="lib-group-row-tags">
                      {r.tags.map(t => <Chip key={t}>{t}</Chip>)}
                    </span>
                    <span className="lib-group-row-weight">{r.weight.toFixed(2)}</span>
                    <span className="lib-group-row-updated">{r.updated}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
