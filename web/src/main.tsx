import { render } from 'preact';
import { useEffect, useRef, useState } from 'preact/hooks';
import { devToken, setDevToken } from './api';
import { StoreProvider, Tab, useStore } from './store';
import { Btn, Dot, Icon } from './ui';
import { Live } from './views/Live';
import { Gallery } from './views/Gallery';
import { Editor } from './views/Editor';
import { Packs } from './views/Packs';
import { Rotation } from './views/Rotation';
import { Media } from './views/Media';
import './styles.css';

const NAV: { id: Tab; label: string; icon: string }[] = [
  { id: 'live', label: 'Live', icon: 'live' },
  { id: 'gallery', label: 'Gallery', icon: 'grid' },
  { id: 'editor', label: 'Editor', icon: 'edit' },
  { id: 'packs', label: 'Packs', icon: 'palette' },
  { id: 'rotation', label: 'Rotation', icon: 'rotate' },
  { id: 'media', label: 'Media', icon: 'image' },
];

function Header({ onToken }: { onToken: () => void }) {
  const { status, metrics, online, needToken } = useStore();
  const dev = status?.device;
  const node = (metrics?.values['node.name'] as string) || location.pathname.match(/@([^/]+)/)?.[1] || 'this node';
  const connected = online && dev?.connected !== false;
  const state = !online ? 'crit' : needToken ? 'warn' : dev?.connected === false ? 'warn' : 'ok';
  const lat = status?.apply_to_first_frame_s;
  return (
    <header class="topbar">
      <div class="brand">
        <svg class="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
          <rect x="3" y="6" width="26" height="18" rx="3" fill="#1f2833" stroke="#66fcf1" stroke-width="2" />
          <path d="M8 18l4-5 3 3 3-5 5 7" fill="none" stroke="#45a29e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
          <rect x="12" y="26" width="8" height="2" rx="1" fill="#45a29e" />
        </svg>
        <div class="brand-divider" />
        <div class="brand-text">
          <span class="brand-name">Display Control</span>
          <span class="brand-node">{node}</span>
        </div>
      </div>
      <div class="top-stats">
        <span class="pill" title={connected ? 'Panel connected and service reachable' : 'Not connected'}>
          <Dot state={state} />
          {!online ? 'service offline' : needToken ? 'token required' : dev?.connected === false ? 'panel disconnected' : 'connected'}
        </span>
        {dev && (
          <span class="pill" title="Device model, USB id and panel resolution">
            {dev.model || 'LCD'} <span class="muted">{dev.vid_pid}</span> {dev.width}x{dev.height}
          </span>
        )}
        {dev && (
          <span class="pill" title="Frames sent to the panel since the service started">
            <Icon name="live" size={13} /> <span class="tick">{dev.frames_sent.toLocaleString()}</span>
          </span>
        )}
        <span class="pill" title="Time from the last apply to the first frame on the panel">
          <Icon name="bolt" size={13} /> {lat == null ? '—' : lat < 1 ? `${Math.round(lat * 1000)} ms` : `${lat.toFixed(2)} s`}
        </span>
      </div>
      <div class="top-actions">
        <button type="button" class={`icon-btn${needToken ? ' attn' : ''}`} onClick={onToken} aria-label="Developer token" title="Developer token">
          <Icon name="key" size={15} />
        </button>
        <a class="btn btn-ghost btn-sm" href="/" title="Back to the node dashboard"><Icon name="back" size={14} /><span>Node</span></a>
      </div>
    </header>
  );
}

function TokenPanel({ close }: { close: () => void }) {
  const { tokenChanged, toast } = useStore();
  const [v, setV] = useState(devToken());
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => ref.current?.focus(), []);
  const save = (e: Event) => {
    e.preventDefault();
    setDevToken(v.trim());
    tokenChanged();
    toast(v.trim() ? 'Developer token set for this tab' : 'Developer token cleared', 'info');
    close();
  };
  return (
    <div class="token-panel card" role="dialog" aria-label="Developer token">
      <form onSubmit={save}>
        <p class="muted small">Only needed when the UI is opened without the node gateway. The token stays in this browser tab (session storage) and is sent as X-Display-Token.</p>
        <div class="row">
          <input ref={ref} class="input" type="password" autocomplete="off" placeholder="display token" value={v}
            onInput={(e) => setV((e.target as HTMLInputElement).value)} onKeyDown={(e) => e.key === 'Escape' && close()} />
          <Btn kind="primary" type="submit" small>Use</Btn>
          <Btn small kind="ghost" onClick={close}>Close</Btn>
        </div>
      </form>
    </div>
  );
}

function Toasts() {
  const { toasts, dismiss } = useStore();
  return (
    <div class="toasts" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div class={`toast toast-${t.kind}`} key={t.id}>
          <Icon name={t.kind === 'err' ? 'x' : t.kind === 'ok' ? 'check' : 'info'} size={15} />
          <span>{t.text}</span>
          <button type="button" class="toast-x" aria-label="Dismiss" onClick={() => dismiss(t.id)}><Icon name="x" size={12} /></button>
        </div>
      ))}
    </div>
  );
}

function Dialog() {
  const { dialog, closeDialog } = useStore();
  const ref = useRef<HTMLDialogElement>(null);
  const [val, setVal] = useState('');
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (dialog) { setVal(dialog.value || ''); if (!d.open) d.showModal(); }
    else if (d.open) d.close();
  }, [dialog]);
  return (
    <dialog ref={ref} class="dlg" onCancel={(e) => { e.preventDefault(); closeDialog(null); }}>
      {dialog && (
        <form method="dialog" onSubmit={(e) => { e.preventDefault(); closeDialog(dialog.kind === 'prompt' ? val : 'ok'); }}>
          <h3>{dialog.title}</h3>
          {dialog.body && <p class="muted">{dialog.body}</p>}
          {dialog.kind === 'prompt' && (
            <input class="input" autoFocus value={val} onInput={(e) => setVal((e.target as HTMLInputElement).value)} />
          )}
          <div class="dlg-actions">
            <Btn kind="ghost" onClick={() => closeDialog(null)}>Cancel</Btn>
            <Btn kind={dialog.danger ? 'danger' : 'primary'} type="submit">{dialog.ok}</Btn>
          </div>
        </form>
      )}
    </dialog>
  );
}

function App() {
  const { tab, go, needToken, online } = useStore();
  const [tokenOpen, setTokenOpen] = useState(false);
  return (
    <>
      <Header onToken={() => setTokenOpen((o) => !o)} />
      {tokenOpen && <TokenPanel close={() => setTokenOpen(false)} />}
      <nav class="tabs" aria-label="Sections">
        {NAV.map((n) => (
          <button type="button" class={`tab${tab === n.id ? ' on' : ''}`} aria-current={tab === n.id ? 'page' : undefined} onClick={() => go(n.id)}>
            <Icon name={n.icon} size={15} /><span>{n.label}</span>
          </button>
        ))}
      </nav>
      <main class="wrap">
        {needToken && !tokenOpen && (
          <div class="banner banner-warn">
            <Icon name="key" /> The display API rejected this request (no token). Open the UI through the node gateway at /display/, or set a developer token.
            <Btn small kind="primary" onClick={() => setTokenOpen(true)}>Set token</Btn>
          </div>
        )}
        {!online && <div class="banner banner-crit"><Icon name="info" /> The display service is not answering. Retrying every few seconds.</div>}
        {tab === 'live' && <Live />}
        {tab === 'gallery' && <Gallery />}
        {tab === 'editor' && <Editor />}
        {tab === 'packs' && <Packs />}
        {tab === 'rotation' && <Rotation />}
        {tab === 'media' && <Media />}
      </main>
      <Toasts />
      <Dialog />
    </>
  );
}

render(<StoreProvider><App /></StoreProvider>, document.getElementById('app')!);
