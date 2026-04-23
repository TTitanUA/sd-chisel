// Library LoRA v2 — final hi-fi. Read-first master-detail with:
// - active filters as chips above list; add via popover
// - detail: view mode with explicit Edit button
// - separate Create page (/library/loras/new) shown in second artboard
// - states: list empty, detail empty

// Shared dataset (richer than v1)
const LIB_DATA_V2 = [
  { name: 'add_detail_xl',           family: 'SDXL',        tags: ['detail','texture'],          triggers: ['detail enhancer','fine detail'], weight: 0.65, author: 'kohya',    updated: '3d ago',
    description: "Микроконтраст и деталь. Не комбинировать с другими detail-LoRA — даёт артефакты.\n\nРекомендуемые веса:\n- 0.4–0.8 для портретов\n- 0.6–1.0 для сцен\n\nЛучше всего работает в связке с `cinematic_lighting_v2` или `painterly_brush_v4`." },
  { name: 'cinematic_lighting_v2',   family: 'SDXL',        tags: ['light','mood','style'],      triggers: ['cinematic','rim light'],         weight: 0.85, author: 'civitai',  updated: '1w ago',
    description: "Драматичный кинематографичный свет с rim-подсветкой и боковым key-светом.\n\nТриггеры нужно явно упоминать в positive prompt.\nСовместима со всеми SDXL-чекпоинтами, проверено на Juggernaut XL и RealVis XL." },
  { name: 'character_redhead_v3',    family: 'Illustrious', tags: ['character','portrait'],      triggers: ['red hair','long hair'],          weight: 1.00, author: 'you',      updated: '4h ago',
    description: "Персонаж: рыжие длинные волосы, зелёные глаза, веснушки. Третья итерация, увеличена точность по мелким чертам." },
  { name: 'anime_ink_style',         family: 'Pony',        tags: ['style','ink','linework'],    triggers: ['ink','linework','sumi-e'],       weight: 0.70, author: 'nerdy',    updated: '2w ago',
    description: "Чернильный анимешный стиль с акцентом на линию. Трейн на 300+ кадров sumi-e." },
  { name: 'studio_portrait_v1',      family: 'SDXL',        tags: ['portrait','studio','light'], triggers: ['studio portrait','softbox'],     weight: 0.80, author: 'you',      updated: '1mo ago',
    description: "Студийное освещение softbox. Мягкие тени, ровный свет." },
  { name: 'moody_atmosphere',        family: 'Flux',        tags: ['mood','atmospheric'],        triggers: ['moody','fog','overcast'],        weight: 0.60, author: 'civitai',  updated: '5d ago', description: "Туманная, пасмурная атмосфера." },
  { name: 'painterly_brush_v4',      family: 'SDXL',        tags: ['style','painterly'],         triggers: ['oil paint','impasto'],           weight: 0.75, author: 'you',      updated: '2d ago', description: "Масляная живопись, impasto-мазки." },
  { name: 'crisp_line_art',          family: 'Illustrious', tags: ['linework','ink'],            triggers: ['clean lineart'],                 weight: 0.90, author: 'nerdy',    updated: '3w ago', description: "Чистая lineart без заливки." },
  { name: 'dramatic_shadow',         family: 'SDXL',        tags: ['light','mood'],              triggers: ['dramatic shadow','chiaroscuro'], weight: 0.80, author: 'civitai',  updated: '6d ago', description: "Чиароскуро, высокий контраст." },
  { name: 'face_restoration_pony',   family: 'Pony',        tags: ['detail','face'],             triggers: ['face detail'],                   weight: 0.55, author: 'kohya',    updated: '1mo ago', description: "Детализация лица для Pony-моделей." },
  { name: 'film_grain_warm',         family: 'Flux',        tags: ['texture','film'],            triggers: ['grain','kodachrome'],            weight: 0.40, author: 'you',      updated: '2d ago', description: "Тёплое плёночное зерно." },
  { name: 'character_elf_archer',    family: 'Illustrious', tags: ['character','fantasy'],       triggers: ['elf','archer','pointed ears'],   weight: 0.95, author: 'civitai',  updated: '5d ago', description: "Эльф-лучник, fantasy-сеттинг." },
];

// ───────────────────────────────────────────────────────────────────────
// LibraryV2 — главный экран /library/loras
// ───────────────────────────────────────────────────────────────────────
function LibraryV2() {
  const [selected, setSelected] = React.useState('cinematic_lighting_v2');
  const [filters, setFilters] = React.useState([
    { kind: 'family', value: 'SDXL' },
    { kind: 'tag', value: 'light' },
  ]);
  const [popoverOpen, setPopoverOpen] = React.useState(false);

  const filtered = LIB_DATA_V2.filter(r => filters.every(f =>
    f.kind === 'family' ? r.family === f.value :
    f.kind === 'tag' ? r.tags.includes(f.value) :
    f.kind === 'author' ? r.author === f.value :
    true
  ));

  const item = LIB_DATA_V2.find(x => x.name === selected) || filtered[0] || LIB_DATA_V2[0];

  const removeFilter = (i) => setFilters(filters.filter((_, idx) => idx !== i));

  return (
    <div className="libv2">
      {/* Left column — list */}
      <div className="libv2-list">
        <div className="libv2-list-head">
          <div className="ds-hstack" style={{ justifyContent:'space-between', marginBottom: 10 }}>
            <div>
              <h2 className="libv2-list-title">LoRA</h2>
              <div className="libv2-list-subtitle">{filtered.length} of {LIB_DATA_V2.length}</div>
            </div>
            <Button variant="primary" size="sm" icon={<Icon name="Plus" />}>New</Button>
          </div>

          <div className="ds-search">
            <Icon name="Search" />
            <input placeholder="Search name, tag, trigger…" />
            <span className="ds-kbd">/</span>
          </div>

          {/* Filter chips row */}
          <div className="libv2-filters">
            {filters.map((f, i) => (
              <span key={i} className="libv2-filter-chip">
                <span className="libv2-filter-kind">{f.kind}</span>
                <span className="libv2-filter-val">{f.value}</span>
                <button onClick={() => removeFilter(i)} className="libv2-filter-x" aria-label="remove">
                  <Icon name="X" size={9} />
                </button>
              </span>
            ))}
            <div className="libv2-filter-wrap">
              <button className="libv2-filter-add" onClick={() => setPopoverOpen(!popoverOpen)}>
                <Icon name="Plus" size={10} />
                Add filter
              </button>
              {popoverOpen && <FilterPopover onAdd={(f) => { setFilters([...filters, f]); setPopoverOpen(false); }} onClose={() => setPopoverOpen(false)} />}
            </div>
            {filters.length > 0 && (
              <button className="libv2-filter-clear" onClick={() => setFilters([])}>Clear</button>
            )}
          </div>
        </div>

        <div className="libv2-list-scroll">
          {filtered.length === 0 ? (
            <div className="libv2-list-empty">
              <Icon name="Search" size={18} />
              <div>No LoRAs match these filters</div>
              <button className="libv2-filter-clear" onClick={() => setFilters([])}>Clear filters</button>
            </div>
          ) : filtered.map(r => (
            <button
              key={r.name}
              onClick={() => setSelected(r.name)}
              className={'libv2-row' + (r.name === selected ? ' is-selected' : '')}
            >
              <div className="libv2-row-top">
                <span className="libv2-row-name">{r.name}</span>
                <span className="libv2-row-family">{r.family}</span>
              </div>
              <div className="libv2-row-tags">
                {r.tags.slice(0, 2).map(t => <span key={t} className="libv2-row-tag">{t}</span>)}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Right column — detail (view mode) */}
      <LibraryV2Detail item={item} />
    </div>
  );
}

// ─── Detail (read-first) ─────────────────────────────────────────────
function LibraryV2Detail({ item }) {
  if (!item) {
    return (
      <div className="libv2-detail libv2-detail-empty">
        <Icon name="Folder" size={24} />
        <div className="libv2-detail-empty-msg">Select a LoRA to see details</div>
      </div>
    );
  }
  return (
    <div className="libv2-detail">
      <div className="libv2-detail-head">
        <div>
          <div className="ds-label-caps" style={{ marginBottom: 6 }}>LoRA</div>
          <h1 className="libv2-detail-title">{item.name}</h1>
        </div>
        <div className="ds-hstack" style={{ gap: 8 }}>
          <Button variant="ghost" size="sm" icon={<Icon name="Copy" />}>Copy ref</Button>
          <Button variant="ghost" size="sm" icon={<Icon name="Trash" />} />
          <Button variant="secondary" size="sm" icon={<Icon name="Edit" />}>Edit</Button>
        </div>
      </div>

      <div className="libv2-detail-meta">
        <DetailMeta label="Family"><Badge variant="neutral">{item.family}</Badge></DetailMeta>
        <DetailMeta label="Weight · rec."><code className="ds-code">{item.weight.toFixed(2)}</code></DetailMeta>
        <DetailMeta label="Author"><span className="libv2-meta-val">{item.author}</span></DetailMeta>
        <DetailMeta label="Updated"><span className="libv2-meta-val">{item.updated}</span></DetailMeta>
      </div>

      <DetailBlock label="Trigger words">
        <div className="ds-hstack" style={{ gap: 6, flexWrap: 'wrap' }}>
          {item.triggers.map(t => <code key={t} className="ds-code">{t}</code>)}
        </div>
      </DetailBlock>

      <DetailBlock label="Tags">
        <div className="ds-hstack" style={{ gap: 6, flexWrap: 'wrap' }}>
          {item.tags.map(t => <Chip key={t}>{t}</Chip>)}
        </div>
      </DetailBlock>

      <DetailBlock label="Description" flex>
        <div className="libv2-desc">{item.description}</div>
      </DetailBlock>

      <DetailBlock label="Used in" last>
        <div className="libv2-used">
          <div className="libv2-used-row">
            <Icon name="Folder" size={12} />
            <span className="libv2-used-name">Character portraits</span>
            <span className="libv2-used-count">12 sessions</span>
          </div>
          <div className="libv2-used-row">
            <Icon name="Folder" size={12} />
            <span className="libv2-used-name">Mood tests</span>
            <span className="libv2-used-count">4 sessions</span>
          </div>
        </div>
      </DetailBlock>
    </div>
  );
}

function DetailMeta({ label, children }) {
  return (
    <div className="libv2-detail-meta-cell">
      <span className="ds-label-caps">{label}</span>
      {children}
    </div>
  );
}

function DetailBlock({ label, children, flex, last }) {
  return (
    <section className={'libv2-detail-block' + (flex ? ' is-flex' : '') + (last ? ' is-last' : '')}>
      <div className="ds-label-caps libv2-block-label">{label}</div>
      <div className="libv2-block-body">{children}</div>
    </section>
  );
}

// ─── Filter popover ──────────────────────────────────────────────────
function FilterPopover({ onAdd, onClose }) {
  return (
    <div className="libv2-popover">
      <div className="libv2-popover-tab">FAMILY</div>
      <div className="libv2-popover-items">
        {['SDXL','Illustrious','Pony','Flux'].map(f => (
          <button key={f} className="libv2-popover-row" onClick={() => onAdd({ kind: 'family', value: f })}>
            <span>{f}</span>
          </button>
        ))}
      </div>
      <div className="libv2-popover-tab">TAG</div>
      <div className="libv2-popover-items">
        {['character','style','detail','light','mood','portrait'].map(t => (
          <button key={t} className="libv2-popover-row" onClick={() => onAdd({ kind: 'tag', value: t })}>
            <span>{t}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────
// LibraryV2Create — /library/loras/new (отдельная страница)
// ───────────────────────────────────────────────────────────────────────
function LibraryV2Create() {
  return (
    <div className="libv2-create">
      <div className="libv2-create-head">
        <div className="ds-hstack" style={{ gap: 10, fontSize: 12, color: 'var(--text-subtle)' }}>
          <span>Library</span>
          <Icon name="Chevron" size={10} />
          <span>LoRAs</span>
          <Icon name="Chevron" size={10} />
          <span style={{ color: 'var(--text)' }}>New</span>
        </div>
        <h1 className="libv2-detail-title" style={{ marginTop: 6 }}>New LoRA</h1>
      </div>

      <div className="libv2-create-body">
        <section className="libv2-create-section">
          <div className="libv2-create-section-head">
            <h3 className="libv2-create-section-title">Identity</h3>
            <div className="libv2-create-section-sub">File name and display.</div>
          </div>
          <div className="libv2-create-section-fields">
            <Input label="Name · filename without .safetensors" placeholder="e.g. character_warrior_v1" />
            <Input label="Display name" placeholder="Warrior character v1" />
            <div className="ds-grid-2">
              <Input label="Author" placeholder="you" />
              <Input label="Version" placeholder="1.0" />
            </div>
            <Input label="Source URL" placeholder="https://civitai.com/models/…" />
          </div>
        </section>

        <section className="libv2-create-section">
          <div className="libv2-create-section-head">
            <h3 className="libv2-create-section-title">Compatibility</h3>
            <div className="libv2-create-section-sub">Which families / checkpoints this LoRA works with.</div>
          </div>
          <div className="libv2-create-section-fields">
            <div>
              <div className="ds-label-caps" style={{ marginBottom: 8 }}>Families (multi)</div>
              <div className="ds-hstack" style={{ gap: 6, flexWrap: 'wrap' }}>
                {['SDXL','Illustrious','Pony','Flux'].map((f, i) => (
                  <button key={f} className={'libv2-pill' + (i < 2 ? ' is-on' : '')}>
                    {i < 2 && <Icon name="Check" size={10} />}
                    {f}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <div className="ds-label-caps" style={{ marginBottom: 8 }}>Recommended weight</div>
              <Slider value={0.75} />
            </div>
          </div>
        </section>

        <section className="libv2-create-section">
          <div className="libv2-create-section-head">
            <h3 className="libv2-create-section-title">Taxonomy</h3>
            <div className="libv2-create-section-sub">Tags and trigger words — used by retriever.</div>
          </div>
          <div className="libv2-create-section-fields">
            <div>
              <div className="ds-label-caps" style={{ marginBottom: 8 }}>Tags</div>
              <div className="libv2-taginput">
                <Chip removable>character</Chip>
                <Chip removable>fantasy</Chip>
                <input placeholder="add tag…" />
              </div>
            </div>
            <div>
              <div className="ds-label-caps" style={{ marginBottom: 8 }}>Trigger words</div>
              <div className="libv2-taginput">
                <code className="ds-code libv2-trigger">warrior <button className="libv2-trigger-x"><Icon name="X" size={8}/></button></code>
                <code className="ds-code libv2-trigger">armor <button className="libv2-trigger-x"><Icon name="X" size={8}/></button></code>
                <input placeholder="add trigger…" />
              </div>
            </div>
          </div>
        </section>

        <section className="libv2-create-section">
          <div className="libv2-create-section-head">
            <h3 className="libv2-create-section-title">Description</h3>
            <div className="libv2-create-section-sub">Markdown. LLM sees this verbatim when picking LoRAs — be specific about what this produces and when to use it.</div>
          </div>
          <div className="libv2-create-section-fields">
            <div className="libv2-create-md">
              <div className="libv2-create-md-toolbar">
                <span className="libv2-md-btn">B</span>
                <span className="libv2-md-btn"><i>i</i></span>
                <span className="libv2-md-btn">`code`</span>
                <span className="libv2-md-btn">list</span>
                <span className="libv2-md-sep" />
                <span className="libv2-md-btn">Preview</span>
              </div>
              <textarea
                className="libv2-create-md-area"
                rows={6}
                placeholder={'Describe what this LoRA produces, recommended weights, incompatibilities…\n\n- 0.6–0.8 for portraits\n- Pairs well with …'}
              />
            </div>
          </div>
        </section>
      </div>

      <footer className="libv2-create-foot">
        <Button variant="ghost">Cancel</Button>
        <Button variant="primary" icon={<Icon name="Check" />}>Create LoRA</Button>
      </footer>
    </div>
  );
}
