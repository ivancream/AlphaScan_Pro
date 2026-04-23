import React, { useEffect, useState } from 'react';
import { Activity } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';

import { useWarrants } from '@/hooks/useWarrants';
import { WarrantTable, type QuickFilters } from '@/components/warrants/WarrantTable';
import { API_V1_BASE } from '@/lib/apiBase';
import { cleanStockSymbol } from '@/lib/stocks';
import { useAppStore } from '@/store/useAppStore';

export default function WarrantSelectionPage() {
    const queryClient = useQueryClient();
    const [searchParams, setSearchParams] = useSearchParams();
    const [input, setInput] = useState('');
    const [symbol, setSymbol] = useState('');
    const { data, isLoading, isFetching, error } = useWarrants(symbol, !!symbol);
    const [syncingMaster, setSyncingMaster] = useState(false);
    const [lastUpdatedLabel, setLastUpdatedLabel] = useState('--:--:--');
    const [filters, setFilters] = useState<QuickFilters>({
        moneynessMin: null,
        moneynessMax: null,
        minEffectiveGearing: null,
        maxSpreadGearingRatio: null,
        minDteDays: null,
    });

    const handleSubmit = () => {
        const normalized = cleanStockSymbol(input);
        if (!normalized) return;
        setSymbol(normalized);
        setSearchParams({ symbol: normalized });
        useAppStore.getState().setSymbol(normalized);
    };

    const handleSyncWarrantMaster = async () => {
        setSyncingMaster(true);
        const controller = new AbortController();
        const timer = window.setTimeout(() => controller.abort(), 180_000);
        try {
            const res = await fetch(`${API_V1_BASE}/warrants/refresh-master`, {
                method: 'POST',
                signal: controller.signal,
            });
            const body = (await res.json().catch(() => ({}))) as {
                detail?: string;
                upserted?: number;
                message?: string;
            };
            if (!res.ok) {
                window.alert(
                    typeof body.detail === 'string' ? body.detail : '權證主檔同步失敗',
                );
                return;
            }
            await queryClient.invalidateQueries({ queryKey: ['warrants'] });
            window.alert(body.message ?? `已同步 ${body.upserted ?? 0} 筆權證主檔`);
        } catch (e: unknown) {
            const aborted =
                (e instanceof DOMException || e instanceof Error) && (e as { name?: string }).name === 'AbortError';
            if (aborted) {
                window.alert('同步逾時（MOPS 下載可能較久）。請稍後再試，或檢查網路與後端日誌。');
            } else {
                window.alert('無法連線至後端，請確認 API 已啟動。');
            }
        } finally {
            window.clearTimeout(timer);
            setSyncingMaster(false);
        }
    };

    useEffect(() => {
        if (!data) return;
        const now = new Date();
        setLastUpdatedLabel(now.toLocaleTimeString('zh-TW', { hour12: false }));
    }, [data]);

    useEffect(() => {
        const querySymbol = cleanStockSymbol(searchParams.get('symbol') ?? '');
        if (!querySymbol) return;
        setInput((prev) => (prev === querySymbol ? prev : querySymbol));
        setSymbol((prev) => (prev === querySymbol ? prev : querySymbol));
        useAppStore.getState().setSymbol(querySymbol);
    }, [searchParams]);

    const warrants = data?.warrants ?? [];
    const underlyingPrice = data?.underlying_price ?? null;
    const underlyingReference = data?.underlying_reference ?? null;
    const changePct = (() => {
        if (
            underlyingPrice === null ||
            underlyingReference === null ||
            underlyingReference === 0
        ) {
            return null;
        }
        return ((underlyingPrice - underlyingReference) / underlyingReference) * 100;
    })();
    const changeColor =
        changePct === null
            ? 'text-gray-300'
            : changePct > 0
              ? 'text-red-400'
              : changePct < 0
                ? 'text-green-400'
                : 'text-gray-300';
    const changeText =
        changePct === null
            ? '--'
            : `${changePct > 0 ? '+' : ''}${changePct.toFixed(2)}%`;

    return (
        <div className="p-6 space-y-5 text-gray-200 animate-in fade-in duration-500">
            <div className="flex flex-wrap items-end justify-between gap-4 border-b border-gray-800 pb-4">
                <div>
                    <h2 className="text-3xl font-bold text-white tracking-widest flex items-center gap-3">
                        <span className="w-1.5 h-8 bg-cyan-500 rounded-full inline-block"></span>
                        權證挑選
                    </h2>
                    <p className="text-xs text-gray-500 mt-2">
                        先選定單一標的，再由後端即時計算該標的關聯權證的 IV / Delta / 實質槓桿 / 差槓比。
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <input
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter') handleSubmit();
                        }}
                        placeholder="輸入標的股票代號"
                        className="w-64 bg-[#161B22] border border-gray-700 text-white px-3 py-2 rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-cyan-500 focus:border-cyan-500"
                    />
                    <button
                        onClick={handleSubmit}
                        className="bg-cyan-600 hover:bg-cyan-700 text-white px-4 py-2 rounded-lg text-sm font-bold transition"
                    >
                        查詢
                    </button>
                    <button
                        type="button"
                        onClick={() => void handleSyncWarrantMaster()}
                        disabled={syncingMaster}
                        className="border border-gray-600 text-gray-300 hover:bg-gray-800 px-3 py-2 rounded-lg text-xs font-semibold transition disabled:opacity-50"
                        title="從證交所 MOPS 下載權證主檔寫入本機資料庫（需網路）"
                    >
                        {syncingMaster ? '同步中…' : '同步主檔'}
                    </button>
                </div>
            </div>

            <div className="text-xs text-gray-400">
                當前標的：<span className="font-mono text-cyan-300">{symbol || '-'}</span>
                {isFetching && (
                    <span className="ml-2 inline-flex items-center gap-1 text-amber-300">
                        <Activity size={12} className="animate-spin" />
                        更新中
                    </span>
                )}
            </div>

            <div className="rounded-xl border border-cyan-900/40 bg-[#111827] px-4 py-3 flex items-center justify-between">
                <div className="text-xs text-gray-400">標的股即時資訊</div>
                <div className="text-sm font-mono text-cyan-300">
                    {symbol ? (
                        <>
                            目前標的股價：
                            <span className="ml-2 text-white font-semibold">
                                {underlyingPrice !== null ? underlyingPrice.toFixed(2) : '--'}
                            </span>
                            <span className={`ml-2 font-semibold ${changeColor}`}>
                                ({changeText})
                            </span>
                        </>
                    ) : (
                        <span className="text-gray-500 text-xs">請先輸入標的並查詢</span>
                    )}
                </div>
            </div>

            <div className="rounded-xl border border-gray-800 bg-[#161B22] p-4">
                <div className="text-xs uppercase tracking-wider text-cyan-300 font-semibold mb-3">
                    Quick Filters
                </div>
                <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
                    <label className="flex flex-col gap-1">
                        <span className="text-xs text-gray-400">價內外最小值 (%)</span>
                        <input
                            type="number"
                            value={filters.moneynessMin ?? ''}
                            onChange={(e) =>
                                setFilters((prev) => ({
                                    ...prev,
                                    moneynessMin: e.target.value === '' ? null : Number(e.target.value),
                                }))
                            }
                            placeholder="不限制"
                            className="bg-[#0E1117] border border-gray-700 rounded px-2 py-1.5 text-sm"
                        />
                    </label>
                    <label className="flex flex-col gap-1">
                        <span className="text-xs text-gray-400">價內外最大值 (%)</span>
                        <input
                            type="number"
                            value={filters.moneynessMax ?? ''}
                            onChange={(e) =>
                                setFilters((prev) => ({
                                    ...prev,
                                    moneynessMax: e.target.value === '' ? null : Number(e.target.value),
                                }))
                            }
                            placeholder="不限制"
                            className="bg-[#0E1117] border border-gray-700 rounded px-2 py-1.5 text-sm"
                        />
                    </label>
                    <label className="flex flex-col gap-1">
                        <span className="text-xs text-gray-400">實質槓桿 ≧</span>
                        <input
                            type="number"
                            step="0.1"
                            value={filters.minEffectiveGearing ?? ''}
                            onChange={(e) =>
                                setFilters((prev) => ({
                                    ...prev,
                                    minEffectiveGearing: e.target.value === '' ? null : Number(e.target.value),
                                }))
                            }
                            placeholder="不限制"
                            className="bg-[#0E1117] border border-gray-700 rounded px-2 py-1.5 text-sm"
                        />
                    </label>
                    <label className="flex flex-col gap-1">
                        <span className="text-xs text-gray-400">差槓比 ≦</span>
                        <select
                            value={filters.maxSpreadGearingRatio === null ? 'none' : String(filters.maxSpreadGearingRatio)}
                            onChange={(e) => {
                                const val = e.target.value;
                                setFilters((prev) => ({
                                    ...prev,
                                    maxSpreadGearingRatio: val === 'none' ? null : Number(val),
                                }));
                            }}
                            className="bg-[#0E1117] border border-gray-700 rounded px-2 py-1.5 text-sm"
                        >
                            <option value="none">不限制</option>
                            <option value="0.0005">0.0005</option>
                            <option value="0.001">0.001</option>
                            <option value="0.002">0.002</option>
                        </select>
                    </label>
                    <label className="flex flex-col gap-1">
                        <span className="text-xs text-gray-400">剩餘天數 (DTE)</span>
                        <select
                            value={filters.minDteDays === null ? 'none' : String(filters.minDteDays)}
                            onChange={(e) => {
                                const val = e.target.value;
                                setFilters((prev) => ({
                                    ...prev,
                                    minDteDays: val === 'none' ? null : Number(val),
                                }));
                            }}
                            className="bg-[#0E1117] border border-gray-700 rounded px-2 py-1.5 text-sm"
                        >
                            <option value="none">不限制</option>
                            <option value="15">≥ 15天</option>
                            <option value="30">≥ 30天</option>
                            <option value="60">≥ 60天</option>
                        </select>
                    </label>
                </div>
            </div>

            {!symbol ? (
                <div className="rounded-xl border border-gray-800 bg-[#161B22] p-10 text-center text-gray-500 text-sm">
                    請在上方輸入標的股票代號後按「查詢」，或使用右鍵選單／網址參數{' '}
                    <span className="font-mono text-gray-400">?symbol=</span>
                    帶入標的。
                </div>
            ) : isLoading ? (
                <div className="rounded-xl border border-gray-800 bg-[#161B22] p-8 text-center text-gray-400">
                    載入權證資料中...
                </div>
            ) : error ? (
                <div className="rounded-xl border border-rose-900/50 bg-rose-950/20 p-4 text-sm text-rose-200 whitespace-pre-wrap">
                    {(error as Error).message || '查詢失敗，請確認後端與 Shioaji 連線狀態'}
                </div>
            ) : warrants.length === 0 ? (
                <div className="rounded-xl border border-gray-800 bg-[#161B22] p-8 text-center space-y-4 text-gray-500">
                    <p>找不到此標的的權證資料。</p>
                    {underlyingPrice !== null && (
                        <p className="text-xs text-emerald-400/90">
                            標的行情已連上（{underlyingPrice.toFixed(2)}），代表主檔尚未含此標的之權證列，請先按「同步主檔」。
                        </p>
                    )}
                    <p className="text-xs text-gray-600 max-w-md mx-auto">
                        若尚未匯入權證主檔（履約價、到期日等），請按上方「同步主檔」從證交所公開 CSV
                        寫入資料庫後再查詢；或於後端停止服務後執行：
                        <span className="font-mono text-gray-400"> python -m backend.scripts.ingest_warrant_master </span>
                    </p>
                    <button
                        type="button"
                        onClick={() => void handleSyncWarrantMaster()}
                        disabled={syncingMaster}
                        className="text-cyan-400 border border-cyan-800 hover:bg-cyan-950/40 px-4 py-2 rounded-lg text-sm disabled:opacity-50"
                    >
                        {syncingMaster ? '同步中…' : '立即同步主檔'}
                    </button>
                </div>
            ) : (
                <WarrantTable
                    data={warrants}
                    filters={filters}
                    lastUpdatedLabel={lastUpdatedLabel}
                    isUpdating={isFetching}
                />
            )}
        </div>
    );
}
