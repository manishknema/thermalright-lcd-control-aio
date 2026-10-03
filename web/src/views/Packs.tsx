import { useState } from 'preact/hooks';
import { Pack, send, slug } from '../api';
import { useStore } from '../store';
import { Badge, Btn, cachedPreview, Card, dropCached, Empty, Field, Icon, Segmented, Thumb } from '../ui';
import { hash, Swatches, uniqueId } from './common';
import { UploadButton } from './Media';

const COLOR_KEYS: { k: string; hint: string }[] = [
  { k: 'ink', hint: 'panel background' }, { k: 'panel', hint: 'cards, core cells' }, { k: 'line', hint: 'gauge tracks' },
  { k: 'text', hint: 'main text' }, { k: 'muted', hint: 'labels' }, { k: 'accent1', hint: 'primary accent' },
  { k: 'accent2', hint: 'second accent' }, { k: 'accent3', hint: 'third accent' }, { k: 'ok', hint: 'heat: cool' },
  { k: 'warn', hint: 'heat: warm' }, { k: 'hot', hint: 'heat: hot' },
];
const ROLES = [
  { k: 'display', hint: 'big numerals' }, { k: 'bold', hint: 'labels and values' }, { k: 'body', hint: 'small text' }, { k: 'mono', hint: 'clocks' },
];
const HEX = /^#[0-9a-fA-F]{6}$/;

function Mock({ p }: { p: Pack }) {
  const c = p.colors;
  return (
    <div class="mock" style={{ background: c.ink, color: c.text }} aria-label="Colour mock-up of the pack" role="img">
      <div class="mock-ring" style={{ borderColor: c.line, borderTopColor: c.ok, borderRightColor: c.warn }}>
        <span style={{ color: c.text }}>62°</span>
        <small style={{ color: c.muted }}>CPU</small>
      </div>
      <div class="mock-side">
        <small style={{ color: c.muted }}>POWER</small>
        <strong style={{ color: c.accent1 }}>184<em>W</em></strong>
        <div class="mock-bar" style={{ background: c.line }}><span style={{ background: c.accent2, width: '64%' }} /></div>
        <div class="mock-panel" style={{ background: c.panel }}>
          <span style={{ background: c.ok }} /><span style={{ background: c.warn }} /><span style={{ background: c.hot }} /><span style={{ background: c.accent3 }} />
        </div>
      </div>
    </div>
  );
}

function fontValue(v: string | null | undefined, fonts: string[]): string {
  if (!v) return '';
  const m = fonts.find((f) => v === 'media/' + f || v.endsWith('/media/' + f));
  return m ? 'media/' + m : v;
}

function PackEditor({ initial, isNew, close }: { initial: Pack; isNew: boolean; close: () => void }) {
  const { media, reload, toast, packs, designs } = useStore();
  const [p, setP] = useState<Pack>(initial);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fonts = media.filter((m) => m.kind === 'font').map((m) => m.path);
  const setColor = (k: string, v: string) => setP((x) => ({ ...x, colors: { ...x.colors, [k]: v } }));
  const setFont = (r: string, v: string | null) => setP((x) => ({ ...x, fonts: { ...x.fonts, [r]: v } }));
  const bad = COLOR_KEYS.filter(({ k }) => !HEX.test(p.colors[k] || ''));
  const save = async () => {
    setBusy(true); setErr(null);
    try {
      const { builtin: _b, ...doc } = p;
      const out = await send<Pack>('PUT', 'packs/' + p.id, doc);
      dropCached('p|' + p.id);
      toast(`Saved pack ${out.name}`, 'ok');
      await reload('packs', 'status');
      close();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  const builtinIds = new Set(packs.filter((x) => x.builtin).map((x) => x.id));
  return (
    <Card title={isNew ? 'New pack' : `Edit ${initial.name}`} icon="palette" class="pack-editor"
      actions={<><Btn small kind="ghost" onClick={close}>Cancel</Btn><Btn small kind="primary" icon="save" disabled={busy || bad.length > 0 || !p.id} onClick={save}>Save pack</Btn></>}>
      {err && <div class="banner banner-crit" role="alert"><Icon name="x" /> {err}</div>}
      <div class="pe-grid">
        <div>
          <div class="props">
            <Field label="Name"><input class="input" value={p.name} onInput={(e) => {
              const name = (e.target as HTMLInputElement).value;
              setP((x) => ({ ...x, name, id: isNew ? uniqueId(name || 'pack', new Set(packs.map((q) => q.id))) : x.id }));
            }} /></Field>
            <Field label="Id" hint={isNew ? 'Lowercase letters, digits and hyphens' : 'Fixed for an existing pack'}>
              <input class="input mono" value={p.id} disabled={!isNew} onInput={(e) => setP((x) => ({ ...x, id: slug((e.target as HTMLInputElement).value) }))} />
            </Field>
            <Field label="Ground"><Segmented label="Ground" value={p.ground} onChange={(g) => setP((x) => ({ ...x, ground: g }))}
              options={[{ value: 'dark', label: 'Dark' }, { value: 'light', label: 'Light' }]} /></Field>
            {p.mark && <Field label="Default mark"><Segmented label="Default mark" value={p.default_mark || 'none'} onChange={(m) => setP((x) => ({ ...x, default_mark: m }))}
              options={[{ value: 'none', label: 'None' }, { value: 'corner', label: 'Corner' }, { value: 'background', label: 'Background' }]} /></Field>}
          </div>
          {builtinIds.has(p.id) && <div class="inline-err">"{p.id}" is a built-in pack id; pick another name.</div>}
          <h4 class="sec-h">Colours</h4>
          <div class="colors">
            {COLOR_KEYS.map(({ k, hint }) => (
              <label class={`colorrow${HEX.test(p.colors[k] || '') ? '' : ' bad'}`}>
                <input type="color" value={HEX.test(p.colors[k] || '') ? p.colors[k] : '#000000'} aria-label={`${k} colour`} onInput={(e) => setColor(k, (e.target as HTMLInputElement).value)} />
                <span class="colorrow-k"><strong>{k}</strong><small>{hint}</small></span>
                <input class="input mono" value={p.colors[k] || ''} aria-label={`${k} hex`} maxLength={7} onInput={(e) => setColor(k, (e.target as HTMLInputElement).value.trim())} />
              </label>
            ))}
          </div>
          <h4 class="sec-h">Fonts</h4>
          <div class="props">
            {ROLES.map(({ k, hint }) => {
              const v = fontValue(p.fonts[k], fonts);
              return (
                <Field label={`${k}`} hint={hint}>
                  <select class="input" value={v} onChange={(e) => setFont(k, (e.target as HTMLSelectElement).value || null)}>
                    <option value="">built-in (DejaVu)</option>
                    {fonts.map((f) => <option value={'media/' + f}>{f}</option>)}
                    {v && !v.startsWith('media/') && <option value={v}>{v.split('/').pop()}</option>}
                  </select>
                </Field>
              );
            })}
          </div>
          <div class="row"><UploadButton small accept=".ttf,.otf" label="Upload font (.ttf / .otf)" onDone={(path, kind) => kind === 'font' && toast(`Font ${path} uploaded; pick it for a role above`, 'info')} /></div>
        </div>
        <div class="pe-side">
          <h4 class="sec-h">Mock-up</h4>
          <Mock p={p} />
          <Swatches pack={p} keys={COLOR_KEYS.map((c) => c.k)} />
          {!isNew && designs[0] && (
            <>
              <h4 class="sec-h">Saved version on the panel renderer</h4>
              <Thumb alt="Server preview" cacheKey={`p|${p.id}|${hash(JSON.stringify(initial))}`}
                load={() => cachedPreview(`p|${p.id}|${hash(JSON.stringify(initial))}`, { selection: { kind: 'design', design: designs[0].id, pack: p.id } })} />
            </>
          )}
          <p class="muted small">The mock-up follows your edits live; the rendered preview (and fonts) update after saving.</p>
        </div>
      </div>
    </Card>
  );
}

export function Packs() {
  const { packs, designs, status, reload, confirm, toast } = useStore();
  const [edit, setEdit] = useState<{ p: Pack; isNew: boolean } | null>(null);
  const customize = (p: Pack) => {
    const name = `${p.name} custom`;
    const id = uniqueId(name, new Set(packs.map((x) => x.id)));
    setEdit({ p: { ...JSON.parse(JSON.stringify(p)), id, name, builtin: false, mark: null }, isNew: true });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };
  const del = async (p: Pack) => {
    if (!(await confirm(`Delete pack "${p.name}"?`, 'Themes using it fall back to Slate.', 'Delete', true))) return;
    try {
      await send('DELETE', 'packs/' + p.id);
      toast(`Deleted ${p.name}`, 'ok');
      reload('packs');
    } catch (e: any) { toast(e.message, 'err'); }
  };
  const active = status?.theme.pack;
  return (
    <div class="stack">
      {edit && <PackEditor key={edit.p.id + edit.isNew} initial={edit.p} isNew={edit.isNew} close={() => setEdit(null)} />}
      <Card title="Theme packs" icon="palette" sub="A pack is the palette and fonts; any design can wear any pack. Built-in packs are read-only: customise one to make your own.">
        {packs.length === 0 ? <Empty title="No packs" /> : (
          <div class="pack-grid">
            {packs.map((p) => (
              <article class={`pcard${active === p.id ? ' is-active' : ''}`}>
                <Thumb alt={`${p.name} pack preview`} cacheKey={`p|${p.id}|${hash(JSON.stringify(p))}`}
                  load={() => cachedPreview(`p|${p.id}|${hash(JSON.stringify(p))}`, { selection: { kind: 'design', design: designs[0]?.id || 'core-gauge', pack: p.id } })} />
                <div class="pcard-body">
                  <div class="gcard-title">
                    <h3>{p.name}</h3>
                    <span class="row">
                      <Badge>{p.ground}</Badge>
                      {p.builtin ? <Badge>built-in</Badge> : <Badge tone="accent">user</Badge>}
                      {active === p.id && <Badge tone="ok">on panel</Badge>}
                    </span>
                  </div>
                  <Swatches pack={p} keys={COLOR_KEYS.map((c) => c.k)} />
                  <div class="pcard-meta muted small">
                    fonts: {Object.values(p.fonts || {}).filter(Boolean).length ? Object.entries(p.fonts).filter(([, v]) => v).map(([k, v]) => `${k} ${String(v).split('/').pop()}`).join(', ') : 'built-in'}
                    {p.mark ? ' · has brand mark' : ''}
                  </div>
                  <div class="gcard-actions">
                    <Btn small icon="copy" onClick={() => customize(p)}>Customise</Btn>
                    {!p.builtin && <Btn small icon="edit" onClick={() => setEdit({ p, isNew: false })}>Edit</Btn>}
                    {!p.builtin && <Btn small kind="danger" icon="trash" onClick={() => del(p)} aria-label={`Delete ${p.name}`} />}
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
