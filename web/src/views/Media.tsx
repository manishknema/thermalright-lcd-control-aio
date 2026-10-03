import { useRef, useState } from 'preact/hooks';
import { MEDIA_EXT, MediaItem, send, uploadPicked } from '../api';
import { useAction, useStore } from '../store';
import { Badge, Btn, cachedImage, Card, dropCached, Empty, Icon, IconBtn, Thumb } from '../ui';

export function mediaThumbPath(path: string) {
  return `media/file?path=${encodeURIComponent(path)}&thumb=1`;
}

function size(b: number | null) {
  if (b == null) return '';
  return b > 2 ** 20 ? `${(b / 2 ** 20).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`;
}

const KIND_LABEL: Record<string, string> = { image: 'Image', gif: 'GIF', video: 'Video', collection: 'Collection', font: 'Font' };

/** Hidden file input + button; uploads one file or a multi-image collection. */
export function UploadButton({ accept, multiple, onDone, label = 'Upload', small }: {
  accept?: string; multiple?: boolean; onDone?: (path: string, kind: string) => void; label?: string; small?: boolean;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const { reload, toast } = useStore();
  const [busy, setBusy] = useState(false);
  const pick = async (files: FileList | null) => {
    if (!files || !files.length) return;
    setBusy(true);
    try {
      const r = await uploadPicked([...files]);
      if (r.skipped.length) toast(`Skipped unsupported: ${r.skipped.slice(0, 5).join(', ')}${r.skipped.length > 5 ? ' …' : ''}. Supported: ${MEDIA_EXT.join(' ')}`, 'info');
      toast(r.kind === 'collection' ? `Created collection ${r.path}` : `Uploaded ${r.path}`, 'ok');
      await reload('media');
      onDone?.(r.path, r.kind);
    } catch (e: any) {
      toast(e.message, 'err');
    } finally {
      setBusy(false);
      if (ref.current) ref.current.value = '';
    }
  };
  return (
    <>
      <input ref={ref} type="file" hidden accept={accept || MEDIA_EXT.join(',')} multiple={multiple}
        onChange={(e) => pick((e.target as HTMLInputElement).files)} />
      <Btn small={small} icon="upload" disabled={busy} onClick={() => ref.current?.click()}>{busy ? 'Uploading…' : label}</Btn>
    </>
  );
}

function MediaTile({ m, selected, onSelect, onDelete }: { m: MediaItem; selected?: boolean; onSelect?: () => void; onDelete?: () => void }) {
  const inner = (
    <>
      <Thumb alt={m.path} cacheKey={m.path} load={() => cachedImage(mediaThumbPath(m.path))} />
      <div class="mtile-meta">
        <span class="mtile-name" title={m.path}>{m.kind === 'collection' ? `Collection (${m.count ?? 0} images)` : m.path}</span>
        <span class="mtile-sub">
          <Badge>{KIND_LABEL[m.kind] || m.kind}</Badge> {m.kind === 'collection' ? <span title={m.path}>{m.path}</span> : size(m.bytes)}
        </span>
      </div>
    </>
  );
  return (
    <div class={`mtile${selected ? ' on' : ''}`}>
      {onSelect ? <button type="button" class="mtile-btn" aria-pressed={selected} onClick={onSelect} title={m.path}>{inner}</button> : inner}
      {onDelete && <IconBtn icon="trash" label={`Delete ${m.path}`} class="mtile-del" onClick={onDelete} />}
    </div>
  );
}

/** Compact picker for the editor (background / foreground / image / font). */
export function MediaPicker({ kinds, value, onChange, multiple, accept, allowNone, noneLabel = 'None' }: {
  kinds: string[]; value?: string | null; onChange: (path: string | null) => void; multiple?: boolean; accept?: string; allowNone?: boolean; noneLabel?: string;
}) {
  const { media } = useStore();
  const items = media.filter((m) => kinds.includes(m.kind));
  return (
    <div class="mpicker">
      <div class="mpicker-bar">
        <UploadButton small accept={accept} multiple={multiple} label={multiple ? 'Upload (several = collection)' : 'Upload'}
          onDone={(p, k) => kinds.includes(k) && onChange(p)} />
        {allowNone && <Btn small kind="ghost" icon="x" disabled={!value} onClick={() => onChange(null)}>{noneLabel}</Btn>}
      </div>
      {items.length === 0 ? (
        <div class="mpicker-empty">No {kinds.join(' / ')} files uploaded yet.</div>
      ) : (
        <div class="mpicker-grid">
          {items.map((m) => <MediaTile m={m} selected={value === m.path} onSelect={() => onChange(m.path)} />)}
        </div>
      )}
    </div>
  );
}

export function Media() {
  const { media, reload, confirm } = useStore();
  const act = useAction();
  const [filter, setFilter] = useState('all');
  const kinds = ['all', 'image', 'gif', 'video', 'collection', 'font'];
  const shown = media.filter((m) => filter === 'all' || m.kind === filter);
  const del = async (m: MediaItem) => {
    if (!(await confirm(`Delete ${m.kind === 'collection' ? 'collection' : 'file'} "${m.path}"?`, 'Themes that use it fall back to a plain colour background.', 'Delete', true))) return;
    if (await act(() => send('DELETE', `media?path=${encodeURIComponent(m.path)}`), `Deleted ${m.path}`)) {
      dropCached('GET ' + mediaThumbPath(m.path));
      reload('media');
    }
  };
  return (
    <Card title="Media library" icon="image"
      sub={<>Backgrounds, foregrounds and fonts on this node. Pick one file, or several images to make a slideshow collection.</>}
      actions={<><Btn small kind="ghost" icon="refresh" onClick={() => reload('media')}>Refresh</Btn><UploadButton multiple /></>}>
      <div class="chips" role="radiogroup" aria-label="Filter by kind">
        {kinds.map((k) => (
          <button type="button" role="radio" aria-checked={filter === k} class={`chip${filter === k ? ' on' : ''}`} onClick={() => setFilter(k)}>
            {k === 'all' ? 'All' : KIND_LABEL[k]} <span class="chip-count">{k === 'all' ? media.length : media.filter((m) => m.kind === k).length}</span>
          </button>
        ))}
      </div>
      {shown.length === 0 ? (
        <Empty icon="upload" title={media.length ? 'Nothing of this kind' : 'No media uploaded yet'}>
          Supported: {MEDIA_EXT.join(' ')}. Several images uploaded together become a collection that cycles on the panel.
        </Empty>
      ) : (
        <div class="media-grid">
          {shown.map((m) => <MediaTile m={m} key={m.path} onDelete={() => del(m)} />)}
        </div>
      )}
      <p class="muted small"><Icon name="info" size={12} /> Thumbnails: images scaled, videos at 10% of their length, collections show their first image, fonts show a sample.</p>
    </Card>
  );
}
