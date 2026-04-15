import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import axios from 'axios';
import {
  AlertCircle,
  BarChart3,
  CandlestickChart as CandlestickIcon,
  Clock3,
  GitMerge,
  PackageX,
  Radio,
  RefreshCw,
  ShieldAlert,
  TimerReset,
  Waves,
  Zap,
} from 'lucide-react';

import { CandlestickChart as StockChart } from '@/components/charts/CandlestickChart';
import { useHistoricalData } from '@/hooks/useHistoricalData';
import { useLiveQuotes } from '@/hooks/useLiveQuotes';
import { useStockTape } from '@/hooks/useStockTape';
import { useTechnicalIndicators } from '@/hooks/useTechnical';
import { cleanStockSymbol, toStockDetailPath } from '@/lib/stocks';
import { useAppStore } from '@/store/useAppStore';

const api = axios.create({ baseURL: 'http://localhost:8000/api/v1' });

// ─── Types ────────────────────────────────────────────────────────────────────

type Tab = 'live' | 'chart' | 'correlation' | 'cb';

type CorrelationRow = {
  rank: number;
  peer_id: string;
  peer_name: string;
  correlation: number;
  current_z_score?: number | null;
};

type CorrelationResponse = {
  stock_id: string;
  stock_name: string;
  calc_date: string;
  lookback_days: number;
  results: CorrelationRow[];
};

type CbResult = {
  cb_id: string;
  name: string;
  cb_close?: number | null;
  premium_pct?: number | null;
  arb_pct?: number | null;
  ytp_pct?: number | null;
  days_left?: number | null;
  stock_price?: number | null;
  conv_price?: number | null;
};

type CbByStockResponse = {
  stock_id: string;
  has_cb: boolean;
  results: CbResult[];
};

type TickItem = {
  ts: string;
  last_price: number;
  change_pct: number;
  volume: number;
};

// ─── Skeleton Components ──────────────────────────────────────────────────────

function SkeletonRow() {
  return (
    <div className="flex items-center justify-between rounded-xl border border-gray-800 bg-[#0E1117] px-4 py-3 animate-pulse">
      <div className="space-y-2">
        <div className="h-4 w-20 rounded bg-gray-800" />
        <div className="h-3 w-14 rounded bg-gray-800" />
      </div>
      <div className="h-4 w-12 rounded bg-gray-800" />
      <div className="h-4 w-16 rounded bg-gray-800" />
    </div>
  );
}

function SkeletonCorrRow() {
  return (
    <div className="w-full rounded-xl border border-gray-800 bg-[#0E1117] px-4 py-4 animate-pulse">
      <div className="flex items-center justify-between gap-4">
        <div className="space-y-2">
          <div className="h-4 w-16 rounded bg-gray-800" />
          <div className="h-3 w-28 rounded bg-gray-800" />
        </div>
        <div className="space-y-2 flex flex-col items-end">
          <div className="h-4 w-14 rounded bg-gray-800" />
          <div className="h-3 w-10 rounded bg-gray-800" />
        </div>
      </div>
    </div>
  );
}

function SkeletonCbTable() {
  return (
    <div className="animate-pulse space-y-3 mt-4">
      <div className="h-8 w-full rounded bg-gray-800/60" />
      {[1, 2, 3].map((i) => (
        <div key={i} className="h-12 w-full rounded bg-gray-800/40" />
      ))}
    </div>
  );
}

function SkeletonIndicators() {
  return (
    <div className="grid grid-cols-3 gap-3 mt-4 animate-pulse">
      {[1, 2, 3, 4, 5, 6].map((i) => (
        <div key={i} className="rounded-xl border border-gray-800 bg-[#0E1117] p-4 space-y-2">
          <div className="h-3 w-16 rounded bg-gray-800" />
          <div className="h-5 w-20 rounded bg-gray-800" />
        </div>
      ))}
    </div>
  );
}

// ─── Reusable UI Atoms ────────────────────────────────────────────────────────

function ErrorBlock({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="mt-6 rounded-xl border border-orange-900/50 bg-orange-950/20 p-5 flex items-start gap-4">
      <AlertCircle size={20} className="text-orange-400 shrink-0 mt-0.5" />
      <div className="flex-1">
        <p className="text-orange-300 font-semibold text-sm">{message}</p>
        {onRetry && (
          <button
            onClick={onRetry}
            className="mt-3 inline-flex items-center gap-2 text-xs bg-orange-900/40 hover:bg-orange-900/60 text-orange-300 px-3 py-1.5 rounded-lg transition-colors border border-orange-800/40"
          >
            <RefreshCw size={12} />
            重試
          </button>
        )}
      </div>
    </div>
  );
}

function EmptyState({ icon, title, desc }: { icon: React.ReactNode; title: string; desc?: string }) {
  return (
    <div className="mt-8 flex flex-col items-center justify-center gap-4 py-14 text-center">
      <div className="w-16 h-16 rounded-full bg-gray-800/60 flex items-center justify-center text-gray-600">
        {icon}
      </div>
      <div>
        <p className="text-gray-400 font-semibold">{title}</p>
        {desc && <p className="text-gray-600 text-sm mt-1">{desc}</p>}
      </div>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-2 px-5 py-3.5 text-sm font-bold transition-all border-b-2 whitespace-nowrap ${
        active
          ? 'text-cyan-400 border-cyan-400 bg-cyan-400/5'
          : 'text-gray-500 border-transparent hover:text-gray-300 hover:bg-white/5'
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

function StatBadge({ label, value, accent = 'text-white' }: { label: string; value: React.ReactNode; accent?: string }) {
  return (
    <div className="rounded-xl border border-gray-800 bg-[#0E1117] p-4">
      <div className="text-[10px] uppercase tracking-[0.22em] text-gray-500">{label}</div>
      <div className={`mt-1.5 text-lg font-black font-mono ${accent}`}>{value}</div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function StockDetailPage() {
  const params = useParams<{ symbol: string }>();
  const navigate = useNavigate();
  const setSymbol = useAppStore((state) => state.setSymbol);

  const symbol = cleanStockSymbol(params?.symbol ?? '');
  const [activeTab, setActiveTab] = useState<Tab>('live');

  useEffect(() => {
    if (symbol) setSymbol(symbol);
  }, [setSymbol, symbol]);

  // ── Data fetching ──────────────────────────────────────────────────────────
  const { data: marketData, isLoading: marketLoading, isError: marketError, refetch: refetchMarket } = useHistoricalData(symbol, 400);
  const { data: technicalData, isLoading: technicalLoading } = useTechnicalIndicators(symbol, !!symbol);
  const { quotesByStockId, lastHeartbeat } = useLiveQuotes(symbol ? [symbol] : []);
  const {
    connectionState: tapeConnectionState,
    stockTicks,
    latestStockTick,
    latestFuturesTicks,
  } = useStockTape(symbol);

  const {
    data: correlationData,
    isLoading: correlationLoading,
    isError: correlationError,
    refetch: refetchCorrelation,
  } = useQuery<CorrelationResponse>({
    queryKey: ['stock-correlation', symbol],
    queryFn: async () => {
      const { data } = await api.get(`/correlation/${symbol}`, { params: { top_n: 6 } });
      return data;
    },
    enabled: !!symbol,
    retry: 1,
  });

  const {
    data: cbData,
    isLoading: cbLoading,
    isError: cbError,
    refetch: refetchCb,
  } = useQuery<CbByStockResponse>({
    queryKey: ['stock-cb', symbol],
    queryFn: async () => {
      const { data } = await api.get(`/cb/by-stock/${symbol}`);
      return data;
    },
    enabled: !!symbol,
    retry: 1,
  });

  // ── Live tick accumulation ─────────────────────────────────────────────────
  const liveQuote = quotesByStockId[symbol];
  const [tickHistory, setTickHistory] = useState<Record<string, TickItem[]>>({});

  const liveTickSig = useMemo(
    () => (latestStockTick ? `${latestStockTick.ts}-${latestStockTick.price}-${latestStockTick.volume}` : ''),
    [latestStockTick],
  );

  useEffect(() => {
    if (!latestStockTick || latestStockTick.symbol !== symbol || !liveTickSig) return;
    setTickHistory((prev) => {
      const history = prev[symbol] ?? [];
      if (
        history[0]?.ts === latestStockTick.ts &&
        history[0]?.last_price === latestStockTick.price &&
        history[0]?.volume === latestStockTick.volume
      ) return prev;
      const next: TickItem = {
        ts: latestStockTick.ts,
        last_price: latestStockTick.price,
        change_pct: liveQuote?.change_pct ?? 0,
        volume: latestStockTick.volume,
      };
      return { ...prev, [symbol]: [next, ...history].slice(0, 20) };
    });
  }, [latestStockTick, liveQuote, liveTickSig, symbol]);

  const recentTicks = tickHistory[symbol] ?? [];

  // ── Derived display values ─────────────────────────────────────────────────
  const snapshot = marketData?.snapshot;
  const summary = technicalData?.summary;

  const displayPrice = liveQuote?.last_price ?? snapshot?.last_price;
  const displayChange = liveQuote?.change_pct ?? snapshot?.change_pct;
  const displayVolume = liveQuote?.volume ?? snapshot?.volume;
  const displayVwap = snapshot?.vwap;
  const isUp = Number(displayChange) >= 0;
  const latestTick = recentTicks[0];

  const indicatorSnapshot = useMemo(
    () => [
      { label: '布林狀態',  value: summary?.BB_Status ?? '—' },
      { label: 'VWAP',      value: displayVwap ? Number(displayVwap).toFixed(2) : '—', accent: 'text-cyan-400' },
      { label: 'RSI (14)',  value: summary?.RSI ?? '—' },
      { label: 'MACD 柱',  value: summary?.MACD_Hist ?? '—' },
      { label: 'RS',        value: summary?.RS ?? '—' },
      { label: 'MA20',      value: summary?.MA20 ?? '—' },
    ],
    [summary, displayVwap],
  );

  // ── Tab navigation ─────────────────────────────────────────────────────────
  const handleTabClick = useCallback((tab: Tab) => setActiveTab(tab), []);

  // ─────────────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-full text-gray-200 overflow-y-auto">

      {/* ══ HERO SECTION ══════════════════════════════════════════════════════ */}
      <div className="shrink-0 bg-gradient-to-b from-[#0A0F1E] to-[#080D14] border-b border-gray-800 px-6 pt-6 pb-5">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">

          {/* Left: identity */}
          <div>
            <p className="text-[10px] uppercase tracking-[0.35em] text-gray-600">
              Stock Intelligence Center
            </p>
            <h1 className="mt-1 text-5xl font-black text-white tracking-tight">{symbol}</h1>
            <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-gray-500">
              <span className="inline-flex items-center gap-1.5">
                <Radio
                  size={12}
                  className={tapeConnectionState === 'open' ? 'text-emerald-400' : 'text-amber-400 animate-pulse'}
                />
                Tape {tapeConnectionState}
              </span>
              <span>Session: {marketData?.session ?? 'after_hours'}</span>
              <span>Heartbeat: {lastHeartbeat ?? 'N/A'}</span>
            </div>
          </div>

          {/* Right: price hero */}
          <div className="text-right">
            <div className={`text-5xl font-black tabular-nums ${isUp ? 'text-red-400' : 'text-green-400'}`}>
              {displayPrice ? Number(displayPrice).toFixed(2) : '—'}
            </div>
            <div className={`mt-1.5 text-base font-mono font-bold ${isUp ? 'text-red-300' : 'text-green-300'}`}>
              {displayChange != null
                ? `${Number(displayChange) > 0 ? '▲' : '▼'} ${Math.abs(Number(displayChange)).toFixed(2)}%`
                : '—'}
            </div>
            <div className="mt-1 text-xs text-gray-600 font-mono">
              Vol {displayVolume ? Number(displayVolume).toLocaleString() : '—'} 張
            </div>
          </div>
        </div>

        {/* Metric strip */}
        <div className="mt-5 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          {technicalLoading || marketLoading ? (
            <SkeletonIndicators />
          ) : (
            indicatorSnapshot.map((item) => (
              <StatBadge key={item.label} label={item.label} value={item.value} accent={item.accent} />
            ))
          )}
        </div>
      </div>

      {/* ══ TAB BAR ═══════════════════════════════════════════════════════════ */}
      <div className="shrink-0 flex items-stretch gap-0 bg-[#0A0F1E] border-b border-gray-800 px-2 overflow-x-auto no-scrollbar">
        <TabButton active={activeTab === 'live'}        onClick={() => handleTabClick('live')}        icon={<Waves size={15} />}          label="即時動態" />
        <TabButton active={activeTab === 'chart'}       onClick={() => handleTabClick('chart')}       icon={<CandlestickIcon size={15} />} label="技術分析" />
        <TabButton active={activeTab === 'correlation'} onClick={() => handleTabClick('correlation')} icon={<GitMerge size={15} />}       label="關聯分析" />
        <TabButton active={activeTab === 'cb'}          onClick={() => handleTabClick('cb')}          icon={<BarChart3 size={15} />}      label="可轉債 (CB)" />
      </div>

      {/* ══ TAB CONTENT ═══════════════════════════════════════════════════════ */}
      <div className="flex-1 min-h-0">

        {/* ── Tab 1: 即時動態 ─────────────────────────────────────────────── */}
        <div className={`h-full p-6 ${activeTab === 'live' ? 'block' : 'hidden'}`}>
          <div className="grid grid-cols-1 xl:grid-cols-[1.3fr_0.7fr] gap-6 h-full">

            {/* Live tick list */}
            <div className="bg-[#161B22] border border-gray-800 rounded-2xl p-5 flex flex-col">
              <div className="flex items-center gap-2 mb-4 shrink-0">
                <Waves size={16} className="text-cyan-400" />
                <h3 className="font-bold text-white text-sm uppercase tracking-wider">即時逐筆成交</h3>
                {liveQuote && (
                  <span className="ml-auto text-[10px] font-mono text-emerald-400 animate-pulse">● LIVE</span>
                )}
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4 shrink-0">
                <StatBadge
                  label="串流狀態"
                  value={tapeConnectionState === 'open' ? '已連線' : tapeConnectionState}
                  accent={tapeConnectionState === 'open' ? 'text-emerald-400' : 'text-amber-400'}
                />
                <StatBadge
                  label="最新 Tick"
                  value={latestTick ? latestTick.last_price.toFixed(2) : '—'}
                  accent={latestTick ? (latestTick.change_pct >= 0 ? 'text-red-400' : 'text-green-400') : 'text-white'}
                />
                <StatBadge
                  label="最後心跳"
                  value={lastHeartbeat ? new Date(lastHeartbeat).toLocaleTimeString('zh-TW', { hour12: false }) : '—'}
                  accent="text-cyan-400"
                />
              </div>

              {latestTick && (
                <div className="mb-4 rounded-2xl border border-cyan-900/30 bg-gradient-to-r from-[#0B1320] to-[#0E1117] px-5 py-4 shrink-0">
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <div className="text-[10px] uppercase tracking-[0.28em] text-gray-500">Latest Execution</div>
                      <div className={`mt-1 text-3xl font-black font-mono ${latestTick.change_pct >= 0 ? 'text-red-400' : 'text-green-400'}`}>
                        {latestTick.last_price.toFixed(2)}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className={`text-lg font-black font-mono ${latestTick.change_pct >= 0 ? 'text-red-400' : 'text-green-400'}`}>
                        {latestTick.change_pct > 0 ? '+' : ''}{latestTick.change_pct.toFixed(2)}%
                      </div>
                      <div className="text-xs text-gray-500 font-mono mt-1">
                        成交量 {latestTick.volume.toLocaleString()} 張
                      </div>
                      <div className="text-xs text-gray-600 font-mono mt-1">
                        {latestTick.ts}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              <div className="flex-1 space-y-2 overflow-y-auto min-h-0">
                {recentTicks.length === 0 ? (
                  <EmptyState
                    icon={tapeConnectionState === 'open' ? <TimerReset size={28} /> : <ShieldAlert size={28} />}
                    title={tapeConnectionState === 'open' ? '等待即時資料串流中' : '尚未建立有效即時連線'}
                    desc={
                      tapeConnectionState === 'open'
                        ? '已串接股票與期貨共同報價流，若目前非盤中則可能暫無新成交。'
                        : '請確認後端 WS 與永豐／fallback 行情來源是否正常。'
                    }
                  />
                ) : (
                  recentTicks.map((tick) => (
                    <div
                      key={`${tick.ts}-${tick.last_price}-${tick.volume}`}
                      className="grid grid-cols-[1.2fr_0.8fr_0.8fr_0.8fr] items-center rounded-xl border border-gray-800 bg-[#0B0E11] px-4 py-3 hover:border-gray-700 transition-colors"
                    >
                      <div>
                        <div className="text-[10px] uppercase tracking-[0.22em] text-gray-600">Time</div>
                        <div className="text-xs text-gray-400 font-mono mt-1">{tick.ts}</div>
                      </div>
                      <div>
                        <div className="text-[10px] uppercase tracking-[0.22em] text-gray-600">Price</div>
                        <div className={`font-mono text-base font-bold mt-1 ${tick.change_pct >= 0 ? 'text-red-400' : 'text-green-400'}`}>
                          {tick.last_price.toFixed(2)}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] uppercase tracking-[0.22em] text-gray-600">Change</div>
                        <div className={`font-mono text-sm font-bold mt-1 ${tick.change_pct >= 0 ? 'text-red-400' : 'text-green-400'}`}>
                          {tick.change_pct > 0 ? '+' : ''}{tick.change_pct.toFixed(2)}%
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="text-[10px] uppercase tracking-[0.22em] text-gray-600">Volume</div>
                        <div className="text-sm text-gray-300 font-mono mt-1">{tick.volume.toLocaleString()} 張</div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Futures + indicators */}
            <div className="space-y-6">
            <div className="bg-[#161B22] border border-gray-800 rounded-2xl p-5">
              <div className="flex items-center gap-2 mb-4">
                <Clock3 size={16} className="text-cyan-400" />
                <h3 className="font-bold text-white text-sm uppercase tracking-wider">期貨聯動報價</h3>
                <span className="ml-auto text-[10px] text-gray-600">TXF / MXF 近月</span>
              </div>
              {latestFuturesTicks.length === 0 ? (
                <EmptyState
                  icon={<Clock3 size={28} />}
                  title="尚未收到期貨即時報價"
                  desc="會與個股頁同步監看近月台指與小台期。"
                />
              ) : (
                <div className="space-y-2">
                  {latestFuturesTicks.map((tick) => (
                    <div
                      key={`${tick.symbol}-${tick.ts}-${tick.price}-${tick.volume}`}
                      className="rounded-xl border border-gray-800 bg-[#0B0E11] px-4 py-3"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <div className="font-mono font-black text-cyan-300">{tick.symbol}</div>
                          <div className="text-xs text-gray-500 mt-0.5">{tick.name}</div>
                        </div>
                        <div className="text-right">
                          <div className="font-mono text-lg font-black text-white">{tick.price.toFixed(2)}</div>
                          <div className="text-xs text-gray-500 mt-0.5">{tick.volume.toLocaleString()} 口</div>
                        </div>
                      </div>
                      <div className="mt-2 text-[11px] text-gray-600 font-mono">{tick.ts}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="bg-[#161B22] border border-gray-800 rounded-2xl p-5">
              <div className="flex items-center gap-2 mb-4">
                <BarChart3 size={16} className="text-amber-400" />
                <h3 className="font-bold text-white text-sm uppercase tracking-wider">技術指標快照</h3>
                <span className="ml-auto text-[10px] text-gray-600">
                  {marketData?.session === 'live' ? '盤中即時' : '盤後快照'}
                </span>
              </div>
              {technicalLoading || marketLoading ? (
                <SkeletonIndicators />
              ) : (
                <div className="grid grid-cols-2 gap-3">
                  {indicatorSnapshot.map((item) => (
                    <StatBadge key={item.label} label={item.label} value={item.value} accent={item.accent} />
                  ))}
                </div>
              )}
              {marketError && (
                <ErrorBlock
                  message="無法載入技術數據，請確認後端 API 是否正常運作。"
                  onRetry={() => refetchMarket()}
                />
              )}
            </div>
            </div>
          </div>
        </div>

        {/* ── Tab 2: 技術分析 ─────────────────────────────────────────────── */}
        {/*
          Keep mounted but hidden so Lightweight Charts doesn't get destroyed
          on tab switch. The ResizeObserver will re-measure when revealed.
        */}
        <div className={`h-full p-6 ${activeTab === 'chart' ? 'flex flex-col' : 'hidden'}`}>
          <div className="bg-[#0B0E11] border border-gray-800 rounded-2xl overflow-hidden flex flex-col flex-1 min-h-0">
            <div className="flex items-center gap-2 px-6 py-4 border-b border-gray-800 shrink-0">
              <CandlestickIcon size={16} className="text-amber-400" />
              <h3 className="font-bold text-white text-sm uppercase tracking-wider">技術 K 線</h3>
              <span className="ml-2 text-xs text-gray-600">Lightweight Charts · 近 400 交易日</span>
            </div>
            <div className="flex-1 min-h-0">
              {symbol ? (
                <StockChart symbol={symbol} indicator1="Volume" indicator2="KD" />
              ) : (
                <div className="flex items-center justify-center h-full text-gray-600">載入中...</div>
              )}
            </div>
          </div>
        </div>

        {/* ── Tab 3: 關聯分析 ─────────────────────────────────────────────── */}
        <div className={`h-full p-6 overflow-y-auto ${activeTab === 'correlation' ? 'block' : 'hidden'}`}>
          <div className="bg-[#161B22] border border-gray-800 rounded-2xl p-5 max-w-2xl">
            <div className="flex items-center gap-2 mb-1">
              <GitMerge size={16} className="text-amber-400" />
              <h3 className="font-bold text-white text-sm uppercase tracking-wider">相關係數排行</h3>
              {correlationData && (
                <span className="ml-auto text-[10px] font-mono text-gray-600">
                  回測 {correlationData.lookback_days} 交易日 · {correlationData.calc_date}
                </span>
              )}
            </div>
            <p className="text-xs text-gray-600 mb-4 ml-0.5">
              Pearson 相關係數，點擊任一列跳轉至該標的情報中心。
            </p>

            {correlationLoading ? (
              <div className="space-y-2">
                {[...Array(6)].map((_, i) => <SkeletonCorrRow key={i} />)}
              </div>
            ) : correlationError ? (
              <ErrorBlock
                message="相關係數計算失敗，請確認後端 correlation API 是否正常。"
                onRetry={() => refetchCorrelation()}
              />
            ) : correlationData?.results?.length ? (
              <div className="space-y-2">
                {correlationData.results.map((row) => (
                  <button
                    key={row.peer_id}
                    type="button"
                    onClick={() => {
                      setSymbol(cleanStockSymbol(row.peer_id));
                      navigate(toStockDetailPath(row.peer_id));
                    }}
                    className="w-full rounded-xl border border-gray-800 bg-[#0E1117] px-4 py-3.5 text-left hover:border-cyan-700/50 hover:bg-[#0d1520] transition-colors group"
                  >
                    <div className="flex items-center justify-between gap-4">
                      <div>
                        <div className="font-mono font-black text-white group-hover:text-cyan-300 transition-colors">
                          {row.peer_id}
                        </div>
                        <div className="text-xs text-gray-500 mt-0.5">{row.peer_name}</div>
                      </div>
                      <div className="text-right shrink-0">
                        <div className="font-mono font-bold text-amber-300">{row.correlation.toFixed(4)}</div>
                        {row.current_z_score != null && (
                          <div className={`text-xs font-mono mt-0.5 ${Number(row.current_z_score) >= 0 ? 'text-red-400' : 'text-green-400'}`}>
                            Z: {Number(row.current_z_score) > 0 ? '+' : ''}{Number(row.current_z_score).toFixed(2)}
                          </div>
                        )}
                      </div>
                    </div>
                    {/* Correlation bar */}
                    <div className="mt-3 h-1 rounded-full bg-gray-800 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-amber-400/70 transition-all duration-500"
                        style={{ width: `${(row.correlation * 100).toFixed(1)}%` }}
                      />
                    </div>
                  </button>
                ))}
              </div>
            ) : (
              <EmptyState
                icon={<GitMerge size={28} />}
                title="目前無足夠數據計算關聯性"
                desc="請確認此標的已有足夠的歷史交易紀錄（至少 60 個交易日）"
              />
            )}
          </div>
        </div>

        {/* ── Tab 4: 可轉債 CB ────────────────────────────────────────────── */}
        <div className={`h-full p-6 overflow-y-auto ${activeTab === 'cb' ? 'block' : 'hidden'}`}>
          <div className="bg-[#161B22] border border-gray-800 rounded-2xl p-5">
            <div className="flex items-center gap-2 mb-1">
              <BarChart3 size={16} className="text-cyan-400" />
              <h3 className="font-bold text-white text-sm uppercase tracking-wider">可轉債 (CB) 資訊</h3>
              {cbData?.has_cb && (
                <span className="ml-auto text-[10px] text-cyan-400 font-mono border border-cyan-800/50 bg-cyan-900/20 px-2 py-0.5 rounded">
                  {cbData.results.length} 檔流通中
                </span>
              )}
            </div>
            <p className="text-xs text-gray-600 mb-4 ml-0.5">
              CB 溢價率、套利報酬率與賣回殖利率。
            </p>

            {cbLoading ? (
              <SkeletonCbTable />
            ) : cbError ? (
              <ErrorBlock
                message="可轉債資料載入失敗，請確認後端 CB API 是否正常。"
                onRetry={() => refetchCb()}
              />
            ) : cbData?.has_cb && cbData.results.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm text-gray-300">
                  <thead className="bg-[#0E1117] border-b border-gray-800">
                    <tr>
                      {['CB 代號', '名稱', 'CB 收盤', '現貨', '轉換價', '溢價率%', '套利%', 'YTP%', '剩餘天數'].map((h) => (
                        <th key={h} className="px-4 py-3 text-[10px] uppercase tracking-wider text-gray-500 font-black first:rounded-tl-lg last:rounded-tr-lg">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-800">
                    {cbData.results.map((row) => {
                      const isHighPremium = (row.premium_pct ?? 0) > 20;
                      const isGoodYtp = (row.ytp_pct ?? 0) >= 3;
                      return (
                        <tr key={row.cb_id} className="hover:bg-[#1C2128] transition-colors">
                          <td className="px-4 py-3 font-mono font-black text-amber-300">{row.cb_id}</td>
                          <td className="px-4 py-3 font-medium text-white">{row.name}</td>
                          <td className="px-4 py-3 font-mono text-gray-300">{row.cb_close?.toFixed(2) ?? '—'}</td>
                          <td className="px-4 py-3 font-mono text-gray-400">{row.stock_price?.toFixed(2) ?? '—'}</td>
                          <td className="px-4 py-3 font-mono text-gray-400">{row.conv_price?.toFixed(2) ?? '—'}</td>
                          <td className={`px-4 py-3 font-mono font-bold ${isHighPremium ? 'text-red-400' : 'text-gray-300'}`}>
                            {row.premium_pct?.toFixed(2) ?? '—'}%
                          </td>
                          <td className="px-4 py-3 font-mono text-gray-300">{row.arb_pct?.toFixed(2) ?? '—'}%</td>
                          <td className={`px-4 py-3 font-mono font-bold ${isGoodYtp ? 'text-green-400' : 'text-gray-400'}`}>
                            {row.ytp_pct?.toFixed(2) ?? '—'}%
                          </td>
                          <td className="px-4 py-3 font-mono text-gray-400">{row.days_left ?? '—'}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>

                {/* Legend */}
                <div className="mt-4 flex flex-wrap gap-4 text-[11px] text-gray-600 border-t border-gray-800 pt-3">
                  <span><span className="text-red-400 font-bold">紅色溢價</span> = 溢價率 &gt; 20%（CB 偏貴）</span>
                  <span><span className="text-green-400 font-bold">綠色 YTP</span> = 賣回殖利率 ≥ 3%（具保護性）</span>
                </div>
              </div>
            ) : (
              <EmptyState
                icon={<PackageX size={32} />}
                title="此標的目前無發行可轉債"
                desc="或該標的的 CB 資料尚未收錄於系統數據庫"
              />
            )}
          </div>
        </div>

      </div>
    </div>
  );
}
