import { get, Pack, send, Selection, slug, Theme } from '../api';
import { Store } from '../store';
import { Segmented } from '../ui';

export function hash(s: string): string {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
  return (h >>> 0).toString(36);
}

export function Swatches({ pack, keys = ['ink', 'panel', 'text', 'accent1', 'accent2', 'accent3', 'ok', 'warn', 'hot'] }: { pack: Pack; keys?: string[] }) {
  return (
    <span class="swatches" aria-hidden="true">
      {keys.map((k) => <span class="sw" style={{ background: pack.colors[k] }} title={`${k} ${pack.colors[k]}`} />)}
    </span>
  );
}

export function PackChips({ packs, value, onChange, label = 'Theme pack' }: { packs: Pack[]; value: string; onChange: (id: string) => void; label?: string }) {
  return (
    <div class="chips" role="radiogroup" aria-label={label}>
      {packs.map((p) => (
        <button type="button" role="radio" aria-checked={p.id === value} class={`chip${p.id === value ? ' on' : ''}`} onClick={() => onChange(p.id)}>
          <span class="chip-ground" style={{ background: p.colors.ink, borderColor: p.colors.line }}>
            <span style={{ background: p.colors.accent1 }} /><span style={{ background: p.colors.accent2 }} /><span style={{ background: p.colors.accent3 }} />
          </span>
          <span>{p.name}</span>
          {!p.builtin && <span class="chip-tag">user</span>}
        </button>
      ))}
    </div>
  );
}

export interface MarkCfg { mode: string; opacity: number; corner?: string; variant?: string }

export function MarkControl({ pack, value, onChange, compact }: { pack?: Pack; value: MarkCfg; onChange: (m: MarkCfg) => void; compact?: boolean }) {
  const has = !!pack?.mark;
  return (
    <div class={`markctl${has ? '' : ' is-disabled'}`} title={has ? 'Brand mark from the pack' : 'This pack has no brand mark'}>
      <span class="markctl-label">Mark</span>
      <Segmented label="Mark mode" disabled={!has} value={has ? value.mode : 'none'} onChange={(mode) => onChange({ ...value, mode })}
        options={[{ value: 'none', label: 'None' }, { value: 'corner', label: 'Corner' }, { value: 'background', label: compact ? 'Bg' : 'Background' }]} />
      <input type="range" class="range" min={0.05} max={0.2} step={0.01} aria-label="Mark opacity"
        disabled={!has || value.mode !== 'background'} value={value.opacity}
        onInput={(e) => onChange({ ...value, opacity: parseFloat((e.target as HTMLInputElement).value) })} />
      <span class="markctl-val">{Math.round(value.opacity * 100)}%</span>
    </div>
  );
}

export function selLabel(sel: Selection, s: Pick<Store, 'designs' | 'themes' | 'legacy' | 'packs'>): string {
  const pk = (id?: string) => s.packs.find((p) => p.id === id)?.name || id || '';
  if (sel.kind === 'design') return `${s.designs.find((d) => d.id === sel.design)?.name || sel.design} · ${pk(sel.pack || 'slate')}`;
  if (sel.kind === 'theme') {
    const t = s.themes.find((x) => x.id === sel.theme);
    return `${t?.name || sel.theme}${sel.pack ? ' · ' + pk(sel.pack) : ''}`;
  }
  return s.legacy.find((x) => x.id === sel.theme)?.name || sel.theme || 'legacy';
}

export function selPreviewKey(sel: Selection, themes: Theme[]): string {
  const t = sel.kind === 'theme' ? themes.find((x) => x.id === sel.theme) : null;
  return 'sel|' + JSON.stringify(sel) + (t ? '|' + hash(JSON.stringify(t)) : '');
}

export function uniqueId(base: string, taken: Set<string>): string {
  let id = slug(base);
  if (!taken.has(id)) return id;
  for (let n = 2; ; n++) {
    const c = `${id.slice(0, 44)}-${n}`;
    if (!taken.has(c)) return c;
  }
}

/** Create a user theme from a design or an existing theme; returns the new id. */
export async function duplicateTheme(srcId: string, name: string, s: Pick<Store, 'designs' | 'themes'>, over: Partial<Theme> = {}): Promise<string> {
  const doc = await get<Theme>('themes/' + encodeURIComponent(srcId));
  const taken = new Set([...s.designs.map((d) => d.id), ...s.themes.map((t) => t.id)]);
  const id = uniqueId(name, taken);
  const isDesign = s.designs.some((d) => d.id === srcId);
  const out: Theme = { ...doc, ...over, id, name, design: isDesign ? srcId : doc.design || srcId };
  delete out.order;
  await send('PUT', 'themes/' + id, out);
  return id;
}
