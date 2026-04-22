import React, { useEffect, useState } from 'react';
import { isAxiosError } from 'axios';
import { useSwingFast, useSwingLong, useSwingWanderer } from '@/hooks/useSwing';
import { LoadingState } from '@/components/ui/LoadingState';
import { useAppStore } from '@/store/useAppStore';
import { useNavigate } from 'react-router-dom';
import { ChipsAnalysisWidget } from '@/components/chips/ChipsAnalysisWidget';
import { TrendingUp, Activity } from 'lucide-react';
import { cleanStockSymbol, toStockDetailPath } from '@/lib/stocks';
import { formatTaipeiScanTime, scannerResultsSourceLabel } from '@/lib/scanMeta';
import {
    DEFAULT_LONG_SELECTION,
    DEFAULT_LONG_THRESHOLDS,
    loadLongSelectionParams,
    saveLongSelectionParams,
} from '@/lib/selectionParams';

function formatSwingScanError(err: unknown): string {
    if (isAxiosError(err)) {
        const code = err.code;
        if (code === 'ECONNABORTED' || code === 'ETIMEDOUT') {
            return '掃描請求逾時（超過 90 秒）。\n系統已自動重試，若仍失敗請稍後再試或縮小篩選條件。';
        }
        if (code === 'ERR_NETWORK' || err.message === 'Network Error') {
            return '無法連線至後端 http://localhost:8000。\n請在專案根目錄另開終端機執行：uvicorn backend.main:app --reload --port 8000';
        }
        const data = err.response?.data as { detail?: string } | undefined;
        if (typeof data?.detail === 'string') {
            return data.detail;
        }
        return err.message || '請求失敗';
    }
    if (err instanceof Error) return err.message;
    return String(err);
}

function formatDdFromHighCell(v: unknown): string {
    if (v === undefined || v === null || v === '') return '-';
    const n = Number(v);
    if (!Number.isFinite(n)) return '-';
    return `${n.toFixed(2)}%`;
}

type Strategy = 'core_long' | 'wanderer';

type ScanRow = Record<string, string | number | boolean | null | undefined> & {
    _ticker: string;
    代號: string;
    名稱: string;
    產業: string;
    收盤價: number;
    '今日漲跌幅(%)': number;
    '成交量(張)': number;
    資料日期: string;
    is_disposition?: boolean;
};

const STRATEGY_CONFIG: Record<Strategy, { label: string; desc: string; color: string }> = {
    core_long: {
        label: '猛虎出閘',
        desc: '通道擴張 + 均線多頭排列 + 爆量表態訊號',
        color: 'red',
    },
    wanderer: {
        label: '浪子回頭',
        desc: '月線重新翻揚 + 布林位階偏低，捕捉均值回歸動能',
        color: 'red',
    },
};

const FilterCheckbox = ({ label, checked, onChange, desc, color }: { label: string, checked: boolean, onChange: (v: boolean) => void, desc: string, color: 'red' | 'amber' }) => (
    <label className="flex items-start gap-3 cursor-pointer group">
        <div className="pt-1">
            <input 
                type="checkbox" 
                checked={checked} 
                onChange={(e) => onChange(e.target.checked)}
                className={`w-5 h-5 rounded border-gray-700 bg-[#0E1117] transition-all cursor-pointer ${
                    color === 'red' ? 'text-red-600 focus:ring-red-500' : 'text-amber-600 focus:ring-amber-500'
                }`}
            />
        </div>
        <div className="flex flex-col">
            <span className={`font-bold transition-colors ${checked ? (color === 'red' ? 'text-red-400' : 'text-amber-300') : 'text-gray-500'}`}>
                {label}
            </span>
            <span className="text-[10px] text-gray-500 font-mono mt-0.5">{desc}</span>
        </div>
    </label>
);

export default function SwingLongPage() {
    const [strategy, setStrategy] = useState<Strategy>('core_long');
    const [selectedItem, setSelectedItem] = useState<ScanRow | null>(null);
    const [onlyShowDisposition, setOnlyShowDisposition] = useState(false);
    const [sortConfig, setSortConfig] = useState<{ key: string, direction: 'asc' | 'desc' } | null>(null);
    const setSymbol         = useAppStore((state) => state.setSymbol);
    const scannedStrategies = useAppStore((state) => state.scannedStrategies);
    const setScanned        = useAppStore((state) => state.setScanned);
    const navigate = useNavigate();

    // UI 篩選（前端即時過濾，不觸發後端重掃）；門檻與勾選可自訂並存於 localStorage
    const [storedSelection, setStoredSelection] = useState(() => loadLongSelectionParams());
    const { longFilters, wandererFilters, thresholds } = storedSelection;

    useEffect(() => {
        saveLongSelectionParams(storedSelection);
    }, [storedSelection]);

    // 後端掃描參數固定為「寬鬆條件」，拿到結果後再由前端 checkbox 過濾
    const longServerParams = { req_ma: false, req_vol: false, req_slope: false };
    const wandererServerParams = { req_slope: false, req_bb_level: false };

    const isLongScanned = scannedStrategies.includes('core_long');
    const isWandererScanned = scannedStrategies.includes('wanderer');

    // 進入頁面時自動啟動掃描
    useEffect(() => {
        setScanned('core_long');
        setScanned('wanderer');
    }, [setScanned]);

    // ── 快速路徑：讀 intraday scanner 記憶體快取（< 100ms） ──────────────────
    const fastStrategy = strategy === 'core_long' ? 'long' : 'wanderer';
    const { data: fastData, isLoading: isFastLoading } = useSwingFast(fastStrategy, true);
    const fastItems = fastData?.items ?? [];
    const hasFastResults = fastItems.length > 0;

    // ── 慢速路徑：全市場掃描（快速路徑為空時才啟用） ────────────────────────
    const slowEnabled = hasFastResults === false && !isFastLoading;
    const { data: coreLongResults, isLoading: isLoadingCore, error: errorCore, refetch: refetchCore } =
        useSwingLong(isLongScanned && strategy === 'core_long' && slowEnabled, longServerParams);
    const { data: wandererResults, isLoading: isLoadingWanderer, error: errorWanderer, refetch: refetchWanderer } =
        useSwingWanderer(isWandererScanned && strategy === 'wanderer' && slowEnabled, wandererServerParams);

    // 優先使用快速路徑結果；快速路徑為空才用慢速路徑
    const slowResults = strategy === 'core_long' ? coreLongResults : wandererResults;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const scanResults: ScanRow[] | undefined = hasFastResults
        ? (fastItems as unknown as ScanRow[])
        : (slowResults as unknown as ScanRow[] | undefined);
    const isLoading = isFastLoading || (strategy === 'core_long' ? isLoadingCore : isLoadingWanderer);
    const isActuallyScanned = true;   // 進頁面即自動掃描，永遠顯示結果區塊
    const error = strategy === 'core_long' ? errorCore : errorWanderer;
    const refetchScan = strategy === 'core_long' ? refetchCore : refetchWanderer;

    const filteredResults: ScanRow[] = (scanResults ?? []).filter((item) => {
            if (strategy === 'core_long') {
                if (longFilters.req_ma && item['均線多排'] !== 'V') return false;
                if (longFilters.req_vol && Number(item['量比']) <= thresholds.minVolRatio) return false;
                if (longFilters.req_slope && Number(item['上軌斜率']) <= thresholds.minUpperBandSlope) return false;
                return true;
            }

            // wanderer
            if (wandererFilters.req_slope && Number(item['月線斜率(%)']) <= thresholds.minMonthlySlopePct) return false;
            if (wandererFilters.req_bb_level && Number(item['布林位階']) >= thresholds.maxBbLevelExclusive) return false;
            if (wandererFilters.req_drawdown) {
                const rawDd = item['自高點下跌(%)'];
                if (rawDd !== undefined && rawDd !== null && rawDd !== '') {
                    if (Number(rawDd) < thresholds.minDrawdownFromHighPct) return false;
                }
            }
            if (onlyShowDisposition) return Boolean(item.is_disposition);
            return true;
        });

    const sortedResults = [...filteredResults];
    if (sortConfig !== null) {
        sortedResults.sort((a, b) => {
            let valA = a[sortConfig.key];
            let valB = b[sortConfig.key];
            
            // Handle V and - specially
            if (valA === 'V') valA = 1;
            else if (valA === '-') valA = 0;
            
            if (valB === 'V') valB = 1;
            else if (valB === '-') valB = 0;

            if (sortConfig.key === '自高點下跌(%)') {
                const parseDd = (v: unknown) =>
                    v === undefined || v === null || v === '' || !Number.isFinite(Number(v))
                        ? Number.NEGATIVE_INFINITY
                        : Number(v);
                valA = parseDd(valA);
                valB = parseDd(valB);
            }

            if (typeof valA === 'string' && typeof valB === 'string') {
                return sortConfig.direction === 'asc' 
                    ? valA.localeCompare(valB) 
                    : valB.localeCompare(valA);
            }

            const safeA = valA ?? Number.NEGATIVE_INFINITY;
            const safeB = valB ?? Number.NEGATIVE_INFINITY;

            if (safeA < safeB) return sortConfig.direction === 'asc' ? -1 : 1;
            if (safeA > safeB) return sortConfig.direction === 'asc' ? 1 : -1;
            return 0;
        });
    }
    const klineRefDate =
        (sortedResults[0]?.['資料日期'] as string | undefined) ??
        (scanResults?.[0]?.['資料日期'] as string | undefined) ??
        '-';
    const usingSlowPath = slowEnabled && (scanResults?.length ?? 0) > 0;

    const cfg = STRATEGY_CONFIG[strategy];
    const btnColor =
        cfg.color === 'amber'
            ? 'bg-amber-600 hover:bg-amber-700 shadow-amber-900/20'
            : 'bg-red-600 hover:bg-red-700 shadow-red-900/20';

    const handleRowClick = (item: ScanRow) => {
        setSelectedItem(item);
        setSymbol(cleanStockSymbol(item._ticker));
    };

    const getChangePctColor = (val: number | string) => {
        const num = Number(val);
        if (isNaN(num)) return 'text-gray-400';
        if (num > 0) return 'text-red-400 font-bold';
        if (num < 0) return 'text-green-400 font-bold';
        return 'text-gray-400 font-bold';
    };

    const handleStrategyChange = (s: Strategy) => {
        setStrategy(s);
        setSelectedItem(null);
        setSortConfig(null);
    };

    const handleStartScan = () => {
        // 第一次點擊: 啟用 query；後續點擊: 主動重掃
        if (strategy === 'core_long' && isLongScanned) {
            void refetchCore();
            return;
        }
        if (strategy === 'wanderer' && isWandererScanned) {
            void refetchWanderer();
            return;
        }
        setScanned(strategy);
    };

    const handleSort = (key: string) => {
        let direction: 'asc' | 'desc' = 'desc';
        if (sortConfig && sortConfig.key === key && sortConfig.direction === 'desc') {
            direction = 'asc';
        }
        setSortConfig({ key, direction });
    };

    const renderSortIcon = (key: string) => {
        if (!sortConfig || sortConfig.key !== key) return <span className="ml-1 opacity-20">↕</span>;
        return sortConfig.direction === 'asc' ? <span className="ml-1 text-white">↑</span> : <span className="ml-1 text-white">↓</span>;
    };

    return (
        <div className="p-6 space-y-6 animate-in fade-in duration-500 text-gray-200">

            {/* Header */}
            <div className="flex justify-between items-center border-b border-gray-800 pb-4">
                <div>
                    <h2 className="text-3xl font-bold text-white tracking-widest flex items-center gap-3">
                        <span className="w-1.5 h-8 bg-red-500 rounded-full inline-block"></span>
                        多方選股策略
                    </h2>
                </div>
                <div className="flex flex-col items-end gap-1">
                <button
                    onClick={handleStartScan}
                    disabled={isLoading}
                    className={`${btnColor} text-white px-6 py-2.5 rounded-lg font-bold shadow-lg transition flex items-center gap-2 disabled:opacity-50`}
                >
                    {isLoading ? <Activity className="animate-spin" size={18} /> : <TrendingUp size={18} />}
                    {isLoading ? '核心引擎掃描中...' : `啟動「${cfg.label}」選股`}
                </button>
                <p className="text-[10px] text-gray-500 max-w-xs text-right">
                    提示：全市場篩選約需 1～3 分鐘；盤中依後端排程與永豐快照更新，為數分鐘級並非逐筆即時。請先啟動後端 API。
                </p>
                </div>
            </div>

            {/* 策略切換 Tabs */}
            <div className="flex gap-2">
                {(Object.entries(STRATEGY_CONFIG) as [Strategy, typeof STRATEGY_CONFIG[Strategy]][]).map(([key, val]) => (
                    <button
                        key={key}
                        onClick={() => handleStrategyChange(key)}
                        className={`px-5 py-2.5 rounded-lg font-bold text-sm transition-all border ${
                            strategy === key
                                ? val.color === 'amber'
                                    ? 'bg-amber-600/20 border-amber-500 text-amber-300'
                                    : 'bg-red-600/20 border-red-500 text-red-300'
                                : 'bg-[#161B22] border-gray-700 text-gray-400 hover:border-gray-500'
                        }`}
                    >
                        {val.label}
                    </button>
                ))}
            </div>

            {/* 策略篩選與參數配置 */}
            <div className={`bg-[#161B22] border rounded-xl p-5 space-y-4 ${cfg.color === 'amber' ? 'border-amber-800/40' : 'border-red-800/40'}`}>
                <div className="flex flex-wrap justify-between items-center gap-2 border-b border-gray-800 pb-2">
                    <p className={`${cfg.color === 'amber' ? 'text-amber-400' : 'text-red-400'} font-bold text-sm tracking-wider uppercase`}>策略篩選條件 (預設全選)</p>
                    <div className="flex flex-wrap items-center gap-3">
                        <span className="text-xs text-gray-500 italic">勾選後將僅顯示符合該條件的標的</span>
                        <button
                            type="button"
                            onClick={() =>
                                setStoredSelection({
                                    ...DEFAULT_LONG_SELECTION,
                                    thresholds: { ...DEFAULT_LONG_THRESHOLDS },
                                })
                            }
                            className="text-xs text-gray-500 hover:text-white underline-offset-2 hover:underline"
                        >
                            重設為預設
                        </button>
                    </div>
                </div>
                
                <div
                    className={`grid grid-cols-1 gap-6 ${
                        strategy === 'core_long' ? 'md:grid-cols-3' : 'md:grid-cols-2 lg:grid-cols-4'
                    }`}
                >
                    {strategy === 'core_long' ? (
                        <>
                            <FilterCheckbox 
                                label="均線多排" 
                                checked={longFilters.req_ma} 
                                onChange={(val) =>
                                    setStoredSelection((prev) => ({
                                        ...prev,
                                        longFilters: { ...prev.longFilters, req_ma: val },
                                    }))
                                }
                                desc="MA5 > MA10 > MA20"
                                color="red"
                            />
                            <FilterCheckbox 
                                label="通道擴張" 
                                checked={longFilters.req_slope} 
                                onChange={(val) =>
                                    setStoredSelection((prev) => ({
                                        ...prev,
                                        longFilters: { ...prev.longFilters, req_slope: val },
                                    }))
                                }
                                desc={`上軌斜率 > ${thresholds.minUpperBandSlope}（下軌斜率 < 0 由後端核心條件保障）`}
                                color="red"
                            />
                            <FilterCheckbox 
                                label="爆量表態" 
                                checked={longFilters.req_vol} 
                                onChange={(val) =>
                                    setStoredSelection((prev) => ({
                                        ...prev,
                                        longFilters: { ...prev.longFilters, req_vol: val },
                                    }))
                                }
                                desc={`量比 > ${thresholds.minVolRatio}`}
                                color="red"
                            />
                        </>
                    ) : (
                        <>
                            <FilterCheckbox 
                                label="月線斜率" 
                                checked={wandererFilters.req_slope} 
                                onChange={(val) =>
                                    setStoredSelection((prev) => ({
                                        ...prev,
                                        wandererFilters: { ...prev.wandererFilters, req_slope: val },
                                    }))
                                }
                                desc={`月線斜率翻揚 > ${thresholds.minMonthlySlopePct}%`}
                                color="red"
                            />
                            <FilterCheckbox 
                                label="布林位階" 
                                checked={wandererFilters.req_bb_level} 
                                onChange={(val) =>
                                    setStoredSelection((prev) => ({
                                        ...prev,
                                        wandererFilters: { ...prev.wandererFilters, req_bb_level: val },
                                    }))
                                }
                                desc={`位階 < ${thresholds.maxBbLevelExclusive}（具備均值回歸空間）`}
                                color="red"
                            />
                            <FilterCheckbox 
                                label="自高點跌幅" 
                                checked={wandererFilters.req_drawdown} 
                                onChange={(val) =>
                                    setStoredSelection((prev) => ({
                                        ...prev,
                                        wandererFilters: { ...prev.wandererFilters, req_drawdown: val },
                                    }))
                                }
                                desc={`近10根日K高點回落 ≥ ${thresholds.minDrawdownFromHighPct}%`}
                                color="red"
                            />
                        </>
                    )}
                </div>

                <div className="border-t border-gray-800 pt-4 space-y-3">
                    <p className="text-xs text-gray-500 font-semibold uppercase tracking-wide">自訂數值門檻</p>
                    {strategy === 'core_long' ? (
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                            <label className="flex flex-col gap-1.5 text-sm">
                                <span className="text-gray-400">量比下限（須大於）</span>
                                <input
                                    type="number"
                                    step="0.1"
                                    min={0}
                                    value={thresholds.minVolRatio}
                                    onChange={(e) => {
                                        const v = parseFloat(e.target.value);
                                        if (!Number.isFinite(v)) return;
                                        setStoredSelection((prev) => ({
                                            ...prev,
                                            thresholds: { ...prev.thresholds, minVolRatio: Math.max(0, v) },
                                        }));
                                    }}
                                    className="bg-[#0E1117] border border-gray-700 rounded-lg px-3 py-2 text-white font-mono text-sm focus:ring-1 focus:ring-red-500 focus:border-red-500"
                                />
                                <span className="text-[10px] text-gray-600">預設 2（與原「五日均量 × 2」一致）</span>
                            </label>
                            <label className="flex flex-col gap-1.5 text-sm">
                                <span className="text-gray-400">上軌斜率下限（須大於）</span>
                                <input
                                    type="number"
                                    step="0.1"
                                    value={thresholds.minUpperBandSlope}
                                    onChange={(e) => {
                                        const v = parseFloat(e.target.value);
                                        if (!Number.isFinite(v)) return;
                                        setStoredSelection((prev) => ({
                                            ...prev,
                                            thresholds: { ...prev.thresholds, minUpperBandSlope: v },
                                        }));
                                    }}
                                    className="bg-[#0E1117] border border-gray-700 rounded-lg px-3 py-2 text-white font-mono text-sm focus:ring-1 focus:ring-red-500 focus:border-red-500"
                                />
                                <span className="text-[10px] text-gray-600">預設 0</span>
                            </label>
                        </div>
                    ) : (
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                            <label className="flex flex-col gap-1.5 text-sm">
                                <span className="text-gray-400">月線斜率下限 %（須大於）</span>
                                <input
                                    type="number"
                                    step="0.1"
                                    value={thresholds.minMonthlySlopePct}
                                    onChange={(e) => {
                                        const v = parseFloat(e.target.value);
                                        if (!Number.isFinite(v)) return;
                                        setStoredSelection((prev) => ({
                                            ...prev,
                                            thresholds: { ...prev.thresholds, minMonthlySlopePct: v },
                                        }));
                                    }}
                                    className="bg-[#0E1117] border border-gray-700 rounded-lg px-3 py-2 text-white font-mono text-sm focus:ring-1 focus:ring-red-500 focus:border-red-500"
                                />
                                <span className="text-[10px] text-gray-600">預設 0.8</span>
                            </label>
                            <label className="flex flex-col gap-1.5 text-sm">
                                <span className="text-gray-400">布林位階上限（須小於）</span>
                                <input
                                    type="number"
                                    step="0.1"
                                    min={0.1}
                                    value={thresholds.maxBbLevelExclusive}
                                    onChange={(e) => {
                                        const v = parseFloat(e.target.value);
                                        if (!Number.isFinite(v)) return;
                                        setStoredSelection((prev) => ({
                                            ...prev,
                                            thresholds: {
                                                ...prev.thresholds,
                                                maxBbLevelExclusive: Math.max(0.1, v),
                                            },
                                        }));
                                    }}
                                    className="bg-[#0E1117] border border-gray-700 rounded-lg px-3 py-2 text-white font-mono text-sm focus:ring-1 focus:ring-red-500 focus:border-red-500"
                                />
                                <span className="text-[10px] text-gray-600">預設 4（排除位階 ≥ 此值）</span>
                            </label>
                            <label className="flex flex-col gap-1.5 text-sm">
                                <span className="text-gray-400">自高點跌幅下限 %（須 ≥）</span>
                                <input
                                    type="number"
                                    step="0.5"
                                    min={0}
                                    max={100}
                                    value={thresholds.minDrawdownFromHighPct}
                                    onChange={(e) => {
                                        const v = parseFloat(e.target.value);
                                        if (!Number.isFinite(v)) return;
                                        setStoredSelection((prev) => ({
                                            ...prev,
                                            thresholds: {
                                                ...prev.thresholds,
                                                minDrawdownFromHighPct: Math.min(100, Math.max(0, v)),
                                            },
                                        }));
                                    }}
                                    className="bg-[#0E1117] border border-gray-700 rounded-lg px-3 py-2 text-white font-mono text-sm focus:ring-1 focus:ring-red-500 focus:border-red-500"
                                />
                                <span className="text-[10px] text-gray-600">預設 10（近10根日K最高 vs 收盤）</span>
                            </label>
                        </div>
                    )}
                </div>
            </div>

            {/* 掃描結果 */}
            {isActuallyScanned && (
                <div className="bg-[#161B22] border border-gray-800 rounded-xl overflow-hidden shadow-xl">
                    <div className="flex justify-between items-start gap-4 bg-[#0E1117] px-6 py-4 border-b border-gray-800">
                        <div className="flex flex-col gap-1.5 sm:flex-row sm:items-start sm:justify-between sm:gap-4 flex-1 min-w-0">
                            <div className="flex flex-col gap-1 min-w-0">
                                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                                    <h3 className="font-bold text-gray-300">掃描結果 ({filteredResults.length})</h3>
                                </div>
                                <div className="text-[11px] text-gray-500 leading-relaxed space-y-0.5 max-w-3xl">
                                    <p title="技術指標使用最後一根 K 棒的交易日；盤中快照成功時應為當日日期，非即時報價時間戳。">
                                        <span className="text-gray-400">K 線基準日</span>：{klineRefDate}
                                    </p>
                                    <p>
                                        {usingSlowPath ? (
                                            <>
                                                <span className="text-gray-400">列表來源</span>
                                                ：全市場掃描（快速路徑尚無資料）
                                                {fastData?.last_run ? (
                                                    <>
                                                        {' '}
                                                        · <span className="text-gray-400">盤中排程上次完成</span>：
                                                        {formatTaipeiScanTime(fastData.last_run)}
                                                    </>
                                                ) : null}
                                            </>
                                        ) : (
                                            <>
                                                <span className="text-gray-400">最後掃描（台北）</span>：
                                                {formatTaipeiScanTime(fastData?.last_run)}
                                                {' · '}
                                                <span className="text-gray-400">快取</span>：
                                                {scannerResultsSourceLabel(fastData?.source)}
                                            </>
                                        )}
                                    </p>
                                </div>
                            </div>
                        </div>
                        {strategy === 'wanderer' && (
                            <label className="flex items-center gap-2 text-sm text-gray-400 cursor-pointer hover:text-white transition">
                                <input 
                                    type="checkbox" 
                                    checked={onlyShowDisposition} 
                                    onChange={(e) => setOnlyShowDisposition(e.target.checked)}
                                    className="w-4 h-4 rounded border-gray-700 bg-[#0E1117] text-amber-500 focus:ring-amber-500"
                                />
                                只顯示處置股
                            </label>
                        )}
                    </div>
                    {isLoading ? (
                        <div className="p-12"><LoadingState text="正在從高速資料庫中執行全市場篩選..." /></div>
                    ) : error ? (
                        <div className="p-6 space-y-4 bg-red-950/20 border-t border-red-900/40">
                            <p className="text-red-300 font-semibold">掃描失敗</p>
                            <pre className="text-xs text-red-200/90 whitespace-pre-wrap font-mono bg-black/30 rounded-lg p-4 overflow-auto max-h-48">
                                {formatSwingScanError(error)}
                            </pre>
                            <button
                                type="button"
                                onClick={() => refetchScan()}
                                className="px-4 py-2 rounded-md bg-red-800 hover:bg-red-700 text-white text-sm"
                            >
                                重試
                            </button>
                        </div>
                    ) : filteredResults && filteredResults.length > 0 ? (
                        <div className="overflow-x-auto">
                            {strategy === 'core_long' ? (
                                <table className="w-full text-left text-sm text-gray-300">
                                    <thead className="bg-[#0E1117] text-gray-400 text-xs uppercase font-semibold border-b border-gray-800">
                                        <tr>
                                            <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort('代號')}>代號{renderSortIcon('代號')}</th>
                                            <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort('名稱')}>名稱{renderSortIcon('名稱')}</th>
                                            <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort('產業')}>產業{renderSortIcon('產業')}</th>
                                            <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort('收盤價')}>股價{renderSortIcon('收盤價')}</th>
                                            <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort('今日漲跌幅(%)')}>漲跌幅{renderSortIcon('今日漲跌幅(%)')}</th>
                                            <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort('成交量(張)')}>成交量(張){renderSortIcon('成交量(張)')}</th>
                                            <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort('月線斜率')}>月線斜率%{renderSortIcon('月線斜率')}</th>
                                            <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort('上軌斜率')}>上軌斜率%{renderSortIcon('上軌斜率')}</th>
                                            <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort('量比')}>量比{renderSortIcon('量比')}</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-gray-800">
                                        {sortedResults.map((item: ScanRow, idx: number) => (
                                            <tr
                                                key={idx}
                                                onClick={() => handleRowClick(item)}
                                                onContextMenu={(e) => {
                                                    e.preventDefault();
                                                    useAppStore.getState().openContextMenu(e.clientX, e.clientY, item['_ticker'] || item['代號']);
                                                }}
                                                className="hover:bg-[#1E293B] cursor-pointer transition-colors"
                                            >
                                                <td 
                                                    className="px-6 py-4 text-[#EAB308] font-mono font-bold hover:underline hover:text-yellow-300 cursor-pointer"
                                                    title="點擊跳轉至技術分析模組"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        const symbol = cleanStockSymbol(item['_ticker']);
                                                        setSymbol(symbol);
                                                        navigate(toStockDetailPath(symbol));
                                                    }}
                                                >
                                                    {item['代號']} ↗
                                                </td>
                                                <td className="px-6 py-4 font-medium text-white">{item['名稱']}</td>
                                                <td className="px-6 py-4 text-gray-400">{item['產業']}</td>
                                                <td className={`px-6 py-4 font-mono ${getChangePctColor(item['今日漲跌幅(%)'])}`}>{Number(item['收盤價']).toFixed(1)}</td>
                                                <td className={`px-6 py-4 font-mono ${getChangePctColor(item['今日漲跌幅(%)'])}`}>{Number(item['今日漲跌幅(%)']).toFixed(2)}%</td>
                                                <td className="px-6 py-4 font-mono">{Number(item['成交量(張)']).toLocaleString()}</td>
                                                <td className="px-6 py-4 font-mono">{Number(item['月線斜率']).toFixed(1)}</td>
                                                <td className="px-6 py-4 font-mono">{Number(item['上軌斜率']).toFixed(1)}</td>
                                                <td className="px-6 py-4 font-mono">{Number(item['量比']).toFixed(1)}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            ) : (
                                /* 浪子回頭結果表 */
                                <table className="w-full text-left text-sm text-gray-300">
                                    <thead className="bg-[#0E1117] text-gray-400 text-xs uppercase font-semibold border-b border-gray-800">
                                        <tr>
                                            <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort('代號')}>代號{renderSortIcon('代號')}</th>
                                            <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort('名稱')}>名稱{renderSortIcon('名稱')}</th>
                                            <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort('產業')}>產業{renderSortIcon('產業')}</th>
                                            <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort('收盤價')}>股價{renderSortIcon('收盤價')}</th>
                                            <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort('今日漲跌幅(%)')}>漲跌幅{renderSortIcon('今日漲跌幅(%)')}</th>
                                            <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort('成交量(張)')}>成交量(張){renderSortIcon('成交量(張)')}</th>
                                            <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort('月線斜率(%)')}>月線斜率(%){renderSortIcon('月線斜率(%)')}</th>
                                            <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort('布林位階')}>布林位階{renderSortIcon('布林位階')}</th>
                                            <th
                                                className="px-6 py-4 cursor-pointer hover:text-white"
                                                title="近10根日K之最高價相對收盤之跌幅(%)"
                                                onClick={() => handleSort('自高點下跌(%)')}
                                            >
                                                自高點下跌{renderSortIcon('自高點下跌(%)')}
                                            </th>
                                            <th className="px-6 py-4 text-red-400 font-bold cursor-pointer hover:text-red-300" onClick={() => handleSort('處置狀態')}>處置狀態{renderSortIcon('處置狀態')}</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-gray-800">
                                        {sortedResults.map((item: ScanRow, idx: number) => (
                                            <tr
                                                key={idx}
                                                onClick={() => handleRowClick(item)}
                                                onContextMenu={(e) => {
                                                    e.preventDefault();
                                                    useAppStore.getState().openContextMenu(e.clientX, e.clientY, item['_ticker'] || item['代號']);
                                                }}
                                                className="hover:bg-[#1E293B] cursor-pointer transition-colors"
                                            >
                                                <td 
                                                    className="px-6 py-4 text-[#EAB308] font-mono font-bold hover:underline hover:text-yellow-300 cursor-pointer"
                                                    title="點擊跳轉至技術分析模組"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        const symbol = cleanStockSymbol(item['_ticker']);
                                                        setSymbol(symbol);
                                                        navigate(toStockDetailPath(symbol));
                                                    }}
                                                >
                                                    {item['代號']} ↗
                                                </td>
                                                <td className="px-6 py-4 font-medium text-white whitespace-nowrap">{item['名稱']}</td>
                                                <td className="px-6 py-4 text-gray-400 whitespace-nowrap">{item['產業']}</td>
                                                <td className={`px-6 py-4 font-mono ${getChangePctColor(item['今日漲跌幅(%)'])}`}>{Number(item['收盤價']).toFixed(1)}</td>
                                                <td className={`px-6 py-4 font-mono ${getChangePctColor(item['今日漲跌幅(%)'])}`}>{Number(item['今日漲跌幅(%)']).toFixed(2)}%</td>
                                                <td className="px-6 py-4 font-mono">{Number(item['成交量(張)']).toLocaleString()}</td>
                                                <td className="px-6 py-4 font-mono">{Number(item['月線斜率(%)']).toFixed(1)}</td>
                                                <td className="px-6 py-4 font-mono">{Number(item['布林位階']).toFixed(1)}</td>
                                                <td className="px-6 py-4 font-mono text-amber-200/90">{formatDdFromHighCell(item['自高點下跌(%)'])}</td>
                                                <td className="px-6 py-4 font-mono">{String(item['處置狀態'] ?? '-')}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            )}
                        </div>
                    ) : (
                        <div className="p-12 text-center text-gray-500">
                            當前市場無符合【{cfg.label}】策略之標的。
                        </div>
                    )}
                </div>
            )}

            {selectedItem && (
                <div className="animate-in slide-in-from-bottom duration-500">
                    <ChipsAnalysisWidget
                        symbol={selectedItem._ticker}
                        techData={selectedItem}
                        title={`深度數據透視: ${selectedItem['代號']} ${selectedItem['名稱']}`}
                    />
                </div>
            )}
        </div>
    );
}
