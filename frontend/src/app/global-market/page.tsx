import React, { useState } from 'react';
import { useMacroData, useMarketNews } from '@/hooks/useGlobalMarket';
import { LoadingState } from '@/components/ui/LoadingState';
import { Globe, RefreshCw, MessageSquare } from 'lucide-react';

const MARKET_OPTIONS = [
    "TAIEX 台股加權指數",
    "Nikkei 225 日經 225",
    "KOSPI 韓國綜合指數",
    "Nasdaq 納斯達克指數",
    "PHLX Semi 費城半導體"
];

export default function GlobalMarketPage() {
    const { data: macroData, isLoading: macroLoading, refetch: refetchMacro } = useMacroData();

    const [selectedMarket, setSelectedMarket] = useState(MARKET_OPTIONS[0]);

    // 直接打新聞爬蟲 API
    const { data: newsData, isLoading: newsLoading } = useMarketNews(selectedMarket);

    return (
        <div className="p-6 space-y-8 animate-in fade-in duration-500 text-gray-200">

            <section>
                <div className="flex justify-between items-end mb-4 border-b border-gray-800 pb-2">
                    <h2 className="text-2xl font-bold text-white tracking-widest flex items-center gap-3">
                        <span className="w-1.5 h-6 bg-[#EAB308] rounded-full inline-block"></span>
                        全球宏觀核心指標
                    </h2>
                    <button
                        onClick={() => refetchMacro()}
                        className="text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 px-3 py-1.5 rounded transition flex items-center gap-1.5 font-bold"
                    >
                        <RefreshCw size={12} />
                        同步即時總經數據
                    </button>
                </div>

                {macroLoading ? (
                    <div className="h-32">
                        <LoadingState text="擷取各國匯率、VIX 指數與核心經濟指標中..." />
                    </div>
                ) : macroData ? (
                    <div className="space-y-6">
                        <div>
                            <h3 className="text-sm text-gray-500 font-black mb-3 tracking-widest uppercase">短線情緒 (風險偏好度量)</h3>
                            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                                <MetricCard label="台幣匯率 (USD/TWD)" value={macroData.short.twd} />
                                <MetricCard label="VIX 恐慌指數" value={macroData.short.vix} />
                                <MetricCard label="美債 10 年殖利率" value={macroData.short.bond} />
                                <MetricCard label="黃金現貨 (Gold)" value={macroData.short.gold} />
                            </div>
                        </div>
                        <div>
                            <h3 className="text-sm text-gray-500 font-black mb-3 tracking-widest uppercase">波段趨勢 (價值錨定基準)</h3>
                            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                                <MetricCard label="美國 CPI 指數" value={macroData.long.cpi} />
                                <MetricCard label="TW 外銷訂單" value={macroData.long.export} />
                                <MetricCard label="PMI 採購經理人指數" value={macroData.long.pmi} />
                                <MetricCard label="國發會景氣燈號" value={macroData.long.signal} />
                            </div>
                        </div>
                    </div>
                ) : (
                    <div className="text-red-500 bg-red-900/10 p-4 rounded border border-red-500/20">無法獲取同步數據，請檢查 API 串接狀態。</div>
                )}
            </section>

            <section>
                <div className="flex items-center gap-2 mb-4">
                    <Globe className="text-[#F9A825]" size={24} />
                    <h2 className="text-2xl font-bold text-white tracking-widest">全球盤勢戰情雷達 (爬蟲新聞)</h2>
                </div>

                <div className="flex flex-col md:flex-row gap-4 mb-6 bg-[#161B22] p-4 rounded-xl border border-gray-800">
                    <select
                        value={selectedMarket}
                        onChange={(e) => setSelectedMarket(e.target.value)}
                        className="bg-[#0E1117] border border-gray-700 text-white rounded px-4 py-2 focus:border-[#F9A825] focus:outline-none flex-1 font-bold"
                    >
                        {MARKET_OPTIONS.map(opt => <option key={opt} value={opt}>{opt}</option>)}
                    </select>
                </div>

                <div className="bg-[#161B22] border border-gray-800 rounded-xl p-8 shadow-2xl relative overflow-hidden">
                    <div className="absolute top-0 right-0 w-96 h-96 bg-[#EAB308]/5 rounded-full blur-[120px] pointer-events-none"></div>
                    <h3 className="text-xl font-bold text-white mb-6 border-b border-gray-800 pb-3 flex items-center gap-2">
                        <MessageSquare size={20} className="text-[#EAB308]" />
                        {selectedMarket} 最新市場快訊爬蟲
                    </h3>
                    
                    {newsLoading ? (
                        <div className="h-20 flex items-center justify-center">
                            <LoadingState text="擷取 Google News 最新新聞摘要中..." />
                        </div>
                    ) : newsData?.news ? (
                        <div className="prose prose-invert max-w-none text-gray-300 leading-relaxed text-base whitespace-pre-wrap relative z-10 font-sans tracking-wide">
                            {newsData.news}
                        </div>
                    ) : (
                        <div className="text-gray-500 italic text-center">暫無即時新聞。</div>
                    )}
                </div>
            </section>

        </div>
    );
}

function MetricCard({ label, value }: { label: string, value: string }) {
    return (
        <div className="bg-[#161B22] p-5 rounded-xl border border-gray-800 shadow-lg group hover:border-[#EAB308] transition-colors">
            <div className="text-[0.7rem] text-gray-500 uppercase tracking-widest font-black mb-2">{label}</div>
            <div className="text-2xl font-mono font-bold text-white group-hover:text-[#EAB308] transition-colors">{value}</div>
        </div>
    );
}
