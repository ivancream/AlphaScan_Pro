import React, { useState } from 'react';
import { useSwingShort } from '@/hooks/useSwing';
import { LoadingState } from '@/components/ui/LoadingState';
import { useAppStore } from '@/store/useAppStore';
import { useNavigate } from 'react-router-dom';
import { ChipsAnalysisWidget } from '@/components/chips/ChipsAnalysisWidget';
import { TrendingDown, Activity } from 'lucide-react';
import { cleanStockSymbol, toStockDetailPath } from '@/lib/stocks';

type ScanRow = Record<string, string | number | boolean | null | undefined> & {
    _ticker: string;
    代號: string;
    名稱: string;
    產業: string;
    收盤價: number;
    '今日漲跌幅(%)': number;
    '成交量(張)': number;
    資料日期: string;
};

const FilterCheckbox = ({ label, checked, onChange, desc, color }: { label: string, checked: boolean, onChange: (v: boolean) => void, desc: string, color: 'green' }) => (
    <label className="flex items-start gap-3 cursor-pointer group">
        <div className="pt-1">
            <input 
                type="checkbox" 
                checked={checked} 
                onChange={(e) => onChange(e.target.checked)}
                className="w-5 h-5 rounded border-gray-700 bg-[#0E1117] transition-all cursor-pointer text-green-600 focus:ring-green-500"
            />
        </div>
        <div className="flex flex-col">
            <span className={`font-bold transition-colors ${checked ? 'text-green-400' : 'text-gray-500'}`}>
                {label}
            </span>
            <span className="text-[10px] text-gray-500 font-mono mt-0.5">{desc}</span>
        </div>
    </label>
);

export default function SwingShortPage() {
    const { scannedStrategies, setScanned } = useAppStore();
    const isScanned = scannedStrategies.includes('short_sell');
    
    const [params, setParams] = useState({
        req_ma: true,
        req_slope: true,
        req_chips: true,
        req_near_band: true
    });
    const { data: scanResults, isLoading, error } = useSwingShort(isScanned, params);
    const [selectedItem, setSelectedItem] = useState<ScanRow | null>(null);

    const setSymbol = useAppStore((state) => state.setSymbol);
    const navigate = useNavigate();

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

    return (
        <div className="p-6 space-y-6 animate-in fade-in duration-500 text-gray-200">
            <div className="flex justify-between items-center border-b border-gray-800 pb-4">
                <div>
                    <h2 className="text-3xl font-bold text-white tracking-widest flex items-center gap-3">
                        <span className="w-1.5 h-8 bg-green-500 rounded-full inline-block"></span>
                        波段空方選股策略
                    </h2>
                </div>
                <button
                    onClick={() => setScanned('short_sell')}
                    disabled={isLoading}
                    className="bg-green-600 hover:bg-green-700 text-white px-6 py-2.5 rounded-lg font-bold shadow-lg shadow-green-900/20 transition flex items-center gap-2 disabled:opacity-50"
                >
                    {isLoading ? <Activity className="animate-spin" size={18} /> : <TrendingDown size={18} />}
                    {isLoading ? "核心引擎掃描中..." : "啟動「高檔出貨」選股"}
                </button>
            </div>

            {/* 策略切換 Tabs (為保持 UI 一致性) */}
            <div className="flex gap-2">
                <button
                    className="px-5 py-2.5 rounded-lg font-bold text-sm transition-all border bg-green-600/20 border-green-500 text-green-300"
                >
                    高檔出貨
                </button>
            </div>

            {/* 策略篩選與參數配置 */}
            <div className="bg-[#161B22] border border-green-800/40 rounded-xl p-5 space-y-4">
                <div className="flex justify-between items-center border-b border-gray-800 pb-2">
                    <p className="text-green-400 font-bold text-sm tracking-wider uppercase">策略篩選條件 (預設全選)</p>
                    <span className="text-xs text-gray-500 italic">勾選後將僅顯示符合該條件的標的</span>
                </div>
                
                <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
                    <FilterCheckbox 
                        label="均線空排" 
                        checked={params.req_ma} 
                        onChange={(val) => setParams(prev => ({ ...prev, req_ma: val }))}
                        desc="MA5 < MA10 < MA20"
                        color="green"
                    />
                    <FilterCheckbox 
                        label="月線下彎" 
                        checked={params.req_slope} 
                        onChange={(val) => setParams(prev => ({ ...prev, req_slope: val }))}
                        desc="月線斜率 < 0"
                        color="green"
                    />
                    <FilterCheckbox 
                        label="籌碼渙散" 
                        checked={params.req_chips} 
                        onChange={(val) => setParams(prev => ({ ...prev, req_chips: val }))}
                        desc="大戶減 / 散戶增"
                        color="green"
                    />
                    <FilterCheckbox 
                        label="沿下軌" 
                        checked={params.req_near_band} 
                        onChange={(val) => setParams(prev => ({ ...prev, req_near_band: val }))}
                        desc="靠近布林下軌 (低買)"
                        color="green"
                    />
                </div>
            </div>

            {isScanned && (
                <div className="bg-[#161B22] border border-gray-800 rounded-xl overflow-hidden shadow-xl">

                    {isLoading ? (
                        <div className="p-12"><LoadingState text="正在從高速資料庫中執行全市場空方篩選..." /></div>
                    ) : error ? (
                        <div className="p-6 text-red-400 bg-red-900/10">掃描過程發生溢出或連線錯誤。</div>
                    ) : scanResults && scanResults.length > 0 ? (
                        <div className="overflow-x-auto">
                            <table className="w-full text-left text-sm text-gray-300">
                                <thead className="bg-[#0E1117] text-gray-400 text-xs uppercase font-semibold border-b border-gray-800">
                                    <tr>
                                        <th className="px-6 py-4">代號</th>
                                        <th className="px-6 py-4">名稱</th>
                                        <th className="px-6 py-4">產業</th>
                                        <th className="px-6 py-4">收盤價</th>
                                        <th className="px-6 py-4">漲跌幅</th>
                                        <th className="px-6 py-4">成交量(張)</th>
                                        <th className="px-6 py-4 text-green-400">均線空排</th>
                                        <th className="px-6 py-4 text-green-400">月線下彎</th>
                                        <th className="px-6 py-4 text-green-400">籌碼渙散</th>
                                        <th className="px-6 py-4">沿下軌</th>
                                        <th className="px-6 py-4">大戶變動</th>
                                        <th className="px-6 py-4">散戶變動</th>
                                        <th className="px-6 py-4 text-xs opacity-50">資料日期</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-800">
                                    {scanResults.map((item: ScanRow, idx: number) => (
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
                                                {item["代號"]} ↗
                                            </td>
                                            <td className="px-6 py-4 font-medium text-white">{item["名稱"]}</td>
                                            <td className="px-6 py-4 text-gray-400">{item['產業']}</td>
                                            <td className="px-6 py-4 font-mono">{Number(item["收盤價"]).toFixed(1)}</td>
                                            <td className={`px-6 py-4 font-mono ${getChangePctColor(item['今日漲跌幅(%)'])}`}>{Number(item['今日漲跌幅(%)']).toFixed(2)}%</td>
                                            <td className="px-6 py-4 font-mono">{Number(item['成交量(張)']).toLocaleString()}</td>
                                            <td className="px-6 py-4 font-bold">{item["空頭排列"]}</td>
                                            <td className="px-6 py-4 font-bold">{item["月線下彎"]}</td>
                                            <td className="px-6 py-4 font-bold tracking-widest">{item["籌碼渙散"]}</td>
                                            <td className="px-6 py-4 font-bold">{item["沿下軌"]}</td>
                                            <td className="px-6 py-4 font-mono text-blue-400">{item["大戶變動"]}</td>
                                            <td className="px-6 py-4 font-mono text-red-400">+{item["散戶變動"]}</td>
                                            <td className="px-6 py-4 font-mono text-gray-500 text-xs">{item['資料日期']}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    ) : (
                        <div className="p-12 text-center text-gray-500">當前無符合【高檔出貨】策略之標的。</div>
                    )}
                </div>
            )}

            {selectedItem && (
                <div className="animate-in slide-in-from-bottom duration-500">
                    <ChipsAnalysisWidget
                        symbol={selectedItem._ticker}
                        isShort={true}
                        techData={selectedItem}
                        title={`深度數據透視: ${selectedItem["代號"]} ${selectedItem["名稱"]}`}
                    />
                </div>
            )}
        </div>
    );
}
