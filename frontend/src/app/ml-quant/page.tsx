import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Brain, RefreshCw, Table2, Layers } from 'lucide-react';

import { useMlQuant, type MlQuantUniverseParam } from '@/hooks/useMlQuant';
import { LoadingState } from '@/components/ui/LoadingState';
import { cleanStockSymbol, toStockDetailPath } from '@/lib/stocks';

function regimeVisual(label: string) {
    const l = label.toLowerCase();
    if (l === 'bull') {
        return {
            title: '多頭',
            subtitle: '風險偏好偏高區間',
            border: 'border-emerald-500/40',
            bg: 'from-emerald-950/80 to-[#0E1117]',
            accent: 'bg-emerald-500',
            glow: 'bg-emerald-500/20',
            text: 'text-emerald-300',
            badge: 'bg-emerald-500/20 text-emerald-200 border-emerald-500/30',
        };
    }
    if (l === 'bear') {
        return {
            title: '空頭',
            subtitle: '風險趨避／波動放大區間',
            border: 'border-sky-600/50',
            bg: 'from-sky-950/70 to-[#0E1117]',
            accent: 'bg-sky-500',
            glow: 'bg-sky-500/15',
            text: 'text-sky-200',
            badge: 'bg-sky-500/15 text-sky-100 border-sky-500/35',
        };
    }
    return {
        title: '盤整／中性',
        subtitle: '趨勢不明或多空均衡',
        border: 'border-amber-500/35',
        bg: 'from-amber-950/50 to-[#0E1117]',
        accent: 'bg-amber-500',
        glow: 'bg-amber-500/15',
        text: 'text-amber-200',
        badge: 'bg-amber-500/15 text-amber-100 border-amber-500/30',
    };
}

function formatPct(v: number | null | undefined, digits = 2): string {
    if (v === null || v === undefined || Number.isNaN(v)) return '—';
    return `${(v * 100).toFixed(digits)}%`;
}

function formatPrice(v: number | null | undefined): string {
    if (v === null || v === undefined || Number.isNaN(v)) return '—';
    return v.toLocaleString('zh-TW', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export default function MlQuantPage() {
    const [universe, setUniverse] = useState<MlQuantUniverseParam>('all');
    const [lookback, setLookback] = useState(100);
    const [symbolsCsv, setSymbolsCsv] = useState('2330,2317');

    const { data, isLoading, error, refetch } = useMlQuant({
        universe,
        lookback,
        symbols: universe === 'symbols' ? symbolsCsv : undefined,
    });

    const vis = useMemo(() => regimeVisual(data?.regime?.regime_label ?? 'sideways'), [data?.regime?.regime_label]);

    return (
        <div className="p-6 space-y-8 animate-in fade-in duration-500 text-gray-200">
            <header className="flex flex-col lg:flex-row lg:items-end justify-between gap-4 border-b border-gray-800 pb-4">
                <div>
                    <h1 className="text-2xl font-bold text-white tracking-widest flex items-center gap-3">
                        <Brain className="text-violet-400 shrink-0" size={28} />
                        ML Quant 儀表板
                    </h1>
                    <p className="text-sm text-gray-500 mt-2 max-w-2xl leading-relaxed">
                        結合 HMM 大盤狀態與 WFO 存活規則，於最新交易日截面評分選股。資料來源為後端 DuckDB
                        與 <code className="text-gray-400">wfo_surviving_rules.json</code>。
                    </p>
                </div>
                <button
                    type="button"
                    onClick={() => void refetch()}
                    disabled={isLoading}
                    className="self-start text-xs bg-gray-800 hover:bg-gray-700 disabled:opacity-50 text-gray-200 px-4 py-2 rounded-lg transition flex items-center gap-2 font-bold border border-gray-700"
                >
                    <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
                    重新推論
                </button>
            </header>

            {/* 參數列 */}
            <section className="bg-[#161B22] border border-gray-800 rounded-xl p-4 md:p-5 flex flex-col lg:flex-row flex-wrap gap-4 items-end">
                <div className="flex flex-col gap-1 min-w-[160px]">
                    <label className="text-[10px] font-black text-gray-500 tracking-widest uppercase">Universe</label>
                    <select
                        value={universe}
                        onChange={(e) => setUniverse(e.target.value as MlQuantUniverseParam)}
                        className="bg-[#0E1117] border border-gray-700 text-white rounded-lg px-3 py-2 text-sm font-bold focus:border-violet-500 focus:outline-none"
                    >
                        <option value="all">全市場 (all)</option>
                        <option value="watchlist">自選股 (watchlist)</option>
                        <option value="symbols">指定代碼 (symbols)</option>
                    </select>
                </div>
                {universe === 'symbols' && (
                    <div className="flex flex-col gap-1 flex-1 min-w-[200px]">
                        <label className="text-[10px] font-black text-gray-500 tracking-widest uppercase">
                            Symbols（逗號分隔）
                        </label>
                        <input
                            value={symbolsCsv}
                            onChange={(e) => setSymbolsCsv(e.target.value)}
                            placeholder="2330,2317"
                            className="bg-[#0E1117] border border-gray-700 text-white rounded-lg px-3 py-2 text-sm font-mono focus:border-violet-500 focus:outline-none"
                        />
                    </div>
                )}
                <div className="flex flex-col gap-1 w-28">
                    <label className="text-[10px] font-black text-gray-500 tracking-widest uppercase">Lookback</label>
                    <input
                        type="number"
                        min={30}
                        max={300}
                        value={lookback}
                        onChange={(e) => setLookback(Number(e.target.value) || 100)}
                        className="bg-[#0E1117] border border-gray-700 text-white rounded-lg px-3 py-2 text-sm font-mono focus:border-violet-500 focus:outline-none"
                    />
                </div>
            </section>

            {error && (
                <div className="text-red-300 bg-red-950/30 border border-red-500/30 p-4 rounded-xl text-sm whitespace-pre-wrap">
                    {error}
                </div>
            )}

            {isLoading && !data ? (
                <div className="h-40">
                    <LoadingState text="載入 ML 推論結果中…" />
                </div>
            ) : data ? (
                <>
                    {/* Market Regime Card */}
                    <section>
                        <h2 className="text-sm text-gray-500 font-black mb-3 tracking-widest uppercase flex items-center gap-2">
                            <Layers size={16} className="text-violet-400" />
                            大盤狀態 (HMM Regime)
                        </h2>
                        <div
                            className={`relative overflow-hidden rounded-2xl border ${vis.border} bg-gradient-to-br ${vis.bg} p-6 md:p-8 shadow-2xl`}
                        >
                            <div
                                className={`pointer-events-none absolute -right-20 -top-20 w-72 h-72 rounded-full blur-[100px] ${vis.glow}`}
                            />
                            <div className="relative flex flex-col md:flex-row md:items-center md:justify-between gap-6">
                                <div className="space-y-2">
                                    <div className="flex items-center gap-3 flex-wrap">
                                        <span className={`h-2 w-12 rounded-full ${vis.accent}`} />
                                        <span className={`text-xs font-black tracking-widest uppercase ${vis.text}`}>
                                            {vis.title}
                                        </span>
                                    </div>
                                    <p className="text-3xl md:text-4xl font-black text-white tracking-tight">
                                        Regime {data.regime.regime_state}{' '}
                                        <span className="text-lg md:text-xl font-bold text-gray-400">
                                            / {data.regime.regime_label}
                                        </span>
                                    </p>
                                    <p className="text-sm text-gray-400 max-w-xl">{vis.subtitle}</p>
                                    <div className="flex flex-wrap gap-2 pt-2 text-xs font-mono text-gray-500">
                                        <span className={`rounded border px-2 py-1 ${vis.badge}`}>
                                            宏觀列日期 {data.regime.date}
                                        </span>
                                        <span className="rounded border border-gray-700 bg-black/30 px-2 py-1">
                                            特徵截面 as_of {data.as_of_date ?? '—'}
                                        </span>
                                        <span className="rounded border border-gray-700 bg-black/30 px-2 py-1">
                                            評估標的數 {data.n_universe}
                                        </span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </section>

                    {/* Picks table */}
                    <section>
                        <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
                            <h2 className="text-sm text-gray-500 font-black tracking-widest uppercase flex items-center gap-2">
                                <Table2 size={16} className="text-violet-400" />
                                規則觸發清單
                            </h2>
                            <p className="text-[10px] text-gray-600 font-mono truncate max-w-full" title={data.rules_path}>
                                {data.rules_path}
                            </p>
                        </div>

                        {data.picks.length === 0 ? (
                            <div className="bg-[#161B22] border border-gray-800 rounded-xl p-8 text-center text-gray-500 text-sm">
                                目前無任何標的觸發存活規則。可調降 WFO 門檻後重跑{' '}
                                <code className="text-gray-400">04_run_wfo_mining</code>，或改用全市場 universe 再試。
                            </div>
                        ) : (
                            <div className="overflow-x-auto rounded-xl border border-gray-800 bg-[#161B22]">
                                <table className="min-w-full text-sm">
                                    <thead>
                                        <tr className="text-left text-[10px] font-black uppercase tracking-widest text-gray-500 border-b border-gray-800">
                                            <th className="px-4 py-3">代號</th>
                                            <th className="px-4 py-3">收盤</th>
                                            <th className="px-4 py-3">IS 勝率</th>
                                            <th className="px-4 py-3">OOS 勝率</th>
                                            <th className="px-4 py-3">規則 (IF-THEN)</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {data.picks.map((row, i) => (
                                            <tr
                                                key={`${row.symbol}-${i}-${row.fold_id}`}
                                                className="border-b border-gray-800/80 hover:bg-black/20 transition"
                                            >
                                                <td className="px-4 py-3 font-mono font-bold">
                                                    <Link
                                                        to={toStockDetailPath(cleanStockSymbol(row.symbol))}
                                                        className="text-violet-300 hover:text-violet-200 underline-offset-2 hover:underline"
                                                    >
                                                        {cleanStockSymbol(row.symbol)}
                                                    </Link>
                                                </td>
                                                <td className="px-4 py-3 font-mono text-gray-200">{formatPrice(row.close)}</td>
                                                <td className="px-4 py-3 font-mono text-emerald-200/90">
                                                    {formatPct(row.is_win_rate, 2)}
                                                </td>
                                                <td className="px-4 py-3 font-mono text-sky-200/90">
                                                    {formatPct(row.oos_win_rate, 2)}
                                                </td>
                                                <td className="px-4 py-3 text-gray-400 text-xs leading-relaxed max-w-xl">
                                                    {row.rule_human_readable}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </section>
                </>
            ) : !error ? (
                <div className="text-gray-500 text-sm">尚無資料，請確認後端已啟動並按「重新推論」。</div>
            ) : null}
        </div>
    );
}
