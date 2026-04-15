import React, { useState, useEffect, useRef } from 'react';
import { useDividendScan, useDividendSearch } from '@/hooks/useDividend';
import { LoadingState } from '@/components/ui/LoadingState';
import { useAppStore } from '@/store/useAppStore';
import { useNavigate } from 'react-router-dom';
import { Search, Monitor, CreditCard, Lightbulb, List, LayoutGrid, Calendar, Activity, TrendingUp, BarChart3 } from 'lucide-react';
import { cleanStockSymbol, toStockDetailPath } from '@/lib/stocks';

export default function DividendAnalysisPage() {
    const [searchInput, setSearchInput] = useState('');
    const [debouncedSearch, setDebouncedSearch] = useState('');
    const [selectedStock, setSelectedStock] = useState<{ id: string, name: string } | null>(null);
    const [isDropdownOpen, setIsDropdownOpen] = useState(false);

    const dropdownRef = useRef<HTMLDivElement>(null);
    const navigate = useNavigate();

    useEffect(() => {
        const timer = setTimeout(() => {
            setDebouncedSearch(searchInput);
        }, 300);
        return () => clearTimeout(timer);
    }, [searchInput]);

    const { data: searchResults, isLoading: searching } = useDividendSearch(debouncedSearch);
    const { data: analysisData, isLoading: analyzing } = useDividendScan(selectedStock?.id || '', !!selectedStock);

    const setSymbol = useAppStore((state) => state.setSymbol);

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
                setIsDropdownOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    const handleSelectStock = (stock: any) => {
        setSelectedStock(stock);
        setSearchInput(`${stock.id} ${stock.name}`);
        setIsDropdownOpen(false);
        setSymbol(cleanStockSymbol(stock.id));
    };

    return (
        <div className="p-6 space-y-6 animate-in fade-in duration-500 text-gray-200">
            <div className="border-b border-gray-800 pb-4">
                <h2 className="text-3xl font-bold text-white tracking-widest flex items-center gap-3">
                    <span className="w-1.5 h-8 bg-[#EAB308] rounded-full inline-block"></span>
                    除權息行為評估中心
                </h2>
                <p className="text-gray-400 mt-2 ml-4 font-medium">個股歷史除權息行情深度統計，多維度回測尋找 <span className="text-[#F9A825]">高勝率填息</span> 現象標的</p>
            </div>

            <div className="bg-[#161B22] p-6 rounded-xl border border-gray-800 shadow-xl max-w-2xl">
                <h3 className="font-bold text-lg text-[#EAB308] mb-4 flex items-center gap-2 tracking-widest uppercase">
                    <Search size={20} />
                    檢索分析標的
                </h3>

                <div className="relative" ref={dropdownRef}>
                    <input
                        type="text"
                        value={searchInput}
                        onChange={(e) => {
                            setSearchInput(e.target.value);
                            setIsDropdownOpen(true);
                            if (e.target.value === '') setSelectedStock(null);
                        }}
                        onFocus={() => setIsDropdownOpen(true)}
                        placeholder="請輸入股票代號或名稱..."
                        className="w-full bg-[#0E1117] border border-gray-700 text-white rounded-lg px-5 py-3 outline-none focus:border-[#EAB308] font-mono text-lg transition-colors shadow-inner"
                    />

                    {isDropdownOpen && searchInput && (
                        <div className="absolute z-50 w-full mt-2 bg-[#1E293B] border border-gray-700 rounded-xl shadow-2xl max-h-64 overflow-y-auto custom-scrollbar">
                            {searching ? (
                                <div className="p-4 text-center text-gray-400 flex items-center justify-center gap-2"><Activity className="animate-spin" size={16} /> 匹配中...</div>
                            ) : searchResults && searchResults.length > 0 ? (
                                <ul className="py-2">
                                    {searchResults.map((stock: any) => (
                                        <li
                                            key={stock.id}
                                            onClick={() => handleSelectStock(stock)}
                                            className="px-5 py-3 hover:bg-gray-800 cursor-pointer flex justify-between items-center transition-colors border-b border-gray-800 last:border-0"
                                        >
                                            <span className="font-mono text-[#EAB308] font-bold text-lg">{stock.id}</span>
                                            <span className="text-white font-medium">{stock.name}</span>
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <div className="p-4 text-center text-gray-500">查無相符之證券標的</div>
                            )}
                        </div>
                    )}
                </div>
            </div>

            {selectedStock && analyzing && <LoadingState text={`正在並行運算 ${selectedStock.name} 近 10 年之歷史除權息數據流...`} />}

            {selectedStock && !analyzing && analysisData && (
                <div className="space-y-8 animate-in slide-in-from-bottom-4 duration-500">
                    {analysisData.message ? (
                        <div className="bg-red-500/10 border border-red-500/30 p-6 rounded-xl text-red-400 font-medium tracking-wide">
                            {analysisData.message}
                        </div>
                    ) : (
                        <>
                            <div className="bg-[#161B22] border border-gray-800 rounded-xl p-6 shadow-xl flex justify-between items-end relative overflow-hidden">
                                <div className="absolute top-0 right-0 w-64 h-64 bg-[#EAB308]/5 rounded-full blur-[80px] pointer-events-none"></div>
                                <div className="relative z-10">
                                    <h3 className="text-3xl font-black text-white tracking-widest">{selectedStock.id} {selectedStock.name}</h3>
                                    <p className="text-gray-400 mt-2 font-mono tracking-tighter uppercase text-sm">樣本數據採樣: 近 10 年共 {analysisData.total_count} 次除息循環</p>
                                </div>
                                <div className="relative z-10 hidden md:block">
                                    <div className="bg-[#0E1117] border border-gray-800 px-4 py-2 rounded-lg text-xs font-black tracking-widest text-[#EAB308] uppercase">系統回測引擎 v1.2</div>
                                </div>
                            </div>

                            <div className="bg-[#161B22] border border-gray-800 rounded-xl overflow-hidden shadow-2xl">
                                <h3 className="p-4 font-black text-white border-b border-gray-800 bg-[#0E1117] flex items-center gap-3 tracking-widest uppercase">
                                    <Monitor size={20} className="text-[#EAB308]" />
                                    勝率與漲跌幅深度維度統計
                                </h3>
                                <div className="overflow-x-auto">
                                    <table className="w-full text-left text-sm text-gray-300">
                                        <thead className="bg-[#0E1117]/80 text-gray-500 text-[11px] font-black uppercase tracking-tight">
                                            <tr>
                                                <th className="px-6 py-4">分析期間</th>
                                                <th className="px-6 py-4 text-right">上漲機率%</th>
                                                <th className="px-6 py-4 text-right">平均填息漲幅%</th>
                                                <th className="px-6 py-4 text-right">平均貼息跌幅%</th>
                                                <th className="px-6 py-4 text-right bg-black/30 font-black text-[#EAB308]">整體加權平均%</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-gray-800/50">
                                            {Object.entries(analysisData.summary).map(([period, stats]: [string, any]) => (
                                                <tr key={period} className="hover:bg-[#1E293B] group transition-colors">
                                                    <td className="px-6 py-4 font-bold text-white group-hover:text-[#EAB308] transition-colors">{period}</td>
                                                    <td className="px-6 py-4 text-right font-mono font-bold">{stats.upProb !== null ? `${stats.upProb}%` : '-'}</td>
                                                    <td className="px-6 py-4 text-right font-mono text-red-500">{stats.upAvg !== null ? `+${stats.upAvg}%` : '-'}</td>
                                                    <td className="px-6 py-4 text-right font-mono text-green-500">{stats.dnAvg !== null ? `${stats.dnAvg}%` : '-'}</td>
                                                    <td className={`px-6 py-4 text-right font-mono font-black bg-black/30 ${stats.avg > 0 ? 'text-red-500' : stats.avg < 0 ? 'text-green-500' : 'text-gray-500'}`}>
                                                        {stats.avg !== null ? `${stats.avg > 0 ? '+' : ''}${stats.avg}%` : '-'}
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            </div>

                            <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                                <div className="bg-[#161B22] border border-gray-800 rounded-xl overflow-hidden shadow-2xl">
                                    <h3 className="p-4 font-black text-white border-b border-gray-800 bg-[#0E1117] flex items-center gap-3 tracking-widest uppercase">
                                        <CreditCard size={20} className="text-green-400" />
                                        歷年股利分配效能紀錄
                                    </h3>
                                    <div className="overflow-x-auto max-h-[450px] custom-scrollbar">
                                        <table className="w-full text-left text-sm">
                                            <thead className="bg-[#0E1117]/80 text-gray-500 text-[10px] font-black uppercase sticky top-0 z-10">
                                                <tr>
                                                    <th className="px-6 py-3">年度</th>
                                                    <th className="px-6 py-3 text-right">現金股利總額</th>
                                                    <th className="px-6 py-3 text-right">平均單次殖利率%</th>
                                                </tr>
                                            </thead>
                                            <tbody className="divide-y divide-gray-800/40">
                                                {analysisData.yearly.map((y: any) => (
                                                    <tr key={y.year} className="hover:bg-[#1E293B]">
                                                        <td className="px-6 py-3 font-black text-white">{y.year}</td>
                                                        <td className="px-6 py-3 text-right font-mono text-[#EAB308]">{y.totalDividend} TWD</td>
                                                        <td className="px-6 py-3 text-right font-mono text-green-400 font-bold">{y.avgYield}%</td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    </div>
                                </div>

                                <div className="bg-[#161B22] border border-gray-800 rounded-xl p-8 shadow-2xl flex flex-col justify-center items-center text-center space-y-6 relative overflow-hidden">
                                    <div className="absolute -bottom-10 -left-10 w-48 h-48 bg-[#EAB308]/5 rounded-full blur-[60px] pointer-events-none"></div>
                                    <div className="w-20 h-20 rounded-full bg-[#EAB308]/10 flex items-center justify-center text-[#EAB308] shadow-inner mb-2 border border-[#EAB308]/20">
                                        <Lightbulb size={40} />
                                    </div>
                                    <h4 className="text-2xl font-black text-white tracking-widest uppercase">除權息核心診斷建議</h4>
                                    <ul className="text-gray-400 space-y-4 text-left max-w-sm font-medium tracking-wide">
                                        <li className="flex gap-3 items-start"><TrendingUp className="text-[#EAB308] shrink-0 mt-1" size={20} /> 鎖定勝率與平均漲幅皆高之期間進行波段佈局。</li>
                                        <li className="flex gap-3 items-start"><BarChart3 className="text-[#EAB308] shrink-0 mt-1" size={20} /> 同步交叉比對 20MA 通道位階，避開高位階除息風險。</li>
                                        <li className="flex gap-3 items-start"><Monitor className="text-[#EAB308] shrink-0 mt-1" size={20} /> 留意填息慣性，部份標的具備強烈「當日填息」特質。</li>
                                    </ul>
                                    <button onClick={() => navigate(toStockDetailPath(selectedStock.id))} className="mt-4 bg-[#0E1117] border border-gray-700 hover:border-[#EAB308] text-[#EAB308] font-black tracking-widest px-8 py-3 rounded-lg transition-all uppercase text-sm">切換至個股情報中心</button>
                                </div>
                            </div>

                            <div className="bg-[#161B22] border border-gray-800 rounded-xl overflow-hidden shadow-2xl">
                                <h3 className="p-4 font-black text-white border-b border-gray-800 bg-[#0E1117] flex items-center gap-3 tracking-widest uppercase">
                                    <List size={20} className="text-[#EAB308]" />
                                    歷史除息環境逐次執行明細
                                </h3>
                                <div className="overflow-x-auto max-h-[600px] custom-scrollbar">
                                    <table className="w-full text-left text-[11px] text-gray-300">
                                        <thead className="bg-[#0E1117] text-gray-500 font-black uppercase tracking-tighter sticky top-0 z-10 border-b border-gray-800">
                                            <tr>
                                                <th className="px-4 py-4 min-w-[100px]">除息基準日</th>
                                                <th className="px-3 py-4 text-right text-[#EAB308]">派發金額</th>
                                                <th className="px-3 py-4 text-right">殖利率%</th>
                                                <th className="px-3 py-4 text-right">T-3 變動</th>
                                                <th className="px-3 py-4 text-right">T-2 變動</th>
                                                <th className="px-3 py-4 text-right">T-1 變動</th>
                                                <th className="px-3 py-4 text-right border-x border-gray-800/50 bg-black/40 font-black text-white">基準日 T0</th>
                                                <th className="px-3 py-4 text-right">T+1 變動</th>
                                                <th className="px-3 py-4 text-right">T+2 變動</th>
                                                <th className="px-3 py-4 text-right">T+3 變動</th>
                                                <th className="px-3 py-4 text-right border-l border-gray-800/50 text-gray-600 bg-black/20">開盤跳空%</th>
                                                <th className="px-3 py-4 text-right text-gray-600 bg-black/20">日內波幅%</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-gray-800/30">
                                            {(analysisData.details || []).map((row: any, i: number) => {
                                                const formatPct = (val: number | null) => {
                                                    if (val === null || val === undefined) return <span className="text-gray-600">--</span>;
                                                    const colorClass = val > 0 ? 'text-red-500 font-black' : val < 0 ? 'text-green-500 font-black' : 'text-gray-500';
                                                    return <span className={colorClass}>{val > 0 ? '+' : ''}{val}%</span>;
                                                };
                                                return (
                                                    <tr key={i} className="hover:bg-[#1E293B] transition-colors border-b border-gray-800/20">
                                                        <td className="px-4 py-3 font-mono text-gray-400">{row.date}</td>
                                                        <td className="px-3 py-3 text-right font-mono font-bold text-[#EAB308]">{row.dividend}</td>
                                                        <td className="px-3 py-3 text-right font-mono font-medium">{row.yieldPct ? `${row.yieldPct}%` : '-'}</td>
                                                        <td className="px-3 py-3 text-right font-mono">{formatPct(row['d-3'])}</td>
                                                        <td className="px-3 py-3 text-right font-mono">{formatPct(row['d-2'])}</td>
                                                        <td className="px-3 py-3 text-right font-mono">{formatPct(row['d-1'])}</td>
                                                        <td className="px-3 py-3 text-right font-mono border-x border-gray-800/50 bg-black/40">{formatPct(row['d0'])}</td>
                                                        <td className="px-3 py-3 text-right font-mono">{formatPct(row['d_plus_1'])}</td>
                                                        <td className="px-3 py-3 text-right font-mono">{formatPct(row['d_plus_2'])}</td>
                                                        <td className="px-3 py-3 text-right font-mono">{formatPct(row['d_plus_3'])}</td>
                                                        <td className="px-3 py-3 text-right font-mono border-l border-gray-800/50 bg-black/20">{formatPct(row['openGap'])}</td>
                                                        <td className="px-3 py-3 text-right font-mono bg-black/20">{formatPct(row['intraday'])}</td>
                                                    </tr>
                                                );
                                            })}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </>
                    )}
                </div>
            )}
        </div>
    );
}
