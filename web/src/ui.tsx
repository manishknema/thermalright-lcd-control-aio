import { ComponentChildren, JSX } from 'preact';
import { useEffect, useRef, useState } from 'preact/hooks';
import { imageUrl, Json, previewUrl } from './api';

// ── icons (inline SVG, stroke-based) ────────────────────────────────────────
const P: Record<string, string> = {
  live: 'M3 12h4l3-8 4 16 3-8h4',
  grid: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z',
  edit: 'M4 20h4L19 9l-4-4L4 16zM14 6l4 4',
  palette: 'M12 3a9 9 0 1 0 0 18c1.5 0 2-1 2-2s-1-1.5-1-2.5 1-1.5 2-1.5h2a4 4 0 0 0 4-4c0-4.5-4-8-9-8zM7.5 11.5h.01M10 7.5h.01M15 7.5h.01',
  rotate: 'M20 12a8 8 0 1 1-2.3-5.6M20 4v5h-5',
  image: 'M4 5h16v14H4zM4 16l5-5 4 4 2-2 5 5M15 9.5h.01',
  node: 'M4 5h16v10H4zM9 19h6M12 15v4',
  usb: 'M12 3v14M12 3l-2 3h4zM8 9v3l4 3M16 8v2l-4 3M12 17a2 2 0 1 0 0 4 2 2 0 0 0 0-4z',
  play: 'M7 5v14l11-7z',
  copy: 'M8 8h11v11H8zM5 16V5h11',
  trash: 'M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13',
  plus: 'M12 5v14M5 12h14',
  up: 'M12 19V5M6 11l6-6 6 6',
  down: 'M12 5v14M6 13l6 6 6-6',
  x: 'M6 6l12 12M18 6L6 18',
  eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z',
  eyeoff: 'M3 3l18 18M10.6 6.1A10 10 0 0 1 12 6c6 0 10 6 10 6a17 17 0 0 1-3 3.6M6.6 6.6C3.8 8.4 2 12 2 12s4 7 10 7c1.6 0 3-.4 4.3-1',
  save: 'M5 4h11l3 3v13H5zM8 4v5h7V4M8 20v-6h8v6',
  upload: 'M12 16V4M7 9l5-5 5 5M4 20h16',
  key: 'M14 10a4 4 0 1 0-3.5 4L12 16h2v2h2v2h4v-3l-6.5-6.5',
  back: 'M15 6l-6 6 6 6',
  refresh: 'M4 12a8 8 0 0 1 14-5.3L20 9M20 4v5h-5M20 12a8 8 0 0 1-14 5.3L4 15M4 20v-5h5',
  font: 'M5 20l6-16h2l6 16M8 14h8',
  check: 'M5 12l5 5 9-10',
  info: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 11v6M12 7.5h.01',
  layers: 'M12 3l9 5-9 5-9-5zM3 13l9 5 9-5',
  bolt: 'M13 2L4 14h7l-1 8 9-12h-7z',
  temp: 'M10 13V5a2 2 0 1 1 4 0v8a4 4 0 1 1-4 0z',
  chip: 'M7 7h10v10H7zM9 3v4M15 3v4M9 17v4M15 17v4M3 9h4M3 15h4M17 9h4M17 15h4',
  mem: 'M3 8h18v8H3zM7 16v3M11 16v3M15 16v3M7 11h2M11 11h2M15 11h2',
  disk: 'M4 6h16v12H4zM8 14h.01M12 14h4',
  spark: 'M3 17l5-6 4 3 4-7 5 6',
};

export function Icon({ name, size = 16, title }: { name: string; size?: number; title?: string }) {
  return (
    <svg class="ic" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden={title ? undefined : 'true'}
      role={title ? 'img' : undefined}>
      {title && <title>{title}</title>}
      <path d={P[name] || P.info} />
    </svg>
  );
}

// ── buttons / inputs ────────────────────────────────────────────────────────
type BtnProps = JSX.HTMLAttributes<HTMLButtonElement> & {
  icon?: string; kind?: 'primary' | 'ghost' | 'danger' | 'default'; small?: boolean; disabled?: boolean;
  type?: 'button' | 'submit';
};

export function Btn({ icon, kind = 'default', small, children, class: cls, ...rest }: BtnProps) {
  return (
    <button type="button" {...rest} class={`btn btn-${kind}${small ? ' btn-sm' : ''}${cls ? ' ' + cls : ''}`}>
      {icon && <Icon name={icon} size={small ? 14 : 16} />}
      {children && <span>{children}</span>}
    </button>
  );
}

export function IconBtn({ icon, label, ...rest }: BtnProps & { label: string }) {
  return (
    <button type="button" {...rest} class={`icon-btn ${rest.class || ''}`} aria-label={label} title={label}>
      <Icon name={icon || 'info'} size={15} />
    </button>
  );
}

export function Segmented<T extends string | number>({ value, options, onChange, disabled, label }: {
  value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; disabled?: boolean; label: string;
}) {
  return (
    <div class={`seg${disabled ? ' is-disabled' : ''}`} role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button type="button" role="radio" aria-checked={o.value === value} disabled={disabled}
          class={o.value === value ? 'on' : ''} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  );
}

export function Field({ label, hint, children, wide }: { label: string; hint?: ComponentChildren; children: ComponentChildren; wide?: boolean }) {
  return (
    <label class={`field${wide ? ' wide' : ''}`}>
      <span class="field-label">{label}</span>
      {children}
      {hint && <span class="field-hint">{hint}</span>}
    </label>
  );
}

export function Toggle({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button type="button" role="switch" aria-checked={checked} disabled={disabled} class={`toggle${checked ? ' on' : ''}`}
      onClick={() => onChange(!checked)}>
      <span class="toggle-track"><span class="toggle-knob" /></span>
      <span>{label}</span>
    </button>
  );
}

export function Card({ title, icon, actions, children, class: cls, sub }: {
  title?: ComponentChildren; icon?: string; actions?: ComponentChildren; children?: ComponentChildren; class?: string; sub?: ComponentChildren;
}) {
  return (
    <section class={`card${cls ? ' ' + cls : ''}`}>
      {(title || actions) && (
        <header class="card-head">
          <div class="card-title">
            {icon && <span class="card-ic"><Icon name={icon} size={16} /></span>}
            <div>
              <h2>{title}</h2>
              {sub && <div class="card-sub">{sub}</div>}
            </div>
          </div>
          {actions && <div class="card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Empty({ icon = 'info', title, children }: { icon?: string; title: string; children?: ComponentChildren }) {
  return (
    <div class="empty">
      <span class="empty-ic"><Icon name={icon} size={28} /></span>
      <strong>{title}</strong>
      {children && <p>{children}</p>}
    </div>
  );
}

export function Badge({ children, tone = 'dim' }: { children: ComponentChildren; tone?: 'dim' | 'ok' | 'warn' | 'crit' | 'accent' }) {
  return <span class={`badge badge-${tone}`}>{children}</span>;
}

export function Dot({ state }: { state: 'ok' | 'warn' | 'crit' | 'off' }) {
  return <span class={`dot dot-${state}`} aria-hidden="true" />;
}

// ── ring gauge ──────────────────────────────────────────────────────────────
export function Ring({ frac, color, size = 64, stroke = 7, children }: {
  frac: number | null; color: string; size?: number; stroke?: number; children?: ComponentChildren;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const f = frac == null || isNaN(frac) ? 0 : Math.max(0, Math.min(1, frac));
  return (
    <div class="ring" style={{ width: size + 'px', height: size + 'px' }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#2a3340" stroke-width={stroke} />
        {f > 0 && <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} stroke-width={stroke}
          stroke-linecap="round" stroke-dasharray={`${c * f} ${c}`} transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: 'stroke-dasharray .5s ease, stroke .5s' }} />}
      </svg>
      <div class="ring-in">{children}</div>
    </div>
  );
}

export function Spark({ data, color, w = 120, h = 28 }: { data: number[]; color: string; w?: number; h?: number }) {
  if (data.length < 2) return <svg class="spark" width={w} height={h} aria-hidden="true" />;
  const lo = Math.min(...data), hi = Math.max(...data);
  const pts = data.map((v, i) => `${(i * w) / (data.length - 1)},${h - 2 - ((v - lo) / (hi - lo || 1)) * (h - 4)}`);
  return (
    <svg class="spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
      <polygon points={`0,${h} ${pts.join(' ')} ${w},${h}`} fill={color} opacity="0.12" />
      <polyline points={pts.join(' ')} fill="none" stroke={color} stroke-width="1.6" stroke-linejoin="round" />
    </svg>
  );
}

// ── images fetched with the token header ───────────────────────────────────
const thumbCache = new Map<string, Promise<string>>();

/** Cached server-rendered preview (object URL). Key must capture every input. */
export function cachedPreview(key: string, req: Json): Promise<string> {
  let p = thumbCache.get(key);
  if (!p) {
    p = previewUrl(req);
    p.catch(() => thumbCache.delete(key));
    thumbCache.set(key, p);
  }
  return p;
}

export function cachedImage(path: string): Promise<string> {
  let p = thumbCache.get('GET ' + path);
  if (!p) {
    p = imageUrl(path);
    p.catch(() => thumbCache.delete('GET ' + path));
    thumbCache.set('GET ' + path, p);
  }
  return p;
}

export function dropCached(prefix: string) {
  for (const k of [...thumbCache.keys()]) if (k.startsWith(prefix)) thumbCache.delete(k);
}

/** Lazy thumbnail: loads when scrolled into view. */
export function Thumb({ load, cacheKey, alt, class: cls, ratio = '4 / 3' }: {
  load: () => Promise<string>; cacheKey: string; alt: string; class?: string; ratio?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [src, setSrc] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [vis, setVis] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (!('IntersectionObserver' in window)) { setVis(true); return; }
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { setVis(true); io.disconnect(); } }, { rootMargin: '200px' });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  useEffect(() => {
    if (!vis) return;
    let alive = true;
    setErr(null);
    load().then((u) => alive && setSrc(u)).catch((e) => alive && setErr(String(e.message || e)));
    return () => { alive = false; };
  }, [vis, cacheKey]);
  return (
    <div ref={ref} class={`thumb${cls ? ' ' + cls : ''}`} style={{ aspectRatio: ratio }}>
      {src ? <img src={src} alt={alt} draggable={false} /> : err ? <span class="thumb-err" title={err}>no preview</span> : <span class="shimmer" />}
    </div>
  );
}

export function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}

export function fmt(v: unknown, digits = 0): string {
  if (v === null || v === undefined || (typeof v === 'number' && isNaN(v))) return '—';
  if (typeof v === 'number') return v.toFixed(digits);
  return String(v);
}

export function heatColor(v: number | null | undefined, lo: number, hi: number): string {
  if (v == null) return '#45a29e';
  const t = (v - lo) / (hi - lo || 1);
  return t < 0.6 ? '#45fc91' : t < 0.85 ? '#fca145' : '#fc4545';
}
