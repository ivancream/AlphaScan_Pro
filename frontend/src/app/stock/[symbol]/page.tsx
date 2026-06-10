import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Virtuoso } from 'react-virtuoso';
import {
  AlertCircle,
  BarChart3,
  CandlestickChart as CandlestickIcon,
  LineChart,
  ListOrdered,
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

type Tab = 'kline' | 'intraday' | 'ticks' | 'large-order-flow';

const TABS: { id: Tab; icon: React.ReactNode; label: string }[] = [
  { id: 'kline', icon: <CandlestickIcon size={15} />, label: 'K 線' },
  { id: 'intraday', icon: <TrendingUp size={15} />, label: '分時' },
  { id: 'ticks', icon: <ListOrdered size={15} />, label: '逐筆' },
  { id: 'large-order-flow', icon: <BarChart3 size={15} />, label: '大單流' },
];

const INDICATOR_OPTIONS: IndicatorType[] = ['Volume', 'MACD', 'RSI', 'KD', 'Bias', 'OBV', 'RS', 'None'];

function formatNumber(value: number | string | null | undefined, digits = 0): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return '-';
  return n.toLocaleString('zh-TW', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function priceDigits(value: number | string | null | undefined) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 2;
  return n < 10 ? 2 : n < 1000 ? 1 : 0;
}

function formatPrice(value: number | string | null | undefined) {
  return formatNumber(value, priceDigits(value));
}

function ErrorBlock({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="m-5 flex items-start gap-4 rounded-md border border-orange-500/30 bg-orange-500/10 p-5">
      <AlertCircle size={20} className="mt-0.5 shrink-0 text-orange-300" />
      <div className="flex-1">
        <p className="text-sm font-semibold text-orange-200">{message}</p>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="mt-3 inline-flex items-center gap-2 rounded-md border border-orange-500/30 bg-orange-500/10 px-3 py-1.5 text-xs font-bold text-orange-200 transition-colors hover:bg-orange-500/20"
          >
            <RefreshCw size={12} />
            重試
          </button>
        )}
      </div>
    </div>
  );
}

function TapeRow({ tick }: { tick: UnifiedTick }) {
  const isOuter = tick.tick_dir === 'OUTER';
  const isInner = tick.tick_dir === 'INNER';
  const priceAccent = isOuter ? 'text-up' : isInner ? 'text-down' : 'text-slate-300';
  const dirLabel = isOuter ? '外盤' : isInner ? '內盤' : '中性';
  const dirBadge = isOuter
    ? 'border-red-500/30 bg-red-500/10 text-red-300'
    : isInner
      ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
      : 'border-slate-700 bg-slate-800/40 text-slate-500';

  return (
    <div className="market-number grid grid-cols-[88px_1fr_88px_72px_72px] items-center border-b border-[var(--as-border)] px-4 py-2 text-sm hover:bg-white/[0.035]">
      <span className="text-xs text-slate-500">{tick.ts}</span>
      <span className={`text-right font-black ${priceAccent}`}>{formatPrice(tick.price)}</span>
      <span className={`text-right text-xs ${tick.pct_chg >= 0 ? 'text-up' : 'text-down'}`}>
        {tick.pct_chg > 0 ? '+' : ''}
        {tick.pct_chg.toFixed(2)}%
      </span>
      <span className="text-right text-xs text-slate-400">{tick.volume.toLocaleString()}</span>
      <span className="flex justify-end">
        <span className={`rounded border px-2 py-0.5 text-[10px] font-bold ${dirBadge}`}>{dirLabel}</span>
      </span>
    </div>
  );
}

function IndicatorSelect({
  label,
  value,
  onChange,
}: {
  label: string;
  value: IndicatorType;
  onChange: (v: IndicatorType) => void;
}) {
  return (
    <label className="flex items-center gap-2 rounded-md border border-[var(--as-border)] bg-[var(--as-card-soft)] px-2 py-1">
      <span className="text-[10px] font-bold text-[var(--as-muted)]">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as IndicatorType)}
        className="bg-transparent text-xs font-bold text-slate-200 outline-none"
      >
        {INDICATOR_OPTIONS.map((opt) => (
          <option key={opt} value={opt} className="bg-[#1B1F29] text-white">
            {opt}
          </option>
        ))}
      </select>
    </label>
  );
}

export default function StockDetailPage() {
  const params = useParams<{ symbol: string }>();
  const setSymbol = useAppStore((state) => state.setSymbol);
  const selectedSymbol = useAppStore((state) => state.selectedSymbol);

  const symbol = cleanStockSymbol(params?.symbol ?? '');
  const [activeTab, setActiveTab] = useState<Tab>('kline');
  const [indicator1, setIndicator1] = useState<IndicatorType>('Volume');
  const [indicator2, setIndicator2] = useState<IndicatorType>('KD');

  useEffect(() => {
    if (!symbol) return;
    if (symbol !== selectedSymbol) {
      setSymbol(symbol);
    }
  }, [symbol, selectedSymbol, setSymbol]);

  const liveSymbols = useMemo(() => (symbol ? [symbol] : []), [symbol]);
  const { data: marketData, isError: marketError, refetch: refetchMarket } = useHistoricalData(symbol, 400);
  const { data: technicalData } = useTechnicalIndicators(symbol, !!symbol);
  const { quotesByStockId, lastHeartbeat } = useLiveQuotes(liveSymbols);
  const { connectionState: tapeState, stockTicks, latestStockTick } = useStockTape(symbol);

  const liveQuote = quotesByStockId[symbol];
  const snapshot = marketData?.snapshot;
  const summary = technicalData?.summary ?? {};

  const displayPrice = liveQuote?.last_price ?? snapshot?.last_price;
  const displayChange = liveQuote?.change_pct ?? snapshot?.change_pct;
  const displayVolume = liveQuote?.volume ?? snapshot?.volume;
  const displayVwap = snapshot?.vwap;
  const isUp = Number(displayChange) >= 0;

  const referencePrice = useMemo(() => {
    const rows = marketData?.data;
    return rows?.length ? rows[rows.length - 1]?.close : undefined;
  }, [marketData]);

  const handleTabClick = useCallback((tab: Tab) => setActiveTab(tab), []);

  const tickStats = useMemo(() => {
    let outer = 0;
    let inner = 0;
    for (const tick of stockTicks) {
      if (tick.tick_dir === 'OUTER') outer += tick.volume;
      if (tick.tick_dir === 'INNER') inner += tick.volume;
    }
    const total = outer + inner;
    return {
      outer,
      inner,
      outerRatio: total ? Math.round((outer / total) * 100) : 50,
    };
  }, [stockTicks]);

  return (
    <div className="flex h-full flex-col overflow-hidden bg-[var(--as-bg)] text-[var(--as-text)]">
      <header className="shrink-0 border-b border-[var(--as-border)] bg-[var(--as-bg-soft)] px-5 py-3">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex min-w-0 items-center gap-5">
            <div>
              <div className="flex items-center gap-2">
                <h1 className="market-number text-3xl font-black leading-none text-white">{symbol}</h1>
                <span className="rounded border border-[var(--as-border)] bg-[var(--as-card)] px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
                  TWSE
                </span>
              </div>
              <div className="mt-2 flex items-center gap-3 text-[11px] text-[var(--as-muted)]">
                <span className="inline-flex items-center gap-1">
                  <Radio size={11} className={tapeState === 'open' ? 'text-[var(--as-green)]' : 'text-[var(--as-yellow)]'} />
                  Tape {tapeState}
                </span>
                <span>Session {marketData?.session ?? '-'}</span>
                <span>HB {lastHeartbeat ?? '-'}</span>
              </div>
            </div>

            <div className="border-l border-[var(--as-border)] pl-5">
              <div className={`market-number text-3xl font-black leading-none ${isUp ? 'text-up' : 'text-down'}`}>
                {formatPrice(displayPrice)}
              </div>
              <div className={`market-number mt-1 text-sm font-black ${isUp ? 'text-up' : 'text-down'}`}>
                {displayChange != null
                  ? `${Number(displayChange) > 0 ? '+' : ''}${Number(displayChange).toFixed(2)}%`
                  : '-'}
                <span className="ml-3 text-xs font-semibold text-slate-500">Vol {formatNumber(displayVolume)} 張</span>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <HeaderMetric label="VWAP" value={formatPrice(displayVwap)} />
            <HeaderMetric label="MA5" value={formatPrice(summary.MA5)} state={Number(summary.Close) >= Number(summary.MA5) ? 'up' : 'down'} />
            <HeaderMetric label="RSI" value={formatNumber(summary.RSI, 1)} state={Number(summary.RSI) >= 50 ? 'up' : 'down'} />
            <HeaderMetric label="MACD" value={formatNumber(summary.MACD_Hist, 2)} state={Number(summary.MACD_Hist) >= 0 ? 'up' : 'down'} />
          </div>
        </div>
      </header>

      <div className="shrink-0 border-b border-[var(--as-border)] bg-[var(--as-bg-soft)] px-3">
        <div className="flex items-stretch overflow-x-auto">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => handleTabClick(tab.id)}
              className={`flex items-center gap-2 whitespace-nowrap border-b-2 px-5 py-3 text-sm font-black transition-colors ${
                activeTab === tab.id
                  ? 'border-[var(--as-yellow)] bg-[rgba(244,197,66,0.08)] text-[var(--as-yellow)]'
                  : 'border-transparent text-slate-500 hover:bg-white/[0.04] hover:text-slate-200'
              }`}
            >
              {tab.icon}
              {tab.label}
            </button>
          ))}

          {activeTab === 'kline' && (
            <div className="ml-auto flex items-center gap-2 px-3">
              <IndicatorSelect label="P1" value={indicator1} onChange={setIndicator1} />
              <IndicatorSelect label="P2" value={indicator2} onChange={setIndicator2} />
            </div>
          )}

          {activeTab === 'intraday' && latestStockTick && (
            <div className="market-number ml-auto flex items-center gap-3 px-4 text-xs text-slate-500">
              <span>最新</span>
              <span className={`font-black ${latestStockTick.pct_chg >= 0 ? 'text-up' : 'text-down'}`}>
                {formatPrice(latestStockTick.price)}
              </span>
              <span>{latestStockTick.ts}</span>
            </div>
          )}

          {activeTab === 'ticks' && (
            <div className="market-number ml-auto flex items-center px-4 text-[11px] text-slate-500">
              {stockTicks.length.toLocaleString()} ticks
            </div>
          )}
        </div>
      </div>

      <main className="min-h-0 flex-1 overflow-hidden p-4">
        <section className={`h-full min-h-0 ${activeTab === 'kline' ? 'grid gap-4 xl:grid-cols-[minmax(0,1fr)_390px]' : 'hidden'}`}>
          <div className="market-card min-h-0 overflow-hidden">
            {marketError ? (
              <ErrorBlock message="K 線資料讀取失敗，請確認後端 API 狀態。" onRetry={() => refetchMarket()} />
            ) : symbol ? (
              <StockChart symbol={symbol} indicator1={indicator1} indicator2={indicator2} />
            ) : (
              <div className="flex h-full items-center justify-center text-slate-600">載入中...</div>
            )}
          </div>

          <aside className="custom-scrollbar min-h-0 space-y-4 overflow-auto">
            <MarketSummaryCard
              price={displayPrice}
              change={displayChange}
              volume={displayVolume}
              vwap={displayVwap}
              provider={snapshot?.provider ?? liveQuote?.provider}
              timestamp={snapshot?.ts ?? liveQuote?.ts}
            />
            <ChipPowerCard outer={tickStats.outer} inner={tickStats.inner} outerRatio={tickStats.outerRatio} />
            <TechnicalCard summary={summary} />
          </aside>
        </section>

        <section className={`h-full min-h-0 ${activeTab === 'intraday' ? 'block' : 'hidden'}`}>
          {stockTicks.length > 0 ? (
            <div className="market-card h-full min-h-0 overflow-hidden p-2">
              <IntradayChart ticks={stockTicks} referencePrice={referencePrice} />
            </div>
          ) : (
            <EmptyState icon={<Waves size={32} />} title="尚無分時資料" />
          )}
        </section>

        <section className={`h-full min-h-0 ${activeTab === 'ticks' ? 'flex flex-col' : 'hidden'}`}>
          {stockTicks.length === 0 ? (
            <EmptyState icon={<TableProperties size={32} />} title={`尚無 ${symbol} 逐筆資料`} />
          ) : (
            <div className="market-card flex min-h-0 flex-1 flex-col overflow-hidden">
              <div className="grid grid-cols-[88px_1fr_88px_72px_72px] border-b border-[var(--as-border)] bg-[var(--as-card-soft)] px-4 py-2 text-[11px] font-black uppercase tracking-wider text-slate-500">
                <span>時間</span>
                <span className="text-right">成交價</span>
                <span className="text-right">漲跌幅</span>
                <span className="text-right">量</span>
                <span className="text-right">方向</span>
              </div>
              <div className="min-h-0 flex-1">
                <Virtuoso
                  data={stockTicks}
                  style={{ height: '100%' }}
                  defaultItemHeight={40}
                  itemContent={(_index, tick) => <TapeRow tick={tick} />}
                />
              </div>
            </div>
          )}
        </section>

        <section className={`h-full min-h-0 ${activeTab === 'large-order-flow' ? 'block' : 'hidden'}`}>
          <LargeOrderFlow symbol={symbol} stockTicks={stockTicks} />
        </section>
      </main>
    </div>
  );
}

function HeaderMetric({ label, value, state }: { label: string; value: string; state?: 'up' | 'down' }) {
  const cls = state === 'up' ? 'text-up' : state === 'down' ? 'text-down' : 'text-white';
  return (
    <div className="market-card-soft min-w-[92px] px-3 py-2">
      <div className="text-[10px] font-bold uppercase tracking-[0.18em] text-[var(--as-muted)]">{label}</div>
      <div className={`market-number mt-1 text-sm font-black ${cls}`}>{value}</div>
    </div>
  );
}

function MarketSummaryCard({
  price,
  change,
  volume,
  vwap,
  provider,
  timestamp,
}: {
  price: number | undefined;
  change: number | undefined;
  volume: number | undefined;
  vwap: number | undefined;
  provider?: string;
  timestamp?: string;
}) {
  const isUp = Number(change) >= 0;
  return (
    <section className="market-card p-4">
      <PanelTitle icon={<LineChart size={16} />} title="報價摘要" />
      <div className="mt-4 grid grid-cols-2 gap-3">
        <ValueTile label="現價" value={formatPrice(price)} cls={isUp ? 'text-up' : 'text-down'} large />
        <ValueTile label="漲跌幅" value={change != null ? `${Number(change) > 0 ? '+' : ''}${Number(change).toFixed(2)}%` : '-'} cls={isUp ? 'text-up' : 'text-down'} large />
        <ValueTile label="成交量" value={`${formatNumber(volume)} 張`} />
        <ValueTile label="VWAP" value={formatPrice(vwap)} />
      </div>
      <div className="mt-4 flex items-center justify-between border-t border-[var(--as-border)] pt-3 text-[11px] text-slate-500">
        <span>{provider ?? 'provider -'}</span>
        <span className="market-number">{timestamp ?? '-'}</span>
      </div>
    </section>
  );
}

function ChipPowerCard({ outer, inner, outerRatio }: { outer: number; inner: number; outerRatio: number }) {
  return (
    <section className="market-card p-4">
      <PanelTitle icon={<Waves size={16} />} title="買賣力道" />
      <div className="mt-4">
        <div className="mb-2 flex items-center justify-between text-xs font-bold">
          <span className="text-up">外盤 {formatNumber(outer)}</span>
          <span className="text-down">內盤 {formatNumber(inner)}</span>
        </div>
        <div className="h-3 overflow-hidden rounded-full bg-[var(--as-card-soft)]">
          <div
            className="h-full rounded-full bg-gradient-to-r from-[var(--as-red)] to-[var(--as-green)]"
            style={{ width: `${Math.min(100, Math.max(0, outerRatio))}%` }}
          />
        </div>
        <div className="market-number mt-3 text-center text-2xl font-black text-white">{outerRatio}%</div>
      </div>
    </section>
  );
}

function TechnicalCard({ summary }: { summary: Record<string, number | string | undefined> }) {
  const close = Number(summary.Close);
  const ma20 = Number(summary.MA20);
  const rsi = Number(summary.RSI);
  const macd = Number(summary.MACD_Hist);
  return (
    <section className="market-card p-4">
      <PanelTitle icon={<TrendingUp size={16} />} title="技術快照" />
      <div className="mt-4 grid grid-cols-2 gap-3">
        <ValueTile label="收盤" value={formatPrice(summary.Close)} cls="text-white" />
        <ValueTile label="MA20" value={formatPrice(summary.MA20)} cls={close >= ma20 ? 'text-up' : 'text-down'} />
        <ValueTile label="RSI" value={formatNumber(summary.RSI, 1)} cls={rsi >= 50 ? 'text-up' : 'text-down'} />
        <ValueTile label="MACD" value={formatNumber(summary.MACD_Hist, 2)} cls={macd >= 0 ? 'text-up' : 'text-down'} />
      </div>
      <div className="mt-4 rounded-md border border-[var(--as-border)] bg-[var(--as-card-soft)] px-3 py-2 text-xs text-slate-400">
        BOLL <span className="ml-2 font-bold text-[var(--as-yellow)]">{String(summary.BB_Status ?? '-')}</span>
      </div>
    </section>
  );
}

function PanelTitle({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <div className="flex items-center justify-between border-b border-[var(--as-border)] pb-3">
      <h2 className="flex items-center gap-2 text-sm font-black text-white">
        <span className="text-[var(--as-yellow)]">{icon}</span>
        {title}
      </h2>
    </div>
  );
}

function ValueTile({ label, value, cls = 'text-white', large = false }: { label: string; value: string; cls?: string; large?: boolean }) {
  return (
    <div className="rounded-md border border-[var(--as-border)] bg-[var(--as-card-soft)] px-3 py-2">
      <div className="text-[10px] font-bold text-[var(--as-muted)]">{label}</div>
      <div className={`market-number mt-1 truncate font-black ${large ? 'text-xl' : 'text-base'} ${cls}`}>{value}</div>
    </div>
  );
}

function EmptyState({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <div className="market-card flex h-full flex-col items-center justify-center gap-3 text-slate-600">
      <div className="opacity-45">{icon}</div>
      <p className="text-sm font-semibold text-slate-500">{title}</p>
    </div>
  );
}
