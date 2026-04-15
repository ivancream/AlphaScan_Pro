import React, { useState } from 'react';
import { useFloorBounceScan, useFloorBounceChart } from '@/hooks/useFloorBounce';
import { LoadingState } from '@/components/ui/LoadingState';
import { useAppStore } from '@/store/useAppStore';
import { useNavigate } from 'react-router-dom';
import { createChart, ColorType, IChartApi, CandlestickSeries, LineSeries } from 'lightweight-charts';
import { LineChart, Play, Activity } from 'lucide-react';

export default function FloorBouncePage() {
    const [showMode, setShowMode] = useState('signals'); // all, ceiling, floor, signals
    const [requireVol, setRequireVol] = useState(true);
    const [filterInactive, setFilterInactive] = useState(true);
    const { scannedStrategies, setScanned } = useAppStore();
    const isScanned = scannedStrategies.includes('floor_bounce');

    // For single stock chart
    const [stockInput, setStockInput] = useState('');
    const [stockToChart, setStockToChart] = useState('');

    const { data: scanResults, isLoading: scanning } = useFloorBounceScan(showMode, requireVol, filterInactive, isScanned);
    const { data: chartData, isLoading: charting } = useFloorBounceChart(stockToChart, !!stockToChart);

    const setSymbol = useAppStore((state) => state.setSymbol);
    const navigate = useNavigate();

    const chartContainerRef = React.useRef<HTMLDivElement>(null);
    const chartRef = React.useRef<IChartApi | null>(null);

    React.useEffect(() => {
        if (!chartContainerRef.current || !chartData || !chartData.data) return;

        const handleResize = () => {
            if (chartContainerRef.current && chartRef.current) {
                chartRef.current.applyOptions({ width: chartContainerRef.current.clientWidth });
            }
        };

        const chart = createChart(chartContainerRef.current, {
            layout: {
                background: { type: ColorType.Solid, color: '#0d0d0d' },
                textColor: '#d1d5db',
            },
            grid: {
                vertLines: { color: '#1f2937' },
                horzLines: { color: '#1f2937' },
            },
            width: chartContainerRef.current.clientWidth,
            height: 500,
            timeScale: {
                timeVisible: true,
                borderColor: '#374151',
            },
            rightPriceScale: {
                borderColor: '#374151',
            },
        });
        chartRef.current = chart;

        const candlestickSeries = chart.addSeries(CandlestickSeries, {
            upColor: '#F43F5E',
            downColor: '#10B981',
            borderVisible: false,
            wickUpColor: '#F43F5E',
            wickDownColor: '#10B981',
        });
        candlestickSeries.setData(chartData.data);

        const maSeries = chart.addSeries(LineSeries, {
            color: '#facc15',
            lineWidth: 2,
            title: 'MA20',
        });

        const maData = chartData.data.filter((d: any) => d.ma20 !== null).map((d: any) => ({
            time: d.time,
            value: d.ma20
        }));
        maSeries.setData(maData);

        const ceilingSeries = chart.addSeries(LineSeries, {
            color: '#ef4444',
            lineWidth: 2,
            lineStyle: 2, // Dashed
            title: `壓力 (+${chartData.ceil_th_pct}%)`,
        });
        const ceilData = chartData.data.filter((d: any) => d.ceiling !== null).map((d: any) => ({
            time: d.time,
            value: d.ceiling
        }));
        ceilingSeries.setData(ceilData);

        const floorSeries = chart.addSeries(LineSeries, {
            color: '#22c55e',
            lineWidth: 2,
            lineStyle: 2, // Dashed
            title: `支撐 (${chartData.floor_th_pct}%)`,
        });
        const floorData = chartData.data.filter((d: any) => d.floor !== null).map((d: any) => ({
            time: d.time,
            value: d.floor
        }));
        floorSeries.setData(floorData);

        window.addEventListener('resize', handleResize);
        return () => {
            window.removeEventListener('resize', handleResize);
            chart.remove();
        };
    }, [chartData]);


    const handleScan = () => {
        setScanned('floor_bounce');
    };

    return (
        <div className="p-6 space-y-6 animate-in fade-in duration-500 text-gray-200">
            <div className="border-b border-gray-800 pb-4">
                <h2 className="text-3xl font-bold text-white tracking-widest flex items-center gap-3">
                    <span className="w-1.5 h-8 bg-[#EAB308] rounded-full inline-block"></span>
                    地板股搶反彈
                </h2>
            </div>

            <div className="bg-[#161B22] p-5 rounded-xl border border-gray-800 space-y-4 shadow-lg">
                <h3 className="font-bold text-lg border-b border-gray-800 pb-2">策略參數控制台</h3>

                <div className="flex flex-wrap gap-6 items-end">
                    <div className="flex-1 min-w-[200px]">
                        <label className="block text-sm font-medium text-gray-400 mb-2">篩選模式</label>
                        <select
                            className="w-full bg-[#0E1117] border border-gray-700 text-white rounded-lg p-2.5 outline-none focus:border-[#EAB308] transition-colors"
                            value={showMode}
                            onChange={(e) => { setShowMode(e.target.value); }}
                        >
                            <option value="all">全市場監控</option>
                            <option value="ceiling">通道壓力選股 (強勢慣性)</option>
                            <option value="floor">通道支撐選股 (超跌反彈)</option>
                            <option value="signals">雙向轉折訊號彙整</option>
                        </select>
                    </div>

                    <div className="flex-1 min-w-[300px] flex flex-col gap-3">
                        <label className="flex items-center gap-2 cursor-pointer group">
                            <input
                                type="checkbox"
                                checked={requireVol}
                                onChange={(e) => { setRequireVol(e.target.checked); }}
                                className="w-4 h-4 accent-[#EAB308] rounded bg-gray-700 border-gray-600 focus:ring-[#EAB308]"
                            />
                            <span className="text-sm font-medium text-gray-300 group-hover:text-white transition-colors">
                                下跌標的須具備恐慌量 (量比 ≥ 2.0)
                            </span>
                        </label>
                        <label className="flex items-center gap-2 cursor-pointer group">
                            <input
                                type="checkbox"
                                checked={filterInactive}
                                onChange={(e) => { setFilterInactive(e.target.checked); }}
                                className="w-4 h-4 accent-[#EAB308] rounded bg-gray-700 border-gray-600 focus:ring-[#EAB308]"
                            />
                            <span className="text-sm font-medium text-gray-300 group-hover:text-white transition-colors">
                                自動過濾低流動性標的
                            </span>
                        </label>
                    </div>

                    <div>
                        <button
                            onClick={handleScan}
                            className="bg-[#EAB308] hover:bg-[#F9A825] text-black px-10 py-3 rounded-lg font-black tracking-widest transition-all shadow-lg shadow-yellow-900/20 active:translate-y-0.5 flex items-center gap-2"
                        >
                            {scanning ? <Activity className="animate-spin" size={18} /> : <Play size={18} />}
                            {scanning ? "高速運算中..." : "啟動核心引擎掃描"}
                        </button>
                    </div>
                </div>
            </div>

            {scanning && <LoadingState text="正在執行全市場 K 線並行運算與通道建模..." />}

            {isScanned && !scanning && scanResults && (
                <div className="space-y-6 animate-in fade-in duration-300">
                    <p className="text-lg">共識別出 <span className="font-bold text-[#EAB308] text-2xl">{scanResults.length}</span> 檔符合策略條件</p>

                    {scanResults.length > 0 && (
                        <div className="bg-[#161B22] border border-gray-800 rounded-xl overflow-hidden shadow-xl">
                            <div className="overflow-x-auto max-h-[600px] custom-scrollbar">
                                <table className="w-full text-left text-sm text-gray-300 relative">
                                    <thead className="bg-[#0E1117] text-gray-400 text-xs font-semibold sticky top-0 z-10 shadow-md">
                                        <tr>
                                            <th className="px-5 py-4 min-w-[100px]">代號</th>
                                            <th className="px-5 py-4 min-w-[120px]">名稱</th>
                                            <th className="px-5 py-4">產業</th>
                                            <th className="px-5 py-4 text-right">當前現價</th>
                                            <th className="px-5 py-4 text-right">日變動%</th>
                                            <th className="px-5 py-4 text-right">成交量(張)</th>
                                            <th className="px-5 py-4 text-right">策略狀態</th>
                                            <th className="px-5 py-4 text-right">20MA 偏移%</th>
                                            <th className="px-5 py-4 text-right">壓力軌%</th>
                                            <th className="px-5 py-4 text-right">支撐軌%</th>
                                            <th className="px-5 py-4 text-right">成交額(億)</th>
                                            <th className="px-5 py-4 text-right">量能倍率</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-gray-800/50">
                                        {scanResults.map((item: any) => {
                                            const isFloor = item.status === 'floor';
                                            const isCeil = item.status === 'ceiling';

                                            return (
                                                <tr
                                                    key={item.id}
                                                    className="hover:bg-[#1E293B] cursor-pointer transition-colors"
                                                    onClick={() => {
                                                        setStockToChart(item.id);
                                                        setStockInput(item.id);
                                                        window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
                                                    }}
                                                >
                                                    <td className="px-5 py-3 font-mono text-[#EAB308]">{item.id}</td>
                                                    <td className="px-5 py-3 font-medium text-white">{item.name}</td>
                                                    <td className="px-5 py-3 text-gray-400">{item.industry}</td>
                                                    <td className="px-5 py-3 text-right font-mono font-medium">{item.close.toFixed(2)}</td>
                                                    <td className={`px-5 py-3 text-right font-mono ${item.daily_ret_pct > 0 ? 'text-red-400' : item.daily_ret_pct < 0 ? 'text-green-400' : ''}`}>
                                                        {item.daily_ret_pct > 0 ? '+' : ''}{item.daily_ret_pct}%
                                                    </td>
                                                    <td className="px-5 py-3 text-right font-mono">{Number(item['成交量(張)']).toLocaleString()}</td>
                                                    <td className="px-5 py-3 text-right">
                                                        {isFloor && <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border border-green-500/50 text-green-400 bg-green-500/10">支撐觸及</span>}
                                                        {isCeil && <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border border-red-500/50 text-red-300 bg-red-500/10">壓力突破</span>}
                                                        {!isFloor && !isCeil && <span className="text-gray-500">-</span>}
                                                    </td>
                                                    <td className={`px-5 py-3 text-right font-mono font-bold ${isCeil ? 'text-red-400' : isFloor ? 'text-green-400' : ''}`}>
                                                        {item.bias_pct > 0 ? '+' : ''}{item.bias_pct}%
                                                    </td>
                                                    <td className="px-5 py-3 text-right font-mono text-red-500/40">{item.ceil_th_pct}%</td>
                                                    <td className="px-5 py-3 text-right font-mono text-green-500/40">{item.floor_th_pct}%</td>
                                                    <td className="px-5 py-3 text-right font-mono text-amber-400">{Number(item['成交額(億)']).toFixed(2)}</td>
                                                    <td className={`px-5 py-3 text-right font-mono ${item.vol_ratio >= 2 ? 'text-yellow-400 font-bold' : ''}`}>
                                                        {item.vol_ratio}x
                                                    </td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    )}
                </div>
            )}

            <div className="pt-8 mt-8 border-t border-gray-800">
                <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-6 gap-4">
                    <div>
                        <h3 className="text-2xl font-bold text-white flex items-center gap-2">
                            <LineChart className="text-[#EAB308]" size={24} />
                            乖離通道走勢分析
                        </h3>
                        <p className="text-gray-400 text-sm mt-1 font-medium">點擊數據列表或輸入代碼，檢索目標個股之歷史軌道變動</p>
                    </div>
                    <div className="flex gap-2">
                        <input
                            type="text"
                            placeholder="輸入標的代號"
                            className="bg-[#0E1117] border border-gray-700 text-white rounded-lg px-4 py-2 outline-none focus:border-[#EAB308] font-mono w-48"
                            value={stockInput}
                            onChange={(e) => setStockInput(e.target.value)}
                            onKeyDown={async (e) => {
                                if (e.key === 'Enter') {
                                    const val = stockInput.trim().toUpperCase();
                                    if (!val) return;
                                    try {
                                        const res = await fetch(`http://localhost:8000/api/v1/market-data/resolve/${val}`);
                                        const data = await res.json();
                                        setStockInput(data.symbol);
                                        setStockToChart(data.symbol);
                                    } catch (err) {
                                        setStockToChart(val);
                                    }
                                }
                            }}
                        />
                        <button
                            className="bg-gray-800 hover:bg-gray-700 text-white px-6 py-2 rounded-lg transition font-bold"
                            onClick={async () => {
                                const val = stockInput.trim().toUpperCase();
                                if (!val) return;
                                try {
                                    const res = await fetch(`http://localhost:8000/api/v1/market-data/resolve/${val}`);
                                    const data = await res.json();
                                    setStockInput(data.symbol);
                                    setStockToChart(data.symbol);
                                } catch (err) {
                                    setStockToChart(val);
                                }
                            }}
                        >
                            檢索
                        </button>
                    </div>
                </div>

                {charting && <LoadingState text={`載入模型圖形中...`} />}

                {chartData && !charting && (
                    <div className="bg-[#0E1117] border border-gray-800 rounded-xl overflow-hidden shadow-2xl relative">
                        <div className="absolute top-4 left-4 z-10 bg-black/50 backdrop-blur pb-1 px-3 py-2 rounded border border-gray-800 pointer-events-none">
                            <span className="font-bold text-white text-lg mr-2">{chartData.name} ({chartData.symbol})</span>
                            <span className="text-gray-400 text-xs tracking-widest">20MA 核心通道模型</span>
                        </div>
                        <div ref={chartContainerRef} className="w-full" />
                    </div>
                )}
            </div>

        </div>
    );
}
