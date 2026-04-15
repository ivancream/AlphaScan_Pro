'use client';

/**
 * AllAroundTicker — 全方位即時流水報價
 *
 * 仿看盤軟體「分時明細」風格：
 *   時間  |  類別  |  成交  |  量
 *
 * 顏色規則：
 *   成交價 → 漲(紅) 跌(綠) 平盤(白) 漲停(紅底) 跌停(綠底)
 *   量     → 外盤(紅) 內盤(綠) 無法判定(灰)
 *
 * 效能：react-virtuoso + React.memo + 100ms 節流批次更新
 */

import React, { useMemo } from 'react';
import { Virtuoso } from 'react-virtuoso';
import type { UnifiedTick, ChgType, TickDir, AssetType } from '@/types/quote';

// ── 成交價顏色（依 chg_type）────────────────────────────────────────────────

const PRICE_STYLE: Record<ChgType, string> = {
  LIMIT_UP:   'text-red-400 font-black',
  UP:         'text-red-400 font-bold',
  FLAT:       'text-gray-100 font-bold',
  DOWN:       'text-green-400 font-bold',
  LIMIT_DOWN: 'text-green-400 font-black',
};

// ── 量顏色（依 tick_dir 外/內盤）────────────────────────────────────────────

const VOL_STYLE: Record<TickDir, string> = {
  OUTER: 'text-red-400',
  INNER: 'text-green-400',
  NONE:  'text-gray-400',
};

// ── 類別標籤 ─────────────────────────────────────────────────────────────────

const ASSET_BADGE: Record<AssetType, { label: string; cls: string }> = {
  '現貨': { label: '現貨', cls: 'text-sky-300    bg-sky-900/40' },
  '期貨': { label: '期貨', cls: 'text-orange-300  bg-orange-900/40' },
  '認購': { label: '認購', cls: 'text-red-300     bg-red-900/30' },
  '認售': { label: '認售', cls: 'text-green-300   bg-green-900/30' },
};

// ── TickRow（完全 memo）──────────────────────────────────────────────────────

interface TickRowProps {
  tick: UnifiedTick;
  volumeThreshold: number;
}

const TickRow = React.memo(({ tick, volumeThreshold }: TickRowProps) => {
  const badge = ASSET_BADGE[tick.asset_type] ?? ASSET_BADGE['現貨'];
  const priceCls = PRICE_STYLE[tick.chg_type] ?? PRICE_STYLE.FLAT;
  const volCls   = VOL_STYLE[tick.tick_dir]   ?? VOL_STYLE.NONE;
  const isLarge  = tick.volume >= volumeThreshold;

  return (
    <div
      className={`
        grid grid-cols-[72px_56px_1fr_80px] items-center
        px-3 py-[5px] border-b border-gray-900/50
        text-xs font-mono select-none transition-colors
        ${isLarge
          ? 'bg-yellow-500/10 border-l-2 border-l-yellow-400'
          : 'hover:bg-white/[0.03]'
        }
      `}
    >
      {/* 時間 */}
      <span className="text-gray-500 tracking-wide">{tick.ts}</span>

      {/* 類別 */}
      <span className={`text-center text-[10px] font-bold rounded px-1 py-px ${badge.cls}`}>
        {badge.label}
      </span>

      {/* 成交價（含代號/名稱） */}
      <div className="flex items-center gap-2 pl-2">
        <span className="text-yellow-400/80 w-14 shrink-0 text-right">{tick.symbol}</span>
        <span className="text-gray-500 w-16 shrink-0 truncate text-[10px]">{tick.name}</span>
        <span className={`flex-1 text-right tabular-nums ${priceCls}`}>
          {tick.price.toFixed(2)}
        </span>
      </div>

      {/* 量 */}
      <span
        className={`text-right tabular-nums font-semibold ${volCls} ${
          isLarge ? 'text-yellow-300' : ''
        }`}
      >
        {tick.volume.toLocaleString()}
      </span>
    </div>
  );
});
TickRow.displayName = 'TickRow';

// ── 表頭 ─────────────────────────────────────────────────────────────────────

const TickerHeader = () => (
  <div
    className="
      grid grid-cols-[72px_56px_1fr_80px] items-center
      px-3 py-2 text-[10px] font-bold uppercase tracking-widest
      text-gray-500 border-b border-gray-700 bg-[#080C14] sticky top-0 z-10
    "
  >
    <span>時間</span>
    <span className="text-center">類別</span>
    <span className="pl-2">成交</span>
    <span className="text-right">量</span>
  </div>
);

// ── 主元件 ────────────────────────────────────────────────────────────────────

interface AllAroundTickerProps {
  ticks:           UnifiedTick[];
  volumeThreshold: number;
  height?:         number | string;
}

export const AllAroundTicker = ({ ticks, volumeThreshold, height = '100%' }: AllAroundTickerProps) => {
  const renderItem = useMemo(
    () => (_index: number, tick: UnifiedTick) => (
      <TickRow tick={tick} volumeThreshold={volumeThreshold} />
    ),
    [volumeThreshold],
  );

  const computeKey = useMemo(
    () => (_index: number, tick: UnifiedTick) => `${tick.ts}-${tick.symbol}-${_index}`,
    [],
  );

  return (
    <div className="flex flex-col h-full bg-[#060A10]">
      <TickerHeader />
      {ticks.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-gray-600 gap-3 py-20">
          <div className="w-10 h-10 border-2 border-cyan-800 border-t-cyan-400 rounded-full animate-spin" />
          <p className="text-sm text-gray-500">等待即時報價推播中...</p>
          <p className="text-[10px] text-gray-700">盤中開始後，每筆成交都將在此顯示</p>
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
