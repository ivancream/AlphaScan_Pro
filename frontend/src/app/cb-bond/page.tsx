import React, { useState } from 'react';
import { useCbScan, useCbStats, useCbHistory, useCbReverse, useCbUpdate } from '@/hooks/useCbTracker';
import { LoadingState } from '@/components/ui/LoadingState';
import { useAppStore } from '@/store/useAppStore';
import { useNavigate } from 'react-router-dom';
import { Radar, Filter, BarChart3, Search, ArrowLeftRight, Cpu, Database, RefreshCw, Zap, Activity, Info, TrendingUp, TrendingDown, Calendar } from 'lucide-react';
import { createChart, ColorType, LineSeries } from 'lightweight-charts';
import { cleanStockSymbol, toStockDetailPath } from '@/lib/stocks';

export default function CbTrackerPage() {
    const [activeTab, setActiveTab] = useState<'scan' | 'stats' | 'lookup' | 'reverse'>('scan');

    return (
        <div className="p-6 space-y-6 animate-in fade-in duration-500 text-gray-200">
            <div className="border-b border-gray-800 pb-4">
                <h2 className="text-3xl font-bold text-white tracking-widest flex items-center gap-3">
                    <span className="w-1.5 h-8 bg-[#F9A825] rounded-full inline-block"></span>
                    可轉債 (CB) 核心雷達系統
                </h2>
                <p className="text-gray-400 mt-2 ml-4 font-medium italic">Monitor CB Premium, Arbitrage returns, and institutional movements to identify alpha in underlying stocks.</p>
            </div>

            <div className="flex border-b border-gray-800 mb-6 bg-[#0E1117] p-1 rounded-t-xl overflow-x-auto no-scrollbar">
                {[
                    { id: 'scan', label: '核心策略篩選', icon: <Filter size={16} /> },
                    { id: 'stats', label: '籌碼分布統計', icon: <BarChart3 size={16} /> },
                    { id: 'lookup', label: '個券歷史溯源', icon: <Search size={16} /> },
                    { id: 'reverse', label: '現貨關聯反推', icon: <ArrowLeftRight size={16} /> }
                ].map(tab => (
                    <button
                        key={tab.id}
                        className={`px-6 py-3 font-black tracking-widest transition-all flex items-center gap-2 whitespace-nowrap ${activeTab === tab.id ? 'text-[#F9A825] border-b-2 border-[#F9A825] bg-[#EAB308]/5' : 'text-gray-500 hover:text-gray-300'}`}
                        onClick={() => setActiveTab(tab.id as any)}
                    >
                        {tab.icon}
                        {tab.label}
                    </button>
                ))}
            </div>

            <div className="animate-in slide-in-from-bottom-2 duration-500">
                {activeTab === 'scan' && <CbScanTab />}
                {activeTab === 'stats' && <CbStatsTab />}
                {activeTab === 'lookup' && <CbLookupTab />}
                {activeTab === 'reverse' && <CbReverseTab />}
            </div>

        </div>
    );
}

function CbScanTab() {
    const [ytpMin, setYtpMin] = useState(3.0);
    const [debtMax, setDebtMax] = useState(80.0);
    const [arbMax, setArbMax] = useState(0.0);
    const [securedOnly, setSecuredOnly] = useState('全部');
    const [daysMax, setDaysMax] = useState(1095);
    const [selectedCb, setSelectedCb] = useState<any>(null);

    const { data: scanData, isLoading, refetch } = useCbScan(ytpMin, debtMax, arbMax, securedOnly, daysMax);
    const { mutate: updateList, isPending: updatingList } = useCbUpdate();

    return (
        <div className="space-y-6">
            <div className="bg-[#161B22] p-6 rounded-xl border border-gray-800 shadow-2xl relative overflow-hidden">
                <div className="absolute top-0 right-0 w-64 h-64 bg-[#EAB308]/5 rounded-full blur-[80px] pointer-events-none"></div>
                <div className="absolute top-6 right-6 flex gap-3 z-10">
                    <button
                        onClick={() => updateList('basic')}
                        disabled={updatingList}
                        className="bg-gray-800 hover:bg-gray-700 text-xs font-bold px-4 py-2 rounded-lg transition flex items-center gap-2 border border-gray-700"
                    >
                        <Database size={14} />
                        {updatingList ? '核心同步中...' : '同步 CB 基本面'}
                    </button>
                    <button
                        onClick={() => updateList('fundamentals')}
                        disabled={updatingList}
                        className="bg-[#EAB308]/10 text-[#EAB308] border border-[#EAB308]/20 hover:bg-[#EAB308]/20 text-xs font-bold px-4 py-2 rounded-lg transition flex items-center gap-2"
                    >
                        <Zap size={14} />
                        更新現貨財報數據
                    </button>
                </div>

                <h3 className="font-black text-white text-lg border-b border-gray-800 pb-3 mb-6 flex items-center gap-2 uppercase tracking-widest">
                    <Filter size={20} className="text-[#F9A825]" />
                    多因子策略篩選控制盤
                </h3>
                <div className="grid grid-cols-2 md:grid-cols-5 gap-6 relative z-10">
                    <FilterInput label="賣回殖利率 (YTP) ≥ (%)" value={ytpMin} onChange={setYtpMin} />
                    <FilterInput label="母公司負債比 ≤ (%)" value={debtMax} onChange={setDebtMax} />
                    <FilterInput label="套利空間溢價 ≤ (%)" value={arbMax} onChange={setArbMax} />
                    <div>
                        <label className="block text-[10px] uppercase font-black text-gray-500 mb-2 tracking-widest">擔保等級</label>
                        <select value={securedOnly} onChange={(e) => setSecuredOnly(e.target.value)} className="w-full bg-[#0E1117] border border-gray-700 rounded-lg p-2.5 text-white font-bold outline-none focus:border-[#F9A825] transition-colors">
                            <option>全部</option>
                            <option>無擔保優先</option>
                            <option>僅無擔保</option>
                        </select>
                    </div>
                    <FilterInput label="距賣回/到期日 ≤ (天)" value={daysMax} onChange={setDaysMax} />
                </div>
            </div>

            {isLoading ? <LoadingState text="正在索引全台股可轉債數據集..." /> : scanData && (
                <>
                    <div className="flex items-center gap-3">
                        <div className="bg-[#EAB308]/10 text-[#EAB308] px-3 py-1 rounded text-xs font-black tracking-widest">RESULT</div>
                        <p className="text-sm text-gray-400">總計 <span className="text-white font-mono font-bold">{scanData.filtered}</span> 檔符合核心篩選 (母體基數 {scanData.total})</p>
                    </div>

                    {selectedCb && <CbInfoCard cb={selectedCb} />}

                    <div className="bg-[#161B22] border border-gray-800 rounded-xl overflow-hidden shadow-2xl">
                        <div className="overflow-x-auto max-h-[600px] custom-scrollbar">
                            <table className="w-full text-left text-sm text-gray-300">
                                <thead className="bg-[#0E1117] text-gray-500 text-[10px] font-black uppercase tracking-tighter sticky top-0 z-10 border-b border-gray-800">
                                    <tr>
                                        <th className="px-5 py-4 min-w-[120px]">代號 / 標的名稱</th>
                                        <th className="px-4 py-4 text-right">CB 委買收盤</th>
                                        <th className="px-4 py-4 text-right">成交殖利率%</th>
                                        <th className="px-4 py-4 text-right">距賣回天數</th>
                                        <th className="px-4 py-4 text-right">預定賣回價</th>
                                        <th className="px-4 py-4 text-right">信用評等</th>
                                        <th className="px-4 py-4 text-right">負債比%</th>
                                        <th className="px-4 py-4 text-right">擔保屬性</th>
                                        <th className="px-4 py-4 text-right">400張大戶%</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-800/40">
                                    {scanData.results.map((row: any) => (
                                        <tr key={row.cb_id} className="hover:bg-[#1E293B] cursor-pointer group transition-colors" onClick={() => setSelectedCb(row)}>
                                            <td className="px-5 py-3">
                                                <div className="font-mono text-[#F9A825] font-black">{row.cb_id}</div>
                                                <div className="text-xs text-white font-medium group-hover:text-[#F9A825] transition-colors">{row.name}</div>
                                            </td>
                                            <td className="px-4 py-3 text-right font-mono text-gray-400 group-hover:text-white">{row.cb_close?.toFixed(2) || '-'}</td>
                                            <td className={`px-4 py-3 text-right font-mono font-black ${row.ytp_pct >= 5 ? 'text-green-500' : row.ytp_pct >= 3 ? 'text-[#EAB308]' : 'text-gray-500'}`}>
                                                {row.ytp_pct?.toFixed(2) || '-'}%
                                            </td>
                                            <td className="px-4 py-3 text-right font-mono font-bold text-white">{row.put_days_left || '-'}</td>
                                            <td className="px-4 py-3 text-right font-mono text-gray-500">{row.put_price?.toFixed(2) || '-'}</td>
                                            <td className="px-4 py-3 text-right font-mono text-xs font-bold text-blue-400 uppercase">{row.credit_rating || '-'}</td>
                                            <td className="px-4 py-3 text-right font-mono">{row.debt_ratio?.toFixed(1) || '-'}</td>
                                            <td className="px-4 py-3 text-right text-[10px] font-black text-gray-500 uppercase">{row.secured_label}</td>
                                            <td className="px-4 py-3 text-right font-mono text-gray-500 group-hover:text-white">{row.tdcc_large_pct?.toFixed(1) || '-'}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </>
            )}
        </div>
    );
}

function FilterInput({ label, value, onChange }: { label: string, value: number, onChange: (v: number) => void }) {
    return (
        <div>
            <label className="block text-[10px] uppercase font-black text-gray-500 mb-2 tracking-widest">{label}</label>
            <input
                type="number"
                value={value}
                onChange={(e) => onChange(Number(e.target.value))}
                className="w-full bg-[#0E1117] border border-gray-700 rounded-lg p-2.5 text-white font-mono font-bold outline-none focus:border-[#F9A825] transition-colors"
            />
        </div>
    );
}

function CbStatsTab() {
    const { data: stats, isLoading } = useCbStats();

    if (isLoading) return <LoadingState text="彙整全市場統計量能中..." />;
    if (!stats?.metrics) return (
        <div className="p-12 text-center bg-[#161B22] border border-dashed border-gray-800 rounded-xl text-gray-500 italic">
            <Info className="mx-auto mb-4 opacity-20" size={48} />
            系統快取尚無當日統計資料，請先至篩選分頁執行資料同步。
        </div>
    );

    return (
        <div className="space-y-8 animate-in fade-in duration-700">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-6">
                <MetricBox label="CB 全市場存量" value={`${stats.metrics.total} 檔`} color="text-white" />
                <MetricBox label="無擔保發行佔比" value={`${stats.metrics.unsecuredPct}%`} color="text-blue-400" />
                <MetricBox label="核心套利平均回報" value={`${stats.metrics.avgArb}%`} color="text-green-400" />
                <MetricBox label="高溢價風險警示" value={`${stats.metrics.highPremiumCount} 檔`} color="text-red-400" />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                <div className="bg-[#161B22] border border-gray-800 p-6 rounded-xl shadow-2xl relative overflow-hidden">
                    <div className="absolute top-0 left-0 w-32 h-32 bg-blue-500/5 rounded-full blur-[60px] pointer-events-none"></div>
                    <h4 className="font-black text-xs text-gray-500 mb-6 tracking-widest uppercase flex items-center gap-2">
                        <Activity size={14} className="text-blue-400" />
                        當日成交動能 TOP 10
                    </h4>
                    <div className="space-y-4">
                        {stats.volumeTop10.map((v: any, i: number) => (
                            <div key={v.cb_id} className="flex justify-between items-center group">
                                <div className="flex gap-4 items-center">
                                    <span className="text-gray-700 font-mono text-xs w-4">{(i + 1).toString().padStart(2, '0')}</span>
                                    <span className="text-[#F9A825] font-black font-mono tracking-tighter w-14">{v.cb_id}</span>
                                    <span className="text-sm text-gray-300 group-hover:text-white transition-colors">{v.name}</span>
                                </div>
                                <div className="text-blue-400 font-mono font-black text-sm bg-blue-500/5 px-3 py-1 rounded-md">{v.volume.toLocaleString()} 張</div>
                            </div>
                        ))}
                    </div>
                </div>
                <div className="bg-[#161B22] border border-gray-800 p-6 rounded-xl shadow-2xl relative overflow-hidden">
                    <div className="absolute top-0 right-0 w-32 h-32 bg-[#EAB308]/5 rounded-full blur-[60px] pointer-events-none"></div>
                    <h4 className="font-black text-xs text-gray-500 mb-6 tracking-widest uppercase flex items-center gap-2">
                        <Calendar size={14} className="text-[#EAB308]" />
                        償債/到期壓力分佈 (按季度)
                    </h4>
                    <div className="flex items-end h-[320px] gap-3 pb-8">
                        {stats.maturityQuarters.map((q: any) => {
                            const maxCount = Math.max(...stats.maturityQuarters.map((x: any) => x.count));
                            const h = (q.count / maxCount) * 100;
                            return (
                                <div key={q.quarter} className="flex-1 flex flex-col items-center gap-2 group h-full justify-end">
                                    <div className="relative w-full group">
                                        <div
                                            className="w-full bg-gradient-to-t from-[#EAB308] to-[#F9A825] rounded-t-sm opacity-60 group-hover:opacity-100 transition-all duration-500 shadow-lg shadow-[#EAB308]/10"
                                            style={{ height: `${h}%` }}
                                        ></div>
                                        <span className="absolute -top-6 left-0 right-0 text-center text-[10px] font-black text-[#EAB308] opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap">{q.count} units</span>
                                    </div>
                                    <div className="relative text-[9px] font-black text-gray-500 rotate-45 origin-left mt-2 whitespace-nowrap group-hover:text-white transition-colors">{q.quarter}</div>
                                </div>
                            )
                        })}
                    </div>
                </div>
            </div>
        </div>
    );
}

function MetricBox({ label, value, color }: { label: string, value: string, color: string }) {
    return (
        <div className="bg-[#161B22] border border-gray-800 p-6 rounded-xl text-center shadow-lg hover:border-gray-600 transition-colors">
            <div className="text-[10px] font-black text-gray-600 uppercase tracking-widest mb-2">{label}</div>
            <div className={`text-3xl font-black ${color} tracking-tighter`}>{value}</div>
        </div>
    );
}

function CbLookupTab() {
    const [searchInput, setSearchInput] = useState('');
    const [selectedCb, setSelectedCb] = useState('');

    const { data: cbData, isLoading } = useCbHistory(selectedCb);

    const chartContainerRef = React.useRef<HTMLDivElement>(null);
    const chartRef = React.useRef<any>(null);

    React.useEffect(() => {
        if (!chartContainerRef.current || !cbData?.history) return;

        if (chartRef.current) {
            chartRef.current.remove();
        }

        const chart = createChart(chartContainerRef.current, {
            layout: { background: { type: ColorType.Solid, color: '#0E1117' }, textColor: '#6B7280', fontSize: 10 },
            grid: { vertLines: { color: '#111827' }, horzLines: { color: '#111827' } },
            width: chartContainerRef.current.clientWidth,
            height: 400,
            timeScale: { borderColor: '#1F2937', barSpacing: 10 },
            rightPriceScale: { borderColor: '#1F2937' },
        });
        chartRef.current = chart;

        const cbSeries = chart.addSeries(LineSeries, {
            color: '#F9A825',
            lineWidth: 3,
            title: `CB PRICE`,
        });

        const histData = cbData.history.map((d: any) => ({
            time: d.date.split('T')[0],
            value: d.close
        })).sort((a: any, b: any) => new Date(a.time).getTime() - new Date(b.time).getTime());

        cbSeries.setData(histData);

        if (cbData.stockHistory && cbData.stockHistory.length > 0) {
            const stockSeries = chart.addSeries(LineSeries, {
                color: '#3B82F6',
                lineWidth: 1,
                lineStyle: 1,
                title: `UNDERLYING ${cbData.info.stock_id}`,
                priceScaleId: 'left',
            });
            chart.priceScale('left').applyOptions({
                visible: true,
                borderColor: '#1F2937',
            });

            const sData = cbData.stockHistory.map((d: any) => ({
                time: d.date.split('T')[0],
                value: d.close
            })).sort((a: any, b: any) => new Date(a.time).getTime() - new Date(b.time).getTime());

            stockSeries.setData(sData);
        }

        const handleResize = () => {
            if (chartContainerRef.current) {
                chart.applyOptions({ width: chartContainerRef.current.clientWidth });
            }
        };
        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            chart.remove();
        };
    }, [cbData]);

    return (
        <div className="space-y-6">
            <div className="flex gap-4 max-w-xl bg-[#161B22] p-2 rounded-xl border border-gray-800 shadow-lg">
                <input
                    type="text"
                    value={searchInput}
                    onChange={(e) => setSearchInput(e.target.value)}
                    placeholder="請輸入 CB 證券代號 (如: 68061)"
                    className="flex-1 bg-transparent border-none text-white rounded px-4 py-2 font-mono font-bold outline-none placeholder:text-gray-600"
                />
                <button
                    onClick={() => setSelectedCb(searchInput)}
                    className="bg-[#EAB308] hover:bg-[#F9A825] text-black font-black tracking-widest px-8 rounded-lg transition-all shadow-lg active:scale-95"
                >
                    查詢
                </button>
            </div>

            {isLoading && <LoadingState text="解析債券歷史成交序列中..." />}

            {cbData?.info && Object.keys(cbData.info).length > 0 && (
                <div className="animate-in slide-in-from-bottom-2 duration-500 space-y-6">
                    <CbInfoCard cb={cbData.info} />

                    <div className="bg-[#161B22] border border-gray-800 rounded-xl p-6 shadow-2xl relative overflow-hidden">
                        <div className="absolute top-0 right-0 w-96 h-96 bg-blue-500/5 rounded-full blur-[100px] pointer-events-none"></div>
                        <h4 className="font-black text-white mb-6 flex items-center gap-2 tracking-widest uppercase">
                            <Activity size={20} className="text-[#F9A825]" />
                            歷史收盤走勢 (CB 橘線 vs 現貨 藍虛線)
                        </h4>
                        <div ref={chartContainerRef} className="w-full rounded-lg overflow-hidden border border-gray-900 shadow-inner" />
                    </div>
                </div>
            )}
        </div>
    );
}

function CbReverseTab() {
    const [minArb, setMinArb] = useState(-10);
    const [minPrice, setMinPrice] = useState(100);

    const { data: reverseData, isLoading } = useCbReverse(minArb, minPrice);
    const setSymbol = useAppStore((state) => state.setSymbol);
    const navigate = useNavigate();

    return (
        <div className="space-y-6">
            <div className="bg-[#161B22] p-6 rounded-xl border border-gray-800 shadow-2xl flex flex-col md:flex-row gap-8 relative overflow-hidden">
                <div className="absolute top-0 left-0 w-64 h-64 bg-green-500/5 rounded-full blur-[80px] pointer-events-none"></div>
                <div className="flex-1 space-y-4">
                    <div className="flex justify-between items-center">
                        <label className="text-[10px] uppercase font-black text-gray-500 tracking-widest">平均套利報酬率上限 (%)</label>
                        <span className="text-[#F9A825] font-mono font-bold">{minArb}%</span>
                    </div>
                    <input type="range" min="-60" max="0" step="1" value={minArb} onChange={(e) => setMinArb(Number(e.target.value))} className="w-full accent-[#F9A825]" />
                </div>
                <div className="flex-1 space-y-4 font-sans">
                    <div className="flex justify-between items-center">
                        <label className="text-[10px] uppercase font-black text-gray-500 tracking-widest">平均 CB 市場收盤下限</label>
                        <span className="text-[#F9A825] font-mono font-bold">{minPrice}</span>
                    </div>
                    <input type="range" min="80" max="240" step="5" value={minPrice} onChange={(e) => setMinPrice(Number(e.target.value))} className="w-full accent-[#F9A825]" />
                </div>
            </div>

            {isLoading ? <LoadingState text="啟動關聯演算反推現貨標的中..." /> : reverseData && (
                <div className="space-y-4">
                    <div className="flex items-center gap-3">
                        <div className="bg-green-500/10 text-green-400 px-3 py-1 rounded text-xs font-black tracking-widest uppercase">IDENTIFIED</div>
                        <p className="text-sm text-gray-400 font-medium">符合條件之現貨標的：<span className="text-white font-black font-mono">{reverseData.length}</span> 檔 <span className="text-[10px] text-gray-600 block md:inline md:ml-2 uppercase tracking-tight">(Click row to jump to Technical Analysis)</span></p>
                    </div>
                    <div className="bg-[#161B22] border border-gray-800 rounded-xl overflow-hidden shadow-2xl">
                        <table className="w-full text-left text-sm text-gray-300">
                            <thead className="bg-[#0E1117] text-gray-500 text-[10px] font-black uppercase tracking-tight border-b border-gray-800">
                                <tr>
                                    <th className="px-5 py-4 min-w-[120px]">標的現貨</th>
                                    <th className="px-4 py-4 text-right">CB 流通檔數</th>
                                    <th className="px-4 py-4 text-right">平均套利報酬%</th>
                                    <th className="px-4 py-4 text-right">最低套利%</th>
                                    <th className="px-4 py-4 text-right">CB 合計成交量</th>
                                    <th className="px-4 py-4 text-right">CB 加權均價</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-800/40">
                                {reverseData.map((row: any) => {
                                    const isExtreme = row.avg_arb <= -25;
                                    const color = isExtreme ? 'text-red-500 font-black' : row.avg_arb <= -12 ? 'text-[#EAB308] font-bold' : '';
                                    return (
                                        <tr
                                            key={row.stock_id}
                                            className="hover:bg-[#1E293B] cursor-pointer group transition-colors"
                                            onClick={() => {
                                                const symbol = cleanStockSymbol(row.stock_id);
                                                setSymbol(symbol);
                                                navigate(toStockDetailPath(symbol));
                                            }}
                                        >
                                            <td className="px-5 py-3">
                                                <div className="font-mono text-[#F9A825] font-black text-base">{row.stock_id}</div>
                                                <div className="text-xs text-white font-medium group-hover:text-[#F9A825] transition-colors">{row.stock_name}</div>
                                            </td>
                                            <td className="px-4 py-3 text-right text-gray-400 font-mono font-bold group-hover:text-white transition-colors">{row.cb_count}</td>
                                            <td className={`px-4 py-3 text-right font-mono ${color} text-base`}>{row.avg_arb?.toFixed(1) || '-'}%</td>
                                            <td className={`px-4 py-3 text-right font-mono text-gray-500`}>{row.min_arb?.toFixed(1) || '-'}%</td>
                                            <td className="px-4 py-3 text-right font-mono text-blue-400 font-bold">{row.total_vol?.toLocaleString() || '-'}</td>
                                            <td className="px-4 py-3 text-right font-mono text-gray-400 group-hover:text-white">{row.avg_cb_price?.toFixed(1) || '-'}</td>
                                        </tr>
                                    )
                                })}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}
        </div>
    );
}

function CbInfoCard({ cb }: { cb: any }) {
    const arbColor = cb.arb_pct > 0 ? 'text-green-500' : 'text-red-500';
    return (
        <div className="bg-black border border-gray-800 rounded-xl p-6 shadow-2xl relative overflow-hidden group">
            <div className="absolute top-0 right-0 w-64 h-64 bg-[#F9A825]/5 rounded-full blur-[80px] pointer-events-none"></div>
            <div className="flex items-center gap-3 mb-6">
                <div className="p-2 bg-[#F9A825]/10 rounded-lg"><Info size={20} className="text-[#F9A825]" /></div>
                <h3 className="text-2xl font-black text-white tracking-widest">{cb.cb_id} {cb.name}</h3>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-6 text-sm relative z-10">
                <InfoItem label="對應現貨標的" value={cb.stock_id} isMono />
                <InfoItem label="目前轉換價格" value={cb.conv_price || '-'} isMono />
                <InfoItem label="債券到期日" value={`${cb.maturity_date?.substring(0, 10)} (${cb.days_left}d)`} smallValue />
                <InfoItem label="信用擔保等級" value={cb.secured_label || '-'} />
                <InfoItem label="CB 市場收盤" value={cb.cb_close || '-'} isMono />
                <InfoItem label="現貨即時價" value={cb.stock_price || '-'} isMono />
                <InfoItem label="核心套利報酬" value={`${cb.arb_pct?.toFixed(1)}%`} color={arbColor} isMono />
                <InfoItem label="轉換價值溢價" value={`${cb.premium_pct?.toFixed(1)}%`} isMono />
            </div>
        </div>
    );
}

function InfoItem({ label, value, isMono = false, smallValue = false, color = "text-white" }: any) {
    return (
        <div className="space-y-1.5">
            <div className="text-[10px] font-black text-gray-600 uppercase tracking-widest leading-none">{label}</div>
            <div className={`font-bold ${isMono ? 'font-mono tracking-tighter' : ''} ${smallValue ? 'text-xs' : 'text-base'} ${color} truncate`}>{value}</div>
        </div>
    );
}
