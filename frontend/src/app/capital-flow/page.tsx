import React, { useState, useMemo, useCallback } from 'react';
import Plot from 'react-plotly.js';
import { useHeatmapData, HeatmapStock } from '@/hooks/useHeatmap';
import { LoadingState } from '@/components/ui/LoadingState';
import { useAppStore } from '@/store/useAppStore';
import { useNavigate } from 'react-router-dom';
import { cleanStockSymbol, toStockDetailPath } from '@/lib/stocks';

// ==========================================
// 視野層級切換
// ==========================================
type ViewLevel = 'macro' | 'meso' | 'micro';

const VIEW_LABELS: Record<ViewLevel, { label: string; desc: string }> = {
    macro: { label: '大視野', desc: '證交所官方產業分類' },
    meso: { label: '中視野', desc: '次產業 (AI 分類)' },
    micro: { label: '小視野', desc: '具體題材/產品線 (AI 分類)' },
};

// ==========================================
// 漲跌幅 → 顏色映射 (紅漲綠跌 台股慣例)
// ==========================================
function getHeatColor(changePct: number): string {
    if (changePct >= 9.5) return '#FF0000';       // 漲停
    if (changePct >= 5) return '#E53935';
    if (changePct >= 3) return '#EF5350';
    if (changePct >= 1) return '#EF9A9A';
    if (changePct >= 0.5) return '#FFCDD2';
    if (changePct > -0.5) return '#424242';       // 平盤
    if (changePct > -1) return '#C8E6C9';
    if (changePct > -3) return '#81C784';
    if (changePct > -5) return '#4CAF50';
    if (changePct > -9.5) return '#2E7D32';
    return '#1B5E20';                              // 跌停
}

// ==========================================
// 組裝 Plotly Treemap 數據
// ==========================================
function buildTreemapData(
    stocks: HeatmapStock[],
    viewLevel: ViewLevel
) {
    // Treemap 需要 labels, parents, values, colors
    const labels: string[] = [];
    const parents: string[] = [];
    const values: number[] = [];
    const colors: string[] = [];
    const customdata: any[] = [];
    const ids: string[] = [];
    const text: string[] = [];

    // 根節點
    const rootLabel = '全市場';
    labels.push(rootLabel);
    parents.push('');
    values.push(0);
    colors.push('#1a1a2e');
    customdata.push({});
    ids.push('root');
    text.push('');

    // 依 viewLevel 建立階層
    const macroSet = new Set<string>();
    const mesoSet = new Set<string>();

    // 建立 macro 層
    for (const s of stocks) {
        const macroKey = `macro:${s.macro}`;
        if (!macroSet.has(macroKey)) {
            macroSet.add(macroKey);
            labels.push(s.macro);
            parents.push('root');
            values.push(0);
            colors.push('#2d2d44');
            customdata.push({});
            ids.push(macroKey);
            text.push('');
        }
    }

    if (viewLevel === 'macro') {
        // 大視野: macro → 個股
        for (const s of stocks) {
            const macroKey = `macro:${s.macro}`;
            const stockId = `stock:${s.ticker}`;
            labels.push(`${s.ticker} ${s.name}`);
            parents.push(macroKey);
            values.push(Math.max(s.turnover, 1));
            colors.push(getHeatColor(s.change_pct));
            customdata.push(s);
            ids.push(stockId);
            text.push(`${s.change_pct >= 0 ? '+' : ''}${s.change_pct}%`);
        }
    } else if (viewLevel === 'meso') {
        // 中視野: macro → meso → 個股
        for (const s of stocks) {
            const macroKey = `macro:${s.macro}`;
            const mesoKey = `meso:${s.macro}/${s.meso}`;
            if (!mesoSet.has(mesoKey)) {
                mesoSet.add(mesoKey);
                labels.push(s.meso);
                parents.push(macroKey);
                values.push(0);
                colors.push('#2d2d44');
                customdata.push({});
                ids.push(mesoKey);
                text.push('');
            }

            const stockId = `stock:${s.ticker}`;
            labels.push(`${s.ticker} ${s.name}`);
            parents.push(mesoKey);
            values.push(Math.max(s.turnover, 1));
            colors.push(getHeatColor(s.change_pct));
            customdata.push(s);
            ids.push(stockId);
            text.push(`${s.change_pct >= 0 ? '+' : ''}${s.change_pct}%`);
        }
    } else {
        // 小視野: macro → meso → micro → 個股 (但層級太深 treemap 會太擁擠, 用 meso → micro 聚合)
        const microSet = new Set<string>();

        for (const s of stocks) {
            const macroKey = `macro:${s.macro}`;
            const mesoKey = `meso:${s.macro}/${s.meso}`;
            const microKey = `micro:${s.macro}/${s.meso}/${s.micro}`;

            if (!mesoSet.has(mesoKey)) {
                mesoSet.add(mesoKey);
                labels.push(s.meso);
                parents.push(macroKey);
                values.push(0);
                colors.push('#2d2d44');
                customdata.push({});
                ids.push(mesoKey);
                text.push('');
            }

            if (!microSet.has(microKey)) {
                microSet.add(microKey);
                labels.push(s.micro);
                parents.push(mesoKey);
                values.push(0);
                colors.push('#3d3d55');
                customdata.push({});
                ids.push(microKey);
                text.push('');
            }

            const stockId = `stock:${s.ticker}`;
            labels.push(`${s.ticker} ${s.name}`);
            parents.push(microKey);
            values.push(Math.max(s.turnover, 1));
            colors.push(getHeatColor(s.change_pct));
            customdata.push(s);
            ids.push(stockId);
            text.push(`${s.change_pct >= 0 ? '+' : ''}${s.change_pct}%`);
        }
    }

    return { labels, parents, values, colors, customdata, ids, text };
}

// ==========================================
// 頁面組件
// ==========================================
export default function HeatmapPage() {
    const [viewLevel, setViewLevel] = useState<ViewLevel>('meso');
    const { data, isLoading, error, refetch } = useHeatmapData();
    const setSymbol = useAppStore((state) => state.setSymbol);
    const navigate = useNavigate();

    // 組裝 Treemap 數據
    const treemapData = useMemo(() => {
        if (!data?.stocks?.length) return null;
        return buildTreemapData(data.stocks, viewLevel);
    }, [data, viewLevel]);

    // 點擊個股 → 跳轉技術分析
    const handleStockClick = useCallback((eventData: any) => {
        if (!eventData?.points?.[0]) return;
        const point = eventData.points[0];
        const id = point.id as string;
        if (id?.startsWith('stock:')) {
            const symbol = cleanStockSymbol(id.replace('stock:', ''));
            setSymbol(symbol);
            navigate(toStockDetailPath(symbol));
        }
    }, [setSymbol, navigate]);

    // 統計資訊
    const stats = useMemo(() => {
        if (!data?.stocks?.length) return null;
        const stocks = data.stocks;
        const totalTurnover = stocks.reduce((sum, s) => sum + s.turnover, 0);
        const upCount = stocks.filter(s => s.change_pct > 0).length;
        const downCount = stocks.filter(s => s.change_pct < 0).length;
        const flatCount = stocks.length - upCount - downCount;
        return { totalTurnover, upCount, downCount, flatCount, total: stocks.length };
    }, [data]);

    return (
        <div className="p-6 space-y-6 animate-in fade-in duration-500 text-gray-200 h-full flex flex-col">

            {/* Header */}
            <div className="border-b border-gray-800 pb-4 shrink-0">
                <div className="flex justify-between items-end">
                    <div>
                        <h2 className="text-3xl font-bold text-white tracking-widest flex items-center gap-3">
                            <span className="w-1.5 h-8 bg-orange-500 rounded-full inline-block"></span>
                            資金流向熱力圖
                        </h2>
                        <p className="text-gray-400 mt-2 ml-4">
                            以 Treemap 視覺化全市場資金分布，面積 = 成交金額，顏色 = 漲跌幅。
                            {data?.date && <span className="text-gray-500 ml-2">資料日期: {data.date}</span>}
                        </p>
                    </div>
                    <div className="flex gap-3 items-center">
                        {/* 重新整理 */}
                        <button
                            onClick={() => refetch()}
                            disabled={isLoading}
                            className="bg-[#1C2128] border border-gray-700 p-2 rounded-lg text-orange-400 hover:bg-[#2D333B] transition-colors"
                        >
                            <span className="material-symbols-outlined text-xl">refresh</span>
                        </button>
                    </div>
                </div>
            </div>

            {/* 視野切換 + 統計資訊 */}
            <div className="flex justify-between items-center shrink-0">
                <div className="bg-[#0E1117] border border-gray-800 rounded-lg p-1 flex">
                    {(Object.entries(VIEW_LABELS) as [ViewLevel, typeof VIEW_LABELS[ViewLevel]][]).map(([key, val]) => (
                        <button
                            key={key}
                            onClick={() => setViewLevel(key)}
                            className={`px-4 py-1.5 rounded-md text-sm font-bold transition-all ${viewLevel === key
                                ? 'bg-orange-500 text-black'
                                : 'text-gray-400 hover:text-white'
                                }`}
                            title={val.desc}
                        >
                            {val.label}
                        </button>
                    ))}
                </div>

                {stats && (
                    <div className="flex gap-6 text-sm">
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

            {/* 錯誤提示 */}
            {error && (
                <div className="bg-red-900/20 border border-red-800 rounded-lg p-4 text-red-400 text-sm shrink-0">
                    {error}
                </div>
            )}

            {/* Treemap */}
            <div className="flex-1 bg-[#161B22] border border-gray-800 rounded-xl overflow-hidden shadow-2xl min-h-0">
                {isLoading ? (
                    <div className="p-12 h-full flex items-center justify-center">
                        <LoadingState text="載入全市場資金流向數據..." />
                    </div>
                ) : treemapData ? (
                    <Plot
                        data={[
                            {
                                type: 'treemap' as any,
                                ids: treemapData.ids,
                                labels: treemapData.labels,
                                parents: treemapData.parents,
                                values: treemapData.values,
                                text: treemapData.text,
                                textinfo: 'label+text',
                                marker: {
                                    colors: treemapData.colors,
                                    line: { width: 1, color: '#0E1117' },
                                },
                                hovertemplate:
                                    '<b>%{label}</b><br>' +
                                    '漲跌幅: %{text}<br>' +
                                    '成交金額: %{value:,.0f}<br>' +
                                    '<extra></extra>',
                                textfont: {
                                    color: '#E0E0E0',
                                    size: 12,
                                    family: 'Inter, sans-serif',
                                },
                                pathbar: {
                                    visible: true,
                                    textfont: { color: '#999', size: 12 },
                                    thickness: 24,
                                    edgeshape: '>',
                                },
                                branchvalues: 'total' as any,
                                maxdepth: viewLevel === 'macro' ? 2 : viewLevel === 'meso' ? 3 : 4,
                                tiling: {
                                    packing: 'squarify' as any,
                                    pad: 2,
                                },
                            } as any,
                        ]}
                        layout={{
                            autosize: true,
                            margin: { t: 30, l: 4, r: 4, b: 4, pad: 0 },
                            paper_bgcolor: '#161B22',
                            plot_bgcolor: '#161B22',
                            font: {
                                color: '#E0E0E0',
                                family: 'Inter, sans-serif',
                            },
                        }}
                        config={{
                            responsive: true,
                            displayModeBar: false,
                            scrollZoom: false,
                        }}
                        style={{ width: '100%', height: '100%' }}
                        useResizeHandler={true}
                        onClick={handleStockClick}
                    />
                ) : (
                    <div className="h-full flex items-center justify-center text-gray-600">
                        無資料可顯示
                    </div>
                )}
            </div>

            {/* 色階說明 */}
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
