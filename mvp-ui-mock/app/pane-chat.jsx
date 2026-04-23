// Chat pane with streaming simulation

function ChatPane({ session, onSendMessage, streaming, onGenerate, canGenerate }) {
  const [draft, setDraft] = React.useState('');
  const scrollRef = React.useRef(null);
  const messages = session?.messages || [];

  React.useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages.length, streaming]);

  const send = () => {
    const t = draft.trim();
    if (!t || streaming) return;
    onSendMessage(t);
    setDraft('');
  };

  return (
    <div className="pane">
      <div className="pane-head">
        <span className="pane-title">Chat</span>
        <span className="pane-sub">· {messages.length} msg</span>
        <div className="spacer" />
        <button className="ds-icon-btn" title="Clear chat"><Icon name="Trash" size={12} /></button>
      </div>
      <div className="pane-body">
        <div className="chat-scroll" ref={scrollRef}>
          {messages.length === 0 && (
            <div style={{ padding: '24px 8px', textAlign: 'center', color: 'var(--text-subtle)', fontSize: 12.5, lineHeight: 1.6 }}>
              {session?.source_image_path
                ? <>Describe the change you want. I'll pick LoRAs from your library and assemble a prompt.</>
                : <>Add a source image first — I need a VL summary to anchor the prompt.</>}
            </div>
          )}
          {messages.map((m, i) => (
            <ChatMessage key={i} role={m.role} content={m.content} streaming={streaming && i === messages.length - 1 && m.role === 'assistant'} />
          ))}
          {streaming && messages[messages.length - 1]?.role !== 'assistant' && (
            <div className="ds-chat ds-chat-assistant">
              <div className="ds-chat-avatar">
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                  <path d="M3 11L7 3L11 11L7 8.5L3 11Z" fill="currentColor" />
                </svg>
              </div>
              <div className="ds-chat-body">
                <div className="ds-chat-meta">sd-chisel · thinking</div>
                <div className="typing-indicator"><span /><span /><span /></div>
              </div>
            </div>
          )}
        </div>
        <div className="chat-composer">
          <textarea
            className="chat-textarea"
            placeholder={session?.source_image_path ? 'Describe the change…' : 'Add source image first'}
            value={draft}
            disabled={!session?.source_image_path || streaming}
            onChange={e => setDraft(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(); }
            }}
          />
          <div className="chat-composer-row">
            <span className="chat-hint">⌘↵ to send</span>
            <div className="spacer" />
            <Button variant="ghost" size="sm" onClick={onGenerate} disabled={!canGenerate || streaming} icon={<Icon name="Spark" size={12} />}>
              Generate prompt
            </Button>
            <Button variant="primary" size="sm" onClick={send} disabled={!draft.trim() || streaming}>
              Send
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ChatMessage({ role, content, streaming }) {
  const time = React.useMemo(() => {
    const d = new Date();
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }, []);
  // Render basic markdown: code, lists, bold
  const rendered = React.useMemo(() => renderInline(content), [content]);
  return (
    <div className={'ds-chat ds-chat-' + role}>
      {role === 'assistant' && (
        <div className="ds-chat-avatar">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M3 11L7 3L11 11L7 8.5L3 11Z" fill="currentColor" />
          </svg>
        </div>
      )}
      <div className="ds-chat-body">
        <div className="ds-chat-meta">{role === 'user' ? 'You' : 'sd-chisel'} · {time}</div>
        <div className="msg-content" dangerouslySetInnerHTML={{ __html: rendered }} />
        {streaming && <span className="ds-chat-cursor" />}
      </div>
    </div>
  );
}

function renderInline(text) {
  if (!text) return '';
  const esc = text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  let html = esc;
  // code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  // bold
  html = html.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  // bullets: lines starting with "- "
  const lines = html.split('\n');
  const out = [];
  let inList = false;
  for (const ln of lines) {
    if (/^\s*-\s+/.test(ln)) {
      if (!inList) { out.push('<ul>'); inList = true; }
      out.push('<li>' + ln.replace(/^\s*-\s+/, '') + '</li>');
    } else {
      if (inList) { out.push('</ul>'); inList = false; }
      out.push(ln ? '<p style="margin:4px 0">' + ln + '</p>' : '');
    }
  }
  if (inList) out.push('</ul>');
  return out.join('');
}

Object.assign(window, { ChatPane });
