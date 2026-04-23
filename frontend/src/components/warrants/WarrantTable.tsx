import React, { useMemo, useState } from 'react';
import { Copy, Check } from 'lucide-react';

import type { WarrantInfo } from '@/types/warrant';

/** 與權證小哥常用欄位順序對齊（置頂 → 代號 → … → 履約價）；`delta` 為 Ask 優先的顯示欄 */
type DataSortKey =
    | 'code'
    | 'name'
    | 'spread_gearing_ratio_ask'
    | 'moneyness_pct'
    | 'ask_effective_gearing'
    | 'bid_iv'
    | 'ask_iv'
    | 'dte_days'
    | 'bid'
    | 'ask'
    | 'bid_size'
    | 'ask_size'
    | 'last'
    | 'change_pct'
    | 'volume'
    | 'delta'
    | 'exercise_ratio'
    | 'strike';

type SortConfig = { key: DataSortKey; direction: 'asc' | 'desc' } | null;

export interface QuickFilters {
    moneynessMin: number | null;
    moneynessMax: number | null;
    minEffectiveGearing: number | null;
    maxSpreadGearingRatio: number | null;
    minDteDays: number | null;
}

/** 權證小哥版面：僅此欄序（不含溢價比、外內比、Theta 等本專案尚未計算者） */
const WG_COLUMNS: Array<{ key: DataSortKey; label: string; highlight?: boolean }> = [
    { key: 'code', label: '代號' },
    { key: 'name', label: '名稱' },
    { key: 'spread_gearing_ratio_ask', label: '差槓比', highlight: true },
    { key: 'moneyness_pct', label: '價內外(%)' },
    { key: 'ask_effective_gearing', label: '槓桿', highlight: true },
    { key: 'bid_iv', label: '買隱波' },
    { key: 'ask_iv', label: '賣隱波' },
    { key: 'dte_days', label: '天數' },
    { key: 'bid', label: '買價' },
    { key: 'ask', label: '賣價' },
    { key: 'bid_size', label: '買量' },
    { key: 'ask_size', label: '賣量' },
    { key: 'last', label: '成交價' },
    { key: 'change_pct', label: '漲跌(%)' },
    { key: 'volume', label: '總量' },
    { key: 'delta', label: 'Delta' },
    { key: 'exercise_ratio', label: '行使比例' },
    { key: 'strike', label: '履約價' },
];

function sortValue(row: WarrantInfo, key: DataSortKey): unknown {
    if (key === 'delta') return row.ask_delta ?? row.bid_delta;
    return row[key as keyof WarrantInfo];
}

function fmtNum(v: number | null | undefined, digits = 2): string {
    if (v === null || v === undefined || Number.isNaN(v)) return '-';
    return Number(v).toFixed(digits);
}

function fmtPct(v: number | null | undefined, digits = 2): string {
    if (v === null || v === undefined || Number.isNaN(v)) return '-';
    return `${Number(v).toFixed(digits)}%`;
}

function fmtVolumeZhang(v: number | null | undefined): string {
    if (v === null || v === undefined || Number.isNaN(v)) return '-';
    return Math.round(Number(v)).toLocaleString('zh-TW');
}

function numericOrEdge(v: unknown, asc: boolean): number {
    if (typeof v === 'number' && Number.isFinite(v)) return v;
    if (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v))) return Number(v);
    return asc ? Number.POSITIVE_INFINITY : Number.NEGATIVE_INFINITY;
}

function escapeCsvCell(input: string): string {
    if (/[",\n]/.test(input)) {
        return `"${input.replace(/"/g, '""')}"`;
    }
    return input;
}

function playCopyBeep() {
    try {
        const Ctx = window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
        if (!Ctx) return;
        const ctx = new Ctx();
        const oscillator = ctx.createOscillator();
        const gain = ctx.createGain();
        oscillator.type = 'sine';
        oscillator.frequency.value = 820;
        gain.gain.value = 0.0001;
        oscillator.connect(gain);
        gain.connect(ctx.destination);
        const now = ctx.currentTime;
        gain.gain.exponentialRampToValueAtTime(0.06, now + 0.005);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.06);
        oscillator.start(now);
        oscillator.stop(now + 0.06);
        oscillator.onended = () => void ctx.close();
    } catch {
        // 音效失敗不影響主流程
    }
}

/** 第一次點某欄時的排序方向（差槓比、代號、名稱習慣由小到大／字母序） */
function initialSortDirection(key: DataSortKey): 'asc' | 'desc' {
    if (key === 'spread_gearing_ratio_ask' || key === 'code' || key === 'name') return 'asc';
    return 'desc';
}

function applySort(rows: WarrantInfo[], sortConfig: SortConfig): WarrantInfo[] {
    const out = [...rows];
    if (!sortConfig) return out;
    const { key, direction } = sortConfig;
    const asc = direction === 'asc';

    out.sort((a, b) => {
        const va = sortValue(a, key);
        const vb = sortValue(b, key);

        if (typeof va === 'string' || typeof vb === 'string') {
            return asc
                ? String(va ?? '').localeCompare(String(vb ?? ''))
                : String(vb ?? '').localeCompare(String(va ?? ''));
        }

        const na = numericOrEdge(va, asc);
        const nb = numericOrEdge(vb, asc);
        if (na < nb) return asc ? -1 : 1;
        if (na > nb) return asc ? 1 : -1;
        return 0;
    });
    return out;
}

export function WarrantTable({
    data,
    filters,
    lastUpdatedLabel,
    isUpdating,
}: {
    data: WarrantInfo[];
    filters: QuickFilters;
    lastUpdatedLabel?: string;
    isUpdating?: boolean;
}) {
    const [sortConfig, setSortConfig] = useState<SortConfig>({
        key: 'spread_gearing_ratio_ask',
        direction: 'asc',
    });
    const [pinnedCodes, setPinnedCodes] = useState<Set<string>>(() => new Set());
    const [copiedCode, setCopiedCode] = useState<string | null>(null);

    const togglePin = (code: string) => {
        setPinnedCodes((prev) => {
            const next = new Set(prev);
            if (next.has(code)) next.delete(code);
            else next.add(code);
            return next;
        });
    };

    const filtered = useMemo(() => {
        return data.filter((row) => {
            const m = row.moneyness_pct;
            if (filters.moneynessMin !== null || filters.moneynessMax !== null) {
                if (m === null) return false;
                if (filters.moneynessMin !== null && m < filters.moneynessMin) return false;
                if (filters.moneynessMax !== null && m > filters.moneynessMax) return false;
            }

            const gearing = row.ask_effective_gearing ?? row.bid_effective_gearing;
            if (filters.minEffectiveGearing !== null) {
                if (gearing === null || gearing < filters.minEffectiveGearing) return false;
            }

            if (filters.maxSpreadGearingRatio !== null) {
                const sgr = row.spread_gearing_ratio_ask ?? row.spread_gearing_ratio_bid;
                if (sgr === null || Number.isNaN(sgr) || sgr > filters.maxSpreadGearingRatio) return false;
            }

            if (filters.minDteDays !== null && row.dte_days < filters.minDteDays) return false;
            return true;
        });
    }, [data, filters]);

    const sorted = useMemo(() => {
        const pinned = filtered.filter((r) => pinnedCodes.has(r.code));
        const rest = filtered.filter((r) => !pinnedCodes.has(r.code));
        return [...applySort(pinned, sortConfig), ...applySort(rest, sortConfig)];
    }, [filtered, sortConfig, pinnedCodes]);

    const onSort = (key: DataSortKey) => {
        setSortConfig((prev) => {
            if (!prev || prev.key !== key) return { key, direction: initialSortDirection(key) };
            return { key, direction: prev.direction === 'desc' ? 'asc' : 'desc' };
        });
    };

    const icon = (key: DataSortKey) => {
        if (!sortConfig || sortConfig.key !== key) return <span className="ml-1 opacity-20">↕</span>;
        return sortConfig.direction === 'asc'
            ? <span className="ml-1 text-cyan-300">↑</span>
            : <span className="ml-1 text-cyan-300">↓</span>;
    };

    const csvCellForCol = (row: WarrantInfo, key: DataSortKey): string => {
        const v = sortValue(row, key);
        if (v === null || v === undefined) return '';
        return escapeCsvCell(String(v));
    };

    const exportCsv = () => {
        const header = ['置頂', ...WG_COLUMNS.map((c) => c.label)].join(',');
        const lines = sorted.map((row) => {
            const pinMark = pinnedCodes.has(row.code) ? '1' : '';
            const cells = WG_COLUMNS.map((c) => csvCellForCol(row, c.key));
            return [pinMark, ...cells].join(',');
        });
        const content = [header, ...lines].join('\n');
        const blob = new Blob([content], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        const ts = new Date().toISOString().replace(/[:.]/g, '-');
        a.href = url;
        a.download = `warrants_${ts}.csv`;
        a.click();
        URL.revokeObjectURL(url);
    };

    const copyCode = async (code: string) => {
        try {
            await navigator.clipboard.writeText(code);
            playCopyBeep();
            setCopiedCode(code);
            window.setTimeout(() => {
                setCopiedCode((prev) => (prev === code ? null : prev));
            }, 2000);
        } catch {
            setCopiedCode('複製失敗');
            window.setTimeout(() => setCopiedCode(null), 2000);
        }
    };

    return (
        <div className="rounded-xl border border-gray-800 bg-[#161B22] shadow-xl overflow-hidden">
            <div className="border-b border-gray-800 bg-[#0E1117] px-4 py-3 text-xs text-gray-400 flex items-center justify-between gap-3">
                <span>欄位順序比照權證小哥常用版面；置頂列會固定在表頭下方。</span>
                <div className="flex items-center gap-2">
                    <span
                        className={`text-[11px] px-2 py-1 rounded border border-gray-700 text-gray-400 ${
                            isUpdating ? 'animate-pulse text-cyan-300 border-cyan-800/70' : ''
                        }`}
                    >
                        Last Updated: {lastUpdatedLabel ?? '--:--:--'}
                    </span>
                    <button
                        onClick={exportCsv}
                        className="px-3 py-1.5 rounded-md border border-cyan-700 text-cyan-300 hover:bg-cyan-900/30 transition"
                    >
                        匯出 CSV
                    </button>
                </div>
            </div>
            <div className="overflow-auto max-h-[70vh]">
                <table className="w-full text-xs text-gray-300 whitespace-nowrap">
                    <thead className="bg-[#0E1117] sticky top-0 z-10 border-b border-gray-800">
                        <tr>
                            <th className="w-10 px-2 py-2 text-center text-gray-500 font-semibold">置頂</th>
                            {WG_COLUMNS.map((col) => (
                                <th
                                    key={col.key}
                                    onClick={() => onSort(col.key)}
                                    className={`px-3 py-2 text-left font-semibold cursor-pointer hover:text-white ${
                                        col.highlight ? 'text-cyan-300' : 'text-gray-400'
                                    }`}
                                >
                                    {col.label}
                                    {icon(col.key)}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {sorted.length === 0 && (
                            <tr>
                                <td
                                    colSpan={WG_COLUMNS.length + 1}
                                    className="px-3 py-6 text-center text-gray-500"
                                >
                                    目前條件下無符合權證，請放寬篩選條件。
                                </td>
                            </tr>
                        )}
                        {sorted.map((row, idx) => {
                            const moneyness = row.moneyness_pct ?? 0;
                            const nearAtm = moneyness >= -5 && moneyness <= 5;
                            const sgrRaw = row.spread_gearing_ratio_ask;
                            const sgrColor =
                                sgrRaw === null || Number.isNaN(sgrRaw)
                                    ? 'text-gray-500'
                                    : sgrRaw <= 0.002
                                      ? 'text-emerald-300 font-bold'
                                      : sgrRaw <= 0.005
                                        ? 'text-amber-300 font-bold'
                                        : 'text-rose-300 font-bold';
                            const chg = row.change_pct;
                            const chgColor =
                                chg === null || chg === undefined || Number.isNaN(chg)
                                    ? 'text-gray-400'
                                    : chg > 0
                                      ? 'text-rose-400'
                                      : chg < 0
                                        ? 'text-emerald-400'
                                        : 'text-gray-300';
                            const stripe = idx % 2 === 0 ? 'bg-[#141922]' : 'bg-[#0E1117]/90';

                            return (
                                <tr key={row.code} className={`${stripe} hover:bg-[#1B2432] transition-colors border-b border-gray-800/60`}>
                                    <td className="px-2 py-2 text-center">
                                        <input
                                            type="checkbox"
                                            checked={pinnedCodes.has(row.code)}
                                            onChange={() => togglePin(row.code)}
                                            className="accent-cyan-500 cursor-pointer"
                                            title="置頂（固定在上）"
                                            aria-label={`置頂 ${row.code}`}
                                        />
                                    </td>
                                    <td className="px-3 py-2 font-mono text-[#EAB308]">
                                        <button
                                            type="button"
                                            onClick={() => void copyCode(row.code)}
                                            className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-[#273142] transition cursor-pointer"
                                            title={`複製 ${row.code}`}
                                        >
                                            <span>{row.code}</span>
                                            {copiedCode === row.code ? (
                                                <Check size={12} className="text-emerald-300" />
                                            ) : (
                                                <Copy size={12} className="text-cyan-300/80" />
                                            )}
                                        </button>
                                    </td>
                                    <td className="px-3 py-2 text-white max-w-[14rem] truncate" title={row.name}>{row.name}</td>
                                    <td className={`px-3 py-2 font-mono ${sgrColor}`}>
                                        {fmtNum(row.spread_gearing_ratio_ask, 4)}
                                    </td>
                                    <td className={`px-3 py-2 font-mono ${moneyness > 0 ? 'text-rose-300' : moneyness < 0 ? 'text-emerald-300' : 'text-gray-300'} ${nearAtm ? 'font-bold' : ''}`}>
                                        {fmtPct(row.moneyness_pct, 2)}
                                    </td>
                                    <td className="px-3 py-2 font-mono text-cyan-300 font-semibold">{fmtNum(row.ask_effective_gearing, 3)}</td>
                                    <td className="px-3 py-2 font-mono">{fmtNum(row.bid_iv, 3)}</td>
                                    <td className="px-3 py-2 font-mono">{fmtNum(row.ask_iv, 3)}</td>
                                    <td className="px-3 py-2 font-mono">{row.dte_days}</td>
                                    <td className="px-3 py-2 font-mono text-emerald-400/95">{fmtNum(row.bid, 3)}</td>
                                    <td className="px-3 py-2 font-mono text-rose-400/95">{fmtNum(row.ask, 3)}</td>
                                    <td className="px-3 py-2 font-mono text-gray-200">{fmtVolumeZhang(row.bid_size)}</td>
                                    <td className="px-3 py-2 font-mono text-gray-200">{fmtVolumeZhang(row.ask_size)}</td>
                                    <td className="px-3 py-2 font-mono text-white">{fmtNum(row.last, 3)}</td>
                                    <td className={`px-3 py-2 font-mono font-medium ${chgColor}`}>{fmtPct(row.change_pct, 2)}</td>
                                    <td className="px-3 py-2 font-mono text-gray-200">{fmtVolumeZhang(row.volume)}</td>
                                    <td className="px-3 py-2 font-mono">{fmtNum(row.ask_delta ?? row.bid_delta, 3)}</td>
                                    <td className="px-3 py-2 font-mono">{fmtNum(row.exercise_ratio, 3)}</td>
                                    <td className="px-3 py-2 font-mono">{fmtNum(row.strike, 2)}</td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
            {copiedCode && (
                <div className="fixed right-6 bottom-6 z-50 rounded-lg border border-cyan-800 bg-[#0E1117]/95 px-3 py-2 text-xs text-cyan-200 shadow-lg animate-in fade-in duration-200">
                    {copiedCode === '複製失敗' ? copiedCode : `已複製 ${copiedCode}`}
                </div>
            )}
        </div>
    );
}
