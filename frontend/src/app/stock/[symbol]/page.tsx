import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Virtuoso } from 'react-virtuoso';
import {
  AlertCircle,
  BarChart3,
  ListOrdered,
  CandlestickChart as CandlestickIcon,
  Radio,
  RefreshCw,
  TableProperties,
  TrendingUp,
  Waves,
} from 'lucide-react';

import { CandlestickChart as StockChart } from '@/components/charts/CandlestickChart';
import { IntradayChart } from '@/components/charts/IntradayChart';
import { LargeOrderFlow } from '@/components/stock/LargeOrderFlow';
import { useHistoricalData } from '@/hooks/useHistoricalData';
import { useLiveQuotes } from '@/hooks/useLiveQuotes';
import { useStockTape } from '@/hooks/useStockTape';
import { useTechnicalIndicators } from '@/hooks/useTechnical';
import { cleanStockSymbol } from '@/lib/stocks';
import { useAppStore } from '@/store/useAppStore';
import type { IndicatorType } from '@/types/chart';
import type { UnifiedTick } from '@/types/quote';

// ─── Tab 定義 ─────────────────────────────────────────────────────────────────

type Tab = 'kline' | 'intraday' | 'ticks' | 'large-order-flow';

const TABS: { id: Tab; icon: React.ReactNode; label: string }[] = [
  { id: 'kline',    icon: <CandlestickIcon size={15} />, label: '技術K線' },
  { id: 'intraday', icon: <TrendingUp size={15} />,       label: '即時走勢' },
  { id: 'ticks',    icon: <ListOrdered size={15} />,      label: '逐筆明細' },
  { id: 'large-order-flow', icon: <BarChart3 size={15} />, label: '大單進出' },
];

// ─── Chart period (未來擴充 15/60 分K 只需在此加項目) ─────────────────────────

type ChartPeriod = 'daily';
const PERIOD_LABELS: Record<ChartPeriod, string> = { daily: '日K' };

// ─── Shared UI atoms ──────────────────────────────────────────────────────────

function ErrorBlock({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="m-6 rounded-xl border border-orange-900/50 bg-orange-950/20 p-5 flex items-start gap-4">
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

const INDICATOR_OPTIONS: IndicatorType[] = ['Volume', 'MACD', 'RSI', 'KD', 'Bias', 'OBV', 'RS', 'None'];

function TapeRow({ tick }: { tick: UnifiedTick }) {
  const isOuter = tick.tick_dir === 'OUTER';
  const isInner = tick.tick_dir === 'INNER';
  const priceAccent = isOuter ? 'text-red-400' : isInner ? 'text-emerald-400' : 'text-gray-300';
  const dirLabel = isOuter ? '外盤' : isInner ? '內盤' : '—';
  const dirBadge = isOuter
    ? 'bg-red-900/30 text-red-400 border-red-800/30'
    : isInner
      ? 'bg-emerald-900/30 text-emerald-400 border-emerald-800/30'
      : 'bg-gray-800/30 text-gray-500 border-gray-700/30';

  return (
    <div className="flex items-center border-b border-gray-800/50 text-sm font-mono px-4 py-2 hover:bg-white/[0.03]">
      <span className="w-[88px] shrink-0 text-gray-500 text-xs">{tick.ts}</span>
      <span className={`flex-1 text-right font-bold ${priceAccent}`}>{tick.price.toFixed(2)}</span>
      <span className={`w-[88px] text-right text-xs ${tick.pct_chg >= 0 ? 'text-red-400' : 'text-emerald-400'}`}>
        {tick.pct_chg > 0 ? '+' : ''}
        {tick.pct_chg.toFixed(2)}%
      </span>
      <span className="w-[72px] text-right text-gray-400 text-xs">{tick.volume.toLocaleString()}</span>
      <span className="w-[72px] flex justify-end">
        <span className={`text-[10px] font-bold border rounded px-2 py-0.5 ${dirBadge}`}>{dirLabel}</span>
      </span>
    </div>
  );
}

function IndicatorSelect({
  value,
  onChange,
}: {
  value: IndicatorType;
  onChange: (v: IndicatorType) => void;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as IndicatorType)}
      className="bg-[#0E1117] border border-gray-700 text-gray-300 text-xs rounded-md px-2 py-1 focus:outline-none focus:border-amber-600"
    >
      {INDICATOR_OPTIONS.map((opt) => (
        <option key={opt} value={opt}>
          {opt}
        </option>
      ))}
    </select>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function StockDetailPage() {
  const params = useParams<{ symbol: string }>();
  const setSymbol = useAppStore((state) => state.setSymbol);
  const selectedSymbol = useAppStore((state) => state.selectedSymbol);

  const symbol = cleanStockSymbol(params?.symbol ?? '');
  const [activeTab, setActiveTab] = useState<Tab>('kline');
  const [chartPeriod, setChartPeriod] = useState<ChartPeriod>('daily');
  const [indicator1, setIndicator1] = useState<IndicatorType>('Volume');
  const [indicator2, setIndicator2] = useState<IndicatorType>('KD');

  useEffect(() => {
    if (!symbol) return;
    if (symbol !== selectedSymbol) {
      setSymbol(symbol);
    }
  }, [symbol, selectedSymbol, setSymbol]);

  const liveSymbols = useMemo(() => (symbol ? [symbol] : []), [symbol]);

  // ── Data ───────────────────────────────────────────────────────────────────
  const { data: marketData, isError: marketError, refetch: refetchMarket } = useHistoricalData(symbol, 400);
  const { data: technicalData } = useTechnicalIndicators(symbol, !!symbol);
  const { quotesByStockId, lastHeartbeat } = useLiveQuotes(liveSymbols);
  const { connectionState: tapeState, stockTicks, latestStockTick } = useStockTape(symbol);

  // ── Derived ────────────────────────────────────────────────────────────────
  const liveQuote = quotesByStockId[symbol];
  const snapshot  = marketData?.snapshot;
  const summary   = technicalData?.summary;

  const displayPrice  = liveQuote?.last_price ?? snapshot?.last_price;
  const displayChange = liveQuote?.change_pct  ?? snapshot?.change_pct;
  const displayVolume = liveQuote?.volume       ?? snapshot?.volume;
  const displayVwap   = snapshot?.vwap;
  const isUp          = Number(displayChange) >= 0;

  const referencePrice = useMemo(() => {
    const rows = marketData?.data;
    return rows?.length ? rows[rows.length - 1]?.close : undefined;
  }, [marketData]);

  const handleTabClick = useCallback((tab: Tab) => setActiveTab(tab), []);

  // ─────────────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-full text-gray-200 overflow-hidden">

      {/* ══ COMPACT HERO ═══════════════════════════════════════════════════════ */}
      <div className="shrink-0 bg-[#0A0F1E] border-b border-gray-800 px-5 py-3">
        <div className="flex items-start gap-6 flex-wrap">

          {/* 代號 + 連線狀態 */}
          <div className="flex items-center gap-4 shrink-0">
            <div>
              <h1 className="text-3xl font-black text-white tracking-tight leading-none">
                {symbol}
              </h1>
              <div className="mt-1 flex items-center gap-3 text-[11px] text-gray-500">
                <span className="inline-flex items-center gap-1">
                  <Radio
                    size={11}
                    className={tapeState === 'open' ? 'text-emerald-400' : 'text-amber-400 animate-pulse'}
                  />
                  Tape {tapeState}
                </span>
                <span>Session: {marketData?.session ?? 'after_hours'}</span>
                <span>HB: {lastHeartbeat ?? 'N/A'}</span>
              </div>
            </div>

            {/* 報價 */}
            <div>
              <div className={`text-3xl font-black tabular-nums leading-none ${isUp ? 'text-red-400' : 'text-green-400'}`}>
                {displayPrice ? Number(displayPrice).toFixed(2) : '—'}
              </div>
              <div className={`mt-0.5 text-sm font-mono font-bold ${isUp ? 'text-red-300' : 'text-green-300'}`}>
                {displayChange != null
                  ? `${Number(displayChange) > 0 ? '▲' : '▼'} ${Math.abs(Number(displayChange)).toFixed(2)}%`
                  : '—'}
                <span className="ml-3 text-gray-500 font-normal text-xs">
                  Vol {displayVolume ? Number(displayVolume).toLocaleString() : '—'} 張
                </span>
              </div>
            </div>
          </div>

        </div>
      </div>

      {/* ══ TAB BAR ════════════════════════════════════════════════════════════ */}
      <div className="shrink-0 flex items-stretch bg-[#0A0F1E] border-b border-gray-800 px-2 overflow-x-auto no-scrollbar">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => handleTabClick(t.id)}
            className={`flex items-center gap-2 px-5 py-3.5 text-sm font-bold transition-all border-b-2 whitespace-nowrap ${
              activeTab === t.id
                ? 'text-cyan-400 border-cyan-400 bg-cyan-400/5'
                : 'text-gray-500 border-transparent hover:text-gray-300 hover:bg-white/5'
            }`}
          >
            {t.icon}
            {t.label}
          </button>
        ))}

        {/* 技術K線 副圖選擇器 — 只在 kline tab 顯示 */}
        {activeTab === 'kline' && (
          <div className="ml-auto flex items-center gap-3 px-4">
            {(Object.keys(PERIOD_LABELS) as ChartPeriod[]).map((p) => (
              <button
                key={p}
                onClick={() => setChartPeriod(p)}
                className={`px-3 py-1 rounded-md text-xs font-bold transition-colors border ${
                  chartPeriod === p
                    ? 'bg-amber-400/15 text-amber-300 border-amber-700/50'
                    : 'text-gray-500 border-transparent hover:text-gray-300 hover:bg-white/5'
                }`}
              >
                {PERIOD_LABELS[p]}
              </button>
            ))}
            <span className="text-gray-600 text-xs">副圖</span>
            <IndicatorSelect value={indicator1} onChange={setIndicator1} />
            <IndicatorSelect value={indicator2} onChange={setIndicator2} />
          </div>
        )}

        {/* 即時走勢 連線狀態 */}
        {activeTab === 'intraday' && latestStockTick && (
          <div className="ml-auto flex items-center gap-3 px-4 text-xs text-gray-500 font-mono">
            <span>最新成交</span>
            <span className={`font-bold ${latestStockTick.pct_chg >= 0 ? 'text-red-400' : 'text-green-400'}`}>
              {latestStockTick.price.toFixed(2)}
            </span>
            <span>{latestStockTick.ts}</span>
          </div>
        )}

        {/* 逐筆明細 筆數（最多保留 50 筆） */}
        {activeTab === 'ticks' && (
          <div className="ml-auto flex items-center px-4 text-[11px] text-gray-500 font-mono">
            最新 {stockTicks.length} 筆（虛擬捲動）
          </div>
        )}
      </div>

      {/* ══ TAB CONTENT (fill remaining height) ════════════════════════════════ */}
      <div className="flex-1 min-h-0 overflow-hidden">

        {/* ── Tab: 技術K線 ──────────────────────────────────────────────────── */}
        <div className={`h-full flex flex-col ${activeTab === 'kline' ? 'flex' : 'hidden'}`}>
          {marketError ? (
            <ErrorBlock message="無法載入 K 線數據，請確認後端 API 是否正常。" onRetry={() => refetchMarket()} />
          ) : symbol ? (
            <div className="flex-1 min-h-0">
              <StockChart symbol={symbol} indicator1={indicator1} indicator2={indicator2} />
            </div>
          ) : (
            <div className="flex items-center justify-center h-full text-gray-600">載入中...</div>
          )}
        </div>

        {/* ── Tab: 即時走勢 ─────────────────────────────────────────────────── */}
        <div className={`h-full flex flex-col ${activeTab === 'intraday' ? 'flex' : 'hidden'}`}>
          {stockTicks.length > 0 ? (
            <div className="flex-1 min-h-0 px-1 pt-1">
              <IntradayChart ticks={stockTicks} referencePrice={referencePrice} />
            </div>
          ) : (
            <div className="flex items-center justify-center h-full flex-col gap-3 text-gray-600">
              <Waves size={32} className="opacity-40" />
              <p className="text-sm">
                {tapeState === 'open'
                  ? '等待即時資料串流中…'
                  : '尚未建立即時連線，請確認後端 WS 是否正常'}
              </p>
            </div>
          )}
        </div>

        {/* ── Tab: 逐筆明細（單一標的 + 虛擬捲動，最多 50 筆） ───────────────────── */}
        <div className={`h-full min-h-0 flex flex-col ${activeTab === 'ticks' ? 'flex' : 'hidden'}`}>
          {stockTicks.length === 0 ? (
            <div className="flex items-center justify-center h-full flex-col gap-3 text-gray-600">
              <TableProperties size={32} className="opacity-40" />
              <p className="text-sm">等待 {symbol} 逐筆成交…</p>
              <p className="text-xs text-gray-600 max-w-md text-center">
                僅訂閱目前個股代號，與全方位流水報價使用相同後端通道；畫面最多保留 50 筆並以虛擬列表渲染。
              </p>
            </div>
          ) : (
            <div className="flex flex-col flex-1 min-h-0 border-t border-gray-800/60">
              <div className="shrink-0 flex text-[11px] uppercase tracking-wider text-gray-500 font-semibold border-b border-gray-800 bg-[#0A0F1E] px-4 py-2">
                <span className="w-[88px]">時間</span>
                <span className="flex-1 text-right">成交價</span>
                <span className="w-[88px] text-right">漲跌幅</span>
                <span className="w-[72px] text-right">量(張)</span>
                <span className="w-[72px] text-right">方向</span>
              </div>
              <div className="flex-1 min-h-0">
                <Virtuoso
                  data={stockTicks}
                  style={{ height: '100%' }}
                  defaultItemHeight={40}
                  itemContent={(_index, tick) => <TapeRow tick={tick} />}
                />
              </div>
            </div>
          )}
        </div>

        {/* ── Tab: 大單進出 ───────────────────────────────────────────────────── */}
        <div className={`h-full min-h-0 flex flex-col ${activeTab === 'large-order-flow' ? 'flex' : 'hidden'}`}>
          <LargeOrderFlow symbol={symbol} stockTicks={stockTicks} />
        </div>
      </div>
    </div>
  );
}
