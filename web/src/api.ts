// Thin client for the display service API. Every URL is relative so the app
// works at the service root or under any reverse-proxy prefix (e.g. /display/<node>/).

export type Json = Record<string, any>;

export interface Widget {
  type: string;
  [k: string]: any;
}

export interface Theme {
  schema?: number;
  id: string;
  name?: string;
  description?: string;
  design?: string;
  pack?: string;
  base?: [number, number];
  mark?: { mode?: string; opacity?: number; variant?: string; corner?: string };
  mark_corner?: string;
  available?: boolean;
  requires?: string[];
  requires_any?: string[];
  background?: { type: string; path?: string; interval?: number };
  foreground?: { path: string; alpha?: number; x?: number; y?: number } | null;
  device?: { rotation?: number; brightness?: number; refresh?: number };
  widgets: Widget[];
  layouts?: Record<string, Widget[]>;
  order?: number;
  [k: string]: any;
}

export interface Pack {
  id: string;
  name: string;
  ground: 'dark' | 'light';
  colors: Record<string, string>;
  fonts: Record<string, string | null>;
  mark: Json | null;
  default_mark: string;
  builtin?: boolean;
  license?: string;
}

export interface Selection {
  kind: 'design' | 'theme' | 'legacy';
  design?: string;
  theme?: string;
  pack?: string;
  mark?: Json;
  device?: Json;
}

export interface Identity {
  node_name?: string; node_id?: string; role?: string; device_kind?: string;
  model?: string; vid_pid?: string; resolution?: string; service?: string;
}

export interface Status {
  identity?: Identity;
  device: {
    vid_pid?: string; model?: string; connected?: boolean; width: number; height: number;
    frames_sent: number; frame_errors: number; last_frame_ms: number; last_frame_at: number; uptime_s: number;
  };
  active: Selection;
  theme: { id?: string; name?: string; pack?: string };
  rotate: { enabled: boolean; seconds: number; items: Selection[] };
  applied_at: number;
  apply_to_first_frame_s: number | null;
  capabilities: Capabilities;
}

export interface Capabilities {
  gpu?: boolean; rapl?: boolean; llm?: boolean; cores?: number; nvme?: boolean; services?: string[];
  rapl_reason?: string | null; gpu_reason?: string | null;
}

export interface CatalogEntry { label: string; unit: string; heat: [number, number] | null; requires: string | null }

export interface Metrics {
  values: Record<string, any>;
  catalog: Record<string, CatalogEntry>;
  capabilities: Capabilities;
}

export interface MediaItem { path: string; kind: 'image' | 'gif' | 'video' | 'collection' | 'font'; count: number | null; bytes: number | null }

export interface NodeInfo {
  hostname: string; node_id?: string; self: boolean; display_url: string | null;
  hw_display: Json | null;
}

export interface DeviceInfo { vid_pid: string; panels: string[]; attached: boolean | null; active: boolean }

export const TOKEN_KEY = 'display-dev-token';

export function devToken(): string {
  try { return sessionStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; }
}

export function setDevToken(t: string) {
  try {
    if (t) sessionStorage.setItem(TOKEN_KEY, t);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch { /* storage blocked: token lives for this page only */ }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

type Listener = (status: number) => void;
const authListeners = new Set<Listener>();
export function onAuthError(fn: Listener) { authListeners.add(fn); return () => authListeners.delete(fn); }

async function raw(method: string, path: string, body?: BodyInit | null, ctype?: string): Promise<Response> {
  const headers: Record<string, string> = {};
  const t = devToken();
  if (t) headers['X-Display-Token'] = t;
  if (ctype) headers['Content-Type'] = ctype;
  let r: Response;
  try {
    r = await fetch('api/' + path, { method, headers, body: body ?? undefined, cache: 'no-store' });
  } catch {
    throw new ApiError(0, 'display service unreachable');
  }
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      if (j && j.error) msg = j.error;
    } catch { /* not JSON */ }
    if (r.status === 401) authListeners.forEach((f) => f(401));
    throw new ApiError(r.status, msg);
  }
  return r;
}

export async function get<T = Json>(path: string): Promise<T> {
  return (await raw('GET', path)).json();
}

export async function send<T = Json>(method: 'POST' | 'PUT' | 'DELETE', path: string, data?: unknown): Promise<T> {
  const r = await raw(method, path, data === undefined ? null : JSON.stringify(data), data === undefined ? undefined : 'application/json');
  return r.json();
}

/** GET an image with the token header (if any) and return an object URL. */
export async function imageUrl(path: string): Promise<string> {
  const r = await raw('GET', path);
  return URL.createObjectURL(await r.blob());
}

/** POST api/preview.png and return an object URL. */
export async function previewUrl(req: Json): Promise<string> {
  const r = await raw('POST', 'preview.png', JSON.stringify(req), 'application/json');
  return URL.createObjectURL(await r.blob());
}

export async function uploadMedia(file: File, dir?: string): Promise<{ path: string; kind: string }> {
  const q = `media?name=${encodeURIComponent(safeName(file.name))}` + (dir ? `&dir=${encodeURIComponent(dir)}` : '');
  const r = await raw('POST', q, file, 'application/octet-stream');
  return r.json();
}

export const IMAGE_EXT = ['.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tiff'];
export const VIDEO_EXT = ['.mp4', '.avi', '.mkv', '.mov', '.webm', '.flv', '.wmv', '.m4v'];
export const FONT_EXT = ['.ttf', '.otf'];
export const MEDIA_EXT = [...IMAGE_EXT, '.gif', ...VIDEO_EXT, ...FONT_EXT];

export function ext(name: string): string {
  const i = name.lastIndexOf('.');
  return i < 0 ? '' : name.slice(i).toLowerCase();
}

/** Server accepts [A-Za-z0-9][A-Za-z0-9._-]{0,95}; make browser file names fit. */
export function safeName(name: string): string {
  const e = ext(name);
  let stem = name.slice(0, name.length - e.length).replace(/[^A-Za-z0-9._-]+/g, '_').replace(/^[^A-Za-z0-9]+/, '');
  if (!stem) stem = 'file';
  return stem.slice(0, 90 - e.length) + e;
}

/** Upload a picked set of files: one file → plain upload; several images → a collection. */
export async function uploadPicked(files: File[]): Promise<{ path: string; kind: string; skipped: string[] }> {
  const skipped = files.filter((f) => !MEDIA_EXT.includes(ext(f.name))).map((f) => f.name);
  const ok = files.filter((f) => MEDIA_EXT.includes(ext(f.name)));
  if (!ok.length) throw new ApiError(400, 'unsupported format; supported: ' + MEDIA_EXT.join(' '));
  if (ok.length === 1) return { ...(await uploadMedia(ok[0])), skipped };
  const imgs = ok.filter((f) => IMAGE_EXT.includes(ext(f.name)));
  skipped.push(...ok.filter((f) => !IMAGE_EXT.includes(ext(f.name))).map((f) => f.name));
  if (!imgs.length) throw new ApiError(400, 'collections hold still images only (' + IMAGE_EXT.join(' ') + ')');
  const { dir } = await send<{ dir: string }>('POST', 'media/collection');
  for (const f of imgs) await uploadMedia(f, dir);
  return { path: dir, kind: 'collection', skipped };
}

export function slug(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 48) || 'theme';
}
