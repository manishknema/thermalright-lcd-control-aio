import { useEffect, useState } from 'preact/hooks';
import { get, imageUrl, Json, send } from '../api';
import { useStore } from '../store';
import { Badge, Btn, Card, cachedPreview, dropCached, Field, fmt, heatColor, Ring, Thumb } from '../ui';

// Digital segment display (e.g. 0416:8001): its own controller drives the LEDs from a
// config file; this page applies presets (mode + LED colours + ranges) to that file.
interface Preset extends Json {
  id: string; name: string; description?: string; available: boolean; unavailable_reason: string | null;
  layouts: Record<string, { display_mode: string }>; ranges?: Record<string, number>; cycle_duration?: number;
}
interface Mode { id: string; label: string; available: boolean }

function LivePanel() {
  const [src, setSrc] = useState<string | null>(null);
  const [scale, setScale] = useState(2);
  useEffect(() => {
    let alive = true, last: string | null = null;
    const tick = () => imageUrl(`frame.png?scale=${scale}&t=${Date.now()}`)
      .then((u) => { if (!alive) return URL.revokeObjectURL(u); if (last) URL.revokeObjectURL(last); last = u; setSrc(u); })
      .catch(() => {});
    tick();
    const i = setInterval(tick, 1000);
    return () => { alive = false; clearInterval(i); if (last) URL.revokeObjectURL(last); };
  }, [scale]);
  return (
    <div class="digi-live">
      {src ? <img src={src} alt="What the segment display shows now" /> : <div class="shimmer-block" />}
      <div class="digi-live-tools">
        <span class="muted">Rendered from the controller's current config and live readings, every second.</span>
        <Btn small kind="ghost" onClick={() => setScale(scale === 2 ? 3 : 2)}>{scale === 2 ? 'Larger' : 'Smaller'}</Btn>
      </div>
    </div>
  );
}

export function Digital() {
  const { status, metrics, toast } = useStore();
  const [presets, setPresets] = useState<Preset[]>([]);
  const [modes, setModes] = useState<Mode[]>([]);
  const [layout, setLayout] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [mode, setMode] = useState('');
  const [cpuMin, setCpuMin] = useState('');
  const [cpuMax, setCpuMax] = useState('');
  const [cycle, setCycle] = useState('');
  const dg = (status as any)?.digital || {};
  const v = metrics?.values || {};
  const gpu = !!metrics?.capabilities.gpu;

  const load = () => Promise.all([
    get<{ presets: Preset[]; layout: string }>('digital/presets').then((r) => { setPresets(r.presets); setLayout(r.layout); }),
    get<{ modes: Mode[] }>('digital/modes').then((r) => setModes(r.modes)),
  ]).catch((e) => toast(String(e.message || e), 'err'));
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (dg.ranges) { setCpuMin(String(dg.ranges.cpu_min_temp ?? '')); setCpuMax(String(dg.ranges.cpu_max_temp ?? '')); }
    if (dg.cycle_duration) setCycle(String(dg.cycle_duration));
  }, [dg.preset, dg.config_mtime]);

  const apply = async (p: Preset, overrides: Json = {}) => {
    setBusy(p.id);
    try {
      await send('POST', 'apply', { preset: p.id, ...overrides });
      toast(`Applied ${p.name}. The display picks it up on its next frame.`);
    } catch (e: any) {
      toast(String(e.message || e), 'err');
    } finally {
      setBusy(null);
    }
  };
  const active = presets.find((p) => p.id === dg.preset);
  const applyTuned = () => {
    if (!active) return toast('Apply a preset first, then tune it.', 'err');
    const ranges: Json = {};
    if (cpuMin !== '') ranges.cpu_min_temp = Number(cpuMin);
    if (cpuMax !== '') ranges.cpu_max_temp = Number(cpuMax);
    apply(active, { display_mode: mode || undefined, ranges, cycle_duration: cycle ? Number(cycle) : undefined });
  };

  return (
    <>
      <div class="grid-2">
        <Card title="On the display now" icon="live" sub={`${layout || dg.layout_mode || ''} layout · mode ${dg.display_mode || '—'} · preset ${active?.name || dg.preset || 'none'}`}>
          <LivePanel />
        </Card>
        <Card title="Readings" icon="chip" sub={gpu ? 'CPU and GPU' : 'No GPU on this node: GPU modes and presets are hidden'}>
          <div class="digi-tiles">
            {[['CPU temperature', v['cpu.temp'], '°C', 35, 95], ['CPU load', v['cpu.load'], '%', 0, 100],
              ...(gpu ? [['GPU temperature', v['gpu.temp'], '°C', 35, 90], ['GPU load', v['gpu.util'], '%', 0, 100]] : [])]
              .map(([label, val, unit, lo, hi]: any) => (
                <div class="tile" key={label}>
                  <Ring frac={val == null ? null : (val - lo) / (hi - lo)} color={heatColor(val, lo, hi)} size={64} stroke={7}>
                    <span class="ring-val">{fmt(val)}</span><span class="ring-unit">{unit}</span>
                  </Ring>
                  <div class="tile-body"><div class="tile-label">{label}</div></div>
                </div>
              ))}
          </div>
        </Card>
      </div>

      <Card title="Presets" icon="grid" sub="Mode, LED colours and ranges in one click. Previews use the live readings."
        actions={<Btn small kind="ghost" icon="refresh" onClick={() => { dropCached('dg|'); load(); }}>Refresh</Btn>}>
        <div class="gallery">
          {presets.map((p) => (
            <article class={`gcard${p.id === dg.preset ? ' is-active' : ''}${p.available ? '' : ' is-unavailable'}`} key={p.id}>
              <Thumb ratio="8 / 3" alt={p.name} cacheKey={`dg|${p.id}`} load={() => cachedPreview(`dg|${p.id}`, { selection: { preset: p.id }, scale: 2 })} />
              <div class="gcard-body">
                <div class="gcard-title"><h3>{p.name}</h3>
                  {p.id === dg.preset && <Badge tone="ok">on display</Badge>}
                  {!p.available && <Badge tone="warn">not on this node</Badge>}
                </div>
                <p class="gcard-desc">{p.description}</p>
                {!p.available && <p class="gcard-note">{p.unavailable_reason}.</p>}
                <div class="gcard-actions">
                  <Btn kind="primary" small icon="play" disabled={!p.available || busy !== null} onClick={() => apply(p)}>Apply</Btn>
                </div>
              </div>
            </article>
          ))}
        </div>
      </Card>

      <Card title="Tune" icon="edit" sub="Adjust the active preset: display mode, the CPU temperature range its colours span, and the cycle time.">
        <div class="digi-tune">
          <Field label="Display mode">
            <select value={mode || dg.display_mode} onChange={(e) => setMode((e.target as HTMLSelectElement).value)}>
              {modes.map((m) => <option value={m.id} disabled={!m.available}>{m.label}{m.available ? '' : ' (needs a GPU)'}</option>)}
            </select>
          </Field>
          <Field label="CPU °C at the start colour"><input type="number" value={cpuMin} onInput={(e) => setCpuMin((e.target as HTMLInputElement).value)} /></Field>
          <Field label="CPU °C at the end colour"><input type="number" value={cpuMax} onInput={(e) => setCpuMax((e.target as HTMLInputElement).value)} /></Field>
          <Field label="Cycle seconds"><input type="number" min={1} max={60} value={cycle} onInput={(e) => setCycle((e.target as HTMLInputElement).value)} /></Field>
          <Btn kind="primary" icon="play" disabled={busy !== null} onClick={applyTuned}>Apply changes</Btn>
        </div>
      </Card>
    </>
  );
}
