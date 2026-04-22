import React, { useState, useMemo, useCallback, useEffect } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useHeatmapData, HeatmapStock } from '@/hooks/useHeatmap';
import { LoadingState } from '@/components/ui/LoadingState';
import { useAppStore } from '@/store/useAppStore';
import { useNavigate } from 'react-router-dom';
import { cleanStockSymbol, toStockDetailPath } from '@/lib/stocks';

type ViewLevel = 'macro' | 'micro';

const VIEW_LABELS: Record<ViewLevel, { label: string; desc: string }> = {
    macro: { label: '板塊', desc: '依主要產業分類聚合板塊' },
    micro: {
        label: '族群',
        desc: '依專案 theme.json 題材聚合；同一檔可屬多個題材鍵，各區塊各列一次；無題材者不列入此視野',
    },
};

/** 板塊聚合列 */
type SectorBlock = {
    key: string;
    label: string;
    stocks: HeatmapStock[];
    totalTurnover: number;
    totalVolume: number;
    avgChangePct: number;
    upCount: number;
    downCount: number;
    flatCount: number;
};

type BlockSortKey =
    | 'label'
    | 'turnover'
    | 'turnover_share'
    | 'avg_change'
    | 'constituents'
    | 'up_count'
    | 'down_count';

/** 板塊內成分股子表排序（僅前端，資料來自同一筆 heatmap API） */
type ComponentSortKey = 'ticker' | 'name' | 'close' | 'change_pct' | 'turnover' | 'volume';

const DEFAULT_COMPONENT_SORT: { key: ComponentSortKey; direction: 'asc' | 'desc' } = {
    key: 'turnover',
    direction: 'desc',
};

function sortComponentStocks(
    stocks: HeatmapStock[],
    cfg: { key: ComponentSortKey; direction: 'asc' | 'desc' }
): HeatmapStock[] {
    const list = [...stocks];
    const { key, direction } = cfg;
    const dir = direction === 'asc' ? 1 : -1;
    list.sort((a, b) => {
        let va: number | string;
        let vb: number | string;
        switch (key) {
            case 'ticker':
                va = a.ticker;
                vb = b.ticker;
                return String(va).localeCompare(String(vb), undefined, { numeric: true }) * dir;
            case 'name':
                va = a.name;
                vb = b.name;
                return String(va).localeCompare(String(vb), 'zh-Hant') * dir;
            case 'close':
                va = a.close;
                vb = b.close;
                break;
            case 'change_pct': {
                const sentinel = direction === 'asc' ? Infinity : -Infinity;
                va = a.change_pct ?? sentinel;
                vb = b.change_pct ?? sentinel;
                break;
            }
            case 'turnover':
                va = a.turnover;
                vb = b.turnover;
                break;
            case 'volume':
                va = a.volume;
                vb = b.volume;
                break;
            default:
                return 0;
        }
        if (va < vb) return -1 * dir;
        if (va > vb) return 1 * dir;
        return 0;
    });
    return list;
}

function getHeatColor(changePct: number | null): string {
    if (changePct == null || Number.isNaN(changePct)) return '#757575';
    if (changePct >= 9.5) return '#FF0000';
    if (changePct >= 5) return '#E53935';
    if (changePct >= 3) return '#EF5350';
    if (changePct >= 1) return '#EF9A9A';
    if (changePct >= 0.5) return '#FFCDD2';
    if (changePct > -0.5) return '#424242';
    if (changePct > -1) return '#C8E6C9';
    if (changePct > -3) return '#81C784';
    if (changePct > -5) return '#4CAF50';
    if (changePct > -9.5) return '#2E7D32';
    return '#1B5E20';
}

function sectorForView(s: HeatmapStock, view: ViewLevel): string {
    const v = view === 'macro' ? s.macro : s.micro;
    const t = (v ?? '').trim();
    return t.length ? t : '（未分類）';
}

/** 族群視野：每檔依 micros 拆成多筆（每筆 micro 為該區塊標籤），板塊成交會重複計入同一檔 */
function expandStocksForMicroView(stocks: HeatmapStock[]): HeatmapStock[] {
    const out: HeatmapStock[] = [];
    for (const s of stocks) {
        const raw = s.micros && s.micros.length > 0 ? s.micros : [s.micro];
        const keys = [...new Set(raw.map((k) => k.trim()).filter(Boolean))];
        const slots = keys.length ? keys : ['（未分類）'];
        for (const micro of slots) {
            out.push({ ...s, micro });
        }
    }
    return out;
}

function buildSectorBlocks(stocks: HeatmapStock[], viewLevel: ViewLevel): SectorBlock[] {
    const map = new Map<string, HeatmapStock[]>();
    for (const s of stocks) {
        const k = sectorForView(s, viewLevel);
        if (!map.has(k)) map.set(k, []);
        map.get(k)!.push(s);
    }

    const blocks: SectorBlock[] = [];
    for (const [label, list] of map) {
        const sortedList = [...list].sort((a, b) => b.turnover - a.turnover);
        const totalTurnover = sortedList.reduce((a, b) => a + b.turnover, 0);
        const totalVolume = sortedList.reduce((a, b) => a + b.volume, 0);
        const forAvg = sortedList.filter((x) => x.change_pct != null);
        const turnoverForAvg = forAvg.reduce((a, b) => a + b.turnover, 0);
        const avgChangePct =
            turnoverForAvg > 0
                ? forAvg.reduce((a, b) => a + (b.change_pct as number) * b.turnover, 0) / turnoverForAvg
                : forAvg.length > 0
                  ? forAvg.reduce((a, b) => a + (b.change_pct as number), 0) / forAvg.length
                  : 0;
        const upCount = sortedList.filter((x) => x.change_pct != null && x.change_pct > 0).length;
        const downCount = sortedList.filter((x) => x.change_pct != null && x.change_pct < 0).length;
        const flatCount = sortedList.length - upCount - downCount;
        blocks.push({
            key: `${viewLevel}::${label}`,
            label,
            stocks: sortedList,
            totalTurnover,
            totalVolume,
            avgChangePct: Math.round(avgChangePct * 100) / 100,
            upCount,
            downCount,
            flatCount,
        });
    }
    return blocks;
}

export default function CapitalFlowPage() {
    const [viewLevel, setViewLevel] = useState<ViewLevel>('macro');
    const [blockSort, setBlockSort] = useState<{ key: BlockSortKey; direction: 'asc' | 'desc' }>({
        key: 'turnover',
        direction: 'desc',
    });
    const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set());
    /** 每個板塊子表獨立排序狀態（key = block.key） */
    const [componentSortByBlock, setComponentSortByBlock] = useState<
        Record<string, { key: ComponentSortKey; direction: 'asc' | 'desc' }>
    >({});

    const { data, isLoading, error, refetch } = useHeatmapData();
    const setSymbol = useAppStore((state) => state.setSymbol);
    const navigate = useNavigate();

    useEffect(() => {
        setExpandedKeys(new Set());
        setComponentSortByBlock({});
    }, [viewLevel]);

    const rawStocks = data?.stocks ?? [];

    const stats = useMemo(() => {
        if (!rawStocks.length) return null;
        const totalTurnover = rawStocks.reduce((sum, s) => sum + s.turnover, 0);
        const upCount = rawStocks.filter((s) => s.change_pct != null && s.change_pct > 0).length;
        const downCount = rawStocks.filter((s) => s.change_pct != null && s.change_pct < 0).length;
        const flatCount = rawStocks.length - upCount - downCount;
        return { totalTurnover, upCount, downCount, flatCount, total: rawStocks.length };
    }, [rawStocks]);

    /** 大盤總成交金額（API 全市場成分各檔 turnover 加總；族群視野下作為占比分母） */
    const marketTotalTurnover = stats?.totalTurnover ?? 0;

    const blockTurnoverSharePct = useCallback(
        (blockTurnover: number) => {
            if (marketTotalTurnover <= 0) return null;
            return (blockTurnover / marketTotalTurnover) * 100;
        },
        [marketTotalTurnover]
    );

    const stocksForBlocks = useMemo(() => {
        if (viewLevel !== 'micro') return rawStocks;
        const themed = rawStocks.filter((s) => Array.isArray(s.micros) && s.micros.length > 0);
        return expandStocksForMicroView(themed);
    }, [rawStocks, viewLevel]);

    const sectorBlocks = useMemo(
        () => buildSectorBlocks(stocksForBlocks, viewLevel),
        [stocksForBlocks, viewLevel]
    );

    const sortedBlocks = useMemo(() => {
        const list = [...sectorBlocks];
        const { key, direction } = blockSort;
        const dir = direction === 'asc' ? 1 : -1;
        list.sort((a, b) => {
            let va: number | string = 0;
            let vb: number | string = 0;
            switch (key) {
                case 'label':
                    va = a.label;
                    vb = b.label;
                    return String(va).localeCompare(String(vb), 'zh-Hant') * dir;
                case 'turnover':
                    va = a.totalTurnover;
                    vb = b.totalTurnover;
                    break;
                case 'turnover_share': {
                    const pa = marketTotalTurnover > 0 ? (a.totalTurnover / marketTotalTurnover) * 100 : 0;
                    const pb = marketTotalTurnover > 0 ? (b.totalTurnover / marketTotalTurnover) * 100 : 0;
                    va = pa;
                    vb = pb;
                    break;
                }
                case 'avg_change':
                    va = a.avgChangePct;
                    vb = b.avgChangePct;
                    break;
                case 'constituents':
                    va = a.stocks.length;
                    vb = b.stocks.length;
                    break;
                case 'up_count':
                    va = a.upCount;
                    vb = b.upCount;
                    break;
                case 'down_count':
                    va = a.downCount;
                    vb = b.downCount;
                    break;
                default:
                    return 0;
            }
            if (typeof va === 'number' && typeof vb === 'number') {
                if (va < vb) return -1 * dir;
                if (va > vb) return 1 * dir;
                return 0;
            }
            return 0;
        });
        return list;
    }, [sectorBlocks, blockSort, marketTotalTurnover]);

    const toggleBlock = useCallback((key: string) => {
        setExpandedKeys((prev) => {
            const next = new Set(prev);
            if (next.has(key)) next.delete(key);
            else next.add(key);
            return next;
        });
    }, []);

    const handleBlockSort = (key: BlockSortKey) => {
        setBlockSort((prev) => {
            if (prev.key === key) {
                return { key, direction: prev.direction === 'asc' ? 'desc' : 'asc' };
            }
            return {
                key,
                direction: key === 'label' ? 'asc' : 'desc',
            };
        });
    };

    const renderBlockSortIcon = (key: BlockSortKey) => {
        if (blockSort.key !== key) return <span className="shrink-0 opacity-20">↕</span>;
        return blockSort.direction === 'asc' ? (
            <span className="shrink-0 text-white">↑</span>
        ) : (
            <span className="shrink-0 text-white">↓</span>
        );
    };

    const handleComponentSort = useCallback((blockKey: string, col: ComponentSortKey) => {
        setComponentSortByBlock((prev) => {
            const cur = prev[blockKey] ?? DEFAULT_COMPONENT_SORT;
            const same = cur.key === col;
            const direction = same
                ? cur.direction === 'asc'
                    ? 'desc'
                    : 'asc'
                : col === 'name' || col === 'ticker'
                  ? 'asc'
                  : 'desc';
            return { ...prev, [blockKey]: { key: col, direction } };
        });
    }, []);

    const renderComponentSortIcon = (blockKey: string, col: ComponentSortKey) => {
        const cfg = componentSortByBlock[blockKey] ?? DEFAULT_COMPONENT_SORT;
        if (cfg.key !== col) return <span className="ml-1 opacity-20">↕</span>;
        return cfg.direction === 'asc' ? (
            <span className="ml-1 text-orange-300/90">↑</span>
        ) : (
            <span className="ml-1 text-orange-300/90">↓</span>
        );
    };

    const goStock = useCallback(
        (ticker: string) => {
            const sym = cleanStockSymbol(ticker);
            setSymbol(sym);
            navigate(toStockDetailPath(sym));
        },
        [setSymbol, navigate]
    );

    return (
        <div className="p-6 space-y-6 animate-in fade-in duration-500 text-gray-200 h-full flex flex-col min-h-0">
            <div className="border-b border-gray-800 pb-4 shrink-0">
                <div className="flex justify-between items-end">
                    <div>
                        <h2 className="text-3xl font-bold text-white tracking-widest flex items-center gap-3">
                            <span className="w-1.5 h-8 bg-orange-500 rounded-full inline-block"></span>
                            資金流向
                        </h2>
                        <p className="text-gray-400 mt-2 ml-4">
                            板塊聚合：點列展開成分股子表（可欄位排序）；後端先讀 DuckDB，若已設定永豐憑證則以
                            <span className="text-orange-300/90"> Shioaji snapshots</span>
                            覆寫全表價量（與排程寫庫節奏解耦）。資料與列表同源、無額外請求。
                            {viewLevel === 'micro' &&
                                data?.theme_micro_ticker_count != null &&
                                data.theme_micro_ticker_count > 0 && (
                                    <span className="text-gray-500 ml-2">
                                        題材表涵蓋約 {data.theme_micro_ticker_count} 檔（見專案 theme.json）；其餘仍依產業／內建對照。
                                    </span>
                                )}
                            {data?.date && (
                                <span className="text-gray-500 ml-2">資料日期: {data.date}</span>
                            )}
                            {data?.data_freshness && (
                                <span className="text-gray-600 ml-2 text-xs">({data.data_freshness})</span>
                            )}
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={() => refetch()}
                        disabled={isLoading}
                        className="h-9 px-3 rounded-lg border border-gray-700/70 bg-[#11161F] text-xs font-medium text-gray-300 hover:text-orange-300 hover:border-orange-500/40 hover:bg-[#171D28] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        title="手動重新抓取最新資料"
                    >
                        {isLoading ? '更新中...' : '手動更新'}
                    </button>
                </div>
            </div>

            <div className="flex flex-wrap justify-between items-center gap-4 shrink-0">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-4">
                    <div className="bg-[#0E1117] border border-gray-800 rounded-lg p-1 flex flex-wrap">
                        {(Object.entries(VIEW_LABELS) as [ViewLevel, (typeof VIEW_LABELS)[ViewLevel]][]).map(
                            ([key, val]) => (
                                <button
                                    key={key}
                                    type="button"
                                    onClick={() => setViewLevel(key)}
                                    className={`px-4 py-1.5 rounded-md text-sm font-bold transition-all ${
                                        viewLevel === key
                                            ? 'bg-orange-500 text-black'
                                            : 'text-gray-400 hover:text-white'
                                    }`}
                                    title={val.desc}
                                >
                                    {val.label}
                                </button>
                            )
                        )}
                    </div>
                </div>

                {stats && (
                    <div className="flex gap-6 text-sm flex-wrap">
                        <div className="flex items-center gap-2">
                            <span className="w-2 h-2 rounded-full bg-red-500"></span>
                            <span className="text-gray-400">上漲</span>
                            <span className="text-red-400 font-bold font-mono">{stats.upCount}</span>
                        </div>
                        <div className="flex items-center gap-2">
                            <span className="w-2 h-2 rounded-full bg-gray-500"></span>
                            <span className="text-gray-400">平盤</span>
                            <span className="text-gray-300 font-bold font-mono">{stats.flatCount}</span>
                        </div>
                        <div className="flex items-center gap-2">
                            <span className="w-2 h-2 rounded-full bg-green-500"></span>
                            <span className="text-gray-400">下跌</span>
                            <span className="text-green-400 font-bold font-mono">{stats.downCount}</span>
                        </div>
                        <div className="text-gray-500">
                            總成交金額
                            <span className="text-orange-400 font-bold font-mono ml-1">
                                {(stats.totalTurnover / 100000000).toFixed(0)}
                            </span>
                            <span className="text-gray-600 ml-0.5">億</span>
                        </div>
                    </div>
                )}
            </div>

            {error && (
                <div className="bg-red-900/20 border border-red-800 rounded-lg p-4 text-red-400 text-sm shrink-0">
                    {error}
                </div>
            )}

            <div className="flex-1 min-h-0 bg-[#161B22] border border-gray-800 rounded-xl overflow-hidden shadow-2xl flex flex-col">
                {isLoading && !rawStocks.length ? (
                    <div className="p-12 flex items-center justify-center">
                        <LoadingState text="載入全市場資金流向數據..." />
                    </div>
                ) : sortedBlocks.length ? (
                    <div className="overflow-auto flex-1">
                        <table className="w-full text-sm text-left border-collapse">
                            <thead className="sticky top-0 z-10 bg-[#0E1117] border-b border-gray-800">
                                <tr className="text-gray-400 font-semibold align-middle">
                                    <th
                                        className="px-3 py-3 pl-4 cursor-pointer hover:text-white min-w-[12rem]"
                                        onClick={() => handleBlockSort('label')}
                                    >
                                        <span className="inline-flex items-center gap-1">
                                            {VIEW_LABELS[viewLevel].label}
                                            {renderBlockSortIcon('label')}
                                        </span>
                                    </th>
                                    <th
                                        className="px-3 py-3 cursor-pointer hover:text-white text-right whitespace-nowrap"
                                        onClick={() => handleBlockSort('constituents')}
                                    >
                                        <span className="inline-flex items-center justify-end gap-1 w-full">
                                            成分家數
                                            {renderBlockSortIcon('constituents')}
                                        </span>
                                    </th>
                                    <th
                                        className="px-3 py-3 cursor-pointer hover:text-white text-right whitespace-nowrap"
                                        onClick={() => handleBlockSort('avg_change')}
                                        title="平均漲跌幅以板塊內成交金額加權"
                                    >
                                        <span className="inline-flex items-center justify-end gap-1 w-full">
                                            <span>
                                                平均漲跌幅%
                                                <span className="text-[10px] font-normal text-gray-500 ml-1">
                                                    （成交加權）
                                                </span>
                                            </span>
                                            {renderBlockSortIcon('avg_change')}
                                        </span>
                                    </th>
                                    <th
                                        className="px-3 py-3 cursor-pointer hover:text-white text-right whitespace-nowrap"
                                        onClick={() => handleBlockSort('turnover')}
                                    >
                                        <span className="inline-flex items-center justify-end gap-1 w-full">
                                            板塊總成交金額
                                            {renderBlockSortIcon('turnover')}
                                        </span>
                                    </th>
                                    <th
                                        className="px-3 py-3 cursor-pointer hover:text-white text-right whitespace-nowrap"
                                        onClick={() => handleBlockSort('turnover_share')}
                                        title="該分類內各檔成交金額加總 ÷ 當日全市場成交金額加總（與上方總成交金額同口徑）。族群視野下同一檔可重複出現在多個題材，故各區塊占比加總可能大於 100%"
                                    >
                                        <span className="inline-flex items-center justify-end gap-1 w-full">
                                            成交額占大盤%
                                            {renderBlockSortIcon('turnover_share')}
                                        </span>
                                    </th>
                                    <th className="px-3 py-3 text-right text-gray-500 whitespace-nowrap">
                                        總成交量(張)
                                    </th>
                                    <th
                                        className="px-3 py-3 cursor-pointer hover:text-white text-right whitespace-nowrap"
                                        onClick={() => handleBlockSort('up_count')}
                                    >
                                        <span className="inline-flex items-center justify-end gap-1 w-full">
                                            上漲家數
                                            {renderBlockSortIcon('up_count')}
                                        </span>
                                    </th>
                                    <th
                                        className="px-3 py-3 cursor-pointer hover:text-white text-right pr-4 whitespace-nowrap"
                                        onClick={() => handleBlockSort('down_count')}
                                    >
                                        <span className="inline-flex items-center justify-end gap-1 w-full">
                                            下跌家數
                                            {renderBlockSortIcon('down_count')}
                                        </span>
                                    </th>
                                </tr>
                            </thead>
                            <tbody>
                                {sortedBlocks.map((block) => {
                                    const open = expandedKeys.has(block.key);
                                    return (
                                        <React.Fragment key={block.key}>
                                            <tr
                                                className="border-b border-gray-800/80 bg-[#1a1f2e]/90 hover:bg-[#252b3a]/90 cursor-pointer transition-colors"
                                                onClick={() => toggleBlock(block.key)}
                                            >
                                                <td className="px-3 py-2.5 pl-3">
                                                    <div className="flex items-start gap-2 min-w-0">
                                                        <span className="shrink-0 mt-0.5 text-gray-500">
                                                            {open ? (
                                                                <ChevronDown className="w-4 h-4" />
                                                            ) : (
                                                                <ChevronRight className="w-4 h-4" />
                                                            )}
                                                        </span>
                                                        <span
                                                            className="text-gray-100 font-medium break-words"
                                                            title={block.label}
                                                        >
                                                            {block.label}
                                                        </span>
                                                    </div>
                                                </td>
                                                <td className="px-3 py-2.5 text-right font-mono text-gray-300">
                                                    {block.stocks.length}
                                                </td>
                                                <td
                                                    className="px-3 py-2.5 text-right font-mono font-bold"
                                                    style={{ color: getHeatColor(block.avgChangePct) }}
                                                >
                                                    {block.avgChangePct >= 0 ? '+' : ''}
                                                    {block.avgChangePct}%
                                                </td>
                                                <td className="px-3 py-2.5 text-right font-mono text-orange-200/90">
                                                    {(block.totalTurnover / 100000000).toFixed(2)} 億
                                                </td>
                                                <td className="px-3 py-2.5 text-right font-mono text-amber-100/90">
                                                    {(() => {
                                                        const p = blockTurnoverSharePct(block.totalTurnover);
                                                        return p == null ? '—' : `${p.toFixed(2)}%`;
                                                    })()}
                                                </td>
                                                <td className="px-3 py-2.5 text-right font-mono text-gray-400">
                                                    {block.totalVolume.toLocaleString()}
                                                </td>
                                                <td className="px-3 py-2.5 text-right font-mono text-red-400">
                                                    {block.upCount}
                                                </td>
                                                <td className="px-3 py-2.5 text-right font-mono text-green-400 pr-4">
                                                    {block.downCount}
                                                </td>
                                            </tr>
                                            {open && (
                                                <tr className="bg-[#0E1117]/60">
                                                    <td colSpan={8} className="p-0 border-b border-gray-800/80">
                                                        <div className="border-l-2 border-orange-500/50 ml-3 pl-2 pr-2 py-2 overflow-x-auto">
                                                            <p className="text-[11px] text-gray-500 mb-2 pl-1">
                                                                成分股穿透（與主表同一筆 API，依欄位即時排序）
                                                            </p>
                                                            <table className="w-full text-xs sm:text-sm border-collapse">
                                                                <thead>
                                                                    <tr className="text-gray-400 border-b border-gray-800/60">
                                                                        <th
                                                                            className="py-2 pr-3 text-left font-medium cursor-pointer hover:text-white select-none"
                                                                            onClick={(e) => {
                                                                                e.stopPropagation();
                                                                                handleComponentSort(block.key, 'ticker');
                                                                            }}
                                                                        >
                                                                            代號{renderComponentSortIcon(block.key, 'ticker')}
                                                                        </th>
                                                                        <th
                                                                            className="py-2 pr-3 text-left font-medium cursor-pointer hover:text-white select-none"
                                                                            onClick={(e) => {
                                                                                e.stopPropagation();
                                                                                handleComponentSort(block.key, 'name');
                                                                            }}
                                                                        >
                                                                            名稱{renderComponentSortIcon(block.key, 'name')}
                                                                        </th>
                                                                        <th
                                                                            className="py-2 pr-3 text-right font-medium cursor-pointer hover:text-white whitespace-nowrap select-none"
                                                                            onClick={(e) => {
                                                                                e.stopPropagation();
                                                                                handleComponentSort(block.key, 'close');
                                                                            }}
                                                                        >
                                                                            最新股價{renderComponentSortIcon(block.key, 'close')}
                                                                        </th>
                                                                        <th
                                                                            className="py-2 pr-3 text-right font-medium cursor-pointer hover:text-white whitespace-nowrap select-none"
                                                                            onClick={(e) => {
                                                                                e.stopPropagation();
                                                                                handleComponentSort(block.key, 'change_pct');
                                                                            }}
                                                                        >
                                                                            漲跌幅%{renderComponentSortIcon(block.key, 'change_pct')}
                                                                        </th>
                                                                        <th
                                                                            className="py-2 pr-3 text-right font-medium cursor-pointer hover:text-white whitespace-nowrap select-none"
                                                                            onClick={(e) => {
                                                                                e.stopPropagation();
                                                                                handleComponentSort(block.key, 'volume');
                                                                            }}
                                                                        >
                                                                            成交量(張){renderComponentSortIcon(block.key, 'volume')}
                                                                        </th>
                                                                        <th
                                                                            className="py-2 text-right font-medium cursor-pointer hover:text-white whitespace-nowrap select-none"
                                                                            onClick={(e) => {
                                                                                e.stopPropagation();
                                                                                handleComponentSort(block.key, 'turnover');
                                                                            }}
                                                                        >
                                                                            成交金額(億){renderComponentSortIcon(block.key, 'turnover')}
                                                                        </th>
                                                                    </tr>
                                                                </thead>
                                                                <tbody>
                                                                    {sortComponentStocks(
                                                                        block.stocks,
                                                                        componentSortByBlock[block.key] ??
                                                                            DEFAULT_COMPONENT_SORT
                                                                    ).map((s) => (
                                                                        <tr
                                                                            key={s.ticker}
                                                                            className="border-b border-gray-800/40 hover:bg-[#161B22]"
                                                                            onClick={(e) => e.stopPropagation()}
                                                                        >
                                                                            <td className="py-1.5 pr-4 font-mono">
                                                                                <button
                                                                                    type="button"
                                                                                    className="text-orange-400 hover:underline"
                                                                                    onClick={() => goStock(s.ticker)}
                                                                                >
                                                                                    {s.ticker}
                                                                                </button>
                                                                            </td>
                                                                            <td className="py-1.5 pr-4 text-gray-300 max-w-[10rem] truncate">
                                                                                {s.name}
                                                                            </td>
                                                                            <td className="py-1.5 pr-4 text-right font-mono text-gray-200">
                                                                                {s.close.toFixed(2)}
                                                                            </td>
                                                                            <td
                                                                                className="py-1.5 pr-3 text-right font-mono font-semibold"
                                                                                style={{
                                                                                    color: getHeatColor(s.change_pct),
                                                                                }}
                                                                                title={
                                                                                    s.change_pct == null
                                                                                        ? s.change_pct_basis === 'unreliable'
                                                                                            ? '前後收盤價尺度不一致或資料異常，已不列入板塊平均（如面額變更、除權未還原等）'
                                                                                            : s.change_pct_basis === 'no_volume'
                                                                                              ? '當日成交量為 0，不計漲跌幅（避免無成交卻帶價的假漲跌）'
                                                                                              : s.change_pct_basis === 'no_reference'
                                                                                                ? '找不到有效前收（上一有量日），不計漲跌幅'
                                                                                                : '無法計算漲跌幅'
                                                                                        : s.change_pct_basis === 'intraday'
                                                                                          ? '與前收相比異常，已改採當日開盤→收盤漲跌幅'
                                                                                          : undefined
                                                                                }
                                                                            >
                                                                                {s.change_pct == null ? (
                                                                                    <span className="text-gray-500 font-normal">—</span>
                                                                                ) : (
                                                                                    <>
                                                                                        {s.change_pct >= 0 ? '+' : ''}
                                                                                        {s.change_pct}%
                                                                                    </>
                                                                                )}
                                                                            </td>
                                                                            <td className="py-1.5 pr-3 text-right font-mono text-gray-500">
                                                                                {s.volume.toLocaleString()}
                                                                            </td>
                                                                            <td className="py-1.5 text-right font-mono text-gray-400">
                                                                                {(s.turnover / 100000000).toFixed(2)}
                                                                            </td>
                                                                        </tr>
                                                                    ))}
                                                                </tbody>
                                                            </table>
                                                        </div>
                                                    </td>
                                                </tr>
                                            )}
                                        </React.Fragment>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                ) : (
                    <div className="h-full flex items-center justify-center text-gray-600 p-12">
                        無資料可顯示
                    </div>
                )}
            </div>

            <div className="flex items-center justify-center gap-1 text-xs text-gray-500 shrink-0 pb-2">
                <span>跌停</span>
                <div className="flex gap-0.5">
                    {['#1B5E20', '#2E7D32', '#4CAF50', '#81C784', '#C8E6C9', '#424242', '#FFCDD2', '#EF9A9A', '#EF5350', '#E53935', '#FF0000'].map((c, i) => (
                        <div key={i} className="w-6 h-3 rounded-sm" style={{ backgroundColor: c }}></div>
                    ))}
                </div>
                <span>漲停</span>
            </div>
        </div>
    );
}
