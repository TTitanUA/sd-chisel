// Library page — CRUD browser + create/edit forms

const { useState: useLS, useCallback: useLC } = React;

function LibraryPage({ families: initFamilies, models: initModels, loras: initLoras, onBack }) {
  const [tab, setTab] = useLS('loras');
  const [families, setFamilies] = useLS(initFamilies);
  const [models, setModels] = useLS(initModels);
  const [loras, setLoras] = useLS(initLoras);

  return (
    <div className="library-page">
      <div className="library-nav">
        <div className="library-nav-title">Library</div>
        <button className={tab === 'loras' ? 'is-active' : ''} onClick={() => setTab('loras')}>
          LoRAs <span className="count">{loras.length}</span>
        </button>
        <button className={tab === 'models' ? 'is-active' : ''} onClick={() => setTab('models')}>
          Models <span className="count">{models.length}</span>
        </button>
        <button className={tab === 'families' ? 'is-active' : ''} onClick={() => setTab('families')}>
          Families <span className="count">{families.length}</span>
        </button>
        <div style={{ flex: 1 }} />
        <button onClick={onBack} style={{ opacity: 0.7 }}>
          <Icon name="Chevron" size={10} /> Back
        </button>
      </div>
      <div className="library-body">
        {tab === 'loras' && (
          <LorasTab
            loras={loras} families={families}
            onSave={(l) => setLoras(ls => { const i = ls.findIndex(x => x.name === l.name); return i >= 0 ? ls.map((x,j) => j===i ? l : x) : [...ls, l]; })}
            onDelete={(name) => setLoras(ls => ls.filter(l => l.name !== name))}
          />
        )}
        {tab === 'models' && (
          <ModelsTab
            models={models} families={families}
            onSave={(m) => setModels(ms => { const i = ms.findIndex(x => x.name === m.name); return i >= 0 ? ms.map((x,j) => j===i ? m : x) : [...ms, m]; })}
            onDelete={(name) => setModels(ms => ms.filter(m => m.name !== name))}
          />
        )}
        {tab === 'families' && (
          <FamiliesTab
            families={families}
            onSave={(f) => setFamilies(fs => { const i = fs.findIndex(x => x.id === f.id); return i >= 0 ? fs.map((x,j) => j===i ? f : x) : [...fs, f]; })}
            onDelete={(id) => setFamilies(fs => fs.filter(f => f.id !== id))}
          />
        )}
      </div>
    </div>
  );
}

// ─── LoRAs tab ──────────────────────────────────────────────────────────
function LorasTab({ loras, families, onSave, onDelete }) {
  const [selected, setSelected] = useLS(loras[0]?.name || null);
  const [view, setView] = useLS('list'); // 'list' | 'create' | 'edit'
  const [filters, setFilters] = useLS([]);
  const [search, setSearch] = useLS('');
  const [popoverOpen, setPopoverOpen] = useLS(false);
  const [editItem, setEditItem] = useLS(null);

  const filtered = loras.filter(r => {
    if (search && !(r.name + ' ' + r.tags.join(' ') + ' ' + r.trigger_words.join(' ')).toLowerCase().includes(search.toLowerCase())) return false;
    return filters.every(f =>
      f.kind === 'family' ? r.family_compat.includes(f.value) :
      f.kind === 'tag' ? r.tags.includes(f.value) : true
    );
  });

  const item = loras.find(x => x.name === selected) || filtered[0] || loras[0];

  if (view === 'create' || view === 'edit') {
    return (
      <LoraForm
        item={view === 'edit' ? editItem : null}
        families={families}
        onSave={(l) => { onSave(l); setSelected(l.name); setView('list'); }}
        onCancel={() => setView('list')}
      />
    );
  }

  return (
    <div className="libv2" style={{ width: '100%' }}>
      <div className="libv2-list">
        <div className="libv2-list-head">
          <div className="ds-hstack" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
            <div>
              <h2 className="libv2-list-title">LoRA</h2>
              <div className="libv2-list-subtitle">{filtered.length} of {loras.length}</div>
            </div>
            <Button variant="primary" size="sm" icon={<Icon name="Plus" />} onClick={() => setView('create')}>New</Button>
          </div>
          <div className="ds-search">
            <Icon name="Search" />
            <input placeholder="Search name, tag, trigger…" value={search} onChange={e => setSearch(e.target.value)} />
          </div>
          <div className="libv2-filters">
            {filters.map((f, i) => (
              <span key={i} className="libv2-filter-chip">
                <span className="libv2-filter-kind">{f.kind}</span>
                <span className="libv2-filter-val">{f.value}</span>
                <button onClick={() => setFilters(filters.filter((_, j) => j !== i))} className="libv2-filter-x"><Icon name="X" size={9} /></button>
              </span>
            ))}
            <div className="libv2-filter-wrap">
              <button className="libv2-filter-add" onClick={() => setPopoverOpen(!popoverOpen)}>
                <Icon name="Plus" size={10} /> Add filter
              </button>
              {popoverOpen && (
                <div className="libv2-popover">
                  <div className="libv2-popover-tab">FAMILY</div>
                  <div className="libv2-popover-items">
                    {families.map(f => (
                      <button key={f.id} className="libv2-popover-row"
                        onClick={() => { setFilters([...filters, { kind: 'family', value: f.id }]); setPopoverOpen(false); }}>
                        {f.display_name}
                      </button>
                    ))}
                  </div>
                  <div className="libv2-popover-tab">TAG</div>
                  <div className="libv2-popover-items">
                    {['character','style','detail','light','mood','portrait','linework','texture'].map(t => (
                      <button key={t} className="libv2-popover-row"
                        onClick={() => { setFilters([...filters, { kind: 'tag', value: t }]); setPopoverOpen(false); }}>
                        {t}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
            {filters.length > 0 && <button className="libv2-filter-clear" onClick={() => setFilters([])}>Clear</button>}
          </div>
        </div>
        <div className="libv2-list-scroll">
          {filtered.length === 0 ? (
            <div className="libv2-list-empty">
              <Icon name="Search" size={18} />
              <div>No matches</div>
              <button className="libv2-filter-clear" onClick={() => { setFilters([]); setSearch(''); }}>Reset</button>
            </div>
          ) : filtered.map(r => (
            <button key={r.name}
              onClick={() => setSelected(r.name)}
              className={'libv2-row' + (r.name === item?.name ? ' is-selected' : '')}>
              <div className="libv2-row-top">
                <span className="libv2-row-name">{r.name}</span>
                <span className="libv2-row-family">{r.family_compat[0]}</span>
              </div>
              <div className="libv2-row-tags">
                {r.tags.slice(0,2).map(t => <span key={t} className="libv2-row-tag">{t}</span>)}
              </div>
            </button>
          ))}
        </div>
      </div>
      {item ? (
        <LoraDetail item={item}
          onEdit={() => { setEditItem(item); setView('edit'); }}
          onDelete={() => { onDelete(item.name); setSelected(null); }}
        />
      ) : (
        <div className="libv2-detail libv2-detail-empty">
          <Icon name="Folder" size={24} />
          <div className="libv2-detail-empty-msg">Select a LoRA to see details</div>
        </div>
      )}
    </div>
  );
}

function LoraDetail({ item, onEdit, onDelete }) {
  return (
    <div className="libv2-detail">
      <div className="libv2-detail-head">
        <div>
          <div className="ds-label-caps" style={{ marginBottom: 6 }}>LoRA</div>
          <h1 className="libv2-detail-title">{item.name}</h1>
        </div>
        <div className="ds-hstack" style={{ gap: 8 }}>
          <Button variant="ghost" size="sm" icon={<Icon name="Trash" />} onClick={onDelete} />
          <Button variant="secondary" size="sm" icon={<Icon name="Edit" />} onClick={onEdit}>Edit</Button>
        </div>
      </div>
      <div className="libv2-detail-meta">
        <div className="libv2-detail-meta-cell">
          <span className="ds-label-caps">Families</span>
          <div className="ds-hstack" style={{gap:4}}>{item.family_compat.map(f => <Badge key={f} variant="neutral">{f.toUpperCase()}</Badge>)}</div>
        </div>
        <div className="libv2-detail-meta-cell">
          <span className="ds-label-caps">Weight · rec.</span>
          <code className="ds-code">{item.recommended_weight.toFixed(2)}</code>
        </div>
        <div className="libv2-detail-meta-cell">
          <span className="ds-label-caps">Author</span>
          <span className="libv2-meta-val">{item.author || '—'}</span>
        </div>
        <div className="libv2-detail-meta-cell">
          <span className="ds-label-caps">Updated</span>
          <span className="libv2-meta-val">{item.updated || '—'}</span>
        </div>
      </div>
      <section className="libv2-detail-block">
        <div className="ds-label-caps libv2-block-label">Trigger words</div>
        <div className="libv2-block-body">
          <div className="ds-hstack" style={{gap:6,flexWrap:'wrap'}}>
            {item.trigger_words.map(t => <code key={t} className="ds-code">{t}</code>)}
          </div>
        </div>
      </section>
      <section className="libv2-detail-block">
        <div className="ds-label-caps libv2-block-label">Tags</div>
        <div className="libv2-block-body">
          <div className="ds-hstack" style={{gap:6,flexWrap:'wrap'}}>
            {item.tags.map(t => <Chip key={t}>{t}</Chip>)}
          </div>
        </div>
      </section>
      <section className="libv2-detail-block is-last">
        <div className="ds-label-caps libv2-block-label">Description</div>
        <div className="libv2-block-body">
          <div className="libv2-desc">{item.description}</div>
        </div>
      </section>
    </div>
  );
}

// ─── LoRA create / edit form ─────────────────────────────────────────────
function LoraForm({ item, families, onSave, onCancel }) {
  const isEdit = !!item;
  const [form, setForm] = useLS(item ? { ...item } : {
    name: '', display_name: '', author: '', version: '', source_url: '',
    family_compat: [], recommended_weight: 0.75,
    tags: [], trigger_words: [], description: '',
    updated: 'just now',
  });
  const [tagInput, setTagInput] = useLS('');
  const [trigInput, setTrigInput] = useLS('');
  const [errors, setErrors] = useLS({});

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const toggleFamily = (id) => {
    set('family_compat', form.family_compat.includes(id)
      ? form.family_compat.filter(x => x !== id)
      : [...form.family_compat, id]);
  };

  const addTag = (val) => {
    const t = val.trim().toLowerCase();
    if (t && !form.tags.includes(t)) set('tags', [...form.tags, t]);
    setTagInput('');
  };
  const addTrig = (val) => {
    const t = val.trim();
    if (t && !form.trigger_words.includes(t)) set('trigger_words', [...form.trigger_words, t]);
    setTrigInput('');
  };

  const validate = () => {
    const e = {};
    if (!form.name.trim()) e.name = 'Required';
    if (!form.description.trim()) e.description = 'Required — LLM sees this verbatim';
    if (form.family_compat.length === 0) e.family_compat = 'Select at least one family';
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const submit = () => { if (validate()) onSave({ ...form, name: form.name.trim() }); };

  return (
    <div className="lib-form">
      <div className="lib-form-head">
        <div className="ds-hstack" style={{ gap: 8, fontSize: 12, color: 'var(--text-subtle)' }}>
          <span style={{ cursor: 'pointer', color: 'var(--text-muted)' }} onClick={onCancel}>Library</span>
          <Icon name="Chevron" size={10} />
          <span style={{ cursor: 'pointer', color: 'var(--text-muted)' }} onClick={onCancel}>LoRAs</span>
          <Icon name="Chevron" size={10} />
          <span style={{ color: 'var(--text)' }}>{isEdit ? item.name : 'New LoRA'}</span>
        </div>
        <h1 className="libv2-detail-title" style={{ marginTop: 6 }}>{isEdit ? `Edit · ${item.name}` : 'New LoRA'}</h1>
      </div>
      <div className="lib-form-body">
        <FormSection title="Identity" sub="Filename and display info.">
          <Input label="Name · filename without .safetensors" placeholder="e.g. character_warrior_v1"
            value={form.name} onChange={e => set('name', e.target.value)}
            error={errors.name} disabled={isEdit} />
          <Input label="Display name" placeholder="Warrior character v1"
            value={form.display_name} onChange={e => set('display_name', e.target.value)} />
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <Input label="Author" placeholder="you" value={form.author} onChange={e => set('author', e.target.value)} />
            <Input label="Version" placeholder="1.0" value={form.version} onChange={e => set('version', e.target.value)} />
          </div>
          <Input label="Source URL" placeholder="https://civitai.com/models/…"
            value={form.source_url} onChange={e => set('source_url', e.target.value)} />
        </FormSection>

        <FormSection title="Compatibility" sub="Which families this LoRA works with.">
          <div>
            <div className="ds-label-caps" style={{ marginBottom: 8 }}>Families (multi-select)</div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {families.map(f => (
                <button key={f.id}
                  className={'libv2-pill' + (form.family_compat.includes(f.id) ? ' is-on' : '')}
                  onClick={() => toggleFamily(f.id)}>
                  {form.family_compat.includes(f.id) && <Icon name="Check" size={10} />}
                  {f.display_name}
                </button>
              ))}
            </div>
            {errors.family_compat && <div style={{ color: 'var(--danger)', fontSize: 11, marginTop: 5 }}>{errors.family_compat}</div>}
          </div>
          <div>
            <div className="ds-label-caps" style={{ marginBottom: 8 }}>Recommended weight</div>
            <Slider value={form.recommended_weight} min={0} max={2} step={0.05} label="weight"
              onChange={v => set('recommended_weight', v)} />
          </div>
        </FormSection>

        <FormSection title="Taxonomy" sub="Tags and trigger words — used by retriever.">
          <div>
            <div className="ds-label-caps" style={{ marginBottom: 8 }}>Tags</div>
            <div className="libv2-taginput">
              {form.tags.map(t => (
                <Chip key={t} removable onRemove={() => set('tags', form.tags.filter(x => x !== t))}>{t}</Chip>
              ))}
              <input placeholder="add tag + Enter…"
                value={tagInput} onChange={e => setTagInput(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); addTag(tagInput); } }} />
            </div>
          </div>
          <div>
            <div className="ds-label-caps" style={{ marginBottom: 8 }}>Trigger words</div>
            <div className="libv2-taginput">
              {form.trigger_words.map(t => (
                <code key={t} className="ds-code libv2-trigger">
                  {t}
                  <button className="libv2-trigger-x" onClick={() => set('trigger_words', form.trigger_words.filter(x => x !== t))}>
                    <Icon name="X" size={8} />
                  </button>
                </code>
              ))}
              <input placeholder="add trigger + Enter…"
                value={trigInput} onChange={e => setTrigInput(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); addTrig(trigInput); } }} />
            </div>
          </div>
        </FormSection>

        <FormSection title="Description" sub="Markdown. LLM sees this verbatim — be specific about what this produces and when to use it.">
          <div>
            <div className="libv2-create-md">
              <div className="libv2-create-md-toolbar">
                <span className="libv2-md-btn"><b>B</b></span>
                <span className="libv2-md-btn"><i>I</i></span>
                <span className="libv2-md-btn">`code`</span>
                <span className="libv2-md-btn">list</span>
              </div>
              <textarea
                className="libv2-create-md-area"
                rows={7}
                placeholder={'Describe what this LoRA produces, recommended weights, incompatibilities…\n\n- 0.6–0.8 for portraits\n- Pairs well with …'}
                value={form.description}
                onChange={e => set('description', e.target.value)}
              />
            </div>
            {errors.description && <div style={{ color: 'var(--danger)', fontSize: 11, marginTop: 5 }}>{errors.description}</div>}
          </div>
        </FormSection>
      </div>
      <footer className="lib-form-foot">
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
        <Button variant="primary" icon={<Icon name="Check" />} onClick={submit}>
          {isEdit ? 'Save changes' : 'Create LoRA'}
        </Button>
      </footer>
    </div>
  );
}

// ─── Models tab ──────────────────────────────────────────────────────────
function ModelsTab({ models, families, onSave, onDelete }) {
  const [view, setView] = useLS('list');
  const [editItem, setEditItem] = useLS(null);
  const [selected, setSelected] = useLS(models[0]?.name || null);
  const [search, setSearch] = useLS('');
  const [familyFilter, setFamilyFilter] = useLS('');
  const [popoverOpen, setPopoverOpen] = useLS(false);

  const filtered = models.filter(m => {
    if (search && !(m.name + ' ' + (m.display_name||'')).toLowerCase().includes(search.toLowerCase())) return false;
    if (familyFilter && m.family_id !== familyFilter) return false;
    return true;
  });

  const item = models.find(m => m.name === selected) || filtered[0] || models[0];

  if (view === 'create' || view === 'edit') {
    return (
      <ModelForm
        item={view === 'edit' ? editItem : null}
        families={families}
        onSave={(m) => { onSave(m); setView('list'); }}
        onCancel={() => setView('list')}
      />
    );
  }

  return (
    <div className="libv2" style={{ width: '100%' }}>
      <div className="libv2-list">
        <div className="libv2-list-head">
          <div className="ds-hstack" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
            <div>
              <h2 className="libv2-list-title">Models</h2>
              <div className="libv2-list-subtitle">{filtered.length} of {models.length}</div>
            </div>
            <Button variant="primary" size="sm" icon={<Icon name="Plus" />} onClick={() => setView('create')}>New</Button>
          </div>
          <div className="ds-search">
            <Icon name="Search" />
            <input placeholder="Search name…" value={search} onChange={e => setSearch(e.target.value)} />
          </div>
          <div className="libv2-filters">
            {familyFilter && (
              <span className="libv2-filter-chip">
                <span className="libv2-filter-kind">family</span>
                <span className="libv2-filter-val">{familyFilter}</span>
                <button onClick={() => setFamilyFilter('')} className="libv2-filter-x"><Icon name="X" size={9} /></button>
              </span>
            )}
            <div className="libv2-filter-wrap">
              <button className="libv2-filter-add" onClick={() => setPopoverOpen(!popoverOpen)}>
                <Icon name="Plus" size={10} /> Family
              </button>
              {popoverOpen && (
                <div className="libv2-popover">
                  <div className="libv2-popover-tab">FAMILY</div>
                  <div className="libv2-popover-items">
                    {families.map(f => (
                      <button key={f.id} className="libv2-popover-row"
                        onClick={() => { setFamilyFilter(f.id); setPopoverOpen(false); }}>
                        {f.display_name}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
            {(familyFilter || search) && (
              <button className="libv2-filter-clear" onClick={() => { setFamilyFilter(''); setSearch(''); }}>Clear</button>
            )}
          </div>
        </div>
        <div className="libv2-list-scroll">
          {filtered.length === 0 ? (
            <div className="libv2-list-empty">
              <Icon name="Search" size={18} />
              <div>No matches</div>
              <button className="libv2-filter-clear" onClick={() => { setFamilyFilter(''); setSearch(''); }}>Reset</button>
            </div>
          ) : filtered.map(m => (
            <button key={m.name}
              onClick={() => setSelected(m.name)}
              className={'libv2-row' + (m.name === item?.name ? ' is-selected' : '')}>
              <div className="libv2-row-top">
                <span className="libv2-row-name">{m.name}</span>
                <span className="libv2-row-family">{m.family_id}</span>
              </div>
              <div className="libv2-row-tags">
                <span className="libv2-row-tag">{m.author}</span>
                {m.version && <span className="libv2-row-tag">v{m.version}</span>}
              </div>
            </button>
          ))}
        </div>
      </div>
      {item ? (
        <div className="libv2-detail">
          <div className="libv2-detail-head">
            <div>
              <div className="ds-label-caps" style={{ marginBottom: 6 }}>Checkpoint</div>
              <h1 className="libv2-detail-title">{item.name}</h1>
            </div>
            <div className="ds-hstack" style={{ gap: 8 }}>
              <Button variant="ghost" size="sm" icon={<Icon name="Trash" />} onClick={() => { onDelete(item.name); setSelected(null); }} />
              <Button variant="secondary" size="sm" icon={<Icon name="Edit" />} onClick={() => { setEditItem(item); setView('edit'); }}>Edit</Button>
            </div>
          </div>
          <div className="libv2-detail-meta">
            <div className="libv2-detail-meta-cell">
              <span className="ds-label-caps">Family</span>
              <Badge variant="accent">{item.family_id.toUpperCase()}</Badge>
            </div>
            <div className="libv2-detail-meta-cell">
              <span className="ds-label-caps">Author</span>
              <span className="libv2-meta-val">{item.author || '—'}</span>
            </div>
            <div className="libv2-detail-meta-cell">
              <span className="ds-label-caps">Version</span>
              <span className="libv2-meta-val">{item.version || '—'}</span>
            </div>
            <div className="libv2-detail-meta-cell">
              <span className="ds-label-caps">Display name</span>
              <span className="libv2-meta-val">{item.display_name || '—'}</span>
            </div>
          </div>
          <section className="libv2-detail-block is-last">
            <div className="ds-label-caps libv2-block-label">Prompt delta</div>
            <div className="libv2-block-body">
              <div className="libv2-desc">{item.description || <span style={{color:'var(--text-subtle)', fontStyle:'italic'}}>No delta rules set.</span>}</div>
            </div>
          </section>
        </div>
      ) : (
        <div className="libv2-detail libv2-detail-empty">
          <Icon name="Folder" size={24} />
          <div className="libv2-detail-empty-msg">Select a model</div>
        </div>
      )}
    </div>
  );
}

function ModelForm({ item, families, onSave, onCancel }) {
  const isEdit = !!item;
  const [form, setForm] = useLS(item ? { ...item } : {
    name: '', display_name: '', family_id: families[0]?.id || '', author: '', version: '', source_url: '', description: '',
  });
  const [errors, setErrors] = useLS({});
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const validate = () => {
    const e = {};
    if (!form.name.trim()) e.name = 'Required';
    if (!form.family_id) e.family_id = 'Required';
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  return (
    <div className="lib-form">
      <div className="lib-form-head">
        <div className="ds-hstack" style={{ gap: 8, fontSize: 12, color: 'var(--text-subtle)' }}>
          <span style={{ cursor: 'pointer', color: 'var(--text-muted)' }} onClick={onCancel}>Library</span>
          <Icon name="Chevron" size={10} />
          <span style={{ cursor: 'pointer', color: 'var(--text-muted)' }} onClick={onCancel}>Models</span>
          <Icon name="Chevron" size={10} />
          <span style={{ color: 'var(--text)' }}>{isEdit ? item.name : 'New model'}</span>
        </div>
        <h1 className="libv2-detail-title" style={{ marginTop: 6 }}>{isEdit ? `Edit · ${item.name}` : 'New model'}</h1>
      </div>
      <div className="lib-form-body">
        <FormSection title="Identity" sub="Checkpoint filename and display info.">
          <Input label="Name · filename without .safetensors" placeholder="e.g. juggernautXL_v11"
            value={form.name} onChange={e => set('name', e.target.value)} error={errors.name} disabled={isEdit} />
          <Input label="Display name" placeholder="Juggernaut XL v11"
            value={form.display_name} onChange={e => set('display_name', e.target.value)} />
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <Input label="Author" placeholder="RunDiffusion" value={form.author} onChange={e => set('author', e.target.value)} />
            <Input label="Version" placeholder="11.0" value={form.version} onChange={e => set('version', e.target.value)} />
          </div>
          <Input label="Source URL" placeholder="https://civitai.com/models/…"
            value={form.source_url} onChange={e => set('source_url', e.target.value)} />
        </FormSection>

        <FormSection title="Family" sub="Which base family this checkpoint belongs to.">
          <div>
            <div className="ds-label-caps" style={{ marginBottom: 8 }}>Family</div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {families.map(f => (
                <button key={f.id}
                  className={'libv2-pill' + (form.family_id === f.id ? ' is-on' : '')}
                  onClick={() => set('family_id', f.id)}>
                  {form.family_id === f.id && <Icon name="Check" size={10} />}
                  {f.display_name}
                </button>
              ))}
            </div>
            {errors.family_id && <div style={{ color: 'var(--danger)', fontSize: 11, marginTop: 5 }}>{errors.family_id}</div>}
          </div>
        </FormSection>

        <FormSection title="Prompt delta" sub="Optional delta rules on top of family.prompt_guide. LLM sees this verbatim.">
          <div className="libv2-create-md">
            <div className="libv2-create-md-toolbar">
              <span className="libv2-md-btn"><b>B</b></span>
              <span className="libv2-md-btn"><i>I</i></span>
              <span className="libv2-md-btn">`code`</span>
            </div>
            <textarea
              className="libv2-create-md-area"
              rows={5}
              placeholder="E.g. Reduce CFG to 3.5–4.5 for best results. Strong face detail — lower detail LoRA weights."
              value={form.description}
              onChange={e => set('description', e.target.value)}
            />
          </div>
        </FormSection>
      </div>
      <footer className="lib-form-foot">
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
        <Button variant="primary" icon={<Icon name="Check" />} onClick={() => { if (validate()) onSave({ ...form, name: form.name.trim() }); }}>
          {isEdit ? 'Save changes' : 'Create model'}
        </Button>
      </footer>
    </div>
  );
}

// ─── Families tab ────────────────────────────────────────────────────────
function FamiliesTab({ families, onSave, onDelete }) {
  const [view, setView] = useLS('list');
  const [editItem, setEditItem] = useLS(null);
  const [selected, setSelected] = useLS(families[0]?.id || null);
  const item = families.find(f => f.id === selected) || families[0];

  if (view === 'create' || view === 'edit') {
    return (
      <FamilyForm
        item={view === 'edit' ? editItem : null}
        onSave={(f) => { onSave(f); setView('list'); }}
        onCancel={() => setView('list')}
      />
    );
  }

  return (
    <div className="libv2" style={{ width: '100%' }}>
      <div className="libv2-list">
        <div className="libv2-list-head">
          <div className="ds-hstack" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
            <div>
              <h2 className="libv2-list-title">Families</h2>
              <div className="libv2-list-subtitle">{families.length} families</div>
            </div>
            <Button variant="primary" size="sm" icon={<Icon name="Plus" />} onClick={() => setView('create')}>New</Button>
          </div>
        </div>
        <div className="libv2-list-scroll">
          {families.map(f => (
            <button key={f.id}
              onClick={() => setSelected(f.id)}
              className={'libv2-row' + (f.id === item?.id ? ' is-selected' : '')}>
              <div className="libv2-row-top">
                <span className="libv2-row-name">{f.display_name}</span>
              </div>
              <div className="libv2-row-tags">
                <span className="libv2-row-tag">{f.id}</span>
              </div>
            </button>
          ))}
        </div>
      </div>
      {item ? (
        <div className="libv2-detail">
          <div className="libv2-detail-head">
            <div>
              <div className="ds-label-caps" style={{ marginBottom: 6 }}>Family</div>
              <h1 className="libv2-detail-title">{item.display_name}</h1>
            </div>
            <div className="ds-hstack" style={{ gap: 8 }}>
              <Button variant="ghost" size="sm" icon={<Icon name="Trash" />} onClick={() => { onDelete(item.id); setSelected(null); }} />
              <Button variant="secondary" size="sm" icon={<Icon name="Edit" />} onClick={() => { setEditItem(item); setView('edit'); }}>Edit</Button>
            </div>
          </div>
          <div className="libv2-detail-meta" style={{ gridTemplateColumns: '1fr 1fr' }}>
            <div className="libv2-detail-meta-cell">
              <span className="ds-label-caps">ID</span>
              <code className="ds-code">{item.id}</code>
            </div>
            <div className="libv2-detail-meta-cell">
              <span className="ds-label-caps">Display name</span>
              <span className="libv2-meta-val">{item.display_name}</span>
            </div>
          </div>
          <section className="libv2-detail-block is-last">
            <div className="ds-label-caps libv2-block-label">Prompt guide</div>
            <div className="libv2-block-body">
              <div className="libv2-desc">{item.prompt_guide}</div>
            </div>
          </section>
        </div>
      ) : (
        <div className="libv2-detail libv2-detail-empty">
          <Icon name="Folder" size={24} />
          <div className="libv2-detail-empty-msg">Select a family</div>
        </div>
      )}
    </div>
  );
}

function FamilyForm({ item, onSave, onCancel }) {
  const isEdit = !!item;
  const [form, setForm] = useLS(item ? { ...item } : { id: '', display_name: '', prompt_guide: '' });
  const [errors, setErrors] = useLS({});
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const validate = () => {
    const e = {};
    if (!form.id.trim()) e.id = 'Required (e.g. sdxl, pony, flux)';
    if (!form.display_name.trim()) e.display_name = 'Required';
    if (!form.prompt_guide.trim()) e.prompt_guide = 'Required — LLM sees this for every session using this family';
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  return (
    <div className="lib-form">
      <div className="lib-form-head">
        <div className="ds-hstack" style={{ gap: 8, fontSize: 12, color: 'var(--text-subtle)' }}>
          <span style={{ cursor: 'pointer', color: 'var(--text-muted)' }} onClick={onCancel}>Library</span>
          <Icon name="Chevron" size={10} />
          <span style={{ cursor: 'pointer', color: 'var(--text-muted)' }} onClick={onCancel}>Families</span>
          <Icon name="Chevron" size={10} />
          <span style={{ color: 'var(--text)' }}>{isEdit ? item.display_name : 'New family'}</span>
        </div>
        <h1 className="libv2-detail-title" style={{ marginTop: 6 }}>{isEdit ? `Edit · ${item.display_name}` : 'New family'}</h1>
      </div>
      <div className="lib-form-body">
        <FormSection title="Identity" sub="ID used in code and display name shown in UI.">
          <Input label="ID (slug, lowercase)" placeholder="e.g. sdxl, pony, flux-schnell"
            value={form.id} onChange={e => set('id', e.target.value.toLowerCase().replace(/\s+/g,'-'))}
            error={errors.id} disabled={isEdit} />
          <Input label="Display name" placeholder="SDXL"
            value={form.display_name} onChange={e => set('display_name', e.target.value)}
            error={errors.display_name} />
        </FormSection>

        <FormSection title="Prompt guide" sub="Base prompting rules for this family. LLM sees this verbatim for every session. Be specific about syntax, quality tags, token style.">
          <div>
            <div className="libv2-create-md">
              <div className="libv2-create-md-toolbar">
                <span className="libv2-md-btn"><b>B</b></span>
                <span className="libv2-md-btn"><i>I</i></span>
                <span className="libv2-md-btn">`code`</span>
                <span className="libv2-md-btn">list</span>
              </div>
              <textarea
                className="libv2-create-md-area"
                rows={10}
                placeholder="E.g.\n\n# SDXL prompting\nUse natural language. Token weights via (keyword:1.2) syntax...\n\nLoRA trigger words take precedence over general style cues."
                value={form.prompt_guide}
                onChange={e => set('prompt_guide', e.target.value)}
              />
            </div>
            {errors.prompt_guide && <div style={{ color: 'var(--danger)', fontSize: 11, marginTop: 5 }}>{errors.prompt_guide}</div>}
          </div>
        </FormSection>
      </div>
      <footer className="lib-form-foot">
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
        <Button variant="primary" icon={<Icon name="Check" />} onClick={() => { if (validate()) onSave({ ...form, id: form.id.trim() }); }}>
          {isEdit ? 'Save changes' : 'Create family'}
        </Button>
      </footer>
    </div>
  );
}

// ─── Shared form primitives ──────────────────────────────────────────────
function FormSection({ title, sub, children }) {
  return (
    <section className="lib-form-section">
      <div className="lib-form-section-head">
        <h3 className="lib-form-section-title">{title}</h3>
        {sub && <div className="lib-form-section-sub">{sub}</div>}
      </div>
      <div className="lib-form-section-fields">{children}</div>
    </section>
  );
}

Object.assign(window, { LibraryPage });
