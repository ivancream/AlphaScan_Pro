'use client';

/**
 * FuturesSpreadRank — 期現貨價差排名
 *
 * 資料源：useTaiexMarketBrief（REST /api/v1/market/taiex-overview，15s poll）
 * 第一版：台指期 vs 加權指數（含 basis_points）
 *        小台（MXF）預留欄位，待 market_brief 擴充後啟用
 */

import React, { useEffect, useState } from 'react';
import { TrendingUp, TrendingDown, RefreshCw, Minus } from 'lucide-react';
import { API_V1_BASE } from '@/lib/apiBase';

type SpreadFilter = 'all' | 'contango' | 'backwardation';

interface SpreadRow {
  id:          string;
  label:       string;     // 顯示名（台指期 vs 加權）
  futuresSym:  string;     // 期貨代碼
  spotPrice:   number | null;
  futPrice:    number | null;
  basisPts:    number | null;  // 期 − 現（點）
  basisPct:    number | null;  // basisPts / spotPrice * 100
  updatedAt:   string;
}

interface SpreadApiRow {
  id: string;
  underlying_symbol: string;
  underlying_name: string;
  futures_symbol: string;
  futures_name: string;
  spot_price: number;
  futures_price: number;
  basis_points: number;
  basis_pct: number;
  spot_ts?: string;
  futures_ts?: string;
}

interface SpreadApiResponse {
  rows: SpreadApiRow[];
  subscribed_stock_futures: number;
}

// ── 工具 ─────────────────────────────────────────────────────────────────────

function calcPct(basis: number | null, spot: number | null): number | null {
  if (basis == null || spot == null || spot === 0) return null;
  return (basis / spot) * 100;
}

function StatusBadge({ basisPts }: { basisPts: number | null }) {
  if (basisPts == null) {
    return <span className="text-gray-600 text-[10px]">—</span>;
  }
  if (Math.abs(basisPts) < 0.01) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full border border-gray-600/50 bg-gray-800/50 text-gray-400">
        <Minus size={10} />
        近平價
      </span>
    );
  }
  if (basisPts > 0) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full border border-red-600/40 bg-red-900/20 text-red-400">
        <TrendingUp size={10} />
        正價差
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full border border-emerald-600/40 bg-emerald-900/20 text-emerald-400">
      <TrendingDown size={10} />
      逆價差
    </span>
  );
}

function SpreadBar({ pct }: { pct: number | null }) {
  if (pct == null) return <div className="h-1 rounded bg-gray-800 w-full" />;
  const clamped = Math.max(-3, Math.min(3, pct));      // 顯示 ±3% 範圍
  const isPos   = clamped >= 0;
  const width   = Math.abs(clamped / 3) * 50;          // 50% max per side

  return (
    <div className="relative h-1.5 rounded-full bg-gray-800/80 overflow-hidden w-full">
      {/* 中線 */}
      <div className="absolute left-1/2 top-0 h-full w-px bg-gray-600/60" />
      {isPos ? (
        <div
          className="absolute top-0 h-full bg-red-500/70 rounded-r-full"
          style={{ left: '50%', width: `${width}%` }}
        />
      ) : (
        <div
          className="absolute top-0 h-full bg-emerald-500/70 rounded-l-full"
          style={{ right: '50%', width: `${width}%` }}
        />
      )}
    </div>
  );
}

// ── SpreadRow 表格列 ──────────────────────────────────────────────────────────

function SpreadTableRow({ row }: { row: SpreadRow }) {
  const bpSign  = row.basisPts != null && row.basisPts > 0 ? '+' : '';
  const pctSign = row.basisPct != null && row.basisPct > 0 ? '+' : '';

  return (
    <tr className="border-b border-gray-800/60 hover:bg-white/[0.025] transition-colors">
      <td className="px-3 py-3">
        <div className="text-base font-black text-gray-100">{row.label}</div>
        <div className="text-xs text-gray-500 font-mono mt-0.5">{row.futuresSym}</div>
      </td>
      <td className="px-3 py-3 text-right font-mono text-sm text-gray-200">
        {row.spotPrice != null
          ? row.spotPrice.toLocaleString('zh-TW', { maximumFractionDigits: 2 })
          : '—'}
      </td>
      <td className="px-3 py-3 text-right font-mono text-sm text-gray-200">
        {row.futPrice != null
          ? row.futPrice.toLocaleString('zh-TW', { maximumFractionDigits: 2 })
          : '—'}
      </td>
      <td className="px-3 py-3 text-right">
        <div className={`font-mono font-black text-base ${
          row.basisPts == null ? 'text-gray-600'
          : row.basisPts > 5  ? 'text-red-400'
          : row.basisPts < -5 ? 'text-emerald-400'
          : 'text-gray-400'
        }`}>
          {row.basisPts != null ? `${bpSign}${row.basisPts.toFixed(0)}` : '—'}
        </div>
        <SpreadBar pct={row.basisPct} />
      </td>
      <td className="px-3 py-3 text-right font-mono font-black text-sm">
        <span className={
          row.basisPct == null ? 'text-gray-600'
          : row.basisPct > 0.1 ? 'text-red-400'
          : row.basisPct < -0.1 ? 'text-emerald-400'
          : 'text-gray-400'
        }>
          {row.basisPct != null ? `${pctSign}${row.basisPct.toFixed(3)}%` : '—'}
        </span>
      </td>
      <td className="px-4 py-3 text-center">
        <StatusBadge basisPts={row.basisPts} />
      </td>
    </tr>
  );
}

// ── 主元件 ───────────────────────────────────────────────────────────────────

export function FuturesSpreadRank() {
  const [data, setData] = useState<SpreadApiResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dataUpdatedAt, setDataUpdatedAt] = useState<number | null>(null);
  const [filter, setFilter] = useState<SpreadFilter>('all');

  useEffect(() => {
    let alive = true;
    let timer: number | null = null;

    const load = async () => {
      setIsLoading(true);
      try {
        const res = await fetch(`${API_V1_BASE}/all-around/futures-spreads?limit=80`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const body = await res.json() as SpreadApiResponse;
        if (!alive) return;
        setData(body);
        setError(null);
        setDataUpdatedAt(Date.now());
      } catch (exc) {
        if (!alive) return;
        setError(exc instanceof Error ? exc.message : '載入失敗');
      } finally {
        if (alive) setIsLoading(false);
      }
    };

    load();
    timer = window.setInterval(load, 15_000);
    return () => {
      alive = false;
      if (timer !== null) window.clearInterval(timer);
    };
  }, []);

  const updatedLabel = dataUpdatedAt
    ? new Date(dataUpdatedAt).toLocaleTimeString('zh-TW', {
        hour: '2-digit', minute: '2-digit', second: '2-digit',
      })
    : '—';

  const allRows: SpreadRow[] = React.useMemo(() => {
    return (data?.rows ?? []).map((row) => ({
      id: row.id,
      label: `${row.underlying_symbol} ${row.underlying_name}`,
      futuresSym: row.futures_symbol,
      spotPrice: row.spot_price,
      futPrice: row.futures_price,
      basisPts: row.basis_points,
      basisPct: row.basis_pct ?? calcPct(row.basis_points, row.spot_price),
      updatedAt: row.futures_ts ?? row.spot_ts ?? updatedLabel,
    }));
  }, [data, updatedLabel]);

  const filtered = allRows.filter((r) => {
    if (filter === 'contango')     return r.basisPts != null && r.basisPts > 0;
    if (filter === 'backwardation') return r.basisPts != null && r.basisPts < 0;
    return true;
  });

  // 依價差%絕對值排序（已有 basis_pct 後才有意義，第一版單行故排序效果不顯著）
  const sorted = [...filtered].sort(
    (a, b) => Math.abs(b.basisPct ?? 0) - Math.abs(a.basisPct ?? 0),
  );

  return (
    <div className="flex flex-col rounded-2xl border border-gray-800 bg-[#0A0F1E] shadow-xl overflow-hidden">
      {/* 標題列 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800/80 bg-[#080C18] shrink-0">
        <div className="flex items-center gap-2">
          <TrendingUp size={15} className="text-orange-400" />
          <h2 className="text-sm font-black text-gray-300 uppercase tracking-[0.15em]">
            個股期正逆價差
          </h2>
        </div>
        <div className="flex items-center gap-1.5 text-[10px] text-gray-600 font-mono">
          <RefreshCw size={9} className={isLoading ? 'animate-spin text-cyan-500' : 'text-gray-700'} />
          {updatedLabel}
        </div>
      </div>

      {/* 過濾切換 */}
      <div className="flex items-center gap-1.5 px-4 py-2 border-b border-gray-800/50 bg-[#080C14] shrink-0">
        {([
          ['all',           '全部'],
          ['contango',      '正價差'],
          ['backwardation', '逆價差'],
        ] as const).map(([val, lbl]) => (
          <button
            key={val}
            onClick={() => setFilter(val)}
            className={`
              text-[10px] font-bold px-2.5 py-0.5 rounded border transition-colors
              ${filter === val
                ? val === 'contango'
                  ? 'bg-red-900/40 border-red-600/50 text-red-300'
                  : val === 'backwardation'
                  ? 'bg-emerald-900/40 border-emerald-600/50 text-emerald-300'
                  : 'bg-cyan-600/25 border-cyan-500/50 text-cyan-300'
                : 'bg-gray-800/40 border-gray-700/50 text-gray-500 hover:text-gray-300'}
            `}
          >
            {lbl}
          </button>
        ))}
        <span className="text-xs text-gray-600 ml-auto">
          個股期 {data?.subscribed_stock_futures ?? 0} 檔 · 依│價差%│降序
        </span>
      </div>

      {/* 資訊說明（price spread bar 解說） */}
      <div className="px-4 py-2 flex items-center gap-4 text-[10px] text-gray-600 border-b border-gray-800/30 bg-[#07090E]">
        <span className="flex items-center gap-1">
          <span className="w-3 h-1 inline-block bg-red-500/70 rounded-full" />
          正價差（期 &gt; 現）
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-1 inline-block bg-emerald-500/70 rounded-full" />
          逆價差（期 &lt; 現）
        </span>
        <span className="text-gray-700">Bar 寬度 = ±3% 範圍</span>
      </div>

      {/* 表格 */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-widest text-gray-600 border-b border-gray-800/80">
              <th className="px-3 py-2 font-bold">現貨標的</th>
              <th className="px-3 py-2 font-bold text-right">現貨</th>
              <th className="px-3 py-2 font-bold text-right">期貨</th>
              <th className="px-3 py-2 font-bold text-right">價差（點）</th>
              <th className="px-3 py-2 font-bold text-right">價差%</th>
              <th className="px-4 py-2 font-bold text-center">狀態</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && !data ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-600 text-xs">
                  載入中…
                </td>
              </tr>
            ) : sorted.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-600 text-xs">
                  {error
                    ? `載入失敗：${error}`
                    : filter !== 'all'
                    ? '目前無符合條件的合約'
                    : '尚無個股期成交或現貨對照資料'}
                </td>
              </tr>
            ) : (
              sorted.map((row) => <SpreadTableRow key={row.id} row={row} />)
            )}
          </tbody>
        </table>
      </div>

      {/* 資料來源提示 */}
      {data && (
        <div className="px-4 py-2 border-t border-gray-800/50 text-[10px] text-gray-700">
          ✓ all-around 即時 tick 快取計算，需同時收到現貨與個股期成交才會出現
        </div>
      )}
    </div>
  );
}
