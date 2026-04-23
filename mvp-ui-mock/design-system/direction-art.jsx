// DirectionArt — artboard A per direction: palette, type scale, spacing,
// radii, shadows, primitives (buttons, inputs, badges, chat, slider, row).

function DirectionArt({ dir }) {
  const theme = dir.id; // always 'quarry'
  const scalePrefix = 'stone';
  const scaleStops = [50,100,150,200,300,400,500,600,700,800,900];
  const isDark = false; // Quarry is a light theme; kept to flag bg patches as is-light.

  return (
    <div data-theme={theme} className="theme-art ds-surface">
      {/* Header */}
      <div className="dir-header">
        <div>
          <h2 className="dir-name">{dir.name}</h2>
          <div className="dir-desc" style={{ marginTop: 6 }}>{dir.desc}</div>
        </div>
        <div className="dir-tag">{dir.tag}</div>
      </div>

      {/* Palette */}
      <div className="block">
        <div className="block-header">
          <div className="block-name">Color · raw scale</div>
          <div className="block-note">{scalePrefix}-50 → {scalePrefix}-900</div>
        </div>
        <div className="ds-swatch-grid" style={{ gridTemplateColumns: `repeat(${scaleStops.length}, 1fr)` }}>
          {scaleStops.map((n) => {
            const isLight = n <= 200;
            return (
              <div
                key={n}
                className={`ds-swatch ${isLight ? 'is-light' : ''}`}
                style={{ background: `var(--${scalePrefix}-${n})` }}
                title={`${scalePrefix}-${n}`}
              >
                {n}
              </div>
            );
          })}
        </div>

        <div className="block-header" style={{ borderTop: 'none', paddingTop: 0, marginTop: 8 }}>
          <div className="block-name">Color · semantic</div>
          <div className="block-note">maps to application roles</div>
        </div>
        <div className="grid2">
          <div className="palette-row">
            <span className="palette-label">bg</span>
            <div className="patch-strip">
              <div style={{ background: 'var(--bg)' }} className={isDark ? '' : 'is-light'}>bg</div>
              <div style={{ background: 'var(--bg-sunken)' }} className={isDark ? '' : 'is-light'}>sunken</div>
              <div style={{ background: 'var(--bg-raised)' }} className={isDark ? '' : 'is-light'}>raised</div>
            </div>
          </div>
          <div className="palette-row">
            <span className="palette-label">surface</span>
            <div className="patch-strip">
              <div style={{ background: 'var(--surface)' }} className={isDark ? '' : 'is-light'}>surface</div>
              <div style={{ background: 'var(--surface-alt)' }} className={isDark ? '' : 'is-light'}>alt</div>
              <div style={{ background: 'var(--border)' }} className={isDark ? '' : 'is-light'}>border</div>
            </div>
          </div>
          <div className="palette-row">
            <span className="palette-label">text</span>
            <div className="patch-strip">
              <div style={{ background: 'var(--text)', color: 'var(--bg)' }}>text</div>
              <div style={{ background: 'var(--text-muted)', color: 'var(--bg)' }}>muted</div>
              <div style={{ background: 'var(--text-subtle)', color: 'var(--bg)' }}>subtle</div>
            </div>
          </div>
          <div className="palette-row">
            <span className="palette-label">accent</span>
            <div className="patch-strip">
              <div style={{ background: 'var(--accent-subtle)' }} className={isDark ? '' : 'is-light'}>subtle</div>
              <div style={{ background: 'var(--accent)' }}>accent</div>
              <div style={{ background: 'var(--accent-hover)' }}>hover</div>
            </div>
          </div>
          <div className="palette-row">
            <span className="palette-label">status</span>
            <div className="patch-strip">
              <div style={{ background: 'var(--success)' }}>success</div>
              <div style={{ background: 'var(--warning)' }}>warning</div>
              <div style={{ background: 'var(--danger)' }}>danger</div>
              <div style={{ background: 'var(--info)' }}>info</div>
            </div>
          </div>
        </div>
      </div>

      {/* Typography */}
      <div className="block">
        <div className="block-header">
          <div className="block-name">Typography</div>
          <div className="block-note">ui · display · mono</div>
        </div>
        <div className="card-demo">
          <div className="type-row">
            <span className="spec">DISPLAY · 40</span>
            <div className="type-sample" style={{ fontFamily: 'var(--font-display)', fontSize: 40, fontWeight: 600, letterSpacing: '-0.03em' }}>
              Chisel the prompt.
            </div>
          </div>
          <div className="type-row">
            <span className="spec">H1 · 28</span>
            <div className="type-sample" style={{ fontFamily: 'var(--font-display)', fontSize: 28, fontWeight: 600, letterSpacing: '-0.02em' }}>
              Project · Character portraits
            </div>
          </div>
          <div className="type-row">
            <span className="spec">H2 · 22</span>
            <div className="type-sample" style={{ fontFamily: 'var(--font-display)', fontSize: 22, fontWeight: 600 }}>
              Generate prompt
            </div>
          </div>
          <div className="type-row">
            <span className="spec">H3 · 18</span>
            <div className="type-sample" style={{ fontSize: 18, fontWeight: 600 }}>
              Pinned LoRAs (3)
            </div>
          </div>
          <div className="type-row">
            <span className="spec">BODY · 14</span>
            <div className="type-sample" style={{ fontSize: 14 }}>
              Опиши, что хочешь изменить в референсе — ассистент подберёт LoRA и соберёт промпт.
            </div>
          </div>
          <div className="type-row">
            <span className="spec">SM · 12</span>
            <div className="type-sample" style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              Secondary helper text, meta, small labels.
            </div>
          </div>
          <div className="type-row">
            <span className="spec">MONO · 12</span>
            <div className="type-sample" style={{ fontSize: 12, fontFamily: 'var(--font-mono)' }}>
              {'<lora:add_detail:0.65> masterpiece, cinematic lighting'}
            </div>
          </div>
          <div className="type-row">
            <span className="spec">CAPS · 10</span>
            <div className="type-sample" style={{ fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-subtle)', fontWeight: 600 }}>
              SECTION LABEL
            </div>
          </div>
        </div>
      </div>

      {/* Spacing + Radii + Shadows */}
      <div className="grid3">
        <div className="block">
          <div className="block-header">
            <div className="block-name">Spacing</div>
            <div className="block-note">4px base</div>
          </div>
          <div className="card-demo" style={{ padding: 14 }}>
            {[4,8,12,16,20,24,32,40,48].map((n) => (
              <div key={n} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 5 }}>
                <div style={{ width: n, height: 10, background: 'var(--accent)' }} />
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)' }}>s-{n/4}</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-subtle)', marginLeft: 'auto' }}>{n}px</span>
              </div>
            ))}
          </div>
        </div>
        <div className="block">
          <div className="block-header">
            <div className="block-name">Radii</div>
            <div className="block-note">r-sm = 3px default</div>
          </div>
          <div className="card-demo" style={{ padding: 14 }}>
            <div className="radii-demo">
              <div style={{ borderRadius: 4 }}>xs · 4</div>
              <div style={{ borderRadius: 6 }}>sm · 6</div>
              <div style={{ borderRadius: 8 }}>md · 8</div>
              <div style={{ borderRadius: 10 }}>lg · 10</div>
              <div style={{ borderRadius: 12 }}>xl · 12</div>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-subtle)', marginTop: 10, lineHeight: 1.5 }}>
              Inputs/buttons/badges — <code className="ds-code">r-sm 6px</code>. Cards — <code className="ds-code">r-md 8px</code>.
              Drawers, popovers — <code className="ds-code">r-lg 10px</code>. Dialogs — <code className="ds-code">r-xl 12px</code>.
            </div>
          </div>
        </div>
        <div className="block">
          <div className="block-header">
            <div className="block-name">Shadows</div>
            <div className="block-note">sm · md · lg</div>
          </div>
          <div className="card-demo shadow-demo" style={{ padding: 14, background: 'var(--bg-sunken)' }}>
            <div style={{ boxShadow: 'var(--shadow-sm)' }}>shadow-sm · cards</div>
            <div style={{ boxShadow: 'var(--shadow-md)' }}>shadow-md · popovers</div>
            <div style={{ boxShadow: 'var(--shadow-lg)' }}>shadow-lg · modals</div>
          </div>
        </div>
      </div>

      {/* Buttons */}
      <div className="block">
        <div className="block-header">
          <div className="block-name">Buttons</div>
          <div className="block-note">primary · secondary · ghost · danger</div>
        </div>
        <div className="card-demo">
          <div className="ds-hstack" style={{ marginBottom: 12 }}>
            <Button variant="primary" size="lg">Generate prompt</Button>
            <Button variant="primary">Generate</Button>
            <Button variant="primary" size="sm">Copy</Button>
          </div>
          <div className="ds-hstack" style={{ marginBottom: 12 }}>
            <Button variant="secondary">Analyze source</Button>
            <Button variant="ghost">Regenerate</Button>
            <Button variant="danger">Delete session</Button>
          </div>
          <div className="ds-hstack">
            <Button variant="primary" icon={<svg width="11" height="11" viewBox="0 0 11 11" fill="none"><path d="M5.5 1v9M1 5.5h9" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/></svg>}>New session</Button>
            <Button variant="secondary" icon={<svg width="11" height="11" viewBox="0 0 11 11" fill="none"><path d="M2 3.5h7M2 5.5h7M2 7.5h4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/></svg>}>Settings</Button>
            <Button variant="ghost" icon={<svg width="11" height="11" viewBox="0 0 11 11" fill="none"><circle cx="5.5" cy="5.5" r="4" stroke="currentColor" strokeWidth="1.3"/></svg>}>Info</Button>
          </div>
        </div>
      </div>

      {/* Inputs + slider + toggle */}
      <div className="grid2">
        <div className="block">
          <div className="block-header">
            <div className="block-name">Inputs</div>
            <div className="block-note">input · textarea · select</div>
          </div>
          <div className="card-demo ds-vstack">
            <Input label="SESSION NAME" placeholder="portrait study · dusk" defaultValue="portrait · dusk v2" />
            <Select label="BASE MODEL" value="illustrious" onChange={() => {}} options={[
              { value: 'sdxl', label: 'SDXL · realvisxl_v4' },
              { value: 'pony', label: 'Pony · ponyV6' },
              { value: 'illustrious', label: 'Illustrious · illustriousXL_v01' },
              { value: 'flux', label: 'Flux · flux_dev_fp8' },
            ]} />
            <Textarea label="POSITIVE PROMPT" rows={3} defaultValue="1girl, red hair, looking away, dramatic rim light, ((masterpiece)), best quality" />
          </div>
        </div>
        <div className="block">
          <div className="block-header">
            <div className="block-name">Slider + Toggle + Badges</div>
            <div className="block-note">LoRA weight · flags · status</div>
          </div>
          <div className="card-demo ds-vstack">
            <Slider label="LoRA · add_detail" min={-2} max={2} value={0.65} />
            <Slider label="LoRA · cinematic_light" min={-2} max={2} value={0.85} />
            <Slider label="denoise (negative test)" min={-2} max={2} value={-0.4} />
            <div className="ds-divider" />
            <Toggle checked={true} label="Use negative prompt" />
            <Toggle checked={false} label="Auto-run analyzer on upload" />
            <div className="ds-divider" />
            <div className="ds-hstack">
              <Badge variant="accent" dot>retrieved</Badge>
              <Badge variant="success" dot>pinned</Badge>
              <Badge variant="warning" dot>unknown lora</Badge>
              <Badge variant="info">sdxl</Badge>
              <Badge variant="neutral">pony</Badge>
              <Badge variant="danger">over-weight</Badge>
            </div>
            <div className="ds-hstack">
              <Chip removable onRemove={() => {}}>style:moody</Chip>
              <Chip removable onRemove={() => {}}>subject:character</Chip>
              <Chip removable onRemove={() => {}}>detail</Chip>
              <Chip>lighting</Chip>
            </div>
          </div>
        </div>
      </div>

      {/* Chat + Row */}
      <div className="block">
        <div className="block-header">
          <div className="block-name">Chat bubbles</div>
          <div className="block-note">user · assistant · streaming</div>
        </div>
        <div className="card-demo ds-vstack" style={{ gap: 16 }}>
          <ChatBubble role="user">
            Сделай освещение резче, по типу контрового, и добавь больше фактуры волос.
          </ChatBubble>
          <ChatBubble role="assistant" meta="ASSISTANT · 2 intents · 4 LoRAs retrieved">
            Подобрал три LoRA: <code className="ds-code">add_detail</code> для фактуры,
            <code className="ds-code"> cinematic_light</code> для rim-lighting и твой
            закреплённый <code className="ds-code">character_v3</code>. Negative оставил базовый.
          </ChatBubble>
          <ChatBubble role="assistant" streaming meta="STREAMING · intent rewriting…">
            Анализирую запрос… выделяю style, detail, character
          </ChatBubble>
        </div>
      </div>

      {/* Library row preview */}
      <div className="block">
        <div className="block-header">
          <div className="block-name">Library row</div>
          <div className="block-note">loras table — dense layout</div>
        </div>
        <div className="card-demo" style={{ padding: 0, overflow: 'hidden' }}>
          <DataRow name="add_detail_xl" tags={['detail','texture']} family="SDXL" weight="0.65" trigger="detail enhancer" />
          <DataRow name="cinematic_lighting_v2" tags={['light','mood','style']} family="SDXL" weight="0.85" trigger="cinematic, rim" />
          <DataRow name="character_redhead_v3" tags={['character']} family="Illust." weight="1.00" trigger="red hair, long" />
          <DataRow name="anime_ink_style" tags={['style','ink']} family="Pony" weight="0.70" trigger="ink, linework" />
        </div>
      </div>

      {/* Final prompt preview */}
      <div className="block">
        <div className="block-header">
          <div className="block-name">Final prompt · composed</div>
          <div className="block-note">monospace · copy blocks</div>
        </div>
        <div className="card-demo ds-vstack">
          <div>
            <div className="ds-label-caps" style={{ marginBottom: 6 }}>POSITIVE</div>
            <div className="mono-pre">1girl, red hair long, looking away, dramatic rim lighting, moody cinematic atmosphere, intricate detail, (masterpiece:1.1), best quality</div>
          </div>
          <div>
            <div className="ds-label-caps" style={{ marginBottom: 6 }}>LORA STRING</div>
            <div className="mono-pre" style={{ color: 'var(--accent)' }}>{'<lora:add_detail_xl:0.65> <lora:cinematic_lighting_v2:0.85> <lora:character_redhead_v3:1.0>'}</div>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { DirectionArt });
