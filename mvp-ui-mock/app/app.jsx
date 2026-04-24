// Main App — ties everything together

const { useState, useEffect, useMemo, useCallback } = React;

const ASSISTANT_REPLIES = [
  "Ок, понял. Смотрю что есть в библиотеке под это — сейчас соберу интенты и подберу LoRA.\n\nЕсли хочешь, нажми **Generate prompt** — покажу, что получилось, и из чего оно собралось.",
  "Понял направление. Смотрю совместимость с выбранным чекпоинтом и подбираю LoRA под каждый аспект:\n- свет / атмосфера\n- характер / персонаж\n- стиль / текстура\n\nГотов собрать промпт.",
  "Ясно. Важно: пинованные LoRA всегда поедут в контекст — я их не выкидываю даже если retriever предложит альтернативы. Генерирую?",
];

function App() {
  const [route, setRoute] = useState({ page: 'workspace' });
  const [sessions, setSessions] = useState(INITIAL_SESSIONS);
  const [activeSessionId, setActiveSessionId] = useState(() => {
    try { return localStorage.getItem('sd-chisel:active') || 's-001' } catch { return 's-001' }
  });
  const [toasts, setToasts] = useState([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [tweaksOpen, setTweaksOpen] = useState(false);
  const [tweaks, setTweaks] = useState(/*EDITMODE-BEGIN*/{
    "density": "comfortable",
    "accent": "#c96442",
    "showDebug": true
  }/*EDITMODE-END*/);

  useEffect(() => {
    try { localStorage.setItem('sd-chisel:active', activeSessionId) } catch {}
  }, [activeSessionId]);

  // Tweak mode protocol
  useEffect(() => {
    const handler = (e) => {
      if (e.data?.type === '__activate_edit_mode') setTweaksOpen(true);
      if (e.data?.type === '__deactivate_edit_mode') setTweaksOpen(false);
    };
    window.addEventListener('message', handler);
    window.parent.postMessage({ type: '__edit_mode_available' }, '*');
    return () => window.removeEventListener('message', handler);
  }, []);

  useEffect(() => {
    document.documentElement.style.setProperty('--accent', tweaks.accent);
  }, [tweaks.accent]);

  const lorasByName = useMemo(() => {
    const o = {}; LORAS.forEach(l => { o[l.name] = l }); return o;
  }, []);

  const activeSession = sessions.find(s => s.id === activeSessionId) || sessions[0];
  const updateSession = (id, patch) => {
    setSessions(s => s.map(x => x.id === id ? (typeof patch === 'function' ? patch(x) : { ...x, ...patch }) : x));
  };

  const toast = (msg, accent) => {
    const id = Math.random().toString(36).slice(2);
    setToasts(t => [...t, { id, msg, accent }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 2200);
  };

  // Chat: simulated streaming
  const onSendMessage = (text) => {
    updateSession(activeSessionId, s => ({ ...s, messages: [...s.messages, { role: 'user', content: text }] }));
    setStreaming(true);
    const reply = ASSISTANT_REPLIES[Math.floor(Math.random() * ASSISTANT_REPLIES.length)];
    let i = 0;
    updateSession(activeSessionId, s => ({ ...s, messages: [...s.messages, { role: 'assistant', content: '' }] }));
    const tick = () => {
      i += Math.max(1, Math.floor(Math.random() * 4));
      const chunk = reply.slice(0, i);
      updateSession(activeSessionId, s => {
        const msgs = [...s.messages];
        msgs[msgs.length - 1] = { role: 'assistant', content: chunk };
        return { ...s, messages: msgs };
      });
      if (i < reply.length) setTimeout(tick, 28);
      else setStreaming(false);
    };
    setTimeout(tick, 260);
  };

  // Generate-prompt: fake two-step with loading
  const onGenerate = () => {
    if (!activeSession?.source_image_path) return;
    setRegenerating(true);
    setTimeout(() => {
      const pinned = (activeSession.pinned || []).map(n => {
        const m = lorasByName[n];
        return { name: n, weight: m?.recommended_weight ?? 0.8, kind: 'pinned' };
      });
      // naive retrieval: pick 2-3 LoRAs matching model family
      const fam = MODELS.find(m => m.name === activeSession.model_name)?.family_id;
      const candidates = LORAS.filter(l => l.family_id === fam && !pinned.find(p => p.name === l.name));
      const picked = shuffle(candidates).slice(0, 3).map(l => ({
        name: l.name, weight: l.recommended_weight, kind: 'retrieved'
      }));
      const prompt = {
        positive: buildPositive(activeSession, [...pinned, ...picked], lorasByName),
        negative: activeSession.use_negative ? 'low quality, blurry, watermark, text, deformed, extra fingers, bad anatomy' : null,
        loras: [...pinned, ...picked],
        intents: [
          { kind: 'style', query: 'match source composition and mood' },
          { kind: 'light', query: 'preserve lighting character' },
          { kind: 'detail', query: 'fine detail enhancer' },
        ],
        retrieved: [...pinned, ...picked].slice(0, 3).map((_, i) => ({
          intent: i,
          loras: picked.slice(0, 3).map(p => [p.name, 0.6 + Math.random() * 0.3]),
        })),
      };
      updateSession(activeSessionId, { lastPrompt: prompt });
      setRegenerating(false);
      toast('Prompt generated', `${prompt.loras.length} LoRAs`);
    }, 1100);
  };

  const onAnalyze = () => {
    setAnalyzing(true);
    setTimeout(() => setAnalyzing(false), 2000);
  };

  const onUploadStub = () => {
    // simulate upload + analyze
    updateSession(activeSessionId, {
      source_image_path: 'https://images.unsplash.com/photo-1492707892479-7bc8d5a4ee93?w=900&q=80',
      vl_summary: null,
    });
    setAnalyzing(true);
    setTimeout(() => {
      updateSession(activeSessionId, {
        vl_summary: 'Close-up portrait, soft natural light from window camera-left. Neutral palette, shallow depth of field. Subject in casual clothing, relaxed expression, gaze toward camera. Background: out-of-focus interior with warm tones.',
      });
      setAnalyzing(false);
      toast('VL summary ready');
    }, 1800);
  };

  const onClearSource = () => updateSession(activeSessionId, { source_image_path: null, vl_summary: null, lastPrompt: null });

  const onNewSession = () => {
    const id = 's-' + Math.random().toString(36).slice(2, 6);
    const ns = {
      id, project_id: activeSession.project_id || 'scrapyard',
      name: 'untitled · ' + new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}),
      model_name: 'juggernautXL_v10', use_negative: true, pinned: [],
      source_image_path: null, vl_summary: null, messages: [], lastPrompt: null,
    };
    setSessions(s => [...s, ns]);
    setActiveSessionId(id);
    toast('Session created');
  };

  const onUpdateLora = (i, updated) => {
    updateSession(activeSessionId, s => ({
      ...s,
      lastPrompt: { ...s.lastPrompt, loras: s.lastPrompt.loras.map((l, idx) => idx === i ? updated : l) }
    }));
  };
  const onPin = (name) => {
    updateSession(activeSessionId, s => ({
      ...s,
      pinned: s.pinned.includes(name) ? s.pinned : [...s.pinned, name],
      lastPrompt: s.lastPrompt ? { ...s.lastPrompt, loras: s.lastPrompt.loras.map(l => l.name === name ? { ...l, kind: 'pinned' } : l) } : s.lastPrompt
    }));
    toast('Pinned');
  };
  const onUnpin = (name) => {
    updateSession(activeSessionId, s => ({
      ...s,
      pinned: s.pinned.filter(n => n !== name),
      lastPrompt: s.lastPrompt ? { ...s.lastPrompt, loras: s.lastPrompt.loras.map(l => l.name === name ? { ...l, kind: 'retrieved' } : l) } : s.lastPrompt
    }));
    toast('Unpinned');
  };

  return (
    <div className="app-shell" data-theme="quarry">
      <Topbar route={route} setRoute={setRoute} endpoint={{
        connected: true,
        base_url: 'localhost:1234',
        vl_model: 'qwen2-vl-7b',
      }} />
      <Sidebar
        projects={PROJECTS}
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelect={(id) => { setActiveSessionId(id); setRoute({ page: 'workspace' }); }}
        onNewSession={onNewSession}
        onNewProject={() => toast('Project creation · stub')}
      />

      {route.page === 'workspace' ? (
        <div className="workspace">
          <div className="ws-header">
            <div className="ws-crumbs">
              <span>{PROJECTS.find(p => p.id === activeSession?.project_id)?.name}</span>
              <span className="sep">/</span>
              <b>{activeSession?.name}</b>
            </div>
            <div className="spacer" />
            <div className="ws-header-actions">
              {activeSession && (
                <>
                  <Badge variant="neutral">
                    {MODELS.find(m => m.name === activeSession.model_name)?.display_name || activeSession.model_name}
                  </Badge>
                  {activeSession.use_negative && <Badge variant="neutral">neg · on</Badge>}
                  {activeSession.pinned?.length > 0 && (
                    <Badge variant="accent" icon={<Icon name="Pin" size={10} />}>
                      {activeSession.pinned.length} pinned
                    </Badge>
                  )}
                </>
              )}
              <Button variant="secondary" size="sm" icon={<Icon name="Settings" size={12} />} onClick={() => setDrawerOpen(true)}>
                Session settings
              </Button>
            </div>
          </div>
          {activeSession ? (
            <div className="ws-grid">
              <SourceImagePane
                session={activeSession}
                analyzing={analyzing}
                onUpload={onUploadStub}
                onAnalyze={onAnalyze}
                onClear={onClearSource}
              />
              <ChatPane
                session={activeSession}
                streaming={streaming}
                onSendMessage={onSendMessage}
                onGenerate={onGenerate}
                canGenerate={!!activeSession?.source_image_path}
              />
              <PromptPane
                session={activeSession}
                lorasByName={lorasByName}
                regenerating={regenerating}
                onCopyToast={(msg) => toast(msg)}
                onRegen={onGenerate}
                onUpdateLora={onUpdateLora}
                onPin={onPin}
                onUnpin={onUnpin}
              />
            </div>          ) : (
            <div className="session-empty">
              <div className="session-empty-card">
                <Icon name="Folder" size={28} />
                <h2>No session selected</h2>
                <p>Pick one from the sidebar, or create a new session to start.</p>
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="workspace">
          <LibraryPage
            families={FAMILIES}
            models={MODELS}
            loras={LORAS}
            onBack={() => setRoute({ page: 'workspace' })}
          />
        </div>
      )}

      {drawerOpen && activeSession && (
        <SessionDrawer
          session={activeSession}
          lorasByName={lorasByName}
          models={MODELS}
          onClose={() => setDrawerOpen(false)}
          onSave={(draft) => { updateSession(activeSessionId, draft); setDrawerOpen(false); toast('Session saved'); }}
        />
      )}

      {tweaksOpen && (
        <div className="tweaks-panel">
          <div className="tweaks-head">
            <span>Tweaks</span>
            <button className="ds-icon-btn" onClick={() => setTweaksOpen(false)}><Icon name="X" size={10} /></button>
          </div>
          <div className="tweaks-body">
            <div>
              <div className="ds-label-caps" style={{ marginBottom: 6 }}>Accent color</div>
              <div style={{ display: 'flex', gap: 6 }}>
                {[
                  ['#c96442','Terracotta'],
                  ['#4a6b8a','Info'],
                  ['#4f7d3a','Forest'],
                  ['#7a5ba3','Plum'],
                ].map(([c, l]) => (
                  <button key={c} onClick={() => { const nt = { ...tweaks, accent: c }; setTweaks(nt); window.parent.postMessage({ type: '__edit_mode_set_keys', edits: { accent: c } }, '*'); }}
                    title={l}
                    style={{
                      width: 28, height: 28, borderRadius: 6, cursor: 'pointer',
                      background: c,
                      border: tweaks.accent === c ? '2px solid var(--text)' : '1px solid var(--border)',
                    }} />
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="toast-root">
        {toasts.map(t => (
          <div key={t.id} className="toast">
            <Icon name="Check" size={12} />
            <span>{t.msg}</span>
            {t.accent && <span className="accent">{t.accent}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}

function shuffle(a) { return [...a].sort(() => Math.random() - 0.5); }

function buildPositive(session, loras, byName) {
  const base = (session.vl_summary || '').split('.').slice(0, 2).join('.').toLowerCase();
  const triggers = loras.flatMap(l => (byName[l.name]?.trigger_words || [])).slice(0, 6).join(', ');
  return `${base}, ${triggers}, highly detailed, cinematic`.replace(/^,\s*/, '').replace(/\s+,/g, ',');
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
