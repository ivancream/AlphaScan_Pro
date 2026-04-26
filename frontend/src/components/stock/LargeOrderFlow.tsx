import { useState } from 'react';
import { RefreshCw } from 'lucide-react';
import type { UnifiedTick } from '@/types/quote';

import { useTickAnalysis } from '@/hooks/useTickAnalysis';
import type { LargePlayerResponse, LargePlayerTrade } from '@/types/tickAnalysis';

function num(v: unknown): number | null {
    if (typeof v === 'number' && Number.isFinite(v)) return v;
    if (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v))) return Number(v);
    return null;
}

function pickNumber(...values: unknown[]): number | null {
    for (const value of values) {
        const parsed = num(value);
        if (parsed !== null) return parsed;
    }
    return null;
}

function normalizeRows(data?: LargePlayerResponse): LargePlayerTrade[] {
    if (!data) return [];
    if (Array.isArray(data.details)) return data.details;
    if (Array.isArray(data.rows)) return data.rows;
    if (Array.isArray(data.trades)) return data.trades;
    return [];
}

function getLots(row: LargePlayerTrade): number {
    return (
        pickNumber(row.lots, row.lot_size, row.volume, row.qty) ?? 0
    );
}

function getDirection(row: LargePlayerTrade): 'BUY' | 'SELL' | 'UNKNOWN' {
    const sideRaw = String(row.side ?? row.direction ?? row.tick_dir ?? '').toUpperCase();
    if (sideRaw.includes('BUY') || sideRaw.includes('OUTER') || sideRaw.includes('B')) return 'BUY';
    if (sideRaw.includes('SELL') || sideRaw.includes('INNER') || sideRaw.includes('S')) return 'SELL';
    return 'UNKNOWN';
}

function fmtNumber(v: number | null | undefined, fractionDigits = 0): string {
    if (v === null || v === undefined || Number.isNaN(v)) return '-';
    return v.toLocaleString('zh-TW', { maximumFractionDigits: fractionDigits, minimumFractionDigits: fractionDigits });
}

function buildFromTicks(ticks: UnifiedTick[]): {
    threshold: number | null;
    buyLots: number;
    sellLots: number;
    netLots: number;
    rows: LargePlayerTrade[];
} {
    if (!ticks.length) {
        return { threshold: null, buyLots: 0, sellLots: 0, netLots: 0, rows: [] };
    }

    const volumes = ticks.map((t) => Math.max(0, Number(t.volume) || 0));
    const avg = volumes.reduce((sum, v) => sum + v, 0) / volumes.length;
    const variance = volumes.reduce((sum, v) => sum + (v - avg) ** 2, 0) / volumes.length;
    const std = Math.sqrt(variance);
    const threshold = Math.max(1, Math.ceil(avg + std * 2));

    const largeTicks = ticks.filter((t) => (Number(t.volume) || 0) >= threshold);
    const rows = largeTicks.map((t) => ({
        ts: t.ts,
        price: t.price,
        volume: t.volume,
        tick_dir: t.tick_dir,
    }));
    const buyLots = largeTicks.reduce((sum, t) => (String(t.tick_dir).toUpperCase() === 'OUTER' ? sum + (Number(t.volume) || 0) : sum), 0);
    const sellLots = largeTicks.reduce((sum, t) => (String(t.tick_dir).toUpperCase() === 'INNER' ? sum + (Number(t.volume) || 0) : sum), 0);

    return {
        threshold,
        buyLots,
        sellLots,
        netLots: buyLots - sellLots,
        rows,
    };
}

function clampPr(v: number): number {
    if (!Number.isFinite(v)) return 97;
    return Math.min(99, Math.max(50, Math.round(v)));
}

export function LargeOrderFlow({ symbol, stockTicks = [] }: { symbol: string; stockTicks?: UnifiedTick[] }) {
    const [pr, setPr] = useState(97);
    const { data, isLoading, isError, error, refetch, isFetching } = useTickAnalysis(symbol, !!symbol, pr);
    const isNotFound = Number((error as { response?: { status?: number } } | null)?.response?.status) === 404;

    const apiRows = normalizeRows(data);
    const local = buildFromTicks(stockTicks);
    const useLocal = isNotFound || !data;

    const rows = useLocal ? local.rows : apiRows;
    const threshold = useLocal
        ? local.threshold
        : pickNumber(data?.threshold, data?.large_order_threshold, data?.summary?.threshold, data?.summary?.large_order_threshold);
    const buyLots = useLocal
        ? local.buyLots
        : (pickNumber(data?.buy_lots, data?.summary?.buy_lots)
            ?? apiRows.reduce((sum, row) => (getDirection(row) === 'BUY' ? sum + getLots(row) : sum), 0));
    const sellLots = useLocal
        ? local.sellLots
        : (pickNumber(data?.sell_lots, data?.summary?.sell_lots)
            ?? apiRows.reduce((sum, row) => (getDirection(row) === 'SELL' ? sum + getLots(row) : sum), 0));
    const netLots = useLocal ? local.netLots : (pickNumber(data?.net_lots, data?.summary?.net_lots) ?? (buyLots - sellLots));
    const shownPr = pickNumber(data?.pr) ?? pr;

    if (isLoading && !isNotFound) {
        return <div className="h-full flex items-center justify-center text-gray-500">載入大單進出資料中...</div>;
    }

    if (isError && !isNotFound) {
        return (
            <div className="m-4 rounded-xl border border-orange-900/50 bg-orange-950/20 p-5">
                <p className="text-orange-300 font-semibold text-sm">
                    無法載入大單進出資料：{(error as Error)?.message ?? '未知錯誤'}
                </p>
                <button
                    onClick={() => refetch()}
                    className="mt-3 inline-flex items-center gap-2 text-xs bg-orange-900/40 hover:bg-orange-900/60 text-orange-300 px-3 py-1.5 rounded-lg transition-colors border border-orange-800/40"
                >
                    <RefreshCw size={12} />
                    重試
                </button>
            </div>
        );
    }

    return (
        <div className="h-full overflow-auto p-4 space-y-4">
            <div className="rounded-xl border border-gray-800 bg-[#161B22] p-4">
                <div className="flex flex-wrap items-center justify-between gap-3 gap-y-2">
                    <h3 className="text-base font-bold text-white">大單進出分析</h3>
                    <div className="flex flex-wrap items-center gap-3">
                        <label className="flex items-center gap-2 text-xs text-gray-400">
                            <span className="whitespace-nowrap">PR 分位</span>
                            <input
                                type="number"
                                min={50}
                                max={99}
                                value={pr}
                                onChange={(e) => setPr(clampPr(Number(e.target.value)))}
                                className="w-[4.5rem] rounded-md border border-gray-700 bg-[#0E1117] px-2 py-1 text-right font-mono text-gray-200 text-xs focus:outline-none focus:border-amber-600"
                                title="50–99，例如 97 表示第 97 百分位數（PR97）"
                            />
                        </label>
                        <span className={`text-[11px] px-2 py-1 rounded border border-gray-700 text-gray-400 ${isFetching ? 'animate-pulse text-cyan-300 border-cyan-800/70' : ''}`}>
                            {isFetching ? '更新中...' : '已更新'}
                        </span>
                    </div>
                </div>
                <p className="mt-2 text-xs text-gray-400">
                    今日大單門檻：取「第 PR{shownPr} 分位之單筆成交金額」與「樣本推導動態下限（中位成交金額 × 2，介於 3 萬～45 萬元）」之較高者；僅列出單筆成交額達門檻之逐筆成交。
                </p>
                {useLocal && (
                    <p className="mt-1 text-[11px] text-amber-400">
                        目前後端尚未提供大單 API，已改用即時逐筆資料前端計算結果。
                    </p>
                )}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                <div className="rounded-xl border border-gray-800 bg-[#161B22] p-4">
                    <p className="text-xs text-gray-500">今日大單門檻</p>
                    <p className="mt-2 text-2xl font-black text-cyan-300 tabular-nums">{fmtNumber(threshold, 0)}</p>
                    <p className="text-xs text-gray-500">單筆成交額(元)</p>
                    {!useLocal && (pickNumber(data?.threshold_quantile) != null || pickNumber(data?.min_amount_floor) != null) && (
                        <p className="mt-2 text-[10px] text-gray-600 leading-relaxed">
                            PR 分位門檻 {fmtNumber(pickNumber(data?.threshold_quantile), 0)} 元 · 動態下限 {fmtNumber(pickNumber(data?.min_amount_floor), 0)} 元
                        </p>
                    )}
                </div>
                <div className="rounded-xl border border-gray-800 bg-[#161B22] p-4">
                    <p className="text-xs text-gray-500">大單買超張數</p>
                    <p className="mt-2 text-2xl font-black text-red-400 tabular-nums">{fmtNumber(buyLots, 0)}</p>
                </div>
                <div className="rounded-xl border border-gray-800 bg-[#161B22] p-4">
                    <p className="text-xs text-gray-500">大單賣超張數</p>
                    <p className="mt-2 text-2xl font-black text-emerald-400 tabular-nums">{fmtNumber(sellLots, 0)}</p>
                </div>
                <div className="rounded-xl border border-gray-800 bg-[#161B22] p-4">
                    <p className="text-xs text-gray-500">大單淨量</p>
                    <p className={`mt-2 text-2xl font-black tabular-nums ${netLots >= 0 ? 'text-red-400' : 'text-emerald-400'}`}>
                        {netLots > 0 ? '+' : ''}
                        {fmtNumber(netLots, 0)}
                    </p>
                </div>
            </div>

            <div className="rounded-xl border border-gray-800 bg-[#161B22] overflow-hidden">
                <div className="border-b border-gray-800 bg-[#0E1117] px-4 py-3 text-xs text-gray-400">
                    觸發門檻逐筆明細（{rows.length} 筆）
                </div>
                <div className="overflow-auto">
                    <table className="w-full text-xs text-gray-300 whitespace-nowrap">
                        <thead className="bg-[#0E1117] sticky top-0 z-10 border-b border-gray-800">
                            <tr>
                                <th className="px-3 py-2 text-left text-gray-500 font-semibold">時間</th>
                                <th className="px-3 py-2 text-right text-gray-500 font-semibold">成交價</th>
                                <th className="px-3 py-2 text-right text-gray-500 font-semibold">成交量(張)</th>
                                <th className="px-3 py-2 text-center text-gray-500 font-semibold">方向</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows.length === 0 && (
                                <tr>
                                    <td colSpan={4} className="px-3 py-6 text-center text-gray-500">
                                        目前無觸發大單門檻的成交明細。
                                    </td>
                                </tr>
                            )}
                            {rows.map((row, idx) => {
                                const direction = getDirection(row);
                                const lots = getLots(row);
                                const stripe = idx % 2 === 0 ? 'bg-[#141922]' : 'bg-[#0E1117]/90';
                                return (
                                    <tr key={`${row.ts ?? row.time ?? 't'}-${idx}`} className={`${stripe} hover:bg-[#1B2432] transition-colors border-b border-gray-800/60`}>
                                        <td className="px-3 py-2 font-mono text-gray-300">{row.ts ?? row.time ?? '-'}</td>
                                        <td className={`px-3 py-2 text-right font-mono ${direction === 'BUY' ? 'text-red-400' : direction === 'SELL' ? 'text-emerald-400' : 'text-gray-300'}`}>
                                            {fmtNumber(num(row.price), 2)}
                                        </td>
                                        <td className={`px-3 py-2 text-right font-mono font-semibold ${direction === 'BUY' ? 'text-red-400' : direction === 'SELL' ? 'text-emerald-400' : 'text-gray-300'}`}>
                                            {fmtNumber(lots, 0)}
                                        </td>
                                        <td className="px-3 py-2 text-center">
                                            <span
                                                className={`inline-flex items-center rounded border px-2 py-0.5 text-[10px] font-bold ${
                                                    direction === 'BUY'
                                                        ? 'bg-red-900/30 text-red-400 border-red-800/30'
                                                        : direction === 'SELL'
                                                          ? 'bg-emerald-900/30 text-emerald-400 border-emerald-800/30'
                                                          : 'bg-gray-800/30 text-gray-400 border-gray-700/30'
                                                }`}
                                            >
                                                {direction === 'BUY' ? '買入' : direction === 'SELL' ? '賣出' : '未知'}
                                            </span>
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
}
