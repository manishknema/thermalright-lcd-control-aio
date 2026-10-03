import { useEffect, useState } from 'preact/hooks';
import { send, Selection, Theme } from '../api';
import { useAction, useStore } from '../store';
import { Badge, Btn, cachedPreview, Card, dropCached, Empty, Thumb } from '../ui';
import { duplicateTheme, hash, MarkCfg, MarkControl, PackChips } from './common';

const DEFAULT_MARK: MarkCfg = { mode: 'none', opacity: 0.1 };

export function Gallery() {
  const store = useStore();
  const { packs, designs, themes, legacy, status, reload, go, confirm, prompt } = store;
  const act = useAction();
  const [pack, setPack] = useState<string>('');
  const [marks, setMarks] = useState<Record<string, MarkCfg>>({});
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (!pack && packs.length) setPack(status?.theme.pack && packs.some((p) => p.id === status.theme.pack) ? status.theme.pack! : packs[0].id);
  }, [packs, status]);
  const packObj = packs.find((p) => p.id === pack);
  const markFor = (id: string): MarkCfg => marks[`${id}|${pack}`] || { ...DEFAULT_MARK, mode: packObj?.mark ? packObj.default_mark || 'none' : 'none' };
  const active = status?.active;

  const apply = async (sel: Selection, label: string) => {
    setBusy(label);
    await act(async () => { await send('POST', 'apply', sel); await reload('status'); }, `Applied ${label}`);
    setBusy(null);
  };

  const dupDesign = async (d: Theme) => {
    const name = await prompt('Duplicate and edit', `${d.name} ${packObj?.name || ''}`.trim(), 'Creates your own copy of this design with the selected pack. Give it a name.', 'Create');
    if (!name) return;
    const m = markFor(d.id);
    const id = await act(() => duplicateTheme(d.id, name, store, { pack, mark: packObj?.mark ? { mode: m.mode, opacity: m.opacity } : { mode: 'none', opacity: 0.1 } }), `Created theme "${name}"`);
    if (id) { await reload('themes'); go('editor', id); }
  };

  const delTheme = async (t: Theme) => {
    if (!(await confirm(`Delete "${t.name || t.id}"?`, 'The theme file is removed from this node. This cannot be undone.', 'Delete', true))) return;
    if (await act(() => send('DELETE', 'themes/' + t.id), `Deleted ${t.name || t.id}`)) reload('themes');
  };

  const refresh = () => { dropCached('d|'); dropCached('t|'); dropCached('l|'); reload('themes', 'designs', 'packs'); };

  return (
    <div class="stack">
      <Card title="Designs" icon="grid" sub="Seven layouts, each rendered with any theme pack. What you see is what the panel shows."
        actions={<Btn small kind="ghost" icon="refresh" onClick={refresh}>Refresh</Btn>}>
        <PackChips packs={packs} value={pack} onChange={setPack} />
        {!designs.length ? <div class="shimmer-block" /> : (
          <div class="gallery">
            {designs.map((d) => {
              const m = markFor(d.id);
              const mark = packObj?.mark ? { mode: m.mode, opacity: m.opacity } : undefined;
              const sel: Selection = { kind: 'design', design: d.id, pack, ...(mark ? { mark } : {}) };
              const isActive = active?.kind === 'design' && active.design === d.id && (active.pack || 'slate') === pack;
              return (
                <article class={`gcard${isActive ? ' is-active' : ''}`} key={d.id}>
                  <Thumb alt={`${d.name} with ${packObj?.name}`} cacheKey={`d|${d.id}|${pack}|${m.mode}|${m.opacity}`}
                    load={() => cachedPreview(`d|${d.id}|${pack}|${mark?.mode}|${mark?.opacity}`, { selection: sel })} />
                  <div class="gcard-body">
                    <div class="gcard-title">
                      <h3>{d.name}</h3>
                      {isActive && <Badge tone="ok">on panel</Badge>}
                    </div>
                    <p class="gcard-desc">{d.description}</p>
                    <MarkControl compact pack={packObj} value={m} onChange={(v) => setMarks((x) => ({ ...x, [`${d.id}|${pack}`]: v }))} />
                    <div class="gcard-actions">
                      <Btn kind="primary" small icon="play" disabled={busy !== null} onClick={() => apply(sel, `${d.name} · ${packObj?.name}`)}>Apply</Btn>
                      <Btn small icon="copy" onClick={() => dupDesign(d)}>Duplicate &amp; edit</Btn>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </Card>

      <Card title="Your themes" icon="layers" sub="Themes you created or duplicated. Edit them in the editor."
        actions={<Btn small icon="plus" onClick={() => go('editor', null)}>New theme</Btn>}>
        {themes.length === 0 ? (
          <Empty icon="layers" title="No themes of your own yet">Pick a design above and use Duplicate &amp; edit to make one.</Empty>
        ) : (
          <div class="gallery">
            {themes.map((t) => {
              const isActive = active?.kind === 'theme' && active.theme === t.id;
              return (
                <article class={`gcard${isActive ? ' is-active' : ''}`} key={t.id}>
                  <Thumb alt={t.name || t.id} cacheKey={`t|${t.id}|${hash(JSON.stringify(t))}`}
                    load={() => cachedPreview(`t|${t.id}|${hash(JSON.stringify(t))}`, { selection: { kind: 'theme', theme: t.id } })} />
                  <div class="gcard-body">
                    <div class="gcard-title">
                      <h3>{t.name || t.id}</h3>
                      {isActive && <Badge tone="ok">on panel</Badge>}
                    </div>
                    <p class="gcard-desc">
                      <code>{t.id}</code> · pack {t.pack || 'slate'} · {t.widgets?.length || 0} widgets{t.background?.type && t.background.type !== 'color' ? ` · ${t.background.type} background` : ''}
                    </p>
                    <div class="gcard-actions">
                      <Btn kind="primary" small icon="play" disabled={busy !== null} onClick={() => apply({ kind: 'theme', theme: t.id }, t.name || t.id)}>Apply</Btn>
                      <Btn small icon="edit" onClick={() => go('editor', t.id)}>Edit</Btn>
                      <Btn small kind="danger" icon="trash" onClick={() => delTheme(t)} aria-label={`Delete ${t.name || t.id}`} />
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </Card>

      <Card title="Legacy themes" icon="image" sub="Upstream v1 YAML themes for this panel resolution">
        {legacy.length === 0 ? (
          <Empty icon="image" title="No legacy themes for this resolution">Legacy theme folders are configured in the service config (legacy_theme_dirs).</Empty>
        ) : (
          <div class="gallery">
            {legacy.map((l) => {
              const isActive = active?.kind === 'legacy' && active.theme === l.id;
              return (
                <article class={`gcard${isActive ? ' is-active' : ''}`} key={l.id}>
                  <Thumb alt={l.name} cacheKey={`l|${l.id}`} load={() => cachedPreview(`l|${l.id}`, { selection: { kind: 'legacy', theme: l.id } })} />
                  <div class="gcard-body">
                    <div class="gcard-title"><h3>{l.name}</h3>{isActive && <Badge tone="ok">on panel</Badge>}</div>
                    <div class="gcard-actions">
                      <Btn kind="primary" small icon="play" disabled={busy !== null} onClick={() => apply({ kind: 'legacy', theme: l.id }, l.name)}>Apply</Btn>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
}
