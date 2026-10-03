import { useEffect, useRef, useState } from 'preact/hooks';
import { DeviceInfo, get, imageUrl, NodeInfo } from '../api';
import { useStore } from '../store';
import { Badge, Btn, Card, Dot, Empty, fmt, heatColor, Icon, Ring, Segmented, Spark } from '../ui';

interface TileDef {
  id: string; label: string; icon: string; unit: string; lo: number; hi: number; digits?: number;
  gpu?: boolean; sub?: (v: Record<string, any>) => string; scaleFromTotal?: boolean;
}

const TILES: TileDef[] = [
  { id: 'cpu.temp', label: 'CPU temperature', icon: 'temp', unit: '°C', lo: 35, hi: 95 },
  { id: 'cpu.power', label: 'CPU package power', icon: 'bolt', unit: 'W', lo: 0, hi: 250, sub: (v) => v['cpu.power'] == null ? 'RAPL not readable' : '' },
  { id: 'cpu.load', label: 'CPU load', icon: 'chip', unit: '%', lo: 0, hi: 100, sub: (v) => `${fmt(v['cpu.freq'], 2)} GHz · ${fmt(v['cpu.count'])} threads` },
  { id: 'gpu.temp', label: 'GPU temperature', icon: 'temp', unit: '°C', lo: 35, hi: 90, gpu: true, sub: (v) => v['gpu.short'] || '' },
  { id: 'gpu.power', label: 'GPU power', icon: 'bolt', unit: 'W', lo: 0, hi: 450, gpu: true },
  { id: 'gpu.util', label: 'GPU utilisation', icon: 'chip', unit: '%', lo: 0, hi: 100, gpu: true, sub: (v) => `${fmt(v['gpu.clock'], 2)} GHz · fan ${fmt(v['gpu.fan'])}%` },
  { id: 'gpu.vram_pct', label: 'VRAM', icon: 'mem', unit: '%', lo: 0, hi: 100, gpu: true, sub: (v) => `${fmt(v['gpu.vram_used'], 1)} / ${fmt(v['gpu.vram_total'], 0)} GB` },
  { id: 'ram.pct', label: 'RAM', icon: 'mem', unit: '%', lo: 0, hi: 100, sub: (v) => `${fmt(v['ram.used'], 1)} / ${fmt(v['ram.total'], 0)} GB` },
  { id: 'nvme.temp', label: 'NVMe temperature', icon: 'disk', unit: '°C', lo: 30, hi: 75 },
  { id: 'sys.power', label: 'System draw', icon: 'bolt', unit: 'W', lo: 0, hi: 700, sub: () => 'CPU package + GPU' },
  { id: 'llm.tokens_s', label: 'LLM tokens/s', icon: 'spark', unit: 'tok/s', lo: 0, hi: 200, digits: 1 },
];

function MetricTile({ d }: { d: TileDef }) {
  const { metrics, history } = useStore();
  const v = metrics?.values[d.id];
  const num = typeof v === 'number' ? v : null;
  const color = d.unit === '°C' || d.unit === '%' ? heatColor(num, d.lo, d.hi) : '#66fcf1';
  const hist = history[d.id] || [];
  const sub = d.sub && metrics ? d.sub(metrics.values) : '';
  return (
    <div class={`tile${num == null ? ' is-null' : ''}`}>
      <Ring frac={num == null ? null : (num - d.lo) / (d.hi - d.lo)} color={color} size={68} stroke={7}>
        <span class="ring-val">{fmt(num, d.digits ?? 0)}</span>
        <span class="ring-unit">{d.unit}</span>
      </Ring>
      <div class="tile-body">
        <div class="tile-label"><Icon name={d.icon} size={13} /> {d.label}</div>
        {sub && <div class="tile-sub">{sub}</div>}
        <Spark data={hist} color={num == null ? '#45a29e' : color} w={130} h={26} />
      </div>
    </div>
  );
}

function CoresTile() {
  const { metrics } = useStore();
  const cores: number[] = metrics?.values['cpu.cores'] || [];
  if (!cores.length) return null;
  return (
    <div class="tile tile-wide">
      <div class="tile-body">
        <div class="tile-label"><Icon name="chip" size={13} /> Per-thread load <span class="muted">({cores.length})</span></div>
        <div class="cores" role="img" aria-label={`Per-thread CPU load: ${cores.map((c) => c.toFixed(0)).join(', ')} percent`}>
          {cores.map((c) => (
            <div class="core" title={`${c.toFixed(0)}%`}>
              <div class="core-fill" style={{ height: `${Math.min(100, c)}%`, background: heatColor(c, 0, 100) }} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function LiveFrame() {
  const { status } = useStore();
  const [src, setSrc] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [zoom, setZoom] = useState<number>(2);
  const prev = useRef<string | null>(null);
  useEffect(() => {
    let alive = true, t = 0;
    const tick = async () => {
      try {
        const u = await imageUrl(`frame.png?scale=2&t=${Date.now()}`);
        if (!alive) { URL.revokeObjectURL(u); return; }
        setSrc(u); setErr(null);
        if (prev.current) { const old = prev.current; setTimeout(() => URL.revokeObjectURL(old), 2000); }
        prev.current = u;
      } catch (e: any) {
        if (alive) setErr(e.message);
      }
      if (alive) t = window.setTimeout(tick, document.hidden ? 5000 : 1000);
    };
    tick();
    return () => { alive = false; clearTimeout(t); };
  }, []);
  const w = status?.device.width || 320, h = status?.device.height || 240;
  const rotating = status?.rotate.enabled;
  return (
    <Card title="On the panel now" icon="live" class="live-card"
      sub="Exactly the frame last sent to the LCD, refreshed every second"
      actions={<Segmented label="Preview zoom" value={zoom} onChange={setZoom} options={[{ value: 1, label: '1x' }, { value: 2, label: '2x' }]} />}>
      <div class="lcd-stage">
        <div class="lcd-bezel" style={{ width: `min(100%, ${w * zoom + 24}px)` }}>
          {src ? <img class="lcd-img" src={src} alt="Live LCD frame" style={{ aspectRatio: `${w} / ${h}` }} />
            : <div class="lcd-img lcd-wait" style={{ aspectRatio: `${w} / ${h}` }}>{err || 'waiting for the first frame'}</div>}
        </div>
      </div>
      <div class="kv-row">
        <div class="kv"><span>Theme</span><strong>{status?.theme.name || '—'}</strong></div>
        <div class="kv"><span>Pack</span><strong>{status?.theme.pack || '—'}</strong></div>
        <div class="kv"><span>Source</span><strong>{status?.active.kind || '—'}</strong></div>
        <div class="kv"><span>Rotation</span><strong>{rotating ? `every ${status!.rotate.seconds}s · ${status!.rotate.items.length} items` : 'off'}</strong></div>
        <div class="kv"><span>Frame time</span><strong>{status ? `${status.device.last_frame_ms} ms` : '—'}</strong></div>
        <div class="kv"><span>Frame errors</span><strong class={status?.device.frame_errors ? 'txt-crit' : ''}>{status?.device.frame_errors ?? '—'}</strong></div>
        <div class="kv"><span>Uptime</span><strong>{status ? uptime(status.device.uptime_s) : '—'}</strong></div>
      </div>
    </Card>
  );
}

function uptime(s: number) {
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m ${s % 60}s`;
}

function Nodes() {
  const [nodes, setNodes] = useState<NodeInfo[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = () => get<{ nodes: NodeInfo[] }>('nodes').then((r) => { setNodes(r.nodes); setErr(null); }).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);
  return (
    <Card title="Display nodes" icon="node" sub="Nodes on the cluster that advertise a hardware display"
      actions={<Btn small kind="ghost" icon="refresh" onClick={load}>Refresh</Btn>}>
      {err && <div class="inline-err">{err}</div>}
      {!nodes ? <div class="shimmer-block" /> : nodes.length === 0 ? <Empty title="No display nodes found" /> : (
        <div class="node-list">
          {nodes.map((n) => {
            const hw = n.hw_display || {};
            const body = (
              <>
                <div class="node-top">
                  <Dot state={hw.connected === false ? 'warn' : 'ok'} />
                  <strong>{n.hostname}</strong>
                  {n.self && <Badge tone="accent">this node</Badge>}
                  {!n.self && !n.display_url && <Badge>info only</Badge>}
                </div>
                <div class="node-meta">
                  <span>{hw.model || 'display'}</span>
                  {hw.resolution && <span>{hw.resolution}</span>}
                  {hw.vid_pid && <span>{hw.vid_pid}</span>}
                  {hw.theme?.name && <span>theme: {hw.theme.name}</span>}
                </div>
                {!n.self && !n.display_url && <div class="node-note">This node's display is not remotely editable (for example a segment display, or its API is not shared on the LAN).</div>}
              </>
            );
            return n.self || !n.display_url
              ? <div class={`node${n.self ? ' is-self' : ''}`}>{body}</div>
              : <a class="node node-link" href={n.display_url}>{body}<span class="node-go">Open <Icon name="back" size={12} /></span></a>;
          })}
        </div>
      )}
    </Card>
  );
}

function Devices() {
  const { status } = useStore();
  const [devs, setDevs] = useState<DeviceInfo[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = () => get<{ devices: DeviceInfo[] }>('devices').then((r) => { setDevs(r.devices); setErr(null); }).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);
  const noneAttached = devs && !devs.some((d) => d.attached) && status?.device.connected === false;
  return (
    <Card title="USB displays" icon="usb" sub="Supported Thermalright panels and whether they are attached here"
      actions={<Btn small kind="ghost" icon="refresh" onClick={load}>Rescan</Btn>}>
      {err && <div class="inline-err">{err}</div>}
      {noneAttached && <div class="banner banner-warn">No supported display found on this node. Supported VID:PID (panel) are listed below.</div>}
      {!devs ? <div class="shimmer-block" /> : (
        <div class="dev-list">
          {devs.map((d) => (
            <div class={`dev${d.active ? ' is-active' : ''}`}>
              <Dot state={d.active ? 'ok' : d.attached ? 'ok' : 'off'} />
              <code>{d.vid_pid}</code>
              <span class="dev-panels">{d.panels.join(' / ')}</span>
              <span class="dev-state">{d.active ? <Badge tone="ok">driving</Badge> : d.attached ? <Badge tone="accent">attached</Badge> : d.attached === null ? <Badge>unknown</Badge> : <span class="muted">not attached</span>}</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

export function Live() {
  const { metrics } = useStore();
  const gpu = !!metrics?.capabilities.gpu;
  const tiles = TILES.filter((t) => (gpu || !t.gpu) && (t.id !== 'llm.tokens_s' || metrics?.capabilities.llm || metrics?.values['llm.tokens_s'] != null));
  return (
    <div class="live-grid">
      <LiveFrame />
      <Card title="Live metrics" icon="spark" class="metrics-card"
        sub={gpu ? 'Values the themes bind to, sampled once a second' : 'No NVIDIA GPU on this node, GPU tiles are hidden'}>
        {!metrics ? <div class="shimmer-block" /> : (
          <div class="tiles">
            {tiles.map((d) => <MetricTile d={d} key={d.id} />)}
            <CoresTile />
          </div>
        )}
      </Card>
      <Nodes />
      <Devices />
    </div>
  );
}
