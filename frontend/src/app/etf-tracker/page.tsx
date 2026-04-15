import React, { useState } from 'react';
import { useEtfList, useEtfDates, useAllEtfDates, useEtfCrossAnalysis, streamEtfReport, useEtfHoldings, useEtfUpdate, useEtfUpdateAll } from '@/hooks/useEtf';
import { LoadingState } from '@/components/ui/LoadingState';
import { useAppStore } from '@/store/useAppStore';
import { useNavigate } from 'react-router-dom';
import { cleanStockSymbol, toStockDetailPath } from '@/lib/stocks';
import { TrendingUp, TrendingDown, Cpu, Activity, BarChart3, Target, PieChart } from 'lucide-react';

export default function EtfTrackerPage() {
    const [activeTab, setActiveTab] = useState<'single' | 'cross'>('single');

    // Tab 1 UI states
    const [selectedEtf, setSelectedEtf] = useState('');
    const [selectedDate, setSelectedDate] = useState('');
    const [compareDate, setCompareDate] = useState('');
    const [showSingleResult, setShowSingleResult] = useState(false);

    // Tab 2 UI states
    const [crossStart, setCrossStart] = useState('');
    const [crossEnd, setCrossEnd] = useState('');
    const [startCrossScan, setStartCrossScan] = useState(false);
    const [reportStream, setReportStream] = useState('');
    const [isAnalyzing, setIsAnalyzing] = useState(false);
    const [updateDate, setUpdateDate] = useState(() => new Date(new Date().getTime() - new Date().getTimezoneOffset() * 60000).toISOString().split('T')[0]);


    // Sorting functionality
    const [sortConfig, setSortConfig] = useState<{ key: string, direction: 'asc' | 'desc' }>({ key: 'newWeight', direction: 'desc' });
    const [crossSortBuy, setCrossSortBuy] = useState<{ key: string, direction: 'asc' | 'desc' }>({ key: 'total_buy_lots', direction: 'desc' });
    const [crossSortSell, setCrossSortSell] = useState<{ key: string, direction: 'asc' | 'desc' }>({ key: 'total_sell_lots', direction: 'desc' });

    // Queries
    const { data: etfListOpts, isLoading: listLoading } = useEtfList();
    const { data: singleDates } = useEtfDates(selectedEtf, !!selectedEtf);
    const { data: allDates } = useAllEtfDates();
    const { data: holdingsNew, isLoading: holdingsLoadingNew } = useEtfHoldings(selectedEtf, selectedDate, showSingleResult);
    const { data: holdingsOld, isLoading: holdingsLoadingOld } = useEtfHoldings(selectedEtf, compareDate, showSingleResult);

    const { data: crossData, isLoading: crossLoading } = useEtfCrossAnalysis(crossStart, crossEnd, startCrossScan);
    const { mutate: triggerUpdateAll, isPending: isUpdatingAll } = useEtfUpdateAll();




    const setSymbol = useAppStore((state) => state.setSymbol);
    const navigate = useNavigate();

    // 自動預設最新日期 (個股追蹤)
    React.useEffect(() => {
        if (singleDates && singleDates.length > 0 && !selectedDate) {
            setSelectedDate(singleDates[0]);
            // 預設舊日期為前一次存檔日
            if (singleDates.length > 1) setCompareDate(singleDates[1]);
        }
    }, [singleDates, selectedDate]);

    // 自動預設最新日期 (跨域分析)
    React.useEffect(() => {
        if (allDates && allDates.length > 0 && !crossEnd) {
            setCrossEnd(allDates[0]);
            if (allDates.length > 1) setCrossStart(allDates[1]);
        }
    }, [allDates, crossEnd]);

    const handleEtfChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
        setSelectedEtf(e.target.value);
        setShowSingleResult(false);
    };

    const handleSort = (key: string) => {
        setSortConfig(prev => ({ key, direction: prev.key === key && prev.direction === 'asc' ? 'desc' : 'asc' }));
    };

    const handleGenerateReport = async () => {
        if (!crossData?.buy_stats || !crossData?.sell_stats) return;
        const buyCsv = crossData.buy_stats.slice(0, 20).map((b: any) => `${b.code},${b.name},${b.etf_count},${b.total_buy_lots}`).join('\n');
        const sellCsv = crossData.sell_stats.slice(0, 20).map((s: any) => `${s.code},${s.name},${s.etf_count},${s.total_sell_lots}`).join('\n');
        setIsAnalyzing(true);
        setReportStream('');
        await streamEtfReport(buyCsv, sellCsv, (c) => setReportStream(p => p + c), () => setIsAnalyzing(false));
    };

    const handleTriggerUpdateAll = () => {

        if (!confirm(`確定要將全域十檔 ETF 的資料自動寫入日期為 ${updateDate} 嗎？這個過程會啟動多個爬蟲，可能耗時一至數分鐘，請勿關閉網頁。`)) return;

        triggerUpdateAll(updateDate, {
            onSuccess: (res) => {
                const totalSuccess = res.results.filter((r: any) => r.status === 'success').length;
                alert(`全域自動更新完成！\n成功: ${totalSuccess} / ${res.results.length} 檔 ETF\n日期: ${res.date}`);
            },
            onError: (err: any) => {
                alert(`全域自動更新發生錯誤: ${err?.response?.data?.detail || err.message}`);
            }
        });
    };


    const resultList = React.useMemo(() => {

        if (!holdingsNew || !holdingsOld) return [];
        const newMap = new Map((holdingsNew as any[]).map(h => [h['代碼'], h]));
        const oldMap = new Map((holdingsOld as any[]).map(h => [h['代碼'], h]));
        const allCodes = new Set([...newMap.keys(), ...oldMap.keys()]);
        return Array.from(allCodes).map(code => {
            const n = newMap.get(code) || { '名稱': '', '股數': 0, '權重(%)': 0 };
            const o = oldMap.get(code) || { '名稱': '', '股數': 0, '權重(%)': 0 };
            const sharesDiff = n['股數'] - o['股數'];
            const weightDiff = Number((n['權重(%)'] - o['權重(%)']).toFixed(2));
            let status = '持平';
            if (!o['股數']) status = '新增';
            else if (!n['股數']) status = '剔除';
            else if (sharesDiff > 0) status = '加碼';
            else if (sharesDiff < 0) status = '減碼';
            return { code, name: n['名稱'] || o['名稱'], newShares: n['股數'], oldShares: o['股數'], sharesDiff, newWeight: n['權重(%)'], weightDiff, status };
        }).filter(x => x.newShares > 0 || x.oldShares > 0);
    }, [holdingsNew, holdingsOld]);

    const sortedResultList = React.useMemo(() => {
        return [...resultList].sort((a, b) => {
            const aV = (a as any)[sortConfig.key];
            const bV = (b as any)[sortConfig.key];
            return sortConfig.direction === 'asc' ? (aV > bV ? 1 : -1) : (aV < bV ? 1 : -1);
        });
    }, [resultList, sortConfig]);

    const handleCrossSortBuy = (key: string) => {
        setCrossSortBuy(prev => ({ key, direction: prev.key === key && prev.direction === 'asc' ? 'desc' : 'asc' }));
    };

    const handleCrossSortSell = (key: string) => {
        setCrossSortSell(prev => ({ key, direction: prev.key === key && prev.direction === 'asc' ? 'desc' : 'asc' }));
    };

    const sortedCrossBuy = React.useMemo(() => {
        if (!crossData?.buy_stats) return [];
        return [...crossData.buy_stats].sort((a, b) => {
            const aV = (a as any)[crossSortBuy.key];
            const bV = (b as any)[crossSortBuy.key];
            return crossSortBuy.direction === 'asc' ? (aV > bV ? 1 : -1) : (aV < bV ? 1 : -1);
        });
    }, [crossData, crossSortBuy]);

    const sortedCrossSell = React.useMemo(() => {
        if (!crossData?.sell_stats) return [];
        return [...crossData.sell_stats].sort((a, b) => {
            const aV = (a as any)[crossSortSell.key];
            const bV = (b as any)[crossSortSell.key];
            return crossSortSell.direction === 'asc' ? (aV > bV ? 1 : -1) : (aV < bV ? 1 : -1);
        });
    }, [crossData, crossSortSell]);

    return (
        <div className="p-6 space-y-6 animate-in fade-in duration-500 text-gray-200">
            <div className="flex flex-col xl:flex-row justify-between items-start xl:items-center border-b border-gray-800 pb-4 gap-6">
                <div className="flex-1">
                    <h2 className="text-3xl font-bold text-white tracking-widest flex items-center gap-3">
                        <span className="w-1.5 h-8 bg-[#EAB308] rounded-full inline-block shrink-0"></span>
                        機構資金主動式 ETF 追蹤
                    </h2>
                    <p className="text-gray-400 mt-2 ml-4 font-medium">深度解析機構法人買賣路徑，捕捉市場核心資金動向</p>
                </div>
                <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 shrink-0 w-full xl:w-auto">
                    <div className="flex items-center justify-between sm:justify-start bg-[#0E1117] border border-gray-700 rounded px-4 py-1.5 focus-within:border-[#EAB308] transition-colors h-[42px]">
                        <span className="text-xs text-gray-500 font-bold mr-3 whitespace-nowrap">寫入日期設定</span>
                        <input
                            type="date"
                            className="bg-transparent text-white outline-none text-sm font-mono cursor-pointer"
                            value={updateDate}
                            onChange={(e) => setUpdateDate(e.target.value)}
                        />
                    </div>
                    <button
                        onClick={handleTriggerUpdateAll}
                        disabled={isUpdatingAll || !updateDate}
                        className="bg-blue-600/20 hover:bg-blue-600/40 text-blue-400 border border-blue-500/30 font-bold px-6 py-2.5 rounded transition disabled:opacity-50 flex items-center justify-center gap-2 tracking-widest leading-none h-[42px] whitespace-nowrap shrink-0"
                    >
                        {isUpdatingAll ? <Activity size={18} className="animate-spin" /> : <Activity size={18} />}
                        {isUpdatingAll ? "全局資料更新中..." : "一鍵自動更新全域 ETF"}
                    </button>
                </div>
            </div>




            <div className="flex gap-4 border-b border-gray-800">
                <button className={`py-3 px-6 font-bold flex items-center gap-2 transition-colors ${activeTab === 'single' ? 'text-[#EAB308] border-b-2 border-[#EAB308]' : 'text-gray-500'}`} onClick={() => setActiveTab('single')}><Target size={16} />個股持股變動</button>
                <button className={`py-3 px-6 font-bold flex items-center gap-2 transition-colors ${activeTab === 'cross' ? 'text-[#EAB308] border-b-2 border-[#EAB308]' : 'text-gray-500'}`} onClick={() => setActiveTab('cross')}><PieChart size={16} />跨領域資金流向</button>
            </div>

            {activeTab === 'single' && (
                <div className="space-y-6">
                    <div className="flex flex-wrap gap-4 bg-[#161B22] p-5 rounded-xl border border-gray-800 items-end">
                        <div className="flex-1 min-w-[200px]">
                            <label className="text-xs text-gray-500 font-black mb-2 block tracking-widest uppercase">選擇追蹤標的</label>
                            <select className="w-full bg-[#0E1117] border border-gray-700 text-white rounded px-3 py-2 outline-none focus:border-[#EAB308]" value={selectedEtf} onChange={handleEtfChange}>

                                <option value="">{listLoading ? "正在連線核心引擎..." : "請選擇分析對象"}</option>
                                {Array.isArray(etfListOpts) && [...etfListOpts].sort((a: any, b: any) => a.code.localeCompare(b.code)).map((e: any) => (
                                    <option key={e.code} value={e.code}>{e.name}</option>
                                ))}
                            </select>
                        </div>


                        <div className="flex-1 min-w-[150px]">
                            <label className="text-xs text-gray-500 font-black mb-2 block tracking-widest uppercase">對局日期(新)</label>
                            <select className="w-full bg-[#0E1117] border border-gray-700 text-white rounded px-3 py-2 outline-none focus:border-[#EAB308]" value={selectedDate} onChange={(e) => setSelectedDate(e.target.value)}>
                                <option value="">{singleDates ? "選擇日期" : "載入中..."}</option>
                                {Array.isArray(singleDates) && singleDates.map((d: string) => <option key={d} value={d}>{d}</option>)}
                            </select>
                        </div>
                        <div className="flex-1 min-w-[150px]">
                            <label className="text-xs text-gray-500 font-black mb-2 block tracking-widest uppercase">對局日期(舊)</label>
                            <select className="w-full bg-[#0E1117] border border-gray-700 text-white rounded px-3 py-2 outline-none focus:border-[#EAB308]" value={compareDate} onChange={(e) => setCompareDate(e.target.value)}>
                                <option value="">{singleDates ? "選擇日期" : "載入中..."}</option>
                                {Array.isArray(singleDates) && singleDates.map((d: string) => <option key={d} value={d}>{d}</option>)}
                            </select>
                        </div>
                        <button onClick={() => setShowSingleResult(true)} disabled={!selectedEtf || !selectedDate || !compareDate} className="bg-[#EAB308] hover:bg-[#F9A825] text-black px-8 py-2.5 rounded font-black tracking-widest transition disabled:opacity-30 h-[42px]">執行差異化分析</button>
                    </div>

                    {showSingleResult && resultList.length > 0 && (
                        <div className="bg-[#161B22] border border-gray-800 rounded-xl overflow-hidden">
                            <table className="w-full text-left text-sm text-gray-300">
                                <thead className="bg-[#0E1117] text-gray-400 font-black text-xs uppercase tracking-widest border-b border-gray-800">
                                    <tr>
                                        <th className="px-6 py-4 cursor-pointer" onClick={() => handleSort('code')}>代碼 {sortConfig.key === 'code' ? (sortConfig.direction === 'asc' ? '↑' : '↓') : ''}</th>
                                        <th className="px-6 py-4">名稱</th>
                                        <th className="px-6 py-4 text-right cursor-pointer" onClick={() => handleSort('newWeight')}>現有權重%</th>
                                        <th className="px-6 py-4 text-right cursor-pointer" onClick={() => handleSort('weightDiff')}>權重增減%</th>
                                        <th className="px-6 py-4 text-right">當前持股數</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-800/50">
                                    {sortedResultList.filter(x => x.newShares > 0).map(item => (
                                        <tr key={item.code} 
                                            className="hover:bg-[#1E293B] cursor-pointer" 
                                            onClick={() => {
                                                const symbol = cleanStockSymbol(item.code);
                                                setSymbol(symbol);
                                                navigate(toStockDetailPath(symbol));
                                            }}
                                            onContextMenu={(e) => {
                                                e.preventDefault();
                                                useAppStore.getState().openContextMenu(e.clientX, e.clientY, item.code);
                                            }}
                                        >
                                            <td className="px-6 py-3 font-mono text-[#EAB308] font-bold">{item.code}</td>
                                            <td className="px-6 py-3 font-medium text-white">{item.name}</td>
                                            <td className="px-6 py-3 text-right font-mono text-white">{item.newWeight.toFixed(2)}</td>
                                            <td className={`px-6 py-3 text-right font-mono font-bold ${item.weightDiff > 0 ? 'text-red-400' : item.weightDiff < 0 ? 'text-green-400' : ''}`}>{item.weightDiff > 0 ? '+' : ''}{item.weightDiff || '-'}</td>
                                            <td className="px-6 py-3 text-right font-mono">{item.newShares.toLocaleString()}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            )}

            {activeTab === 'cross' && (
                <div className="space-y-6">
                    <div className="flex flex-wrap gap-4 bg-[#161B22] p-5 rounded-xl border border-gray-800 items-end">
                        <div className="flex-1">
                            <label className="text-xs text-gray-500 font-black mb-2 block tracking-widest uppercase">追蹤起始日期</label>
                            <select className="w-full bg-[#0E1117] border border-gray-700 text-white rounded px-3 py-2 outline-none focus:border-[#EAB308]" value={crossStart} onChange={(e) => setCrossStart(e.target.value)}>
                                <option value="">起始基準點</option>
                                {allDates?.map((d: string) => <option key={d} value={d}>{d}</option>)}
                            </select>
                        </div>
                        <div className="flex-1">
                            <label className="text-xs text-gray-500 font-black mb-2 block tracking-widest uppercase">追蹤結束日期</label>
                            <select className="w-full bg-[#0E1117] border border-gray-700 text-white rounded px-3 py-2 outline-none focus:border-[#EAB308]" value={crossEnd} onChange={(e) => setCrossEnd(e.target.value)}>
                                <option value="">當前分析終點</option>
                                {allDates?.map((d: string) => <option key={d} value={d}>{d}</option>)}
                            </select>
                        </div>
                        <button onClick={() => setStartCrossScan(true)} disabled={!crossStart || !crossEnd} className="bg-[#EAB308] hover:bg-[#F9A825] text-black px-8 py-2.5 rounded font-black tracking-widest transition shadow-lg shadow-yellow-900/10">啟動全域資金動向分析</button>
                    </div>

                    {crossData && (
                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                            <div className="bg-[#161B22] border border-gray-800 rounded-xl overflow-hidden shadow-2xl">
                                <h3 className="p-4 bg-[#0E1117] border-b border-gray-800 text-green-400 font-black flex items-center gap-2 tracking-widest uppercase"><TrendingUp size={18} /> 機構法人共同加碼名單</h3>
                                <div className="max-h-[500px] overflow-y-auto">
                                    <table className="w-full text-left text-sm">
                                        <thead className="sticky top-0 bg-[#0E1117] text-gray-500 text-[10px] font-black uppercase tracking-tighter shadow-sm">
                                            <tr>
                                                <th className="px-4 py-2 cursor-pointer hover:text-white transition-colors" onClick={() => handleCrossSortBuy('code')}>標的辨識 {crossSortBuy.key === 'code' ? (crossSortBuy.direction === 'asc' ? '↑' : '↓') : ''}</th>
                                                <th className="px-4 py-2 text-right cursor-pointer hover:text-white transition-colors" onClick={() => handleCrossSortBuy('etf_count')}>加碼檔數 {crossSortBuy.key === 'etf_count' ? (crossSortBuy.direction === 'asc' ? '↑' : '↓') : ''}</th>
                                                <th className="px-4 py-2 text-right cursor-pointer hover:text-white transition-colors" onClick={() => handleCrossSortBuy('weight_diff')}>權重變動% {crossSortBuy.key === 'weight_diff' ? (crossSortBuy.direction === 'asc' ? '↑' : '↓') : ''}</th>
                                                <th className="px-4 py-2 text-right cursor-pointer hover:text-white transition-colors" onClick={() => handleCrossSortBuy('total_buy_lots')}>總張數變動 {crossSortBuy.key === 'total_buy_lots' ? (crossSortBuy.direction === 'asc' ? '↑' : '↓') : ''}</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-gray-800/40">
                                            {sortedCrossBuy.slice(0, 50).map((b: any) => (
                                                <tr key={b.code} className="hover:bg-[#1E293B]"
                                                    onContextMenu={(e) => {
                                                        e.preventDefault();
                                                        useAppStore.getState().openContextMenu(e.clientX, e.clientY, b.code);
                                                    }}
                                                >
                                                    <td className="px-4 py-2"><div className="font-mono text-[#EAB308] font-bold">{b.code}</div><div className="text-white text-xs">{b.name}</div></td>
                                                    <td className="px-4 py-2 text-right font-mono font-bold">{b.etf_count}</td>
                                                    <td className={`px-4 py-2 text-right font-mono font-bold ${b.weight_diff > 0 ? 'text-red-400' : b.weight_diff < 0 ? 'text-green-400' : 'text-gray-400'}`}>{b.weight_diff > 0 ? '+' : ''}{b.weight_diff}%</td>
                                                    <td className="px-4 py-2 text-right font-mono text-white">+{b.total_buy_lots.toLocaleString()}</td>

                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                            <div className="bg-[#161B22] border border-gray-800 rounded-xl overflow-hidden shadow-2xl">
                                <h3 className="p-4 bg-[#0E1117] border-b border-gray-800 text-red-400 font-black flex items-center gap-2 tracking-widest uppercase"><TrendingDown size={18} /> 機構法人共同減碼名單</h3>
                                <div className="max-h-[500px] overflow-y-auto">
                                    <table className="w-full text-left text-sm">
                                        <thead className="sticky top-0 bg-[#0E1117] text-gray-500 text-[10px] font-black uppercase tracking-tighter shadow-sm">
                                            <tr>
                                                <th className="px-4 py-2 cursor-pointer hover:text-white transition-colors" onClick={() => handleCrossSortSell('code')}>標的辨識 {crossSortSell.key === 'code' ? (crossSortSell.direction === 'asc' ? '↑' : '↓') : ''}</th>
                                                <th className="px-4 py-2 text-right cursor-pointer hover:text-white transition-colors" onClick={() => handleCrossSortSell('etf_count')}>減碼檔數 {crossSortSell.key === 'etf_count' ? (crossSortSell.direction === 'asc' ? '↑' : '↓') : ''}</th>
                                                <th className="px-4 py-2 text-right cursor-pointer hover:text-white transition-colors" onClick={() => handleCrossSortSell('weight_diff')}>權重變動% {crossSortSell.key === 'weight_diff' ? (crossSortSell.direction === 'asc' ? '↑' : '↓') : ''}</th>
                                                <th className="px-4 py-2 text-right cursor-pointer hover:text-white transition-colors" onClick={() => handleCrossSortSell('total_sell_lots')}>總張數變動 {crossSortSell.key === 'total_sell_lots' ? (crossSortSell.direction === 'asc' ? '↑' : '↓') : ''}</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-gray-800/40">
                                            {sortedCrossSell.slice(0, 50).map((s: any) => (
                                                <tr key={s.code} className="hover:bg-[#1E293B]"
                                                    onContextMenu={(e) => {
                                                        e.preventDefault();
                                                        useAppStore.getState().openContextMenu(e.clientX, e.clientY, s.code);
                                                    }}
                                                >
                                                    <td className="px-4 py-2"><div className="font-mono text-[#EAB308] font-bold">{s.code}</div><div className="text-white text-xs">{s.name}</div></td>
                                                    <td className="px-4 py-2 text-right font-mono font-bold">{s.etf_count}</td>
                                                    <td className={`px-4 py-2 text-right font-mono font-bold ${s.weight_diff > 0 ? 'text-red-400' : s.weight_diff < 0 ? 'text-green-400' : 'text-gray-400'}`}>{s.weight_diff > 0 ? '+' : ''}{s.weight_diff}%</td>
                                                    <td className="px-4 py-2 text-right font-mono text-white">-{s.total_sell_lots.toLocaleString()}</td>

                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                    )}

                    {crossData && (
                        <div className="space-y-4 pt-6 border-t border-gray-800">
                            <div className="flex justify-between items-center">
                                <h3 className="text-2xl font-black text-white flex items-center gap-3 tracking-widest uppercase"><Cpu size={24} className="text-[#EAB308]" /> AI 機構核心動向解讀</h3>
                                <button onClick={handleGenerateReport} disabled={isAnalyzing} className="bg-gradient-to-r from-[#F9A825] to-[#F57F17] hover:brightness-110 text-black font-black px-10 py-3 rounded shadow-xl transition disabled:opacity-30 flex items-center gap-2 uppercase tracking-wide">
                                    {isAnalyzing ? <Activity className="animate-spin" size={18} /> : <BarChart3 size={18} />}
                                    {isAnalyzing ? "模型運算中..." : "啟動經理人意圖透視"}
                                </button>
                            </div>
                            <div className="bg-[#0E1117] border border-gray-700 rounded-xl p-8 min-h-[200px] shadow-2xl relative overflow-hidden">
                                <div className="absolute top-0 right-0 w-96 h-96 bg-[#EAB308]/5 rounded-full blur-[120px] pointer-events-none"></div>
                                <div className="prose prose-invert max-w-none text-gray-300 leading-relaxed text-lg whitespace-pre-wrap relative z-10 font-sans tracking-wide">
                                    {reportStream}
                                    {isAnalyzing && <span className="inline-block w-2.5 h-6 ml-1 bg-[#EAB308] animate-pulse rounded-full" />}
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
