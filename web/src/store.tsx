import { ComponentChildren, createContext } from 'preact';
import { useCallback, useContext, useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { get, Json, MediaItem, Metrics, onAuthError, Pack, Status, Theme, onSignInNeeded } from './api';

export type Tab = 'live' | 'gallery' | 'editor' | 'packs' | 'rotation' | 'media';
export type ToastKind = 'ok' | 'err' | 'info';
export interface ToastMsg { id: number; kind: ToastKind; text: string }

interface DialogReq {
  kind: 'confirm' | 'prompt';
  title: string;
  body?: string;
  value?: string;
  ok: string;
  danger?: boolean;
  resolve: (v: string | null) => void;
}

export interface Store {
  status: Status | null;
  online: boolean;
  needToken: boolean;
  needSignIn: boolean;
  metrics: Metrics | null;
  history: Record<string, number[]>;
  packs: Pack[];
  designs: Theme[];
  themes: Theme[];
  legacy: Json[];
  media: MediaItem[];
  tab: Tab;
  editing: string | null;
  go: (tab: Tab, editing?: string | null) => void;
  reload: (...what: ('packs' | 'designs' | 'themes' | 'media' | 'status')[]) => Promise<void>;
  toast: (text: string, kind?: ToastKind) => void;
  toasts: ToastMsg[];
  dismiss: (id: number) => void;
  confirm: (title: string, body?: string, ok?: string, danger?: boolean) => Promise<boolean>;
  prompt: (title: string, value?: string, body?: string, ok?: string) => Promise<string | null>;
  dialog: DialogReq | null;
  closeDialog: (v: string | null) => void;
  tokenChanged: () => void;
}

const Ctx = createContext<Store>(null as unknown as Store);
export const useStore = () => useContext(Ctx);

const HIST = 90;
const TABS: Tab[] = ['live', 'gallery', 'editor', 'packs', 'rotation', 'media'];

function readHash(): { tab: Tab; editing: string | null } {
  const [t, e] = location.hash.replace(/^#\/?/, '').split('/');
  return { tab: (TABS as string[]).includes(t) ? (t as Tab) : 'live', editing: e ? decodeURIComponent(e) : null };
}

export function StoreProvider({ children }: { children: ComponentChildren }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [online, setOnline] = useState(true);
  const [needToken, setNeedToken] = useState(false);
  const [needSignIn, setNeedSignIn] = useState(false);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [history, setHistory] = useState<Record<string, number[]>>({});
  const [packs, setPacks] = useState<Pack[]>([]);
  const [designs, setDesigns] = useState<Theme[]>([]);
  const [themes, setThemes] = useState<Theme[]>([]);
  const [legacy, setLegacy] = useState<Json[]>([]);
  const [media, setMedia] = useState<MediaItem[]>([]);
  const [route, setRoute] = useState(readHash());
  const [toasts, setToasts] = useState<ToastMsg[]>([]);
  const [dialog, setDialog] = useState<DialogReq | null>(null);
  const seq = useRef(0);
  const [epoch, setEpoch] = useState(0);

  const toast = useCallback((text: string, kind: ToastKind = 'ok') => {
    const id = ++seq.current;
    setToasts((t) => [...t.slice(-3), { id, kind, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === 'err' ? 7000 : 3500);
  }, []);
  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);

  const reload = useCallback(async (...what: string[]) => {
    const all = what.length === 0;
    const jobs: Promise<unknown>[] = [];
    if (all || what.includes('packs')) jobs.push(get<{ packs: Pack[] }>('packs').then((r) => setPacks(r.packs)));
    if (all || what.includes('designs')) jobs.push(get<{ designs: Theme[] }>('designs').then((r) => setDesigns(r.designs)));
    if (all || what.includes('themes')) jobs.push(get<{ themes: Theme[]; legacy: Json[] }>('themes').then((r) => { setThemes(r.themes); setLegacy(r.legacy); }));
    if (all || what.includes('media')) jobs.push(get<{ media: MediaItem[] }>('media').then((r) => setMedia(r.media)));
    if (all || what.includes('status')) jobs.push(get<Status>('status').then(setStatus));
    const res = await Promise.allSettled(jobs);
    const bad = res.find((r) => r.status === 'rejected') as PromiseRejectedResult | undefined;
    if (bad && !all) toast(String(bad.reason?.message || bad.reason), 'err');
  }, [toast]);

  useEffect(() => onAuthError(() => setNeedToken(true)), []);
  useEffect(() => onSignInNeeded(() => setNeedSignIn(true)), []);
  useEffect(() => { reload(); }, [epoch]);

  // status ~1/s, metrics ~1/s (history for sparklines kept client side)
  useEffect(() => {
    let alive = true;
    let timer = 0;
    const tick = async () => {
      try {
        const [s, m] = await Promise.all([get<Status>('status'), get<Metrics>('metrics')]);
        if (!alive) return;
        setStatus(s); setMetrics(m); setOnline(true); setNeedToken(false);
        setHistory((h) => {
          const n: Record<string, number[]> = {};
          for (const [k, v] of Object.entries(m.values)) {
            if (typeof v === 'number') n[k] = [...(h[k] || []), v].slice(-HIST);
          }
          return n;
        });
      } catch (e: any) {
        if (alive) setOnline(e?.status !== 0);
      }
      if (alive) timer = window.setTimeout(tick, document.hidden ? 5000 : 1000);
    };
    tick();
    return () => { alive = false; clearTimeout(timer); };
  }, [epoch]);

  useEffect(() => {
    const on = () => setRoute(readHash());
    addEventListener('hashchange', on);
    return () => removeEventListener('hashchange', on);
  }, []);

  const go = useCallback((tab: Tab, editing?: string | null) => {
    const e = editing === undefined ? (tab === 'editor' ? route.editing : null) : editing;
    location.hash = '#/' + tab + (e ? '/' + encodeURIComponent(e) : '');
    setRoute({ tab, editing: e });
    window.scrollTo({ top: 0 });
  }, [route.editing]);

  const confirm = useCallback((title: string, body?: string, ok = 'Confirm', danger = false) =>
    new Promise<boolean>((res) => setDialog({ kind: 'confirm', title, body, ok, danger, resolve: (v) => res(v !== null) })), []);
  const prompt = useCallback((title: string, value = '', body?: string, ok = 'OK') =>
    new Promise<string | null>((res) => setDialog({ kind: 'prompt', title, body, value, ok, resolve: res })), []);
  const closeDialog = useCallback((v: string | null) => {
    setDialog((d) => { d?.resolve(v); return null; });
  }, []);

  const value = useMemo<Store>(() => ({
    status, online, needToken, needSignIn, metrics, history, packs, designs, themes, legacy, media,
    tab: route.tab, editing: route.editing, go, reload: reload as Store['reload'], toast, toasts, dismiss,
    confirm, prompt, dialog, closeDialog, tokenChanged: () => setEpoch((e) => e + 1),
  }), [status, online, needToken, needSignIn, metrics, history, packs, designs, themes, legacy, media, route, go, reload, toast, toasts, dismiss, confirm, prompt, dialog, closeDialog]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** Wrap an async action: toast the error text, return undefined on failure. */
export function useAction() {
  const { toast } = useStore();
  return useCallback(async <T,>(fn: () => Promise<T>, ok?: string): Promise<T | undefined> => {
    try {
      const r = await fn();
      if (ok) toast(ok, 'ok');
      return r;
    } catch (e: any) {
      toast(String(e?.message || e), 'err');
      return undefined;
    }
  }, [toast]);
}
