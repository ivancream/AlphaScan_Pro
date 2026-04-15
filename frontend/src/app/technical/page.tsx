import React, { useState } from 'react';
import { Activity, TrendingUp, Search, PlayCircle, Layout, LayoutGrid, Info } from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';
import { useTechnicalIndicators, streamTechnicalReport } from '@/hooks/useTechnical';
import { LoadingState } from '@/components/ui/LoadingState';
import { CandlestickChart } from '@/components/charts/CandlestickChart';
import { Database, Cpu, LayoutPanelLeft, LineChart } from 'lucide-react';
import { IndicatorType } from '@/types/chart';

export default function TechnicalPage() {
    const selectedSymbol = useAppStore((state) => state.selectedSymbol);

    const [startAnalysis, setStartAnalysis] = useState(false);
    const [reportStream, setReportStream] = useState('');
    const [isAnalyzing, setIsAnalyzing] = useState(false);

    // 副圖指標選擇狀態
    const [indicator1, setIndicator1] = useState<IndicatorType>('Volume');
    const [indicator2, setIndicator2] = useState<IndicatorType>('KD');

    // Queries
    const { data: techData, isLoading: techLoading, error: techError } = useTechnicalIndicators(selectedSymbol, startAnalysis);

    const handleGenerateReport = async () => {
        if (!techData) return;
        setIsAnalyzing(true);
        setReportStream('');
        await streamTechnicalReport(selectedSymbol, (textChunk) => setReportStream(prev => prev + textChunk), () => setIsAnalyzing(false));
    };

    return (
        <div className="p-6 space-y-8 animate-in fade-in duration-500 text-gray-200 lg:max-w-full">

            {/* Header / Toolbar Area */}
            <div className="flex flex-col lg:flex-row justify-between items-start lg:items-center border-b border-gray-800 pb-4 gap-4">
                <div className="flex items-center gap-6">
                    <div>
                        <h2 className="text-3xl font-bold text-white tracking-widest flex items-center gap-3">
                            <span className="w-1.5 h-8 bg-[#EAB308] rounded-full inline-block"></span>
                            專業技術面分析
                        </h2>
                    </div>

                    {/* 指標選取面板 */}
                    <div className="flex gap-4 items-center bg-[#161B22] p-2 rounded-lg border border-gray-700 shadow-inner">
                        <div className="flex flex-col">
                            <label className="text-[10px] text-gray-400 font-black ml-1 mb-1 tracking-widest uppercase">第一副圖指標</label>
                            <select
                                value={indicator1}
                                onChange={(e) => setIndicator1(e.target.value as IndicatorType)}
                                className="bg-[#0B0E11] text-xs text-white border border-gray-600 rounded px-3 py-1.5 outline-none min-w-[110px] focus:border-[#EAB308] transition-all"
                            >
                                {INDICATOR_OPTIONS.map(opt => <option key={opt} value={opt}>{translateIndicator(opt)}</option>)}
                            </select>
                        </div>
                        <div className="flex flex-col border-l border-gray-800 pl-4">
                            <label className="text-[10px] text-gray-400 font-black ml-1 mb-1 tracking-widest uppercase">第二副圖指標</label>
                            <select
                                value={indicator2}
                                onChange={(e) => setIndicator2(e.target.value as IndicatorType)}
                                className="bg-[#0B0E11] text-xs text-white border border-gray-600 rounded px-3 py-1.5 outline-none min-w-[110px] focus:border-[#EAB308] transition-all"
                            >
                                {INDICATOR_OPTIONS.map(opt => <option key={opt} value={opt}>{translateIndicator(opt)}</option>)}
                            </select>
                        </div>
                    </div>
                </div>

                <button
                    onClick={() => setStartAnalysis(true)}
                    className="bg-[#1E293B] hover:bg-[#334155] border border-gray-700 text-white px-8 py-2.5 rounded-lg font-bold shadow-md transition flex items-center gap-2 group"
                >
                    <LayoutPanelLeft className="group-hover:rotate-12 transition-transform" size={18} />
                    同步最新市場行情
                </button>
            </div>

            {/* Full Width Dynamic Chart Area */}
            <section className="w-full bg-[#0B0E11] border border-gray-800 rounded-xl shadow-2xl min-h-[700px] overflow-hidden">
                {startAnalysis ? (
                    <CandlestickChart symbol={selectedSymbol} indicator1={indicator1} indicator2={indicator2} />
                ) : (
                    <div className="h-[700px] flex items-center justify-center text-gray-500 italic bg-[#0B0E11]">
                        點擊右上方按鈕載入 {selectedSymbol || '標的'} 歷史行情數據
                    </div>
                )}
            </section>

            {/* Bottom Panel: Indicator Snapshot + AI Analysis */}
            <div className="grid grid-cols-1 xl:grid-cols-4 gap-6">
                {/* 指標數值快照 */}
                <section className="xl:col-span-4 bg-[#161B22] border border-gray-800 rounded-xl p-4 shadow-xl flex flex-col h-full">
                    <h3 className="text-sm font-bold text-[#EAB308] tracking-widest uppercase mb-4 border-b border-gray-800 pb-2">
                        數據摘要
                    </h3>
                    {techLoading ? <LoadingState text="載入中" /> : techData ? (
                        <div className="grid grid-cols-2 md:grid-cols-6 gap-3 flex-1 pr-1">
                            <CompactMetric label="收盤價" value={techData.summary.Close} highlight={false} />
                            <CompactMetric label="MA5" value={techData.summary.MA5} highlight={techData.summary.Close > techData.summary.MA5} />
                            <CompactMetric label="MA20" value={techData.summary.MA20} highlight={techData.summary.Close > techData.summary.MA20} />
                            <CompactMetric label="RSI(14)" value={techData.summary.RSI} highlight={techData.summary.RSI > 50} />
                            <CompactMetric label="KD-K" value={techData.summary.K} highlight={techData.summary.K > techData.summary.D} />
                            <CompactMetric label="MACD柱" value={techData.summary.MACD_Hist} highlight={techData.summary.MACD_Hist > 0} />
                            <CompactMetric label="相對強度(RS)" value={techData.summary.RS} highlight={techData.summary.RS > 100} />
                        </div>
                    ) : <div className="text-gray-600 text-center py-10 italic">尚未載入資料</div>}

                    {techData && (
                        <div className={`mt-4 p-2 text-center text-xs font-bold rounded border ${techData.summary.BB_Status === 'Upper Band' ? 'bg-red-900/20 text-red-500 border-red-800/50' :
                            techData.summary.BB_Status === 'Lower Band' ? 'bg-green-900/10 text-green-500 border-green-800/50' :
                                'bg-[#0E1117] text-gray-500 border-gray-800'
                            }`}>
                            布林位階：{techData.summary.BB_Status}
                        </div>
                    )}
                </section>
            </div>
        </div>
    );
}

const translateIndicator = (type: string) => {
    const map: Record<string, string> = {
        'Volume': '成交量(量能)',
        'MACD': 'MACD (平滑異同)',
        'RSI': 'RSI (相對強弱)',
        'KD': 'KD (隨機指標)',
        'Bias': '乖離率 (20MA)',
        'OBV': 'OBV (能量潮)',
        'RS': 'RS (相對大盤強度)',
        'None': '不顯示'
    };
    return map[type] || type;
};

const INDICATOR_OPTIONS: IndicatorType[] = ['Volume', 'MACD', 'RSI', 'KD', 'Bias', 'OBV', 'RS', 'None'];

function CompactMetric({ label, value, highlight }: { label: string, value: string | number, highlight: boolean }) {
    const isNeutral = value === 'N/A' || isNaN(Number(value));
    return (
        <div className={`p-2 rounded border bg-[#0B0E11] ${isNeutral ? 'border-gray-800' : highlight ? 'border-red-900/30' : 'border-green-900/30'}`}>
            <div className="text-[9px] text-gray-500 mb-0.5 uppercase tracking-tighter">{label}</div>
            <div className={`text-sm font-bold font-mono ${isNeutral ? 'text-gray-400' : highlight ? 'text-red-500' : 'text-green-500'}`}>{value}</div>
        </div>
    );
}
