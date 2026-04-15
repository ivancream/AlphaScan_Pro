import React, { useState, useRef, useEffect } from 'react';
import { createChart, ColorType, CandlestickSeries, LineSeries } from 'lightweight-charts';
import { Search, Activity, Trash2, Plus, BarChart3, Info, List, X, ArrowUpRight, ArrowDownRight, ChevronDown, ChevronUp, Calendar } from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';

export default function DispositionPage() {
    const [symbol, setSymbol] = useState('');
    const [loading, setLoading] = useState(false);
    const [data, setData] = useState<any>(null);
    const [error, setError] = useState<string | null>(null);

    // 手動新增事件
    const [showAddForm, setShowAddForm] = useState(false);
    const [manualStart, setManualStart] = useState('');
    const [manualEnd, setManualEnd] = useState('');
    const [addingEvent, setAddingEvent] = useState(false);

    // 當日處置清單 Modal
    const [showListModal, setShowListModal] = useState(false);
    const [currentList, setCurrentList] = useState<any[]>([]);
    const [listLoading, setListLoading] = useState(false);

    const fetchCurrentList = async () => {
        setListLoading(true);
        try {
            const res = await fetch('http://localhost:8000/api/v1/disposition/current');
            const json = await res.json();
            if (json.status === 'success') setCurrentList(json.data);
        } catch {} finally { setListLoading(false); }
    };

    const handleOpenList = () => {
        setShowListModal(true);
        if (currentList.length === 0) fetchCurrentList();
    };

    // 搜尋 + 自動分析
    const handleSearch = async (targetSymbol?: string) => {
        const s = targetSymbol || symbol;
        if (!s) return;
        setSymbol(s);
        setLoading(true);
        setError(null);
        setData(null);
        try {
            const res = await fetch(`http://localhost:8000/api/v1/disposition/search/${s}`);
            const json = await res.json();
            if (json.status === 'success') {
                setData(json.data);
                if (json.data.events.length === 0 && json.data.found_count === 0) {
                    setError('未找到任何處置紀錄，可手動新增事件。');
                }
            } else {
                setError(json.detail || '分析失敗');
            }
        } catch (err: any) {
            setError(err.message || '連線錯誤');
        } finally {
            setLoading(false);
        }
    };

    // 手動新增事件
    const handleAddEvent = async () => {
        if (!symbol || !manualStart || !manualEnd) return;
        setAddingEvent(true);
        try {
            const res = await fetch('http://localhost:8000/api/v1/disposition/add-event', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ stock_id: symbol, disp_start: manualStart, disp_end: manualEnd }),
            });
            const json = await res.json();
            if (json.status === 'success') {
                setData(json.data);
                setShowAddForm(false);
                setManualStart('');
                setManualEnd('');
                setError(null);
            }
        } catch {} finally { setAddingEvent(false); }
    };

    // 從處置清單點擊個股
    const handleSelectFromList = (code: string) => {
        setShowListModal(false);
        handleSearch(code);
    };

    return (
        <div className="p-6 space-y-6 animate-in fade-in duration-500 text-gray-200">
            {/* Header */}
            <div className="flex justify-between items-center border-b border-gray-800 pb-4">
                <div>
                    <h2 className="text-3xl font-bold text-white tracking-widest flex items-center gap-3">
                        <span className="w-1.5 h-8 bg-[#ef5350] rounded-full inline-block"></span>
                        處置股走勢統計分析
                    </h2>
                </div>
                <button
                    onClick={handleOpenList}
                    className="flex items-center gap-2 bg-[#1E293B] hover:bg-[#334155] border border-gray-700 text-white px-5 py-2.5 rounded-lg shadow transition"
                >
                    <List size={18} className="text-[#ef5350]" />
                    <span className="font-bold">當日處置清單</span>
                </button>
            </div>

            {/* Search Bar */}
            <div className="flex gap-3">
                <div className="relative flex-1 max-w-md">
                    <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                    <input
                        type="text"
                        value={symbol}
                        onChange={e => setSymbol(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && handleSearch()}
                        className="w-full bg-[#0E1117] border border-gray-700 rounded-lg pl-10 pr-4 py-3 text-white font-mono font-bold outline-none focus:border-[#ef5350] transition placeholder:text-gray-600"
                        placeholder="輸入台股代號 (例: 2603)"
                    />
                </div>
                <button
                    onClick={() => handleSearch()}
                    disabled={loading || !symbol}
                    className={`font-black tracking-widest px-8 py-3 rounded-lg transition-all shadow-lg text-white flex items-center gap-2 ${loading ? 'bg-gray-700' : 'bg-[#ef5350] hover:bg-[#ff7977] active:scale-95'} disabled:opacity-50`}
                >
                    {loading ? <Activity className="animate-spin" size={18} /> : <Search size={18} />}
                    {loading ? '搜尋中...' : '搜尋處置紀錄'}
                </button>
            </div>

            {/* Error */}
            {error && (
                <div className="bg-red-500/10 border border-red-800/50 text-red-400 p-4 rounded-xl flex items-center gap-3">
                    <Info size={18} /> {error}
                    {data?.found_count === 0 && (
                        <button
                            onClick={() => setShowAddForm(true)}
                            className="ml-auto text-sm font-bold text-[#ef5350] hover:text-white transition border border-[#ef5350]/30 px-3 py-1 rounded-lg"
                        >
                            + 手動新增
                        </button>
                    )}
                </div>
            )}

            {/* Manual Add Form */}
            {showAddForm && (
                <div className="bg-[#161B22] border border-gray-800 rounded-xl p-5 space-y-4 animate-in slide-in-from-top-2 duration-300">
                    <h4 className="text-sm font-bold text-gray-400 flex items-center gap-2">
                        <Calendar size={16} />
                        手動新增處置事件 (API 可能漏抓的歷史紀錄)
                    </h4>
                    <div className="flex gap-3 items-end">
                        <div className="space-y-1">
                            <label className="text-[10px] text-gray-500 uppercase font-black tracking-widest">處置起日</label>
                            <input type="date" value={manualStart} onChange={e => setManualStart(e.target.value)}
                                className="bg-[#0E1117] border border-gray-700 rounded-lg px-3 py-2 text-white font-mono outline-none focus:border-[#ef5350]" />
                        </div>
                        <div className="space-y-1">
                            <label className="text-[10px] text-gray-500 uppercase font-black tracking-widest">處置迄日</label>
                            <input type="date" value={manualEnd} onChange={e => setManualEnd(e.target.value)}
                                className="bg-[#0E1117] border border-gray-700 rounded-lg px-3 py-2 text-white font-mono outline-none focus:border-[#ef5350]" />
                        </div>
                        <button onClick={handleAddEvent} disabled={addingEvent || !manualStart || !manualEnd}
                            className="bg-[#ef5350] hover:bg-[#ff7977] text-white font-bold px-6 py-2 rounded-lg transition disabled:opacity-50">
                            {addingEvent ? '新增中...' : '新增並分析'}
                        </button>
                        <button onClick={() => setShowAddForm(false)} className="text-gray-500 hover:text-white transition p-2">
                            <X size={18} />
                        </button>
                    </div>
                </div>
            )}

            {/* Loading */}
            {loading && (
                <div className="p-12 text-center bg-[#161B22] border border-dashed border-gray-800 rounded-xl text-gray-400 font-bold animate-pulse flex flex-col items-center justify-center">
                    <Activity size={32} className="mb-4 text-[#ef5350] animate-bounce" />
                    正在搜尋處置紀錄並分析走勢...
                </div>
            )}

            {/* Empty State */}
            {!data && !loading && !error && (
                <div className="p-12 text-center bg-[#161B22] border border-dashed border-gray-800 rounded-xl text-gray-500 italic">
                    <Activity className="mx-auto mb-4 opacity-20" size={48} />
                    輸入股票代號，系統將自動搜尋歷史處置紀錄並計算每日漲跌幅統計。
                </div>
            )}

            {/* Results */}
            {data && data.events.length > 0 && (
                <div className="space-y-8 animate-in slide-in-from-bottom-2 duration-500">
                    {/* Found Events Badge */}
                    <div className="flex items-center gap-3">
                        <span className="bg-[#ef5350]/10 text-[#ef5350] border border-[#ef5350]/30 px-4 py-2 rounded-lg text-sm font-bold">
                            找到 {data.events.length} 筆有效處置事件
                        </span>
                        <button
                            onClick={() => setShowAddForm(!showAddForm)}
                            className="text-gray-500 hover:text-white text-sm flex items-center gap-1 transition"
                        >
                            <Plus size={14} /> 手動新增漏抓的事件
                        </button>
                    </div>

                    {/* Summary Stats */}
                    {data.summary.length > 0 && (
                        <div className="bg-[#161B22] border border-gray-800 rounded-xl p-6 shadow-2xl relative overflow-hidden">
                            <div className="absolute top-0 right-0 w-64 h-64 bg-[#ef5350]/5 rounded-full blur-[80px] pointer-events-none"></div>
                            <h3 className="font-black text-white mb-6 flex items-center gap-2 tracking-widest uppercase">
                                <BarChart3 size={20} className="text-[#ef5350]" />
                                多事件彙總統計 (共 {data.events.length} 個事件)
                            </h3>

                            <div className="overflow-x-auto custom-scrollbar pb-3">
                                <table className="w-full text-left text-sm text-gray-300 whitespace-nowrap">
                                    <thead className="bg-[#0E1117] text-gray-500 text-[10px] font-black uppercase tracking-tight border-b border-gray-800">
                                        <tr>
                                            <th className="px-4 py-3">節點</th>
                                            <th className="px-4 py-3 text-right">樣本數</th>
                                            <th className="px-4 py-3 text-right">勝率 (%)</th>
                                            <th className="px-4 py-3 text-right">平均累積漲跌幅</th>
                                            <th className="px-4 py-3 text-right">中位數</th>
                                            <th className="px-4 py-3 text-right">最大</th>
                                            <th className="px-4 py-3 text-right">最小</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-gray-800/40">
                                        {data.summary.map((row: any, i: number) => {
                                            const winColor = row.win_rate >= 60 ? 'text-[#ef5350]' : row.win_rate <= 40 ? 'text-[#26a69a]' : 'text-gray-400';
                                            const avgColor = row.avg_ret > 0 ? 'text-[#ef5350]' : row.avg_ret < 0 ? 'text-[#26a69a]' : 'text-gray-400';
                                            return (
                                                <tr key={i} className="hover:bg-[#1E293B] transition-colors">
                                                    <td className="px-4 py-3 text-[#F9A825] font-black">{row.node}</td>
                                                    <td className="px-4 py-3 text-right font-mono">{row.count}</td>
                                                    <td className={`px-4 py-3 text-right font-mono font-black ${winColor}`}>{row.win_rate.toFixed(1)}%</td>
                                                    <td className={`px-4 py-3 text-right font-mono font-bold ${avgColor}`}>{row.avg_ret > 0 ? '+' : ''}{row.avg_ret.toFixed(2)}%</td>
                                                    <td className={`px-4 py-3 text-right font-mono font-bold ${row.median_ret > 0 ? 'text-[#ef5350]' : row.median_ret < 0 ? 'text-[#26a69a]' : 'text-gray-400'}`}>
                                                        {row.median_ret > 0 ? '+' : ''}{row.median_ret.toFixed(2)}%
                                                    </td>
                                                    <td className="px-4 py-3 text-right font-mono text-gray-400">{row.max > 0 ? '+' : ''}{row.max.toFixed(2)}%</td>
                                                    <td className="px-4 py-3 text-right font-mono text-gray-400">{row.min > 0 ? '+' : ''}{row.min.toFixed(2)}%</td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    )}

                    {/* Individual Event Cards */}
                    {data.events.map((ev: any, i: number) => (
                        <EventCard key={i} index={i} event={ev} />
                    ))}
                </div>
            )}

            {/* Current List Modal */}
            {showListModal && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-in fade-in duration-200">
                    <div className="bg-[#161B22] border border-gray-700 rounded-xl shadow-2xl w-full max-w-4xl flex flex-col max-h-[80vh] overflow-hidden">
                        <div className="flex justify-between items-center p-5 border-b border-gray-800 bg-[#0E1117]">
                            <h3 className="text-xl font-bold text-white flex items-center gap-2">
                                <List className="text-[#ef5350]" />
                                全市場處置中個股名單
                            </h3>
                            <button onClick={() => setShowListModal(false)} className="text-gray-400 hover:text-white transition">
                                <X size={24} />
                            </button>
                        </div>
                        <div className="p-6 overflow-y-auto custom-scrollbar flex-1">
                            {listLoading ? (
                                <div className="py-12 flex flex-col items-center justify-center text-gray-400">
                                    <Activity className="animate-spin text-[#ef5350] mb-4" size={32} />
                                    <p>正在爬取交易所公告...</p>
                                </div>
                            ) : currentList.length === 0 ? (
                                <div className="py-12 text-center text-gray-500">目前無正在處置中的個股。</div>
                            ) : (
                                <table className="w-full text-left text-sm text-gray-300">
                                    <thead className="bg-[#0E1117] text-gray-400 text-xs uppercase font-bold border-b border-gray-800">
                                        <tr>
                                            <th className="px-4 py-3">市場</th>
                                            <th className="px-4 py-3">代號</th>
                                            <th className="px-4 py-3">名稱</th>
                                            <th className="px-4 py-3 text-red-400">處置條件</th>
                                            <th className="px-4 py-3">起日</th>
                                            <th className="px-4 py-3">迄日</th>
                                            <th className="px-4 py-3">成交量(張)</th>
                                            <th className="px-4 py-3">成交額(億)</th>
                                            <th className="px-4 py-3 text-right">操作</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-gray-800">
                                        {currentList.map((item, idx) => (
                                            <tr key={idx} 
                                                onContextMenu={(e) => {
                                                    e.preventDefault();
                                                    useAppStore.getState().openContextMenu(e.clientX, e.clientY, item.code);
                                                }}
                                                className="hover:bg-[#1E293B] transition-colors"
                                            >
                                                <td className="px-4 py-3">
                                                    <span className={`px-2 py-1 rounded text-xs font-bold ${item.market === '上市' ? 'bg-blue-900/30 text-blue-400 border border-blue-800/50' : 'bg-green-900/30 text-green-400 border border-green-800/50'}`}>
                                                        {item.market}
                                                    </span>
                                                </td>
                                                <td className="px-4 py-3 font-mono text-[#F9A825] font-bold">{item.code}</td>
                                                <td className="px-4 py-3 text-white font-medium">{item.name}</td>
                                                <td className="px-4 py-3 font-bold text-red-300">每 {item.mins} 撮合</td>
                                                <td className="px-4 py-3 font-mono text-gray-400">{item.start}</td>
                                                <td className="px-4 py-3 font-mono text-gray-400">{item.end}</td>
                                                <td className="px-4 py-3 font-mono text-sm">{item["成交量(張)"]?.toLocaleString() || 0}</td>
                                                <td className="px-4 py-3 font-mono text-sm text-amber-400">{item["成交額(億)"]?.toFixed(2) || 0}</td>
                                                <td className="px-4 py-3 text-right">
                                                    <button
                                                        onClick={() => handleSelectFromList(item.code)}
                                                        className="text-[#ef5350] hover:text-white transition text-xs font-bold border border-[#ef5350]/30 hover:border-white/30 px-3 py-1 rounded-lg"
                                                    >
                                                        分析走勢
                                                    </button>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            )}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}


// ── 單一事件卡片 (含每日漲幅表格 + K 線圖) ──
function EventCard({ index, event }: { index: number; event: any }) {
    const [expanded, setExpanded] = useState(index === 0); // 預設展開第一個
    const eventData = event.data;

    return (
        <div className="bg-[#161B22] border border-gray-800 rounded-xl overflow-hidden shadow-2xl">
            {/* Card Header */}
            <button
                onClick={() => setExpanded(!expanded)}
                className="w-full p-5 flex justify-between items-center bg-[#0E1117] hover:bg-[#161B22] transition-colors text-left"
            >
                <div className="flex items-center gap-4">
                    <span className="w-8 h-8 rounded-full bg-[#ef5350]/20 text-[#ef5350] font-black flex items-center justify-center text-sm">
                        {index + 1}
                    </span>
                    <div>
                        <h4 className="font-black text-white tracking-wider">
                            處置期 {event.disp_start} ~ {event.disp_end}
                        </h4>
                        <span className="text-gray-500 text-xs">
                            共 {eventData.disp_days} 個處置交易日 &#183; 
                            基準收盤: <span className="text-white">{eventData.ref_close.toFixed(2)}</span>
                        </span>
                    </div>
                </div>
                {expanded ? <ChevronUp size={20} className="text-gray-400" /> : <ChevronDown size={20} className="text-gray-400" />}
            </button>

            {/* Card Body */}
            {expanded && (
                <div className="p-5 space-y-6 animate-in slide-in-from-top-1 duration-300">
                    {/* 每日漲幅表格 */}
                    <div className="overflow-x-auto custom-scrollbar">
                        <table className="w-full text-left text-sm text-gray-300">
                            <thead className="text-gray-500 text-[10px] font-black uppercase tracking-tight border-b border-gray-800">
                                <tr>
                                    <th className="px-4 py-3">階段</th>
                                    <th className="px-4 py-3">日期</th>
                                    <th className="px-4 py-3 text-right">收盤價</th>
                                    <th className="px-4 py-3 text-right">當日漲跌 %</th>
                                    <th className="px-4 py-3 text-right">累積漲跌 %</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-800/30">
                                {eventData.daily_rows.map((row: any, i: number) => {
                                    const phaseColors: Record<string, string> = {
                                        pre: 'text-blue-400',
                                        during: 'text-[#ef5350]',
                                        post: 'text-[#66BB6A]',
                                    };
                                    const phaseBg: Record<string, string> = {
                                        pre: '',
                                        during: 'bg-[#ef5350]/5',
                                        post: '',
                                    };
                                    const dailyColor = row.daily_ret > 0 ? 'text-[#ef5350]' : row.daily_ret < 0 ? 'text-[#26a69a]' : 'text-gray-400';
                                    const cumColor = row.cum_ret > 0 ? 'text-[#ef5350]' : row.cum_ret < 0 ? 'text-[#26a69a]' : 'text-gray-400';

                                    return (
                                        <tr key={i} className={`hover:bg-[#1E293B] transition-colors ${phaseBg[row.phase_tag]}`}>
                                            <td className={`px-4 py-3 font-black text-xs ${phaseColors[row.phase_tag]}`}>
                                                {row.phase}
                                            </td>
                                            <td className="px-4 py-3 font-mono text-gray-400 text-xs">{row.date}</td>
                                            <td className="px-4 py-3 text-right font-mono text-white font-bold">{row.close.toFixed(2)}</td>
                                            <td className={`px-4 py-3 text-right font-mono font-bold ${dailyColor}`}>
                                                {row.daily_ret > 0 ? '+' : ''}{row.daily_ret.toFixed(2)}%
                                            </td>
                                            <td className={`px-4 py-3 text-right font-mono font-bold ${cumColor}`}>
                                                {row.cum_ret > 0 ? '+' : ''}{row.cum_ret.toFixed(2)}%
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>

                    {/* K 線圖 */}
                    <EventChart data={eventData} />
                </div>
            )}
        </div>
    );
}


// ── K 線圖元件 ──
function EventChart({ data }: { data: any }) {
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<any>(null);

    useEffect(() => {
        if (!chartContainerRef.current || !data?.chart_data?.length) return;
        if (chartRef.current) chartRef.current.remove();

        const chart = createChart(chartContainerRef.current, {
            layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#6B7280', fontSize: 11 },
            grid: { vertLines: { color: '#1E293B' }, horzLines: { color: '#1E293B' } },
            width: chartContainerRef.current.clientWidth,
            height: 300,
            timeScale: { borderColor: '#1F2937' },
            rightPriceScale: { borderColor: '#1F2937' },
        });
        chartRef.current = chart;

        const candleSeries = chart.addSeries(CandlestickSeries, {
            upColor: '#ef5350', downColor: '#26a69a', borderVisible: false,
            wickUpColor: '#ef5350', wickDownColor: '#26a69a',
        });

        const cumRetSeries = chart.addSeries(LineSeries, {
            color: '#ffa726', lineWidth: 2, priceScaleId: 'left', title: '累積 %'
        });
        chart.priceScale('left').applyOptions({ visible: true, borderColor: '#1F2937' });

        const sortedData = [...data.chart_data].sort((a: any, b: any) => new Date(a.time).getTime() - new Date(b.time).getTime());
        candleSeries.setData(sortedData.map((d: any) => ({ time: d.time, open: d.open, high: d.high, low: d.low, close: d.close })));
        cumRetSeries.setData(sortedData.map((d: any) => ({ time: d.time, value: d.cum_ret })));

        // Markers
        const markers: any[] = [];
        let inPre = false, inDuring = false, inPost = false;
        sortedData.forEach((d: any) => {
            if (d.time >= data.event_dates.pre_start && d.time < data.event_dates.disp_start && !inPre) {
                markers.push({ time: d.time, position: 'belowBar', color: '#1E88E5', shape: 'arrowUp', text: '進關前' });
                inPre = true;
            }
            if (d.time >= data.event_dates.disp_start && d.time <= data.event_dates.disp_end && !inDuring) {
                markers.push({ time: d.time, position: 'belowBar', color: '#ef5350', shape: 'arrowUp', text: '處置中' });
                inDuring = true;
            }
            if (d.time > data.event_dates.disp_end && !inPost) {
                markers.push({ time: d.time, position: 'belowBar', color: '#66BB6A', shape: 'arrowUp', text: '出關後' });
                inPost = true;
            }
        });
        if (markers.length > 0) (candleSeries as any).setMarkers(markers);

        const handleResize = () => {
            if (chartContainerRef.current) chart.applyOptions({ width: chartContainerRef.current.clientWidth });
        };
        window.addEventListener('resize', handleResize);
        return () => { window.removeEventListener('resize', handleResize); chart.remove(); };
    }, [data]);

    return (
        <div className="bg-[#0E1117] rounded-xl border border-gray-800 p-4 shadow-inner">
            <div ref={chartContainerRef} className="w-full" />
        </div>
    );
}
