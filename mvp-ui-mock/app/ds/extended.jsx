// Extended components — icons, drawer, dialog, popover, library table,
// markdown editor, empty/loading/error states.

const { useState: useS2 } = React;

// ─── Icon set ──────────────────────────────────────────────────────────
// 14px viewBox, 1.3 stroke, round linecap, monochrome. Inherits currentColor.
const I = {
  Plus:     <svg viewBox="0 0 14 14" fill="none"><path d="M7 2v10M2 7h10" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/></svg>,
  Search:   <svg viewBox="0 0 14 14" fill="none"><circle cx="6" cy="6" r="3.5" stroke="currentColor" strokeWidth="1.3"/><path d="M8.7 8.7l3 3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/></svg>,
  Settings: <svg viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="1.7" stroke="currentColor" strokeWidth="1.3"/><path d="M7 1.5v1.8M7 10.7v1.8M12.5 7h-1.8M3.3 7H1.5M10.9 3.1l-1.3 1.3M4.4 9.6l-1.3 1.3M10.9 10.9l-1.3-1.3M4.4 4.4L3.1 3.1" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/></svg>,
  Image:    <svg viewBox="0 0 14 14" fill="none"><rect x="1.5" y="2.5" width="11" height="9" rx="1" stroke="currentColor" strokeWidth="1.3"/><circle cx="5" cy="5.5" r="1" stroke="currentColor" strokeWidth="1.3"/><path d="M2 10l3-3 3.5 3.5L10 9l2.5 2.5" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round"/></svg>,
  Copy:     <svg viewBox="0 0 14 14" fill="none"><rect x="4.5" y="4.5" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.3"/><path d="M9.5 4.5V3a.5.5 0 00-.5-.5H3a.5.5 0 00-.5.5v6a.5.5 0 00.5.5h1.5" stroke="currentColor" strokeWidth="1.3"/></svg>,
  Trash:    <svg viewBox="0 0 14 14" fill="none"><path d="M2.5 3.5h9M5.5 3.5V2.5h3v1M3.5 3.5l.7 8h5.6l.7-8M6 6v4M8 6v4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  Edit:     <svg viewBox="0 0 14 14" fill="none"><path d="M9 2.5l2.5 2.5M2.5 11.5v-2L9.5 2.5l2 2L4.5 11.5h-2z" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  Pin:      <svg viewBox="0 0 14 14" fill="none"><path d="M9 2.5l2.5 2.5-1.7 1.7-3.3 1L4 10l-1-1 1.3-2.5 1-3.3L7 1.5l2 1zM4 10l-2.5 2.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  Filter:   <svg viewBox="0 0 14 14" fill="none"><path d="M1.5 2.5h11l-4 5v4l-3-1.5v-2.5l-4-5z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round"/></svg>,
  Chat:     <svg viewBox="0 0 14 14" fill="none"><path d="M2 3.5c0-.5.5-1 1-1h8c.5 0 1 .5 1 1v5c0 .5-.5 1-1 1H6l-3 2.5v-2.5H3c-.5 0-1-.5-1-1v-5z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round"/></svg>,
  Spark:    <svg viewBox="0 0 14 14" fill="none"><path d="M7 1.5l1.3 3.7 3.7 1.3-3.7 1.3L7 11.5 5.7 7.8 2 6.5l3.7-1.3L7 1.5z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round"/></svg>,
  X:        <svg viewBox="0 0 14 14" fill="none"><path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/></svg>,
  Check:    <svg viewBox="0 0 14 14" fill="none"><path d="M2.5 7.5l3 3 6-7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  Warn:     <svg viewBox="0 0 14 14" fill="none"><path d="M7 1.5l6 11h-12l6-11zM7 6v3M7 10.5v.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  Folder:   <svg viewBox="0 0 14 14" fill="none"><path d="M1.5 3.5c0-.5.5-1 1-1h3l1.5 1.5h5c.5 0 1 .5 1 1v6c0 .5-.5 1-1 1h-9.5c-.5 0-1-.5-1-1v-7.5z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round"/></svg>,
  Chevron:  <svg viewBox="0 0 14 14" fill="none"><path d="M4 3l4 4-4 4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  ChevronRight: <svg viewBox="0 0 14 14" fill="none"><path d="M5 3l4 4-4 4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  ChevronDown:  <svg viewBox="0 0 14 14" fill="none"><path d="M3 5l4 4 4-4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg>,
};

function Icon({ name, size = 14 }) {
  return <span style={{ display: 'inline-flex', width: size, height: size, color: 'inherit' }}>{React.cloneElement(I[name], { width: size, height: size })}</span>;
}

// ─── Drawer ────────────────────────────────────────────────────────────
function DrawerMock() {
  return (
    <div className="ds-drawer-mock">
      <div className="ds-drawer-backdrop" />
      <div className="ds-drawer">
        <div className="ds-drawer-head">
          <div>
            <div className="ds-label-caps">SESSION SETTINGS</div>
            <div style={{ fontSize: 'var(--text-lg)', fontWeight: 600, marginTop: 4 }}>portrait · dusk v2</div>
          </div>
          <button className="ds-icon-btn"><Icon name="X" /></button>
        </div>
        <div className="ds-drawer-body">
          <Select label="BASE MODEL" value="illustrious" onChange={()=>{}} options={[
            { value: 'sdxl', label: 'SDXL · realvisxl_v4' },
            { value: 'illustrious', label: 'Illustrious · illustriousXL_v01' },
          ]} />
          <div>
            <div className="ds-label-caps" style={{marginBottom:6}}>PINNED LORAs · 2</div>
            <div className="ds-vstack" style={{gap: 4}}>
              <div className="ds-pin-row">
                <Icon name="Pin" /><span style={{fontFamily:'var(--font-mono)', fontSize:12, flex:1}}>character_redhead_v3</span>
                <Badge variant="accent">1.0</Badge>
                <button className="ds-icon-btn"><Icon name="X" /></button>
              </div>
              <div className="ds-pin-row">
                <Icon name="Pin" /><span style={{fontFamily:'var(--font-mono)', fontSize:12, flex:1}}>style_ink_v2</span>
                <Badge variant="accent">0.7</Badge>
                <button className="ds-icon-btn"><Icon name="X" /></button>
              </div>
            </div>
            <Button variant="ghost" size="sm" icon={<Icon name="Plus" />}>Add LoRA</Button>
          </div>
          <Toggle checked={true} label="Use negative prompt" />
          <div className="ds-divider" />
          <div className="ds-label-caps">ENDPOINTS</div>
          <Input label="VL · base_url" defaultValue="http://localhost:1234/v1" />
          <Input label="VL · model" defaultValue="qwen2-vl-7b-instruct" />
          <Input label="PROMPT · model" defaultValue="mistral-nemo-12b" />
        </div>
        <div className="ds-drawer-foot">
          <Button variant="ghost">Cancel</Button>
          <Button variant="primary">Save changes</Button>
        </div>
      </div>
    </div>
  );
}

// ─── Dialog ────────────────────────────────────────────────────────────
function DialogMock() {
  return (
    <div className="ds-dialog-mock">
      <div className="ds-drawer-backdrop" />
      <div className="ds-dialog">
        <div style={{display:'flex', gap:12, alignItems:'flex-start'}}>
          <div style={{
            width:32, height:32, borderRadius:'var(--r-sm)',
            background:'color-mix(in oklab, var(--danger) 15%, transparent)',
            color:'var(--danger)',
            display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0
          }}><Icon name="Warn" /></div>
          <div style={{flex:1}}>
            <div style={{fontFamily:'var(--font-display)', fontSize:'var(--text-lg)', fontWeight:600, color:'var(--text)'}}>Delete session?</div>
            <div style={{fontSize:13, color:'var(--text-muted)', marginTop:6, lineHeight:1.55}}>
              <b style={{color:'var(--text)'}}>portrait · dusk v2</b> будет удалён вместе со всей историей чата (28 сообщений), промптами (12) и картинками на диске. Действие необратимо.
            </div>
          </div>
        </div>
        <div style={{display:'flex', gap:8, justifyContent:'flex-end', marginTop:20}}>
          <Button variant="ghost">Cancel</Button>
          <Button variant="primary" style={{background:'var(--danger)', borderColor:'var(--danger)'}}>Delete session</Button>
        </div>
      </div>
    </div>
  );
}

// ─── Popover ───────────────────────────────────────────────────────────
function PopoverMock() {
  return (
    <div style={{position:'relative', padding: '40px 24px 100px'}}>
      <Button variant="secondary" icon={<Icon name="Filter" />}>Filter LoRAs</Button>
      <div className="ds-popover" style={{top: 78, left: 24}}>
        <div className="ds-popover-head">Filters</div>
        <div className="ds-popover-body">
          <div className="ds-label-caps" style={{marginBottom:6}}>FAMILY</div>
          <div className="ds-hstack" style={{marginBottom:12, gap: 4}}>
            <Chip>SDXL</Chip><Chip>Pony</Chip><Chip>Illustrious</Chip><Chip>Flux</Chip>
          </div>
          <div className="ds-label-caps" style={{marginBottom:6}}>TAGS</div>
          <div className="ds-hstack" style={{gap: 4}}>
            <Chip>style</Chip><Chip>detail</Chip><Chip>character</Chip>
            <Chip>lighting</Chip><Chip>mood</Chip>
          </div>
        </div>
        <div className="ds-popover-foot">
          <Button variant="ghost" size="sm">Reset</Button>
          <Button variant="primary" size="sm">Apply · 14 matches</Button>
        </div>
      </div>
    </div>
  );
}

// ─── Library table (full) ──────────────────────────────────────────────
function LibraryTable() {
  const rows = [
    { name: 'add_detail_xl', family: 'SDXL', tags: ['detail','texture'], trigger: 'detail enhancer', weight: 0.65, used: 24 },
    { name: 'cinematic_lighting_v2', family: 'SDXL', tags: ['light','mood','style'], trigger: 'cinematic, rim', weight: 0.85, used: 18 },
    { name: 'character_redhead_v3', family: 'Illust.', tags: ['character'], trigger: 'red hair, long', weight: 1.0, used: 12 },
    { name: 'anime_ink_style', family: 'Pony', tags: ['style','ink'], trigger: 'ink, linework', weight: 0.7, used: 9 },
    { name: 'studio_portrait_v1', family: 'SDXL', tags: ['portrait','studio'], trigger: 'studio portrait', weight: 0.8, used: 7 },
    { name: 'moody_atmosphere', family: 'Flux', tags: ['mood','atmospheric'], trigger: 'moody, fog', weight: 0.6, used: 4 },
  ];
  return (
    <div className="ds-table">
      <div className="ds-table-toolbar">
        <div className="ds-search">
          <Icon name="Search" />
          <input placeholder="Search LoRAs by name, tag, trigger…" />
          <span className="ds-kbd">/</span>
        </div>
        <div className="ds-hstack">
          <Button variant="secondary" size="sm" icon={<Icon name="Filter" />}>Filter · 2</Button>
          <Button variant="primary" size="sm" icon={<Icon name="Plus" />}>New LoRA</Button>
        </div>
      </div>
      <div className="ds-table-head">
        <div>Name · trigger</div>
        <div>Tags</div>
        <div>Family</div>
        <div style={{textAlign:'right'}}>Weight</div>
        <div style={{textAlign:'right'}}>Used</div>
      </div>
      {rows.map(r => (
        <div className="ds-table-row" key={r.name}>
          <div>
            <div style={{fontFamily:'var(--font-mono)', fontSize:13, color:'var(--text)'}}>{r.name}</div>
            <div style={{fontSize:11, color:'var(--text-subtle)', marginTop:2, fontFamily:'var(--font-mono)'}}>{r.trigger}</div>
          </div>
          <div className="ds-hstack" style={{gap:4}}>
            {r.tags.map(t => <Chip key={t}>{t}</Chip>)}
          </div>
          <div><Badge variant="neutral">{r.family}</Badge></div>
          <div style={{textAlign:'right', fontFamily:'var(--font-mono)', fontSize:12, color:'var(--text-muted)'}}>{r.weight.toFixed(2)}</div>
          <div style={{textAlign:'right', fontFamily:'var(--font-mono)', fontSize:12, color:'var(--text-subtle)'}}>{r.used}</div>
        </div>
      ))}
      <div className="ds-table-foot">6 of 143 LoRAs</div>
    </div>
  );
}

// ─── Markdown editor ───────────────────────────────────────────────────
function MdEditor() {
  return (
    <div className="ds-md">
      <div className="ds-md-toolbar">
        <div className="ds-hstack" style={{gap:2}}>
          <button className="ds-md-btn"><b>B</b></button>
          <button className="ds-md-btn" style={{fontStyle:'italic'}}>I</button>
          <button className="ds-md-btn">H1</button>
          <button className="ds-md-btn">H2</button>
          <div style={{width:1, height:16, background:'var(--border)', margin:'0 4px'}} />
          <button className="ds-md-btn">≡</button>
          <button className="ds-md-btn">1.</button>
          <button className="ds-md-btn">&#123;&#125;</button>
          <button className="ds-md-btn">&lt;/&gt;</button>
        </div>
        <div className="ds-hstack">
          <button className="ds-md-tab is-active">Edit</button>
          <button className="ds-md-tab">Preview</button>
        </div>
      </div>
      <div className="ds-md-split">
        <div className="ds-md-pane">
          <div style={{fontFamily:'var(--font-mono)', fontSize:12.5, lineHeight:1.7, whiteSpace:'pre-wrap'}}>
{`# character_redhead_v3

LoRA для портретов рыжеволосой героини. Обучена на 120
референсах с уклоном в editorial-освещение.

## Trigger words
\`red hair long\`, \`freckles\`

## Recommended weight
**1.0** для портретов, 0.7 для full-body.

## Conflicts
- Не миксовать с \`character_blonde_v2\` (взаимно гасят)
- С \`cinematic_lighting_v2\` — уменьшить вес до 0.8`}
          </div>
        </div>
        <div className="ds-md-pane ds-md-preview">
          <h1 style={{fontFamily:'var(--font-display)', fontSize:22, margin:'0 0 12px', fontWeight:600, letterSpacing:'-0.02em'}}>character_redhead_v3</h1>
          <p style={{fontSize:13, color:'var(--text-muted)', lineHeight:1.6}}>
            LoRA для портретов рыжеволосой героини. Обучена на 120
            референсах с уклоном в editorial-освещение.
          </p>
          <h2 style={{fontSize:14, margin:'14px 0 6px', fontWeight:600}}>Trigger words</h2>
          <p style={{fontSize:13, color:'var(--text-muted)'}}>
            <code className="ds-code">red hair long</code>, <code className="ds-code">freckles</code>
          </p>
          <h2 style={{fontSize:14, margin:'14px 0 6px', fontWeight:600}}>Recommended weight</h2>
          <p style={{fontSize:13, color:'var(--text-muted)'}}><b style={{color:'var(--text)'}}>1.0</b> для портретов, 0.7 для full-body.</p>
        </div>
      </div>
    </div>
  );
}

// ─── Empty / Loading / Error states ────────────────────────────────────
function EmptyState() {
  return (
    <div className="ds-state">
      <div className="ds-state-glyph">
        <Icon name="Image" size={24} />
      </div>
      <div className="ds-state-title">Нет исходника</div>
      <div className="ds-state-sub">Перетащи картинку сюда или выбери файл — я опишу её через VL и начнём.</div>
      <div className="ds-hstack" style={{marginTop:16}}>
        <Button variant="primary" size="sm">Choose file</Button>
        <Button variant="ghost" size="sm">Paste from clipboard</Button>
      </div>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="ds-state">
      <div className="ds-state-glyph">
        <div className="ds-spinner" />
      </div>
      <div className="ds-state-title">Анализирую исходник</div>
      <div className="ds-state-sub">VL-модель описывает композицию, освещение и объекты. Обычно 3–6 секунд.</div>
      <div className="ds-progress" style={{marginTop:16}}>
        <div className="ds-progress-bar" style={{width:'62%'}} />
      </div>
    </div>
  );
}

function ErrorState() {
  return (
    <div className="ds-state ds-state-error">
      <div className="ds-state-glyph">
        <Icon name="Warn" size={24} />
      </div>
      <div className="ds-state-title">LMStudio не отвечает</div>
      <div className="ds-state-sub">
        Не удалось соединиться с <code className="ds-code">http://localhost:1234/v1</code>. Проверь, что сервер запущен и модель загружена.
      </div>
      <div className="ds-hstack" style={{marginTop:16}}>
        <Button variant="primary" size="sm">Retry</Button>
        <Button variant="ghost" size="sm">Open endpoint settings</Button>
      </div>
    </div>
  );
}

// ─── Iconography showcase ──────────────────────────────────────────────
function IconShowcase() {
  return (
    <div className="card-demo">
      <div style={{display:'grid', gridTemplateColumns:'repeat(8,1fr)', gap:12}}>
        {Object.keys(I).map(k => (
          <div key={k} style={{display:'flex', flexDirection:'column', alignItems:'center', gap:6, padding:10, background:'var(--surface)', borderRadius:'var(--r-sm)', border:'1px solid var(--border)'}}>
            <div style={{color:'var(--text)', display:'flex', alignItems:'center', justifyContent:'center', height:18}}>
              <Icon name={k} size={16} />
            </div>
            <div style={{fontSize:10, fontFamily:'var(--font-mono)', color:'var(--text-subtle)'}}>{k}</div>
          </div>
        ))}
      </div>
      <div style={{marginTop:16, fontSize:12, color:'var(--text-muted)', lineHeight:1.6}}>
        <b style={{color:'var(--text)'}}>Правила:</b> 14px viewBox, stroke 1.3px, round linecap/join,
        монохром через <code className="ds-code">currentColor</code>. Без заливок, кроме как знак
        chisel в брендинге. Для плотного UI — 14px, для заголовков пустых стейтов — 24px.
      </div>
    </div>
  );
}

Object.assign(window, {
  Icon, DrawerMock, DialogMock, PopoverMock, LibraryTable,
  MdEditor, EmptyState, LoadingState, ErrorState, IconShowcase,
});
