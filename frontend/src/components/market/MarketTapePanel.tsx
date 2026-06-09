'use client';

/**
 * MarketTapePanel — 即時內外盤成交瀑布流
 *
 * 資料源：useAllAroundStore (Zustand) → /ws/all-around-ticker（全量推送）
 * 顯示：現貨 + 期貨 + 認購/認售，最新在最上方
 *
 * 顏色規則：
 *   外盤買（OUTER）→ 紅字 + 紅左邊框
 *   內盤賣（INNER）→ 綠字 + 綠左邊框
 *   中性（NONE）   → 灰
 */

import React, { useEffect, useMemo, useState } from 'react';
import { Virtuoso } from 'react-virtuoso';
import { Activity, Filter, Zap } from 'lucide-react';
import type { UnifiedTick, AssetType, TickDir, ChgType } from '@/types/quote';
import { useAllAroundStore } from '@/store/useAllAroundStore';

// ── 色彩映射 ──────────────────────────────────────────────────────────────────

const PRICE_CLS: Record<ChgType, string> = {
  LIMIT_UP:   'text-red-300 font-black',
  UP:         'text-red-400 font-bold',
  FLAT:       'text-gray-200 font-semibold',
  DOWN:       'text-emerald-400 font-bold',
  LIMIT_DOWN: 'text-emerald-300 font-black',
};

const ROW_BORDER: Record<TickDir, string> = {
  OUTER: 'border-l-4 border-l-red-500',
  INNER: 'border-l-4 border-l-emerald-500',
  NONE:  'border-l border-l-gray-800/40 bg-gray-900/20',
};

const DIR_LABEL: Record<TickDir, { text: string; cls: string }> = {
  OUTER: { text: '外盤買', cls: 'text-red-400' },
  INNER: { text: '內盤賣', cls: 'text-emerald-400' },
  NONE:  { text: '中性',   cls: 'text-gray-500' },
};

const ASSET_BADGE: Record<AssetType, { label: string; icon: string; cls: string }> = {
  '現貨': { label: '現貨', icon: '',   cls: 'text-sky-300    bg-sky-900/40    border-sky-700/50' },
  '期貨': { label: '期貨', icon: '📈', cls: 'text-orange-300 bg-orange-900/40 border-orange-700/50' },
  '認購': { label: '認購', icon: '🎫', cls: 'text-red-300    bg-red-900/30    border-red-700/40' },
  '認售': { label: '認售', icon: '🎫', cls: 'text-emerald-300 bg-emerald-900/30 border-emerald-700/40' },
};

function rowTone(tick: UnifiedTick): string {
  if (tick.tick_dir === 'NONE') return 'hover:bg-white/[0.035]';

  const amount = tick.asset_type === '期貨'
    ? tick.volume
    : tick.price * tick.volume * 1000;
  const tier =
    tick.asset_type === '期貨'
      ? amount >= 20 ? 3 : amount >= 5 ? 2 : 1
      : amount >= 20_000_000 ? 3 : amount >= 5_000_000 ? 2 : 1;
  const assetOverlay =
    tick.asset_type === '期貨' ? ' ring-1 ring-orange-400/20'
    : tick.asset_type === '認購' || tick.asset_type === '認售' ? ' ring-1 ring-cyan-400/15'
    : '';

  if (tick.tick_dir === 'OUTER') {
    return [
      tier === 3 ? 'bg-red-950/70 hover:bg-red-950/80'
      : tier === 2 ? 'bg-red-950/50 hover:bg-red-950/65'
      : 'bg-red-950/32 hover:bg-red-950/48',
      'text-red-100',
      assetOverlay,
    ].join(' ');
  }

  return [
    tier === 3 ? 'bg-emerald-950/70 hover:bg-emerald-950/80'
    : tier === 2 ? 'bg-emerald-950/50 hover:bg-emerald-950/65'
    : 'bg-emerald-950/32 hover:bg-emerald-950/48',
    'text-emerald-100',
    assetOverlay,
  ].join(' ');
}

// ── TickRow ───────────────────────────────────────────────────────────────────

interface TickRowProps {
  tick:            UnifiedTick;
  volumeThreshold: number;
}

const TickRow = React.memo(({ tick, volumeThreshold }: TickRowProps) => {
  const badge    = ASSET_BADGE[tick.asset_type] ?? ASSET_BADGE['現貨'];
  const rowBorder = ROW_BORDER[tick.tick_dir]   ?? ROW_BORDER.NONE;
  const dirInfo  = DIR_LABEL[tick.tick_dir]     ?? DIR_LABEL.NONE;
  const isLarge  = tick.volume >= volumeThreshold && volumeThreshold > 0;
  const sign     = tick.pct_chg > 0 ? '+' : '';
  const sideCls = tick.tick_dir === 'OUTER'
    ? 'text-red-50'
    : tick.tick_dir === 'INNER'
    ? 'text-emerald-50'
    : 'text-gray-300';

  return (
    <div
      className={`
        grid items-center px-3 py-2
        border-b border-gray-900/60
        text-sm font-mono select-none
        transition-colors duration-75
        ${rowBorder}
        ${rowTone(tick)}
        ${isLarge ? 'shadow-[inset_0_0_0_1px_rgba(250,204,21,0.12)]' : ''}
      `}
      style={{ gridTemplateColumns: '72px 68px 62px 1fr 78px 76px 72px' }}
    >
      {/* 時間 */}
      <span className="text-gray-300/80 tracking-tight text-xs">{tick.ts}</span>

      {/* 代號 */}
      <span className="text-yellow-200 font-black truncate">{tick.symbol}</span>

      {/* 類別 badge */}
      <span className={`
        text-center text-[11px] font-black rounded px-1.5 py-0.5 border
        ${badge.cls}
      `}>
        {badge.icon && <span className="mr-0.5">{badge.icon}</span>}
        {badge.label}
      </span>

      {/* 名稱 */}
      <span className={`${sideCls} text-xs font-semibold truncate px-1`}>{tick.name}</span>

      {/* 內外盤 */}
      <span className={`text-center text-xs font-black ${dirInfo.cls}`}>
        {dirInfo.text}
      </span>

      {/* 成交價 */}
      <span className={`text-right tabular-nums text-sm font-black ${sideCls}`}>
        {tick.price.toFixed(tick.price < 100 ? 2 : tick.price < 1000 ? 1 : 0)}
      </span>

      {/* 量 + 漲跌幅 */}
      <div className="flex flex-col items-end gap-px">
        <span className={`tabular-nums font-semibold ${
          tick.tick_dir === 'OUTER' ? 'text-red-50'
          : tick.tick_dir === 'INNER' ? 'text-emerald-50'
          : 'text-gray-400'
        } ${isLarge ? 'font-black' : ''}`}>
          {tick.volume.toLocaleString()}
        </span>
        <span className={`text-[9px] tabular-nums ${
          tick.pct_chg > 0 ? 'text-red-200' : tick.pct_chg < 0 ? 'text-emerald-200' : 'text-gray-400'
        }`}>
          {sign}{tick.pct_chg.toFixed(2)}%
        </span>
      </div>
    </div>
  );
});
TickRow.displayName = 'MarketTapeRow';

// ── 表頭 ──────────────────────────────────────────────────────────────────────

const TapeHeader = () => (
  <div
    className="
      grid items-center px-3 py-2
      text-xs font-bold uppercase tracking-widest
      text-gray-600 border-b border-gray-700/80
      bg-[#060A10] sticky top-0 z-10
    "
    style={{ gridTemplateColumns: '72px 68px 62px 1fr 78px 76px 72px' }}
  >
    <span>時間</span>
    <span>代號</span>
    <span className="text-center">類別</span>
    <span className="pl-1">名稱</span>
    <span className="text-center">內外盤</span>
    <span className="text-right">成交</span>
    <span className="text-right">量 / 幅</span>
  </div>
);

// ── 主元件 ───────────────────────────────────────────────────────────────────

const ASSET_FILTER_OPTIONS: { label: string; value: AssetType | 'all' }[] = [
  { label: '全部', value: 'all' },
  { label: '現貨', value: '現貨' },
  { label: '期貨', value: '期貨' },
  { label: '權證', value: '認購' },
];

export function MarketTapePanel({ height = 540 }: { height?: number }) {
  const ticks           = useAllAroundStore((s) => s.ticks);
  const connectionState = useAllAroundStore((s) => s.connectionState);
  const connect         = useAllAroundStore((s) => s.connect);
  const disconnect      = useAllAroundStore((s) => s.disconnect);
  const tickCount       = useAllAroundStore((s) => s.tickCount);

  const [minVolume,    setMinVolume]    = useState(0);
  const [assetFilter,  setAssetFilter]  = useState<AssetType | 'all'>('all');
  const [dirFilter,    setDirFilter]    = useState<TickDir | 'all'>('all');

  // 掛載時確保已連線
  useEffect(() => {
    connect();
    return () => {
      // 刻意不 disconnect — 其他頁面也可能在用此 store
    };
  }, [connect]);

  const filtered = useMemo(() => {
    return ticks.filter((t) => {
      if (minVolume > 0 && t.volume < minVolume) return false;
      if (assetFilter !== 'all') {
        if (assetFilter === '認購') {
          if (t.asset_type !== '認購' && t.asset_type !== '認售') return false;
        } else {
          if (t.asset_type !== assetFilter) return false;
        }
      }
      if (dirFilter !== 'all' && t.tick_dir !== dirFilter) return false;
      return true;
    });
  }, [ticks, minVolume, assetFilter, dirFilter]);

  const renderItem = useMemo(
    () => (_: number, tick: UnifiedTick) => (
      <TickRow tick={tick} volumeThreshold={minVolume} />
    ),
    [minVolume],
  );

  const computeKey = useMemo(
    () => (_i: number, tick: UnifiedTick) =>
      `${tick.ts}-${tick.symbol}-${tick.price}-${_i}`,
    [],
  );

  const connDot =
    connectionState === 'open'        ? 'bg-emerald-400 animate-pulse'
    : connectionState === 'connecting' ? 'bg-yellow-400 animate-pulse'
    : connectionState === 'error'      ? 'bg-red-500'
    : 'bg-gray-600';

  return (
    <div className="flex flex-col h-full rounded-2xl border border-gray-800 bg-[#060A10] shadow-xl overflow-hidden">
      {/* Panel 標題列 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800/80 bg-[#080C14] shrink-0">
        <div className="flex items-center gap-2">
          <Activity size={15} className="text-cyan-400" />
          <h2 className="text-sm font-black text-gray-300 uppercase tracking-[0.15em]">
            即時內外盤成交
          </h2>
          <div className={`w-1.5 h-1.5 rounded-full ml-1 ${connDot}`} title={connectionState} />
        </div>
        <div className="flex items-center gap-1.5 text-[10px] text-gray-500 font-mono">
          <Zap size={10} className="text-yellow-500" />
          {tickCount.toLocaleString()} 筆
        </div>
      </div>

      {/* 過濾控制列 */}
      <div className="flex flex-wrap items-center gap-2 px-4 py-2 border-b border-gray-800/60 bg-[#07090F] shrink-0">
        {/* 資產類別切換 */}
        <div className="flex gap-1">
          {ASSET_FILTER_OPTIONS.map(({ label, value }) => (
            <button
              key={value}
              onClick={() => setAssetFilter(value as AssetType | 'all')}
              className={`
                text-[10px] font-bold px-2 py-0.5 rounded border transition-colors
                ${assetFilter === value
                  ? 'bg-cyan-600/30 border-cyan-500/60 text-cyan-300'
                  : 'bg-gray-800/40 border-gray-700/50 text-gray-500 hover:text-gray-300'}
              `}
            >
              {label}
            </button>
          ))}
        </div>

        {/* 內外盤方向切換 */}
        <div className="flex gap-1 ml-1">
          {([['all','全向'],['OUTER','外盤'],['INNER','內盤']] as const).map(([val, lbl]) => (
            <button
              key={val}
              onClick={() => setDirFilter(val as TickDir | 'all')}
              className={`
                text-[10px] font-bold px-2 py-0.5 rounded border transition-colors
                ${dirFilter === val
                  ? val === 'OUTER'
                    ? 'bg-red-900/40 border-red-600/50 text-red-300'
                    : val === 'INNER'
                    ? 'bg-emerald-900/40 border-emerald-600/50 text-emerald-300'
                    : 'bg-cyan-600/30 border-cyan-500/60 text-cyan-300'
                  : 'bg-gray-800/40 border-gray-700/50 text-gray-500 hover:text-gray-300'}
              `}
            >
              {lbl}
            </button>
          ))}
        </div>

        {/* 量的門檻 */}
        <div className="flex items-center gap-1.5 ml-auto">
          <Filter size={10} className="text-gray-600" />
          <span className="text-[10px] text-gray-500">≥</span>
          <input
            type="number"
            min={0}
            max={9999}
            step={10}
            value={minVolume}
            onChange={(e) => setMinVolume(Math.max(0, Number(e.target.value)))}
            className="w-14 bg-gray-800/60 border border-gray-700/60 rounded px-1.5 py-px text-[10px] font-mono text-gray-300 focus:outline-none focus:border-cyan-600/60"
          />
          <span className="text-[10px] text-gray-600">張</span>
          <span className="text-[10px] text-gray-600 ml-1">共 {filtered.length}</span>
        </div>
      </div>

      {/* 表頭 */}
      <TapeHeader />

      {/* 瀑布流 */}
      {filtered.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-gray-600 gap-3">
          <div className="w-8 h-8 border-2 border-cyan-900 border-t-cyan-500 rounded-full animate-spin" />
          <p className="text-xs text-gray-500">
            {connectionState === 'open' ? '等待符合條件的成交 tick…' : '連線中…'}
          </p>
          {minVolume > 0 && (
            <p className="text-[10px] text-gray-700">目前門檻 ≥ {minVolume} 張，可嘗試降低</p>
          )}
        </div>
      ) : (
        <Virtuoso
          style={{ height }}
          data={filtered}
          itemContent={renderItem}
          computeItemKey={computeKey}
          overscan={300}
        />
      )}
    </div>
  );
}
