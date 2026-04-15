/**
 * AllAroundTicker — 全方位即時流水報價
 *
 * 效能設計：
 * - react-virtuoso 虛擬化：只渲染可視範圍內的 DOM 節點
 * - TickRow 用 React.memo 嚴格阻斷 re-render（key 相同則不重繪）
 * - computeItemKey 使用 ts+symbol 讓 React 精確追蹤舊節點，不整個重建
 * - store 內 100ms 節流批次更新，每秒最多觸發 10 次 re-render
 */

import React, { useMemo } from 'react';
import { Virtuoso } from 'react-virtuoso';
import type { UnifiedTick, AssetType, TickType } from '@/types/quote';

// ── 靜態映射（不放在元件內，避免每次渲染重建）────────────────────────────

const ASSET_META: Record<AssetType, { label: string; cls: string }> = {
  STOCK:   { label: '股', cls: 'text-sky-400 bg-sky-900/30' },
  WARRANT: { label: '權', cls: 'text-purple-400 bg-purple-900/30' },
  FUTURES: { label: '期', cls: 'text-orange-400 bg-orange-900/30' },
};

const TICK_CLS: Record<TickType, { price: string; dir: string; row: string }> = {
  BUY_UP:    { price: 'text-red-400',   dir: '↑外', row: '' },
  SELL_DOWN: { price: 'text-green-400', dir: '↓內', row: '' },
  NEUTRAL:   { price: 'text-gray-300',  dir: '—',   row: '' },
};

// ── TickRow（完全 memo，僅 tick 物件本身改變才重繪）──────────────────────

interface TickRowProps {
  tick: UnifiedTick;
  volumeThreshold: number;
}

const TickRow = React.memo(({ tick, volumeThreshold }: TickRowProps) => {
  const asset    = ASSET_META[tick.asset_type] ?? ASSET_META.STOCK;
  const tickMeta = TICK_CLS[tick.tick_type]    ?? TICK_CLS.NEUTRAL;
  const isLarge  = tick.volume >= volumeThreshold;
  const timeStr  = tick.ts.slice(11, 19);   // HH:MM:SS

  return (
    <div
      className={`
        flex items-center gap-0 px-2 py-[3px] border-b border-gray-900/60
        text-xs font-mono select-none
        ${isLarge ? 'bg-yellow-500/10 border-l-2 border-l-yellow-400' : 'hover:bg-white/5'}
      `}
    >
      {/* 類型標籤 */}
      <span className={`w-7 shrink-0 text-center rounded text-[10px] font-bold px-0.5 mr-2 ${asset.cls}`}>
        {asset.label}
      </span>

      {/* 代號 */}
      <span className="w-16 shrink-0 text-yellow-300 font-bold tracking-wider">
        {tick.symbol}
      </span>

      {/* 名稱 */}
      <span className="w-20 shrink-0 text-gray-400 truncate">
        {tick.name}
      </span>

      {/* 成交價 */}
      <span className={`w-20 shrink-0 text-right font-bold ${tickMeta.price}`}>
        {tick.price.toFixed(2)}
      </span>

      {/* 單筆量 */}
      <span
        className={`w-12 shrink-0 text-right font-semibold ${
          isLarge ? 'text-yellow-300' : 'text-gray-400'
        }`}
      >
        {tick.volume}
      </span>

      {/* 外/內盤方向 */}
      <span className={`w-10 shrink-0 text-center font-bold text-[10px] ${tickMeta.price}`}>
        {tickMeta.dir}
      </span>

      {/* 時間 */}
      <span className="flex-1 text-right text-gray-600 text-[10px]">
        {timeStr}
      </span>
    </div>
  );
});
TickRow.displayName = 'TickRow';

// ── 表頭（靜態，不參與虛擬列表）─────────────────────────────────────────

const TickerHeader = () => (
  <div className="flex items-center px-2 py-2 text-[10px] font-bold uppercase text-gray-500 border-b border-gray-700 bg-[#0A0F1E] tracking-widest">
    <span className="w-7 mr-2 text-center">型</span>
    <span className="w-16">代號</span>
    <span className="w-20">名稱</span>
    <span className="w-20 text-right">成交價</span>
    <span className="w-12 text-right">量(張)</span>
    <span className="w-10 text-center">方向</span>
    <span className="flex-1 text-right">時間</span>
  </div>
);

// ── 主元件 ────────────────────────────────────────────────────────────────

interface AllAroundTickerProps {
  ticks:           UnifiedTick[];
  volumeThreshold: number;
  height?:         number | string;
}

export const AllAroundTicker = ({ ticks, volumeThreshold, height = '100%' }: AllAroundTickerProps) => {
  // 穩定的 itemContent callback，避免 Virtuoso 每次都拿到新函式
  const renderItem = useMemo(
    () => (_index: number, tick: UnifiedTick) => (
      <TickRow tick={tick} volumeThreshold={volumeThreshold} />
    ),
    [volumeThreshold],
  );

  // 穩定 key（ts + symbol 組合唯一）
  const computeKey = useMemo(
    () => (_index: number, tick: UnifiedTick) => `${tick.ts}-${tick.symbol}`,
    [],
  );

  return (
    <div className="flex flex-col h-full">
      <TickerHeader />
      {ticks.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-gray-600 gap-2">
          <span className="text-4xl">📡</span>
          <p className="text-sm">等待即時報價推播中...</p>
          <p className="text-xs text-gray-700">盤中開始後，每筆成交都將在此顯示</p>
        </div>
      ) : (
        <Virtuoso
          style={{ height }}
          data={ticks}
          itemContent={renderItem}
          computeItemKey={computeKey}
          overscan={200}
        />
      )}
    </div>
  );
};
