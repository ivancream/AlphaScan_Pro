import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  Bell,
  BellOff,
  Eraser,
  Pause,
  Play,
  Radio,
  Settings2,
  Ticket,
  TrendingDown,
  TrendingUp,
  Upload,
  Wifi,
  WifiOff,
  Zap,
} from 'lucide-react';

import {
  useIntradayMonitor,
  useMonitorMicroSnapshot,
  type IntradayMonitorConfig,
} from '@/hooks/useIntradayMonitor';
import type { MonitorConnectionState, MonitorSignalEvent } from '@/types/intradayMonitor';

const DEFAULT_CONFIG: IntradayMonitorConfig = {
  symbols: ['TXF', 'MXF', '2330', '2317', '2454', '3231', '2603'],
  stockLotThreshold: 50,
  warrantLotThreshold: 100,
  moveWindowSec: 60,
  movePctThreshold: 1.5,
  continuousWindowSec: 3,
  continuousMinCount: 3,
  maxWarrantsPerStock: 40,
  includeWarrants: true,
  includeIndexFutures: true,
  futuresLotThreshold: 10,
  futuresConsecutiveMinCount: 10,
  futuresConsecutiveMinVolume: 30,
  futuresReversalMinLots: 5,
  futuresVwapDeviationPct: 0.25,
  futuresWallLots: 80,
};

function parseSymbols(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(/[\s,;，、]+/)
        .map((item) => item.trim().toUpperCase().replace('.TW', '').replace('.TWO', ''))
        .filter(Boolean),
    ),
  );
}

function formatNumber(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '-';
  return value.toLocaleString('zh-TW', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function connectionMeta(state: MonitorConnectionState) {
  if (state === 'open') return { label: '監控中', cls: 'text-emerald-300', dot: 'bg-emerald-400' };
  if (state === 'connecting') return { label: '連線中', cls: 'text-amber-300', dot: 'bg-amber-400 animate-pulse' };
  if (state === 'error') return { label: '連線錯誤', cls: 'text-red-300', dot: 'bg-red-400' };
  return { label: '已暫停', cls: 'text-slate-400', dot: 'bg-slate-600' };
}

function signalIcon(event: MonitorSignalEvent) {
  if (event.event_type === 'warrant_spot_link') return <Ticket size={15} />;
  if (event.event_type === 'rapid_rise' || event.event_type === 'rapid_drop') return <Zap size={15} />;
  if (event.event_type === 'continuous_buy' || event.event_type === 'continuous_sell') return <Activity size={15} />;
  return event.side === 'buy' ? <TrendingUp size={15} /> : <TrendingDown size={15} />;
}

function playSignalSound(event: MonitorSignalEvent) {
  const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextCtor) return;
  const ctx = new AudioContextCtor();
  const oscillator = ctx.createOscillator();
  const gain = ctx.createGain();
  const isWarrant = event.event_type === 'warrant_spot_link';
  oscillator.type = isWarrant ? 'triangle' : 'sine';
  oscillator.frequency.value = isWarrant ? 760 : event.side === 'buy' ? 980 : 430;
  gain.gain.setValueAtTime(0.001, ctx.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.08, ctx.currentTime + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.16);
  oscillator.connect(gain);
  gain.connect(ctx.destination);
  oscillator.start();
  oscillator.stop(ctx.currentTime + 0.18);
}

declare global {
  interface Window {
    webkitAudioContext?: typeof AudioContext;
  }
}

export default function IntradayMonitorPage() {
  const [draftConfig, setDraftConfig] = useState(DEFAULT_CONFIG);
  const [symbolsText, setSymbolsText] = useState(DEFAULT_CONFIG.symbols.join(','));
  const [activeConfig, setActiveConfig] = useState(DEFAULT_CONFIG);
  const [enabled, setEnabled] = useState(true);
  const [soundEnabled, setSoundEnabled] = useState(false);
  const [selectedSymbol, setSelectedSymbol] = useState<string>(DEFAULT_CONFIG.symbols[0]);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const lastSoundIdRef = useRef<string | null>(null);

  const monitor = useIntradayMonitor(activeConfig, enabled);
  const { snapshot, error: microError } = useMonitorMicroSnapshot(selectedSymbol, enabled);

  const status = connectionMeta(monitor.connectionState);
  const shioajiConnected = monitor.ready?.health.shioaji_connected ?? false;
  const latestEvent = monitor.events[0] ?? null;

  useEffect(() => {
    if (!latestEvent) return;
    const target = latestEvent.related_symbol || latestEvent.symbol;
    if (target) {
      setSelectedSymbol((prev) => prev || target);
    }
    if (soundEnabled && latestEvent.id !== lastSoundIdRef.current) {
      lastSoundIdRef.current = latestEvent.id;
      playSignalSound(latestEvent);
    }
  }, [latestEvent, soundEnabled]);

  const stats = useMemo(() => {
    let buy = 0;
    let sell = 0;
    let warrant = 0;
    for (const event of monitor.events) {
      if (event.side === 'buy') buy += 1;
      if (event.side === 'sell') sell += 1;
      if (event.event_type === 'warrant_spot_link') warrant += 1;
    }
    return { buy, sell, warrant };
  }, [monitor.events]);

  const applyConfig = () => {
    const symbols = parseSymbols(symbolsText);
    const next = { ...draftConfig, symbols };
    setActiveConfig(next);
    setEnabled(true);
    if (symbols[0]) setSelectedSymbol(symbols[0]);
  };

  const importCsv = async (file: File | undefined) => {
    if (!file) return;
    const text = await file.text();
    const symbols = parseSymbols(text);
    setSymbolsText(symbols.join(','));
    setDraftConfig((prev) => ({ ...prev, symbols }));
  };

  const updateNumber = (key: keyof IntradayMonitorConfig, value: number) => {
    setDraftConfig((prev) => ({ ...prev, [key]: value }));
  };

  return (
    <div className="flex h-full flex-col bg-[#070A0F] text-slate-200">
      <section className="shrink-0 border-b border-slate-800 bg-[#0A1018]">
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-md border border-cyan-500/30 bg-cyan-500/10 text-cyan-300">
              <Radio size={20} />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-3">
                <h2 className="truncate text-lg font-bold tracking-widest text-white">權現連動全方位監控</h2>
                <span className={`inline-flex items-center gap-1.5 text-xs font-semibold ${status.cls}`}>
                  <span className={`h-2 w-2 rounded-full ${status.dot}`} />
                  {status.label}
                </span>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-3 text-[11px] text-slate-500">
                <span className={shioajiConnected ? 'text-emerald-300' : 'text-red-300'}>
                  API {shioajiConnected ? '已連線' : '未連線'}
                </span>
                <span>訊號 {monitor.eventCount.toLocaleString('zh-TW')}</span>
                <span>權證 mapping {monitor.ready?.health.warrant_mapping_count ?? '-'}</span>
                <span>隔日沖標籤 {monitor.ready?.health.overnight_branch_symbol_count ?? '-'}</span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setSoundEnabled((prev) => !prev)}
              className={`inline-flex h-9 items-center gap-2 rounded-md border px-3 text-xs font-semibold transition-colors ${
                soundEnabled
                  ? 'border-yellow-400/40 bg-yellow-400/10 text-yellow-200'
                  : 'border-slate-700 bg-slate-900 text-slate-400 hover:text-white'
              }`}
            >
              {soundEnabled ? <Bell size={15} /> : <BellOff size={15} />}
              音效
            </button>
            <button
              type="button"
              onClick={() => setEnabled((prev) => !prev)}
              className="inline-flex h-9 items-center gap-2 rounded-md border border-slate-700 bg-slate-900 px-3 text-xs font-semibold text-slate-200 transition-colors hover:border-cyan-500/50 hover:text-cyan-200"
            >
              {enabled ? <Pause size={15} /> : <Play size={15} />}
              {enabled ? '暫停' : '啟動'}
            </button>
            <button
              type="button"
              onClick={monitor.clearEvents}
              className="inline-flex h-9 items-center gap-2 rounded-md border border-slate-700 bg-slate-900 px-3 text-xs font-semibold text-slate-400 transition-colors hover:text-white"
            >
              <Eraser size={15} />
              清空
            </button>
          </div>
        </div>

        <div className="grid gap-3 border-t border-slate-800/70 px-4 py-3 xl:grid-cols-[minmax(280px,1fr)_auto]">
          <div className="flex min-w-0 items-center gap-2">
            <input
              value={symbolsText}
              onChange={(event) => setSymbolsText(event.target.value)}
              className="h-10 min-w-0 flex-1 rounded-md border border-slate-700 bg-[#060A10] px-3 text-sm text-white outline-none transition-colors placeholder:text-slate-600 focus:border-cyan-500"
              placeholder="輸入監控股票代號，例如 2330, 2317, 2454"
            />
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,.txt"
              className="hidden"
              onChange={(event) => void importCsv(event.target.files?.[0])}
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="inline-flex h-10 items-center gap-2 rounded-md border border-slate-700 bg-slate-900 px-3 text-xs font-semibold text-slate-300 transition-colors hover:text-white"
            >
              <Upload size={15} />
              匯入 CSV
            </button>
            <button
              type="button"
              onClick={applyConfig}
              className="inline-flex h-10 items-center gap-2 rounded-md bg-cyan-500 px-4 text-xs font-black tracking-widest text-slate-950 transition-colors hover:bg-cyan-300"
            >
              <Settings2 size={15} />
              套用
            </button>
          </div>

          <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-7">
            <NumberInput label="現貨張數" value={draftConfig.stockLotThreshold} onChange={(value) => updateNumber('stockLotThreshold', value)} />
            <NumberInput label="權證張數" value={draftConfig.warrantLotThreshold} onChange={(value) => updateNumber('warrantLotThreshold', value)} />
            <NumberInput label="急拉秒數" value={draftConfig.moveWindowSec} onChange={(value) => updateNumber('moveWindowSec', value)} />
            <NumberInput label="急拉幅度%" value={draftConfig.movePctThreshold} step={0.1} onChange={(value) => updateNumber('movePctThreshold', value)} />
            <NumberInput label="連續秒數" value={draftConfig.continuousWindowSec} onChange={(value) => updateNumber('continuousWindowSec', value)} />
            <NumberInput label="連續筆數" value={draftConfig.continuousMinCount} onChange={(value) => updateNumber('continuousMinCount', value)} />
            <NumberInput label="權證上限" value={draftConfig.maxWarrantsPerStock} onChange={(value) => updateNumber('maxWarrantsPerStock', value)} />
          </div>
        </div>
      </section>

      <main className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_380px]">
        <section className="flex min-h-0 flex-col border-r border-slate-800">
          <div className="grid shrink-0 grid-cols-3 border-b border-slate-800 bg-[#09111B] text-xs">
            <MetricTile label="買盤訊號" value={stats.buy} cls="text-red-300" />
            <MetricTile label="賣盤訊號" value={stats.sell} cls="text-emerald-300" />
            <MetricTile label="權現連動" value={stats.warrant} cls="text-yellow-200" />
          </div>

          <div className="min-h-0 flex-1 overflow-auto custom-scrollbar">
            <div className="min-w-[1040px]">
              <div className="sticky top-0 z-10 grid grid-cols-[118px_150px_174px_96px_96px_210px_minmax(220px,1fr)] border-b border-slate-700 bg-[#0B1220] px-3 py-2 text-[11px] font-bold tracking-widest text-slate-500">
                <span>時間</span>
                <span>代號名稱</span>
                <span>事件類型</span>
                <span className="text-right">成交價</span>
                <span className="text-right">張數</span>
                <span>籌碼標籤</span>
                <span>訊息</span>
              </div>

              {monitor.events.length === 0 ? (
                <div className="flex h-[420px] flex-col items-center justify-center gap-3 text-slate-600">
                  {monitor.connectionState === 'open' ? <Wifi size={28} /> : <WifiOff size={28} />}
                  <p className="text-sm text-slate-500">等待符合條件的盤中訊號</p>
                  {monitor.error && <p className="text-xs text-red-300">{monitor.error}</p>}
                </div>
              ) : (
                monitor.events.map((event) => (
                  <SignalRow key={event.id} event={event} onSelect={() => setSelectedSymbol(event.related_symbol || event.symbol)} />
                ))
              )}
            </div>
          </div>
        </section>

        <aside className="min-h-0 overflow-auto bg-[#070B12] custom-scrollbar">
          <DetailPanel
            selectedSymbol={selectedSymbol}
            snapshot={snapshot}
            error={microError}
            onSelectSymbol={setSelectedSymbol}
          />
        </aside>
      </main>
    </div>
  );
}

function NumberInput({
  label,
  value,
  step = 1,
  onChange,
}: {
  label: string;
  value: number;
  step?: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="flex h-10 min-w-[96px] items-center gap-2 rounded-md border border-slate-800 bg-[#060A10] px-2">
      <span className="whitespace-nowrap text-[10px] font-semibold text-slate-500">{label}</span>
      <input
        type="number"
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="min-w-0 flex-1 bg-transparent text-right text-xs font-bold text-slate-100 outline-none"
      />
    </label>
  );
}

function MetricTile({ label, value, cls }: { label: string; value: number; cls: string }) {
  return (
    <div className="border-r border-slate-800 px-4 py-3 last:border-r-0">
      <div className="text-[11px] font-semibold tracking-widest text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-black tabular-nums ${cls}`}>{value.toLocaleString('zh-TW')}</div>
    </div>
  );
}

function SignalRow({ event, onSelect }: { event: MonitorSignalEvent; onSelect: () => void }) {
  const isBuy = event.side === 'buy';
  const bg = isBuy
    ? 'border-l-red-400 bg-red-500/[0.08] hover:bg-red-500/[0.13]'
    : 'border-l-emerald-400 bg-emerald-500/[0.08] hover:bg-emerald-500/[0.13]';
  const sideText = isBuy ? 'text-red-300' : 'text-emerald-300';

  return (
    <button
      type="button"
      onClick={onSelect}
      className={`grid w-full grid-cols-[118px_150px_174px_96px_96px_210px_minmax(220px,1fr)] items-center border-b border-slate-900 border-l-2 px-3 py-2 text-left text-xs transition-colors ${bg}`}
    >
      <span className="font-mono text-slate-400">{event.time}</span>
      <span className="min-w-0">
        <span className="font-mono font-black text-yellow-200">{event.related_symbol || event.symbol}</span>
        <span className="ml-2 inline-block max-w-[82px] truncate align-bottom text-slate-400">{event.related_name || event.name}</span>
      </span>
      <span className={`inline-flex min-w-0 items-center gap-2 font-bold ${sideText}`}>
        {signalIcon(event)}
        <span className="truncate">{event.event_label}</span>
      </span>
      <span className="text-right font-mono font-bold text-slate-100">{formatNumber(event.price, event.price < 10 ? 2 : 1)}</span>
      <span className="text-right font-mono font-bold text-white">{formatNumber(event.volume)}</span>
      <span className="truncate text-[11px] text-yellow-200">{event.tag || '-'}</span>
      <span className="truncate text-slate-300">{event.message}</span>
    </button>
  );
}

function DetailPanel({
  selectedSymbol,
  snapshot,
  error,
  onSelectSymbol,
}: {
  selectedSymbol: string;
  snapshot: ReturnType<typeof useMonitorMicroSnapshot>['snapshot'];
  error: string | null;
  onSelectSymbol: (symbol: string) => void;
}) {
  return (
    <div className="flex min-h-full flex-col">
      <div className="border-b border-slate-800 px-4 py-3">
        <div className="text-[11px] font-bold tracking-[0.28em] text-slate-500">DETAIL PANEL</div>
        <div className="mt-2 flex items-baseline justify-between gap-3">
          <div>
            <div className="font-mono text-xl font-black text-white">{snapshot?.symbol || selectedSymbol}</div>
            <div className="mt-1 text-xs text-slate-400">{snapshot?.name || '讀取中'}</div>
          </div>
          {error && <span className="text-xs text-red-300">{error}</span>}
        </div>
      </div>

      <section className="border-b border-slate-800 px-4 py-3">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-bold tracking-widest text-slate-300">最佳五檔</h3>
          <span className={snapshot?.order_book.source === 'live_bidask' ? 'text-[11px] text-cyan-300' : 'text-[11px] text-slate-500'}>
            {snapshot?.order_book.source === 'live_bidask' ? 'LIVE BIDASK' : 'SNAPSHOT'}
          </span>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-3">
          <BookSide title="委買" levels={snapshot?.order_book.bid ?? []} side="bid" />
          <BookSide title="委賣" levels={snapshot?.order_book.ask ?? []} side="ask" />
        </div>
      </section>

      <section className="border-b border-slate-800 px-4 py-3">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-bold tracking-widest text-slate-300">權現連動</h3>
          <span className="text-[11px] text-slate-500">{snapshot?.underlying_symbol ?? selectedSymbol}</span>
        </div>
        <div className="mt-3 space-y-2">
          {(snapshot?.related_warrants ?? []).length === 0 ? (
            <div className="rounded-md border border-slate-800 bg-slate-950/60 px-3 py-4 text-center text-xs text-slate-600">
              尚無相關權證即時成交
            </div>
          ) : (
            snapshot?.related_warrants.map((item) => (
              <button
                key={item.symbol}
                type="button"
                onClick={() => onSelectSymbol(item.symbol)}
                className="grid w-full grid-cols-[68px_1fr_64px_70px] items-center gap-2 rounded-md border border-slate-800 bg-slate-950/60 px-3 py-2 text-left text-xs transition-colors hover:border-cyan-500/40"
              >
                <span className={item.cp === 'call' ? 'font-mono font-bold text-red-300' : 'font-mono font-bold text-emerald-300'}>
                  {item.symbol}
                </span>
                <span className="truncate text-slate-400">{item.name}</span>
                <span className="text-right font-mono text-slate-200">{formatNumber(item.last_price, 2)}</span>
                <span className="text-right font-mono font-bold text-yellow-200">{formatNumber(item.volume)}</span>
              </button>
            ))
          )}
        </div>
      </section>

      <section className="min-h-0 flex-1 px-4 py-3">
        <h3 className="text-xs font-bold tracking-widest text-slate-300">最近成交</h3>
        <div className="mt-3 overflow-hidden rounded-md border border-slate-800">
          {(snapshot?.tape ?? []).length === 0 ? (
            <div className="bg-slate-950/60 px-3 py-6 text-center text-xs text-slate-600">等待 tick</div>
          ) : (
            snapshot?.tape.slice(0, 18).map((tick, index) => (
              <div
                key={`${tick.ts}-${tick.symbol}-${index}`}
                className="grid grid-cols-[70px_1fr_74px_66px] border-b border-slate-900 bg-slate-950/50 px-3 py-1.5 text-xs last:border-b-0"
              >
                <span className="font-mono text-slate-500">{tick.ts}</span>
                <span className="truncate text-slate-400">{tick.name || tick.symbol}</span>
                <span className={tick.tick_dir === 'OUTER' ? 'text-right font-mono text-red-300' : tick.tick_dir === 'INNER' ? 'text-right font-mono text-emerald-300' : 'text-right font-mono text-slate-300'}>
                  {formatNumber(tick.price, tick.price < 10 ? 2 : 1)}
                </span>
                <span className="text-right font-mono text-yellow-200">{formatNumber(tick.volume)}</span>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}

function BookSide({
  title,
  levels,
  side,
}: {
  title: string;
  levels: Array<{ price: number; volume: number }>;
  side: 'bid' | 'ask';
}) {
  const color = side === 'bid' ? 'text-red-300' : 'text-emerald-300';
  return (
    <div className="overflow-hidden rounded-md border border-slate-800 bg-slate-950/60">
      <div className={`border-b border-slate-800 px-3 py-2 text-xs font-bold ${color}`}>{title}</div>
      {levels.length === 0 ? (
        <div className="px-3 py-6 text-center text-xs text-slate-600">等待快照</div>
      ) : (
        levels.map((level, index) => (
          <div key={`${side}-${index}`} className="grid grid-cols-2 border-b border-slate-900 px-3 py-1.5 text-xs last:border-b-0">
            <span className={`font-mono font-bold ${color}`}>{formatNumber(level.price, level.price < 10 ? 2 : 1)}</span>
            <span className="text-right font-mono text-slate-300">{formatNumber(level.volume)}</span>
          </div>
        ))
      )}
    </div>
  );
}
