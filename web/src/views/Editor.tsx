import { useEffect, useRef, useState } from 'preact/hooks';
import { CatalogEntry, get, Pack, previewUrl, send, Theme, Widget } from '../api';
import { useAction, useStore } from '../store';
import { Badge, Btn, cachedPreview, Card, Empty, Field, Icon, IconBtn, Segmented, Thumb, Toggle, useDebounced } from '../ui';
import { duplicateTheme, hash, MarkControl, PackChips, uniqueId } from './common';
import { MediaPicker } from './Media';

// ── widget catalogue ────────────────────────────────────────────────────────
const PRESETS: { label: string; w: Widget }[] = [
  { label: 'Label text', w: { type: 'text', x: 20, y: 20, text: 'LABEL', size: 12, font: 'bold', color: 'muted', upper: true } },
  { label: 'Metric in text', w: { type: 'text', x: 20, y: 40, text: '{cpu.temp:.0f}°', size: 28, font: 'bold', color: 'text' } },
  { label: 'Number with unit', w: { type: 'number', x: 20, y: 60, metric: 'cpu.load', format: '.0f', size: 40, font: 'display', color: 'text', unit: '%', unit_size: 16, unit_dy: 20, gap: 4 } },
  { label: 'Arc gauge', w: { type: 'arc', cx: 160, cy: 120, r: 50, width: 10, metric: 'cpu.temp', min: 20, max: 100, color: 'heat' } },
  { label: 'Ring', w: { type: 'ring', cx: 160, cy: 120, r: 40, width: 10, metric: 'cpu.load', min: 0, max: 100, color: 'accent1' } },
  { label: 'Bar', w: { type: 'bar', x: 20, y: 200, w: 120, h: 8, metric: 'cpu.load', min: 0, max: 100, color: 'accent2' } },
  { label: 'Sparkline', w: { type: 'sparkline', x: 20, y: 140, w: 140, h: 40, metric: 'cpu.temp', seconds: 60, color: 'accent1' } },
  { label: 'Core grid', w: { type: 'coregrid', x: 16, y: 40, w: 288, h: 160, gap: 4, values: true, label_size: 9 } },
  { label: 'Time', w: { type: 'clock', x: 200, y: 10, format: '%H:%M', size: 20, font: 'mono', color: 'text' } },
  { label: 'Date', w: { type: 'clock', x: 200, y: 40, format: '%d/%m', size: 14, font: 'mono', color: 'muted' } },
  { label: 'Service dots', w: { type: 'dots', x: 16, y: 220, services: [], size: 10 } },
  { label: 'Panel rectangle', w: { type: 'rect', x: 10, y: 10, w: 140, h: 100, radius: 8, color: 'panel' } },
  { label: 'Image', w: { type: 'image', x: 0, y: 0, w: 64, h: 64, path: '', opacity: 1 } },
];

const TYPE_ICON: Record<string, string> = {
  text: 'font', number: 'font', arc: 'rotate', ring: 'rotate', bar: 'layers', sparkline: 'spark', coregrid: 'grid',
  clock: 'info', dots: 'check', rect: 'layers', image: 'image',
};

type FieldKind = 'num' | 'text' | 'template' | 'metric' | 'font' | 'color' | 'track' | 'anchor' | 'bool' | 'format' | 'clockfmt' | 'services' | 'path' | 'cols' | 'heat';
interface FDef { k: string; kind: FieldKind; label: string; min?: number; max?: number; step?: number; ph?: string | number; hint?: string }

const XY: FDef[] = [{ k: 'x', kind: 'num', label: 'x' }, { k: 'y', kind: 'num', label: 'y' }];
const WH: FDef[] = [{ k: 'w', kind: 'num', label: 'Width', min: 1 }, { k: 'h', kind: 'num', label: 'Height', min: 1 }];
const RANGE: FDef[] = [{ k: 'min', kind: 'num', label: 'Min', ph: 0 }, { k: 'max', kind: 'num', label: 'Max', ph: 100 }];
const FIELDS: Record<string, FDef[]> = {
  text: [...XY, { k: 'text', kind: 'template', label: 'Text' }, { k: 'size', kind: 'num', label: 'Size', min: 4, max: 200, ph: 12 },
    { k: 'font', kind: 'font', label: 'Font' }, { k: 'color', kind: 'color', label: 'Colour' }, { k: 'anchor', kind: 'anchor', label: 'Anchor' },
    { k: 'upper', kind: 'bool', label: 'Upper case' }, { k: 'metric', kind: 'metric', label: 'Metric for heat colour', hint: 'Only used when the colour is heat' }, { k: 'heat', kind: 'heat', label: 'Heat range' },
    { k: 'avoid_mark', kind: 'bool', label: 'Move aside for a corner mark' }],
  number: [...XY, { k: 'metric', kind: 'metric', label: 'Metric' }, { k: 'format', kind: 'format', label: 'Format', ph: '.0f' },
    { k: 'size', kind: 'num', label: 'Size', min: 4, max: 300, ph: 40 }, { k: 'font', kind: 'font', label: 'Font' }, { k: 'color', kind: 'color', label: 'Colour' },
    { k: 'heat', kind: 'heat', label: 'Heat range' },
    { k: 'unit', kind: 'text', label: 'Unit', ph: 'W' }, { k: 'unit_size', kind: 'num', label: 'Unit size', ph: 16 }, { k: 'unit_font', kind: 'font', label: 'Unit font' },
    { k: 'unit_color', kind: 'color', label: 'Unit colour' }, { k: 'unit_dy', kind: 'num', label: 'Unit y offset', ph: 0 }, { k: 'gap', kind: 'num', label: 'Unit gap', ph: 4 },
    { k: 'avoid_mark', kind: 'bool', label: 'Move aside for a corner mark' }],
  arc: [{ k: 'cx', kind: 'num', label: 'Centre x' }, { k: 'cy', kind: 'num', label: 'Centre y' }, { k: 'r', kind: 'num', label: 'Radius', min: 1, ph: 40 },
    { k: 'width', kind: 'num', label: 'Stroke', min: 1, ph: 12 }, { k: 'metric', kind: 'metric', label: 'Metric' }, ...RANGE,
    { k: 'start', kind: 'num', label: 'Start angle', ph: 135 }, { k: 'sweep', kind: 'num', label: 'Sweep', ph: 270 },
    { k: 'color', kind: 'color', label: 'Colour' }, { k: 'heat', kind: 'heat', label: 'Heat range' }, { k: 'track', kind: 'track', label: 'Track colour' }],
  ring: [{ k: 'cx', kind: 'num', label: 'Centre x' }, { k: 'cy', kind: 'num', label: 'Centre y' }, { k: 'r', kind: 'num', label: 'Radius', min: 1, ph: 40 },
    { k: 'width', kind: 'num', label: 'Stroke', min: 1, ph: 12 }, { k: 'metric', kind: 'metric', label: 'Metric' }, ...RANGE,
    { k: 'color', kind: 'color', label: 'Colour' }, { k: 'heat', kind: 'heat', label: 'Heat range' }, { k: 'track', kind: 'track', label: 'Track colour' }],
  bar: [...XY, ...WH, { k: 'metric', kind: 'metric', label: 'Metric' }, ...RANGE, { k: 'color', kind: 'color', label: 'Colour' },
    { k: 'heat', kind: 'heat', label: 'Heat range' }, { k: 'track', kind: 'track', label: 'Track colour' }, { k: 'radius', kind: 'num', label: 'Corner radius', ph: 3 },
    { k: 'avoid_mark', kind: 'bool', label: 'Move aside for a corner mark' }],
  sparkline: [...XY, ...WH, { k: 'metric', kind: 'metric', label: 'Metric' }, { k: 'seconds', kind: 'num', label: 'Seconds shown', min: 5, max: 600, ph: 60 },
    { k: 'min', kind: 'num', label: 'Floor (min)', hint: 'Optional lower bound of the scale' },
    { k: 'color', kind: 'color', label: 'Colour' }, { k: 'heat', kind: 'heat', label: 'Heat range' }, { k: 'fill', kind: 'bool', label: 'Fill under line' }, { k: 'dot', kind: 'bool', label: 'End dot' }],
  coregrid: [...XY, ...WH, { k: 'cols', kind: 'cols', label: 'Columns' }, { k: 'gap', kind: 'num', label: 'Gap', ph: 4 },
    { k: 'values', kind: 'bool', label: 'Show values' }, { k: 'label_size', kind: 'num', label: 'Label size', ph: 9 }],
  clock: [...XY, { k: 'format', kind: 'clockfmt', label: 'Format' }, { k: 'size', kind: 'num', label: 'Size', min: 4, max: 200, ph: 13 },
    { k: 'font', kind: 'font', label: 'Font' }, { k: 'color', kind: 'color', label: 'Colour' }, { k: 'anchor', kind: 'anchor', label: 'Anchor' }, { k: 'upper', kind: 'bool', label: 'Upper case' }],
  dots: [...XY, { k: 'services', kind: 'services', label: 'Services' }, { k: 'size', kind: 'num', label: 'Size', ph: 10 }],
  rect: [...XY, ...WH, { k: 'radius', kind: 'num', label: 'Corner radius', ph: 6 }, { k: 'color', kind: 'color', label: 'Colour' }],
  image: [...XY, ...WH, { k: 'path', kind: 'path', label: 'Image' }, { k: 'opacity', kind: 'num', label: 'Opacity', min: 0, max: 1, step: 0.05, ph: 1 }],
};
const DEFAULT_BOOL: Record<string, boolean> = { fill: true, dot: true, values: true };
const ROLES = ['text', 'muted', 'ink', 'panel', 'line', 'accent1', 'accent2', 'accent3', 'ok', 'warn', 'hot'];
const ANCHORS = ['la', 'ma', 'ra', 'lm', 'mm', 'rm', 'ls', 'ms', 'rs', 'lb', 'mb', 'rb'];
const FONTS = ['display', 'bold', 'body', 'mono'];

// ── geometry ────────────────────────────────────────────────────────────────
interface Box { x: number; y: number; w: number; h: number; kx: string; ky: string }

function textW(s: string, size: number) {
  const plain = s.replace(/\{[^}]*\}/g, '000');
  return Math.max(size * 0.6, plain.length * size * 0.58);
}

function anchorBox(x: number, y: number, w: number, h: number, anchor = 'la'): Box {
  const ha = anchor[0], va = anchor[1] || 'a';
  const bx = ha === 'm' ? x - w / 2 : ha === 'r' ? x - w : x;
  const by = va === 'm' ? y - h / 2 : va === 's' || va === 'b' || va === 'd' ? y - h * 0.85 : y;
  return { x: bx, y: by, w, h, kx: 'x', ky: 'y' };
}

function box(w: Widget): Box {
  const n = (k: string, d: number) => (typeof w[k] === 'number' ? w[k] : d);
  switch (w.type) {
    case 'arc': case 'ring': {
      const r = n('r', 40), sw = n('width', 12);
      return { x: n('cx', 0) - r - sw / 2, y: n('cy', 0) - r - sw / 2, w: 2 * r + sw, h: 2 * r + sw, kx: 'cx', ky: 'cy' };
    }
    case 'bar': return { x: n('x', 0), y: n('y', 0), w: n('w', 100), h: Math.max(4, n('h', 6)), kx: 'x', ky: 'y' };
    case 'rect': return { x: n('x', 0), y: n('y', 0), w: n('w', 10), h: n('h', 10), kx: 'x', ky: 'y' };
    case 'sparkline': return { x: n('x', 0), y: n('y', 0), w: n('w', 100), h: n('h', 40), kx: 'x', ky: 'y' };
    case 'coregrid': return { x: n('x', 0), y: n('y', 0), w: n('w', 288), h: n('h', 160), kx: 'x', ky: 'y' };
    case 'image': return { x: n('x', 0), y: n('y', 0), w: n('w', 48), h: n('h', 48), kx: 'x', ky: 'y' };
    case 'number': {
      const s = n('size', 40);
      const u = w.unit ? textW(String(w.unit), n('unit_size', 16)) + n('gap', 4) : 0;
      return anchorBox(n('x', 0), n('y', 0), textW('00', s) + u, s * 1.05, 'la');
    }
    case 'clock': {
      const s = n('size', 13);
      const f = String(w.format || '%H:%M').replace(/%[A-Za-z]/g, (m) => (m === '%A' || m === '%B' ? 'Wednesday' : m === '%a' || m === '%b' ? 'Wed' : m === '%Y' ? '2026' : '00'));
      return anchorBox(n('x', 0), n('y', 0), textW(f, s), s * 1.1, w.anchor);
    }
    case 'dots': {
      const s = n('size', 10);
      const names: string[] = w.services || [];
      const width = names.reduce((a, nm) => a + s * 0.8 + 4 + textW(nm, s) + 10, 0) || s * 4;
      return { x: n('x', 0), y: n('y', 0), w: width, h: s * 1.3, kx: 'x', ky: 'y' };
    }
    default: {
      const s = n('size', 12);
      return anchorBox(n('x', 0), n('y', 0), textW(String(w.text ?? ''), s), s * 1.1, w.anchor);
    }
  }
}

function summary(w: Widget): string {
  if (w.type === 'text') return String(w.text || '').slice(0, 28) || '(empty text)';
  if (w.type === 'clock') return w.format || '%H:%M';
  if (w.type === 'dots') return (w.services || []).join(', ') || 'no services';
  if (w.type === 'rect') return `${w.w ?? 10}x${w.h ?? 10} ${w.color || 'panel'}`;
  if (w.type === 'image') return (w.path || 'no image').split('/').pop();
  if (w.type === 'coregrid') return 'per-thread load';
  return w.metric || 'no metric';
}

// ── property editors ────────────────────────────────────────────────────────
function NumIn({ value, onChange, min, max, step, ph, label }: { value: any; onChange: (v: number | undefined) => void; min?: number; max?: number; step?: number; ph?: string | number; label?: string }) {
  return (
    <input class="input" type="number" inputMode="decimal" aria-label={label} value={value ?? ''} placeholder={ph === undefined ? '' : String(ph)} min={min} max={max} step={step ?? 'any'}
      onInput={(e) => { const s = (e.target as HTMLInputElement).value; const v = parseFloat(s); onChange(s === '' || isNaN(v) ? undefined : v); }} />
  );
}

function ColorIn({ value, onChange, pack, allowHeat, label, def }: { value?: string; onChange: (v: string | undefined) => void; pack?: Pack; allowHeat?: boolean; label: string; def: string }) {
  const v = value ?? '';
  const isHex = v.startsWith('#');
  const sel = isHex ? 'custom' : v;
  const swatch = isHex ? v : v === 'heat' ? 'linear-gradient(90deg,#45fc91,#fca145,#fc4545)' : pack?.colors[v || def] || '#888';
  return (
    <div class="color-in">
      <span class="color-sw" style={{ background: swatch }} />
      <select class="input" aria-label={label} value={sel} onChange={(e) => {
        const s = (e.target as HTMLSelectElement).value;
        onChange(s === '' ? undefined : s === 'custom' ? (pack?.colors[v || def] || '#66fcf1') : s);
      }}>
        <option value="">default ({def})</option>
        {ROLES.map((r) => <option value={r}>{r}</option>)}
        {allowHeat && <option value="heat">heat (ok to hot)</option>}
        <option value="custom">custom hex</option>
      </select>
      {isHex && <input type="color" aria-label={label + ' hex'} value={v.length === 7 ? v : '#66fcf1'} onInput={(e) => onChange((e.target as HTMLInputElement).value)} />}
    </div>
  );
}

function MetricIn({ value, onChange, catalog, label }: { value?: string; onChange: (v: string | undefined) => void; catalog: Record<string, CatalogEntry>; label: string }) {
  return (
    <select class="input" aria-label={label} value={value || ''} onChange={(e) => onChange((e.target as HTMLSelectElement).value || undefined)}>
      <option value="">(none)</option>
      {Object.entries(catalog).map(([id, c]) => <option value={id}>{c.label} ({id}){c.requires ? ` · needs ${c.requires}` : ''}</option>)}
      {value && !catalog[value] && <option value={value}>{value}</option>}
    </select>
  );
}

function TemplateIn({ value, onChange, catalog }: { value: string; onChange: (v: string) => void; catalog: Record<string, CatalogEntry> }) {
  const ref = useRef<HTMLInputElement>(null);
  const insert = (id: string) => {
    if (!id) return;
    const el = ref.current;
    const tok = `{${id}${['cpu.freq', 'gpu.clock', 'gpu.vram_used', 'ram.used'].includes(id) ? ':.1f' : catalog[id]?.unit ? ':.0f' : ''}}`;
    const s = value || '';
    const at = el?.selectionStart ?? s.length;
    onChange(s.slice(0, at) + tok + s.slice(at));
  };
  return (
    <div class="tpl">
      <input ref={ref} class="input mono" value={value} aria-label="Text template" onInput={(e) => onChange((e.target as HTMLInputElement).value)} />
      <select class="input" aria-label="Insert metric token" value="" onChange={(e) => { insert((e.target as HTMLSelectElement).value); (e.target as HTMLSelectElement).value = ''; }}>
        <option value="">Insert metric…</option>
        {Object.entries(catalog).filter(([id]) => id !== 'cpu.cores').map(([id, c]) => <option value={id}>{c.label} {c.unit && `(${c.unit})`}</option>)}
      </select>
      <span class="field-hint">Tokens: <code>{'{cpu.temp}'}</code>, <code>{'{cpu.temp:.0f}'}</code> (Python format), <code>{'{gpu.power@peak:.0f}'}</code> for the recent peak. Missing values show as an em dash.</span>
    </div>
  );
}

function WidgetProps({ w, onChange, catalog, pack }: { w: Widget; onChange: (w: Widget) => void; catalog: Record<string, CatalogEntry>; pack?: Pack }) {
  const set = (k: string, v: any) => {
    const n = { ...w };
    if (v === undefined || v === '' || (Array.isArray(v) && k !== 'services' && !v.length)) delete n[k];
    else n[k] = v;
    onChange(n);
  };
  const defs = FIELDS[w.type] || XY;
  const catHeat = catalog[w.metric || '']?.heat;
  return (
    <div class="props">
      {defs.map((f) => {
        const v = w[f.k];
        switch (f.kind) {
          case 'num': return <Field label={f.label} hint={f.hint}><NumIn label={f.label} value={v} min={f.min} max={f.max} step={f.step} ph={f.ph} onChange={(x) => set(f.k, x)} /></Field>;
          case 'text': return <Field label={f.label}><input class="input" value={v ?? ''} placeholder={String(f.ph ?? '')} onInput={(e) => set(f.k, (e.target as HTMLInputElement).value)} /></Field>;
          case 'template': return <Field label={f.label} wide><TemplateIn value={v ?? ''} onChange={(x) => set(f.k, x)} catalog={catalog} /></Field>;
          case 'metric': return <Field label={f.label} hint={f.hint} wide><MetricIn label={f.label} value={v} onChange={(x) => {
            const n = { ...w };
            if (x) n.metric = x; else delete n.metric;
            if (x && w.type === 'number' && !w.unit && catalog[x]?.unit) n.unit = catalog[x].unit;
            onChange(n);
          }} catalog={catalog} /></Field>;
          case 'font': return <Field label={f.label}><select class="input" value={v ?? ''} onChange={(e) => set(f.k, (e.target as HTMLSelectElement).value)}>
            <option value="">default</option>{FONTS.map((x) => <option value={x}>{x}</option>)}</select></Field>;
          case 'color': return <Field label={f.label}><ColorIn label={f.label} value={v} pack={pack} allowHeat onChange={(x) => set(f.k, x)} def={w.type === 'rect' ? 'panel' : ['arc', 'ring', 'bar', 'sparkline'].includes(w.type) ? 'accent1' : 'text'} /></Field>;
          case 'track': return <Field label={f.label}><ColorIn label={f.label} value={v} pack={pack} onChange={(x) => set(f.k, x)} def="line" /></Field>;
          case 'heat': {
            const colorHeat = w.color === 'heat' || w.unit_color === 'heat';
            if (!colorHeat) return null;
            const hv = Array.isArray(v) ? (v as [number, number]) : undefined;
            return (
              <Field label={f.label} hint={catHeat ? `Default for this metric: ${catHeat[0]} to ${catHeat[1]}` : 'Low value is ok colour, high is hot'}>
                <div class="pair">
                  <NumIn label="Heat low" value={hv?.[0]} ph={catHeat?.[0] ?? 0} onChange={(x) => set('heat', x === undefined && hv?.[1] === undefined ? undefined : [x ?? catHeat?.[0] ?? 0, hv?.[1] ?? catHeat?.[1] ?? 100])} />
                  <NumIn label="Heat high" value={hv?.[1]} ph={catHeat?.[1] ?? 100} onChange={(x) => set('heat', x === undefined && hv?.[0] === undefined ? undefined : [hv?.[0] ?? catHeat?.[0] ?? 0, x ?? catHeat?.[1] ?? 100])} />
                </div>
              </Field>
            );
          }
          case 'anchor': return <Field label={f.label} hint="Left/middle/right + ascender/middle/baseline"><select class="input" value={v ?? 'la'} onChange={(e) => set(f.k, (e.target as HTMLSelectElement).value)}>
            {ANCHORS.map((a) => <option value={a}>{a}</option>)}</select></Field>;
          case 'bool': return <div class="field"><Toggle label={f.label} checked={v ?? DEFAULT_BOOL[f.k] ?? false} onChange={(x) => set(f.k, x)} /></div>;
          case 'format': return <Field label={f.label} hint="Python format spec: .0f, .1f, .2f"><input class="input mono" value={v ?? ''} placeholder=".0f" onInput={(e) => set(f.k, (e.target as HTMLInputElement).value)} /></Field>;
          case 'clockfmt': return <Field label={f.label} hint="strftime: %H:%M time, %d/%m date, %a weekday"><div class="tpl">
            <input class="input mono" value={v ?? ''} placeholder="%H:%M" onInput={(e) => set(f.k, (e.target as HTMLInputElement).value)} />
            <select class="input" aria-label="Clock format presets" value="" onChange={(e) => { const s = (e.target as HTMLSelectElement).value; if (s) set(f.k, s); }}>
              <option value="">Presets…</option>
              {['%H:%M', '%H:%M:%S', '%I:%M %p', '%d/%m', '%a %d %b', '%Y-%m-%d', '%A'].map((p) => <option value={p}>{p}</option>)}
            </select></div></Field>;
          case 'services': return <Field label={f.label} hint="Comma separated; names from the service config extras.services"><input class="input" value={(v || []).join(', ')}
            onInput={(e) => set(f.k, (e.target as HTMLInputElement).value.split(',').map((s) => s.trim()).filter(Boolean))} /></Field>;
          case 'cols': return <Field label={f.label} hint="auto picks the best fit"><input class="input" value={v ?? 'auto'} onInput={(e) => {
            const s = (e.target as HTMLInputElement).value.trim(); set(f.k, s === '' || s === 'auto' ? undefined : /^\d+$/.test(s) ? parseInt(s) : s);
          }} /></Field>;
          case 'path': return <Field label={f.label} wide hint="Absolute path of an image on the node (image widgets are not resolved against the media folder)">
            <input class="input mono" value={v ?? ''} placeholder="/path/to/image.png" onInput={(e) => set(f.k, (e.target as HTMLInputElement).value)} /></Field>;
        }
        return null;
      })}
      <Field label="Show when"><select class="input" value={w.requires || ''} onChange={(e) => set('requires', (e.target as HTMLSelectElement).value)}>
        <option value="">always</option><option value="gpu">node has a GPU</option><option value="!gpu">node has no GPU</option>
        <option value="rapl">CPU power readable</option><option value="!rapl">CPU power not readable</option>
        <option value="llm">LLM metrics configured</option><option value="!llm">no LLM metrics</option></select></Field>
    </div>
  );
}

// ── canvas ──────────────────────────────────────────────────────────────────
function Canvas({ doc, sel, setSel, onMove, previewSrc, previewErr, loading, snap, grid, zoom }: {
  doc: Theme; sel: number | null; setSel: (i: number | null) => void; onMove: (i: number, x: number, y: number, commit: boolean) => void;
  previewSrc: string | null; previewErr: string | null; loading: boolean; snap: number; grid: boolean; zoom: number;
}) {
  const [bw, bh] = doc.base || [320, 240];
  const caps = (useStore().metrics?.capabilities || {}) as Record<string, unknown>;
  const unmet = (w: Widget) => !!w.requires && !!caps[String(w.requires).replace('!', '')] === String(w.requires).startsWith('!');
  const ref = useRef<HTMLDivElement>(null);
  const drag = useRef<{ i: number; sx: number; sy: number; ox: number; oy: number; b: Box; scale: number; moved: boolean } | null>(null);
  // Keep the whole widget box on the canvas (or at least its anchor when it is bigger).
  const clamp = (b: Box, ox: number, oy: number, kx: number, ky: number): [number, number] => {
    const offx = b.x - ox, offy = b.y - oy;
    const cx = b.w <= bw ? Math.min(Math.max(kx, -offx), bw - b.w - offx) : Math.min(Math.max(kx, 0), bw);
    const cy = b.h <= bh ? Math.min(Math.max(ky, -offy), bh - b.h - offy) : Math.min(Math.max(ky, 0), bh);
    return [Math.round(cx), Math.round(cy)];
  };
  const down = (e: PointerEvent, i: number) => {
    e.preventDefault(); e.stopPropagation();
    setSel(i);
    const w = doc.widgets[i], b = box(w);
    const scale = (ref.current!.getBoundingClientRect().width || bw) / bw;
    drag.current = { i, sx: e.clientX, sy: e.clientY, ox: w[b.kx] ?? 0, oy: w[b.ky] ?? 0, b, scale, moved: false };
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  };
  const move = (e: PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    let nx = d.ox + (e.clientX - d.sx) / d.scale, ny = d.oy + (e.clientY - d.sy) / d.scale;
    if (snap > 1 && !e.altKey) { nx = Math.round(nx / snap) * snap; ny = Math.round(ny / snap) * snap; }
    const [cx, cy] = clamp(d.b, d.ox, d.oy, nx, ny);
    d.moved = true;
    onMove(d.i, cx, cy, false);
  };
  const up = () => {
    const d = drag.current;
    drag.current = null;
    if (d?.moved) onMove(d.i, doc.widgets[d.i][d.b.kx], doc.widgets[d.i][d.b.ky], true);
  };
  const key = (e: KeyboardEvent, i: number) => {
    const step = e.shiftKey ? 10 : 1;
    const dx = e.key === 'ArrowLeft' ? -step : e.key === 'ArrowRight' ? step : 0;
    const dy = e.key === 'ArrowUp' ? -step : e.key === 'ArrowDown' ? step : 0;
    if (!dx && !dy) return;
    e.preventDefault();
    const w = doc.widgets[i], b = box(w), ox = w[b.kx] ?? 0, oy = w[b.ky] ?? 0;
    const [cx, cy] = clamp(b, ox, oy, ox + dx, oy + dy);
    onMove(i, cx, cy, true);
  };
  const dev = doc.device || {};
  return (
    <div class="canvas-wrap">
      <div class="canvas" ref={ref} style={{ width: `min(100%, ${bw * zoom}px)`, aspectRatio: `${bw} / ${bh}` }}
        onPointerDown={() => setSel(null)} onPointerMove={move as any} onPointerUp={up} onPointerCancel={up}>
        {previewSrc && <img class="canvas-img" src={previewSrc} alt="Rendered preview of the theme" draggable={false} />}
        {grid && <div class="canvas-grid" style={{ backgroundSize: `${(snap / bw) * 100}% ${(snap / bh) * 100}%` }} />}
        {doc.widgets.map((w, i) => {
          const b = box(w);
          return (
            <button type="button" class={`wbox${sel === i ? ' on' : ''}${w.hidden ? ' is-hidden' : ''}${unmet(w) ? ' is-unmet' : ''}`}
              title={unmet(w) ? `Not drawn on this node (needs ${w.requires})` : undefined}
              style={{ left: `${(b.x / bw) * 100}%`, top: `${(b.y / bh) * 100}%`, width: `${(b.w / bw) * 100}%`, height: `${(b.h / bh) * 100}%` }}
              aria-label={`${w.type} ${summary(w)} at ${w[b.kx] ?? 0}, ${w[b.ky] ?? 0}. Arrow keys move it.`}
              onPointerDown={(e) => down(e as unknown as PointerEvent, i)} onFocus={() => setSel(i)} onKeyDown={(e) => key(e as unknown as KeyboardEvent, i)}>
              {sel === i && <span class="wbox-tag">{w.type} {Math.round(w[b.kx] ?? 0)},{Math.round(w[b.ky] ?? 0)}</span>}
            </button>
          );
        })}
        {loading && <span class="canvas-busy" aria-hidden="true" />}
      </div>
      {previewErr && <div class="inline-err"><Icon name="info" size={14} /> {previewErr}</div>}
      <div class="canvas-foot muted small">
        Base canvas {bw}x{bh}, scaled to the panel. Drag to move (Alt disables snapping), arrow keys nudge 1 px, Shift+arrow 10 px.
        {dev.rotation ? ` Shown unrotated; the panel rotates it ${dev.rotation}°.` : ''}
      </div>
    </div>
  );
}

// ── theme settings ──────────────────────────────────────────────────────────
function ThemeSettings({ doc, set, packs }: { doc: Theme; set: (patch: Partial<Theme>) => void; packs: Pack[] }) {
  const pack = packs.find((p) => p.id === (doc.pack || 'slate'));
  const bg = doc.background || { type: 'color' };
  const fg = doc.foreground || null;
  const dev = doc.device || {};
  const mark = { mode: doc.mark?.mode || 'none', opacity: doc.mark?.opacity ?? 0.1, corner: doc.mark?.corner, variant: doc.mark?.variant };
  const kindFor: Record<string, string[]> = { image: ['image'], gif: ['gif'], video: ['video'], collection: ['collection'] };
  return (
    <div class="settings">
      <section class="set-sec">
        <h4>Pack</h4>
        <PackChips packs={packs} value={doc.pack || 'slate'} onChange={(p) => set({ pack: p })} />
      </section>
      <section class="set-sec">
        <h4>Brand mark</h4>
        <MarkControl pack={pack} value={mark} onChange={(m) => set({ mark: { ...doc.mark, mode: m.mode, opacity: m.opacity } })} />
        {pack?.mark ? (
          <div class="props">
            <Field label="Corner"><select class="input" value={mark.corner || doc.mark_corner || 'br'} onChange={(e) => set({ mark: { ...doc.mark, mode: mark.mode, corner: (e.target as HTMLSelectElement).value } })}>
              <option value="br">bottom right</option><option value="bl">bottom left</option><option value="tr">top right</option><option value="tl">top left</option></select></Field>
            <Field label="Variant"><select class="input" value={mark.variant || 'auto'} onChange={(e) => set({ mark: { ...doc.mark, mode: mark.mode, variant: (e.target as HTMLSelectElement).value } })}>
              <option value="auto">auto (from ground)</option><option value="deep">deep</option><option value="ivory">ivory</option></select></Field>
          </div>
        ) : <p class="muted small">The {pack?.name || 'selected'} pack has no brand mark, so mark settings do not apply.</p>}
      </section>
      <section class="set-sec">
        <h4>Background</h4>
        <Segmented label="Background type" value={bg.type} onChange={(t) => set({ background: t === 'color' ? { type: 'color' } : { type: t, path: kindFor[t].includes(bg.type) ? bg.path : undefined, ...(t === 'collection' ? { interval: bg.interval ?? 2 } : {}) } })}
          options={[{ value: 'color', label: 'Colour' }, { value: 'image', label: 'Image' }, { value: 'gif', label: 'GIF' }, { value: 'video', label: 'Video' }, { value: 'collection', label: 'Slides' }]} />
        {bg.type === 'color' ? (
          <p class="muted small">Plain pack ground colour (<span class="inline-sw" style={{ background: pack?.colors.ink }} /> ink).</p>
        ) : (
          <>
            {!bg.path && <div class="inline-err">Pick or upload a {bg.type} below; a theme with an empty background path cannot be saved.</div>}
            <MediaPicker kinds={kindFor[bg.type]} value={bg.path} multiple={bg.type === 'collection'}
              accept={bg.type === 'gif' ? '.gif' : bg.type === 'video' ? '.mp4,.avi,.mkv,.mov,.webm,.flv,.wmv,.m4v' : '.png,.jpg,.jpeg,.bmp,.webp,.tiff'}
              onChange={(p) => set({ background: { ...bg, path: p || undefined } })} />
            {bg.type === 'collection' && (
              <Field label="Seconds per image"><NumIn label="Seconds per image" value={bg.interval} min={0.5} step={0.5} ph={2} onChange={(x) => set({ background: { ...bg, interval: x } })} /></Field>
            )}
          </>
        )}
      </section>
      <section class="set-sec">
        <h4>Foreground overlay</h4>
        <p class="muted small">A transparent PNG drawn over the widgets at its own size.</p>
        <MediaPicker kinds={['image', 'gif']} value={fg?.path} allowNone noneLabel="No foreground" accept=".png,.gif,.webp"
          onChange={(p) => set({ foreground: p ? { alpha: 1, x: 0, y: 0, ...(fg || {}), path: p } : null })} />
        {fg && (
          <div class="props">
            <Field label={`Opacity ${Math.round((fg.alpha ?? 1) * 100)}%`} wide>
              <input type="range" class="range" min={0} max={1} step={0.01} value={fg.alpha ?? 1} onInput={(e) => set({ foreground: { ...fg, alpha: parseFloat((e.target as HTMLInputElement).value) } })} />
            </Field>
            <Field label="x (panel px)"><NumIn label="Foreground x" value={fg.x} ph={0} onChange={(x) => set({ foreground: { ...fg, x: x ?? 0 } })} /></Field>
            <Field label="y (panel px)"><NumIn label="Foreground y" value={fg.y} ph={0} onChange={(y) => set({ foreground: { ...fg, y: y ?? 0 } })} /></Field>
          </div>
        )}
      </section>
      <section class="set-sec">
        <h4>Device</h4>
        <Field label="Rotation"><Segmented label="Rotation" value={dev.rotation ?? 0} onChange={(r) => set({ device: { ...dev, rotation: r } })}
          options={[0, 90, 180, 270].map((r) => ({ value: r, label: `${r}°` }))} /></Field>
        <Field label={`Brightness ${dev.brightness ?? 100}%`} wide>
          <input type="range" class="range" min={5} max={100} step={1} value={dev.brightness ?? 100} onInput={(e) => set({ device: { ...dev, brightness: parseInt((e.target as HTMLInputElement).value) } })} />
        </Field>
        <Field label="Refresh (seconds per frame)" hint="0.1 to 10; animated backgrounds play at their own rate">
          <NumIn label="Refresh seconds" value={dev.refresh} min={0.1} max={10} step={0.1} ph={1} onChange={(x) => set({ device: { ...dev, refresh: x } })} />
        </Field>
      </section>
    </div>
  );
}

// ── start screen ────────────────────────────────────────────────────────────
function StartScreen() {
  const store = useStore();
  const { themes, designs, packs, go, reload, prompt } = store;
  const act = useAction();
  const [design, setDesign] = useState('');
  const [pack, setPack] = useState('slate');
  useEffect(() => { if (!design && designs.length) setDesign(designs[0].id); }, [designs]);
  const create = async () => {
    const d = designs.find((x) => x.id === design);
    const name = await prompt('Name the new theme', `${d?.name || 'My'} theme`, undefined, 'Create');
    if (!name) return;
    const id = await act(() => duplicateTheme(design, name, store, { pack }), `Created theme "${name}"`);
    if (id) { await reload('themes'); go('editor', id); }
  };
  return (
    <div class="stack">
      <Card title="Edit a theme" icon="edit" sub="Your themes. Built-in designs are read-only: duplicate one to edit it.">
        {themes.length === 0 ? <Empty icon="layers" title="No themes yet">Start one from a design below.</Empty> : (
          <div class="gallery gallery-sm">
            {themes.map((t) => (
              <button type="button" class="gcard gcard-btn" onClick={() => go('editor', t.id)}>
                <Thumb alt={t.name || t.id} cacheKey={`t|${t.id}|${hash(JSON.stringify(t))}`} load={() => cachedPreview(`t|${t.id}|${hash(JSON.stringify(t))}`, { selection: { kind: 'theme', theme: t.id } })} />
                <div class="gcard-body"><h3>{t.name || t.id}</h3><p class="gcard-desc">{t.widgets.length} widgets · {t.pack}</p></div>
              </button>
            ))}
          </div>
        )}
      </Card>
      <Card title="Start from a design" icon="plus">
        <div class="props">
          <Field label="Design" wide><select class="input" value={design} onChange={(e) => setDesign((e.target as HTMLSelectElement).value)}>
            {designs.map((d) => <option value={d.id}>{d.name} · {d.description}</option>)}</select></Field>
        </div>
        <PackChips packs={packs} value={pack} onChange={setPack} />
        <div class="row"><Btn kind="primary" icon="plus" disabled={!design} onClick={create}>Create and edit</Btn></div>
      </Card>
    </div>
  );
}

// ── editor ──────────────────────────────────────────────────────────────────
export function Editor() {
  const store = useStore();
  const { editing, status, themes, designs, packs, metrics, go, reload, confirm, prompt, toast } = store;
  const act = useAction();
  const [doc, setDoc] = useState<Theme | null>(null);
  const [saved, setSaved] = useState('');
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [panel, setPanel] = useState<'widget' | 'theme'>('widget');
  const [snap, setSnap] = useState(4);
  const [grid, setGrid] = useState(false);
  const [zoom, setZoom] = useState(2);
  const [preset, setPreset] = useState(0);
  const [apiErr, setApiErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [prev, setPrev] = useState<{ src: string | null; err: string | null; loading: boolean }>({ src: null, err: null, loading: false });
  const autoOpened = useRef(false);

  // auto-open the active user theme when the editor is opened without one
  useEffect(() => {
    if (!editing && !autoOpened.current && status?.active.kind === 'theme' && status.active.theme) {
      autoOpened.current = true;
      go('editor', status.active.theme);
    }
  }, [editing, status?.active.kind]);

  useEffect(() => {
    if (!editing) { setDoc(null); return; }
    let alive = true;
    setLoadErr(null); setSel(null); setApiErr(null);
    get<Theme>('themes/' + encodeURIComponent(editing)).then((t) => {
      if (!alive) return;
      if (designs.some((d) => d.id === editing) && !themes.some((x) => x.id === editing)) {
        setLoadErr(`"${t.name}" is a built-in design and cannot be changed. Duplicate it to edit.`);
      }
      const n: Theme = { ...t, widgets: t.widgets || [] };
      setDoc(n); setSaved(JSON.stringify(n));
    }).catch((e) => alive && setLoadErr(e.message));
    return () => { alive = false; };
  }, [editing]);

  const dirty = !!doc && JSON.stringify(doc) !== saved;
  useEffect(() => {
    if (!dirty) return;
    const h = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    addEventListener('beforeunload', h);
    return () => removeEventListener('beforeunload', h);
  }, [dirty]);

  // live preview (debounced), unrotated so the overlay lines up
  const previewDoc = useDebounced(doc, 220);
  const lastUrl = useRef<string | null>(null);
  useEffect(() => {
    if (!previewDoc) return;
    let alive = true;
    const base = previewDoc.base || [320, 240];
    const t: Theme = { ...previewDoc, device: { ...(previewDoc.device || {}), rotation: 0 } };
    setPrev((p) => ({ ...p, loading: true }));
    previewUrl({ theme: t, size: base, scale: 2 }).then((u) => {
      if (!alive) { URL.revokeObjectURL(u); return; }
      if (lastUrl.current) URL.revokeObjectURL(lastUrl.current);
      lastUrl.current = u;
      setPrev({ src: u, err: null, loading: false });
    }).catch((e) => alive && setPrev((p) => ({ ...p, err: e.message, loading: false })));
    return () => { alive = false; };
  }, [previewDoc]);

  const catalog = metrics?.catalog || {};
  const pack = packs.find((p) => p.id === (doc?.pack || 'slate'));
  const isBuiltin = !!editing && designs.some((d) => d.id === editing) && !themes.some((t) => t.id === editing);

  if (!editing) return <StartScreen />;
  if (loadErr && !doc) return <Card title="Editor" icon="edit"><div class="inline-err">{loadErr}</div><Btn onClick={() => go('editor', null)}>Back to theme list</Btn></Card>;
  if (!doc) return <Card title="Editor" icon="edit"><div class="shimmer-block" /></Card>;

  const set = (patch: Partial<Theme>) => setDoc((d) => d && ({ ...d, ...patch }));
  const setW = (i: number, w: Widget) => setDoc((d) => d && ({ ...d, widgets: d.widgets.map((x, j) => (j === i ? w : x)) }));
  const onMove = (i: number, x: number, y: number) => setDoc((d) => {
    if (!d) return d;
    const w = d.widgets[i], b = box(w);
    return { ...d, widgets: d.widgets.map((o, j) => (j === i ? { ...w, [b.kx]: x, [b.ky]: y } : o)) };
  });
  const addWidget = () => {
    const w = JSON.parse(JSON.stringify(PRESETS[preset].w));
    setDoc((d) => d && ({ ...d, widgets: [...d.widgets, w] }));
    setSel(doc.widgets.length); setPanel('widget');
  };
  const removeW = (i: number) => { setDoc((d) => d && ({ ...d, widgets: d.widgets.filter((_, j) => j !== i) })); setSel(null); };
  const moveW = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= doc.widgets.length) return;
    setDoc((d) => { if (!d) return d; const ws = [...d.widgets]; [ws[i], ws[j]] = [ws[j], ws[i]]; return { ...d, widgets: ws }; });
    setSel(j);
  };
  const dupW = (i: number) => {
    const w = { ...doc.widgets[i] }, b = box(w);
    w[b.kx] = (w[b.kx] ?? 0) + 8; w[b.ky] = (w[b.ky] ?? 0) + 8;
    setDoc((d) => d && ({ ...d, widgets: [...d.widgets.slice(0, i + 1), w, ...d.widgets.slice(i + 1)] }));
    setSel(i + 1);
  };

  const save = async (): Promise<boolean> => {
    setBusy(true); setApiErr(null);
    try {
      const out = await send<Theme>('PUT', 'themes/' + doc.id, doc);
      const n = { ...out, widgets: out.widgets || [] };
      setDoc(n); setSaved(JSON.stringify(n));
      toast(`Saved ${n.name}`, 'ok');
      reload('themes');
      return true;
    } catch (e: any) {
      setApiErr(e.message); toast(e.message, 'err');
      return false;
    } finally { setBusy(false); }
  };
  const saveAs = async () => {
    const name = await prompt('Save as a new theme', `${doc.name || doc.id} copy`, undefined, 'Save');
    if (!name) return;
    const taken = new Set([...designs.map((d) => d.id), ...themes.map((t) => t.id)]);
    const id = uniqueId(name, taken);
    setBusy(true); setApiErr(null);
    try {
      await send('PUT', 'themes/' + id, { ...doc, id, name });
      toast(`Saved as ${name}`, 'ok');
      await reload('themes');
      setSaved(JSON.stringify(doc));
      go('editor', id);
    } catch (e: any) { setApiErr(e.message); toast(e.message, 'err'); } finally { setBusy(false); }
  };
  const apply = async () => {
    if (dirty && !(await save())) return;
    setBusy(true);
    await act(async () => { await send('POST', 'apply', { kind: 'theme', theme: doc.id }); await reload('status'); }, `${doc.name} is on the panel`);
    setBusy(false);
  };
  const del = async () => {
    if (!(await confirm(`Delete "${doc.name || doc.id}"?`, 'This removes the theme file from the node.', 'Delete', true))) return;
    try {
      await send('DELETE', 'themes/' + doc.id);
      toast(`Deleted ${doc.name}`, 'ok');
      setSaved(JSON.stringify(doc));
      await reload('themes');
      go('editor', null);
    } catch (e: any) { setApiErr(e.message); toast(e.message, 'err'); }
  };
  const revert = () => { setDoc(JSON.parse(saved)); setApiErr(null); };
  const switchTheme = async (id: string) => {
    if (dirty && !(await confirm('Discard unsaved changes?', undefined, 'Discard', true))) return;
    autoOpened.current = true;
    go('editor', id || null);
  };

  const selW = sel !== null ? doc.widgets[sel] : null;
  const isActive = status?.active.kind === 'theme' && status.active.theme === doc.id;
  const tuned = Object.keys(doc.layouts || {});

  return (
    <div class="editor">
      <div class="ed-bar card">
        <div class="ed-title">
          <select class="input" aria-label="Theme being edited" value={doc.id} onChange={(e) => switchTheme((e.target as HTMLSelectElement).value)}>
            {themes.map((t) => <option value={t.id}>{t.name || t.id}</option>)}
            {!themes.some((t) => t.id === doc.id) && <option value={doc.id}>{doc.name || doc.id}</option>}
            <option value="">All themes / new…</option>
          </select>
          <input class="input ed-name" aria-label="Theme name" value={doc.name || ''} onInput={(e) => set({ name: (e.target as HTMLInputElement).value })} />
          <code class="muted hide-sm">{doc.id}</code>
          {dirty ? <Badge tone="warn">unsaved</Badge> : <Badge tone="dim">saved</Badge>}
          {isActive && <Badge tone="ok">on panel</Badge>}
        </div>
        <div class="ed-actions">
          <Btn small kind="ghost" disabled={!dirty || busy} onClick={revert}>Revert</Btn>
          <Btn small icon="save" disabled={busy || isBuiltin || !dirty} onClick={save}>Save</Btn>
          <Btn small icon="copy" disabled={busy} onClick={saveAs}>Save as new</Btn>
          <Btn small kind="primary" icon="play" disabled={busy || isBuiltin} onClick={apply}>{dirty ? 'Save & apply' : 'Apply'}</Btn>
          <Btn small kind="danger" icon="trash" disabled={busy || isBuiltin} onClick={del} aria-label="Delete theme" />
        </div>
      </div>
      {loadErr && <div class="banner banner-warn"><Icon name="info" /> {loadErr}</div>}
      {apiErr && <div class="banner banner-crit" role="alert"><Icon name="x" /> {apiErr}</div>}
      {tuned.length > 0 && (
        <div class="banner banner-warn"><Icon name="info" /> This theme has hand-tuned layouts for {tuned.join(', ')}; those panels use them instead of the widgets edited here.
          <Btn small onClick={() => set({ layouts: undefined })}>Remove tuned layouts</Btn></div>
      )}

      <div class="ed-grid">
        <Card title="Widgets" icon="layers" class="ed-list" sub={`${doc.widgets.length} on this theme, drawn top to bottom`}>
          <div class="add-row">
            <select class="input" aria-label="Widget to add" value={preset} onChange={(e) => setPreset(parseInt((e.target as HTMLSelectElement).value))}>
              {PRESETS.map((p, i) => <option value={i}>{p.label}</option>)}
            </select>
            <Btn small kind="primary" icon="plus" onClick={addWidget}>Add</Btn>
          </div>
          {doc.widgets.length === 0 ? <Empty icon="layers" title="No widgets">Add one above.</Empty> : (
            <ol class="wlist">
              {doc.widgets.map((w, i) => (
                <li class={`wrow${sel === i ? ' on' : ''}${w.hidden ? ' is-hidden' : ''}`}>
                  <button type="button" class="wrow-main" aria-pressed={sel === i} onClick={() => { setSel(i); setPanel('widget'); }}>
                    <span class="wrow-ic"><Icon name={TYPE_ICON[w.type] || 'info'} size={14} /></span>
                    <span class="wrow-txt"><strong>{w.type}</strong><span>{summary(w)}</span></span>
                    {w.requires && <Badge>{w.requires}</Badge>}
                  </button>
                  <span class="wrow-tools">
                    <IconBtn icon={w.hidden ? 'eyeoff' : 'eye'} label={w.hidden ? 'Show widget' : 'Hide widget'} onClick={() => setW(i, { ...w, hidden: w.hidden ? undefined : true })} />
                    <IconBtn icon="up" label="Move up (drawn earlier)" disabled={i === 0} onClick={() => moveW(i, -1)} />
                    <IconBtn icon="down" label="Move down (drawn later)" disabled={i === doc.widgets.length - 1} onClick={() => moveW(i, 1)} />
                    <IconBtn icon="trash" label="Remove widget" onClick={() => removeW(i)} />
                  </span>
                </li>
              ))}
            </ol>
          )}
        </Card>

        <Card title="Canvas" icon="edit" class="ed-canvas"
          actions={<>
            <Segmented label="Snap" value={snap} onChange={setSnap} options={[{ value: 1, label: 'free' }, { value: 4, label: '4px' }, { value: 8, label: '8px' }]} />
            <Toggle label="Grid" checked={grid} onChange={setGrid} />
            <Segmented label="Canvas zoom" value={zoom} onChange={setZoom} options={[{ value: 1, label: '1x' }, { value: 2, label: '2x' }, { value: 3, label: '3x' }]} />
          </>}>
          <Canvas doc={doc} sel={sel} setSel={(i) => { setSel(i); if (i !== null) setPanel('widget'); }} onMove={onMove}
            previewSrc={prev.src} previewErr={prev.err} loading={prev.loading} snap={snap} grid={grid} zoom={zoom} />
        </Card>

        <Card class="ed-props" title={
          <div class="seg seg-title" role="tablist" aria-label="Property panel">
            <button type="button" role="tab" aria-selected={panel === 'widget'} class={panel === 'widget' ? 'on' : ''} onClick={() => setPanel('widget')}>Widget</button>
            <button type="button" role="tab" aria-selected={panel === 'theme'} class={panel === 'theme' ? 'on' : ''} onClick={() => setPanel('theme')}>Look &amp; device</button>
          </div>}>
          {panel === 'theme' ? <ThemeSettings doc={doc} set={set} packs={packs} /> : selW ? (
            <>
              <div class="props-head">
                <span><Icon name={TYPE_ICON[selW.type] || 'info'} size={14} /> <strong>{selW.type}</strong> #{sel! + 1}</span>
                <span class="row">
                  <Btn small kind="ghost" icon="copy" onClick={() => dupW(sel!)}>Duplicate</Btn>
                  <Btn small kind="danger" icon="trash" onClick={() => removeW(sel!)}>Remove</Btn>
                </span>
              </div>
              <WidgetProps w={selW} onChange={(w) => setW(sel!, w)} catalog={catalog} pack={pack} />
            </>
          ) : <Empty icon="edit" title="No widget selected">Click a widget on the canvas or in the list, or switch to Look &amp; device for pack, background, foreground, rotation and brightness.</Empty>}
        </Card>
      </div>
    </div>
  );
}
