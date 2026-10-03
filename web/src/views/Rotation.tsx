import { useEffect, useState } from 'preact/hooks';
import { Selection, send } from '../api';
import { useStore } from '../store';
import { Badge, Btn, cachedPreview, Card, Empty, Field, IconBtn, Segmented, Thumb, Toggle } from '../ui';
import { PackChips, selLabel, selPreviewKey } from './common';

export function Rotation() {
  const store = useStore();
  const { status, designs, themes, packs, legacy, reload, toast } = store;
  const [enabled, setEnabled] = useState(false);
  const [seconds, setSeconds] = useState(15);
  const [items, setItems] = useState<Selection[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [kind, setKind] = useState<'design' | 'theme' | 'legacy'>('design');
  const [design, setDesign] = useState('');
  const [pack, setPack] = useState('slate');
  const [theme, setTheme] = useState('');

  useEffect(() => {
    if (status && !loaded) {
      setEnabled(status.rotate.enabled); setSeconds(status.rotate.seconds); setItems(status.rotate.items || []); setLoaded(true);
    }
  }, [status]);
  useEffect(() => { if (!design && designs.length) setDesign(designs[0].id); }, [designs]);
  useEffect(() => { if (!theme && themes.length) setTheme(themes[0].id); }, [themes]);

  const saved = status ? JSON.stringify({ e: status.rotate.enabled, s: status.rotate.seconds, i: status.rotate.items }) : '';
  const dirty = loaded && saved !== JSON.stringify({ e: enabled && items.length > 1, s: seconds, i: items });

  const add = () => {
    const sel: Selection | null = kind === 'design' ? (design ? { kind: 'design', design, pack } : null)
      : kind === 'theme' ? (theme ? { kind: 'theme', theme } : null)
      : (theme ? { kind: 'legacy', theme } : null);
    if (sel) setItems((x) => [...x, sel]);
  };
  const mv = (i: number, d: number) => setItems((x) => { const n = [...x]; const j = i + d; if (j < 0 || j >= n.length) return x; [n[i], n[j]] = [n[j], n[i]]; return n; });
  const save = async () => {
    setBusy(true); setErr(null);
    try {
      const out = await send<{ enabled: boolean; seconds: number; items: Selection[] }>('PUT', 'rotation', { enabled, seconds, items });
      setEnabled(out.enabled); setSeconds(out.seconds); setItems(out.items);
      toast(out.enabled ? `Rotating ${out.items.length} themes every ${out.seconds}s` : 'Rotation saved (off)', 'ok');
      if (enabled && !out.enabled) toast('Rotation needs at least two items to run', 'info');
      await reload('status');
    } catch (e: any) { setErr(e.message); toast(e.message, 'err'); } finally { setBusy(false); }
  };

  return (
    <div class="stack">
      <Card title="Rotation" icon="rotate" sub="Cycle the panel through several themes. Applying a single theme elsewhere does not turn this off."
        actions={<>
          {dirty && <Badge tone="warn">unsaved</Badge>}
          <Btn small kind="ghost" disabled={!dirty || busy} onClick={() => { setLoaded(false); }}>Revert</Btn>
          <Btn small kind="primary" icon="save" disabled={busy || !dirty} onClick={save}>Save rotation</Btn>
        </>}>
        {err && <div class="inline-err" role="alert">{err}</div>}
        <div class="rot-top">
          <Toggle label={enabled ? 'Rotation on' : 'Rotation off'} checked={enabled} onChange={setEnabled} />
          <Field label="Seconds per item" hint="5 to 3600">
            <input class="input" type="number" min={5} max={3600} value={seconds} onInput={(e) => setSeconds(Math.max(5, Math.min(3600, parseInt((e.target as HTMLInputElement).value) || 5)))} />
          </Field>
          {enabled && items.length < 2 && <span class="txt-warn small">Add at least two items for rotation to run.</span>}
        </div>
        {items.length === 0 ? <Empty icon="rotate" title="Nothing in the rotation">Add designs or your themes below.</Empty> : (
          <ol class="rot-list">
            {items.map((s, i) => (
              <li class="rot-item">
                <span class="rot-n">{i + 1}</span>
                <Thumb alt={selLabel(s, store)} cacheKey={selPreviewKey(s, themes)} load={() => cachedPreview(selPreviewKey(s, themes), { selection: s })} />
                <div class="rot-txt"><strong>{selLabel(s, store)}</strong><span class="muted small">{s.kind}</span></div>
                <span class="wrow-tools">
                  <IconBtn icon="up" label="Earlier" disabled={i === 0} onClick={() => mv(i, -1)} />
                  <IconBtn icon="down" label="Later" disabled={i === items.length - 1} onClick={() => mv(i, 1)} />
                  <IconBtn icon="trash" label="Remove from rotation" onClick={() => setItems((x) => x.filter((_, j) => j !== i))} />
                </span>
              </li>
            ))}
          </ol>
        )}
      </Card>
      <Card title="Add to rotation" icon="plus">
        <Segmented label="Item kind" value={kind} onChange={(k) => { setKind(k); setTheme(k === 'legacy' ? legacy[0]?.id || '' : themes[0]?.id || ''); }}
          options={[{ value: 'design', label: 'Design + pack' }, { value: 'theme', label: 'Your theme' }, ...(legacy.length ? [{ value: 'legacy' as const, label: 'Legacy' }] : [])]} />
        {kind === 'design' ? (
          <>
            <div class="props">
              <Field label="Design" wide><select class="input" value={design} onChange={(e) => setDesign((e.target as HTMLSelectElement).value)}>
                {designs.map((d) => <option value={d.id}>{d.name}</option>)}</select></Field>
            </div>
            <PackChips packs={packs} value={pack} onChange={setPack} />
          </>
        ) : (
          <div class="props">
            <Field label={kind === 'theme' ? 'Theme' : 'Legacy theme'} wide>
              {(kind === 'theme' ? themes : legacy).length === 0 ? <span class="muted">None available.</span> : (
                <select class="input" value={theme} onChange={(e) => setTheme((e.target as HTMLSelectElement).value)}>
                  {(kind === 'theme' ? themes : legacy).map((t: any) => <option value={t.id}>{t.name || t.id}</option>)}
                </select>
              )}
            </Field>
          </div>
        )}
        <div class="row"><Btn kind="primary" icon="plus" onClick={add}>Add item</Btn></div>
      </Card>
    </div>
  );
}
