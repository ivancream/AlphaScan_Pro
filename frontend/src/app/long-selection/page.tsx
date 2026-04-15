import React, { useState } from 'react';
import { isAxiosError } from 'axios';
import { useSwingLong, useSwingWanderer } from '@/hooks/useSwing';
import { LoadingState } from '@/components/ui/LoadingState';
import { useAppStore } from '@/store/useAppStore';
import { useNavigate } from 'react-router-dom';
import { ChipsAnalysisWidget } from '@/components/chips/ChipsAnalysisWidget';
import { TrendingUp, Activity } from 'lucide-react';
import { cleanStockSymbol, toStockDetailPath } from '@/lib/stocks';

function formatSwingScanError(err: unknown): string {
    if (isAxiosError(err)) {
        const code = err.code;
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
        desc: '布林通道開口擴張 (必要) + 均線多頭排列 (建議) + 爆量表態訊號',
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
    const setSymbol = useAppStore((state) => state.setSymbol);
    const { scannedStrategies, setScanned } = useAppStore();
    const navigate = useNavigate();

    const [longParams, setLongParams] = useState({
        req_ma: true,
        req_vol: true,
        req_slope: true
    });
    const [wandererParams, setWandererParams] = useState({
        req_slope: true,
        req_bb_level: true
    });

    const isLongScanned = scannedStrategies.includes('core_long');
    const isWandererScanned = scannedStrategies.includes('wanderer');

    // 根據策略啟用對應 hook（只有在已執行掃描 && 對應策略時才 enabled）
    const { data: coreLongResults, isLoading: isLoadingCore, error: errorCore, refetch: refetchCore } =
        useSwingLong(isLongScanned && strategy === 'core_long', longParams);
    const { data: wandererResults, isLoading: isLoadingWanderer, error: errorWanderer, refetch: refetchWanderer } =
        useSwingWanderer(isWandererScanned && strategy === 'wanderer', wandererParams);

    const scanResults = strategy === 'core_long' ? coreLongResults : wandererResults;
    const isLoading = strategy === 'core_long' ? isLoadingCore : isLoadingWanderer;
    const isActuallyScanned = strategy === 'core_long' ? isLongScanned : isWandererScanned;
    const error = strategy === 'core_long' ? errorCore : errorWanderer;
    const refetchScan = strategy === 'core_long' ? refetchCore : refetchWanderer;

    const filteredResults: ScanRow[] = Array.isArray(scanResults)
        ? scanResults.filter((item: ScanRow) => {
            if (strategy === 'wanderer' && onlyShowDisposition) return item.is_disposition;
            return true;
        })
        : [];

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
                        波段多方選股策略
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
                    提示：全市場篩選約需 1～3 分鐘，請務必先啟動後端 API。
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
                <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                    <p className={`${cfg.color === 'amber' ? 'text-amber-400' : 'text-red-400'} font-bold text-sm tracking-wider uppercase`}>策略篩選條件 (預設全選)</p>
                    <span className="text-xs text-gray-500 italic">勾選後將僅顯示符合該條件的標的</span>
                </div>
                
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                    {strategy === 'core_long' ? (
                        <>
                            <FilterCheckbox 
                                label="均線多排" 
                                checked={longParams.req_ma} 
                                onChange={(val) => setLongParams(prev => ({ ...prev, req_ma: val }))}
                                desc="MA5 > MA10 > MA20"
                                color="red"
                            />
                            <FilterCheckbox 
                                label="斜率翻揚" 
                                checked={longParams.req_slope} 
                                onChange={(val) => setLongParams(prev => ({ ...prev, req_slope: val }))}
                                desc="上軌斜率 > 0% 且處於擴張狀態"
                                color="red"
                            />
                            <FilterCheckbox 
                                label="爆量表態" 
                                checked={longParams.req_vol} 
                                onChange={(val) => setLongParams(prev => ({ ...prev, req_vol: val }))}
                                desc="成交量增長 > 2.0 倍"
                                color="red"
                            />
                        </>
                    ) : (
                        <>
                            <FilterCheckbox 
                                label="月線斜率" 
                                checked={wandererParams.req_slope} 
                                onChange={(val) => setWandererParams(prev => ({ ...prev, req_slope: val }))}
                                desc="月線斜率翻揚 > 0.8%"
                                color="amber"
                            />
                            <FilterCheckbox 
                                label="布林位階" 
                                checked={wandererParams.req_bb_level} 
                                onChange={(val) => setWandererParams(prev => ({ ...prev, req_bb_level: val }))}
                                desc="位階 < 4 (具備均值回歸空間)"
                                color="amber"
                            />
                        </>
                    )}
                </div>
            </div>

            {/* 掃描結果 */}
            {isActuallyScanned && (
                <div className="bg-[#161B22] border border-gray-800 rounded-xl overflow-hidden shadow-xl">
                    <div className="flex justify-between items-center bg-[#0E1117] px-6 py-4 border-b border-gray-800">
                        <h3 className="font-bold text-gray-300">掃描結果 ({filteredResults.length})</h3>
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
                                            <th className="px-6 py-4 text-red-400 font-bold cursor-pointer hover:text-red-300" onClick={() => handleSort('均線多排')}>均線多排{renderSortIcon('均線多排')}</th>
                                            <th className="px-6 py-4 text-red-400 font-bold cursor-pointer hover:text-red-300" onClick={() => handleSort('爆量表態')}>爆量表態{renderSortIcon('爆量表態')}</th>
                                            <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort('月線斜率')}>月線斜率%{renderSortIcon('月線斜率')}</th>
                                            <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort('上軌斜率')}>上軌斜率%{renderSortIcon('上軌斜率')}</th>
                                            <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort('量比')}>量比{renderSortIcon('量比')}</th>
                                            <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort('成交額(億)')}>成交額(億){renderSortIcon('成交額(億)')}</th>
                                            <th className="px-6 py-4 cursor-pointer hover:text-white text-xs opacity-50" onClick={() => handleSort('資料日期')}>日期{renderSortIcon('資料日期')}</th>
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
                                                <td className="px-6 py-4 font-mono">{Number(item['收盤價']).toFixed(1)}</td>
                                                <td className={`px-6 py-4 font-mono ${getChangePctColor(item['今日漲跌幅(%)'])}`}>{Number(item['今日漲跌幅(%)']).toFixed(2)}%</td>
                                                <td className="px-6 py-4 font-mono">{Number(item['成交量(張)']).toLocaleString()}</td>
                                                <td className="px-6 py-4 font-bold">{item['均線多排']}</td>
                                                <td className="px-6 py-4 font-bold">{item['爆量表態']}</td>
                                                <td className="px-6 py-4 font-mono">{Number(item['月線斜率']).toFixed(1)}</td>
                                                <td className="px-6 py-4 font-mono">{Number(item['上軌斜率']).toFixed(1)}</td>
                                                <td className="px-6 py-4 font-mono">{Number(item['量比']).toFixed(1)}</td>
                                                <td className="px-6 py-4 font-mono text-amber-400">{Number(item['成交額(億)']).toFixed(2)}</td>
                                                <td className="px-6 py-4 font-mono text-gray-500 text-xs">{item['資料日期']}</td>
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
                                            <th className="px-6 py-4 text-amber-400 font-bold cursor-pointer hover:text-amber-300" onClick={() => handleSort('月線斜率(%)')}>月線斜率(%){renderSortIcon('月線斜率(%)')}</th>
                                            <th className="px-6 py-4 text-amber-400 font-bold cursor-pointer hover:text-amber-300" onClick={() => handleSort('布林位階')}>布林位階{renderSortIcon('布林位階')}</th>
                                            <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort('成交額(億)')}>成交額(億){renderSortIcon('成交額(億)')}</th>
                                            <th className="px-6 py-4 text-red-400 font-bold cursor-pointer hover:text-red-300" onClick={() => handleSort('處置狀態')}>處置狀態{renderSortIcon('處置狀態')}</th>
                                            <th className="px-6 py-4 cursor-pointer hover:text-white text-xs opacity-50" onClick={() => handleSort('資料日期')}>日期{renderSortIcon('資料日期')}</th>
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
                                                <td className="px-6 py-4 font-mono">{Number(item['收盤價']).toFixed(1)}</td>
                                                <td className={`px-6 py-4 font-mono ${getChangePctColor(item['今日漲跌幅(%)'])}`}>{Number(item['今日漲跌幅(%)']).toFixed(2)}%</td>
                                                <td className="px-6 py-4 font-mono">{Number(item['成交量(張)']).toLocaleString()}</td>
                                                <td className="px-6 py-4 font-mono text-amber-300 font-bold">{Number(item['月線斜率(%)']).toFixed(1)}</td>
                                                <td className="px-6 py-4 font-mono font-bold">
                                                    <span className={Number(item['布林位階']) < 0 ? 'text-green-400 bg-green-900/50 px-2 py-1 rounded' : 'text-green-400'}>
                                                        {Number(item['布林位階']).toFixed(1)}
                                                    </span>
                                                </td>
                                                <td className="px-6 py-4 font-mono text-amber-400">{Number(item['成交額(億)']).toFixed(2)}</td>
                                                <td className="px-6 py-4 font-bold text-red-400">{item['處置狀態']}</td>
                                                <td className="px-6 py-4 font-mono text-gray-500 text-xs">{item['資料日期']}</td>
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
