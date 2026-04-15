import React, { useState } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { useFundamentalInfo, useFundamentalSentiment, streamFundamentalReport } from '@/hooks/useFundamental';
import { LoadingState } from '@/components/ui/LoadingState';
import { Database, MessageSquare, Cpu, BarChart3, Search, Activity } from 'lucide-react';

export default function FundamentalPage() {
    const selectedSymbol = useAppStore((state) => state.selectedSymbol);

    const [startAnalysis, setStartAnalysis] = useState(false);
    const [reportStream, setReportStream] = useState('');
    const [isAnalyzing, setIsAnalyzing] = useState(false);

    // Queries
    const { data: infoData, isLoading: infoLoading, error: infoError } = useFundamentalInfo(selectedSymbol, startAnalysis);
    const { data: sentimentData, isLoading: sentimentLoading } = useFundamentalSentiment(selectedSymbol, startAnalysis);

    const handleGenerateReport = async () => {
        if (!infoData || !sentimentData) return;

        setIsAnalyzing(true);
        setReportStream('');

        await streamFundamentalReport(
            selectedSymbol,
            infoData,
            sentimentData,
            (textChunk) => {
                setReportStream(prev => prev + textChunk);
            },
            () => {
                setIsAnalyzing(false);
            }
        );
    };

    return (
        <div className="p-6 space-y-8 animate-in fade-in duration-500 text-gray-200">

            <div className="flex justify-between items-center border-b border-gray-800 pb-4">
                <div>
                    <h2 className="text-3xl font-bold text-white tracking-widest flex items-center gap-3">
                        <span className="w-1.5 h-8 bg-[#EAB308] rounded-full inline-block"></span>
                        基本面與輿情分析
                    </h2>
                </div>
                <button
                    onClick={() => setStartAnalysis(true)}
                    className="bg-[#1E293B] hover:bg-[#334155] border border-gray-700 text-white px-6 py-2.5 rounded-lg font-bold transition flex items-center gap-2"
                >
                    <Search size={18} />
                    同步個股基本面數據
                </button>
            </div>

            {startAnalysis && (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">

                    {/* 左側：基本面硬數據 */}
                    <section className="bg-[#161B22] border border-gray-800 rounded-xl p-6 shadow-xl">
                        <h3 className="text-xl font-bold text-[#EAB308] mb-6 flex items-center gap-2">
                            <Database size={20} />
                            核心營運能力與財務摘要
                        </h3>

                        {infoLoading ? (
                            <div className="h-40">
                                <LoadingState text={`連線至資料庫獲取 ${selectedSymbol} 財報...`} />
                            </div>
                        ) : infoError ? (
                            <div className="text-red-400 p-4 bg-red-900/20 rounded">無法獲取公司財報數據，請確認代碼是否正確。</div>
                        ) : infoData ? (
                            <div className="space-y-4">
                                <div className="flex justify-between items-end border-b border-gray-700 pb-2">
                                    <span className="text-gray-400">公司名稱</span>
                                    <span className="text-xl font-bold text-white">{infoData.name}</span>
                                </div>
                                <div className="grid grid-cols-2 gap-4">
                                    <DataMetric label="最新股價" value={infoData.price} />
                                    <DataMetric label="本益比 (PE)" value={infoData.pe} />
                                    <DataMetric label="股東權益報酬率 (ROE)" value={infoData.roe} />
                                    <DataMetric label="營收成長率" value={infoData.growth} />
                                    <DataMetric label="毛利率" value={infoData.margin} />
                                    <DataMetric label="負債比" value={infoData.debt_ratio} />
                                </div>
                                <div className="mt-4 pt-4 border-t border-gray-800">
                                    <span className="text-xs text-gray-500 block mb-1">近期技術面狀態</span>
                                    <div className="text-sm font-mono text-gray-300 bg-[#0E1117] p-3 rounded">{infoData.technicals}</div>
                                </div>
                            </div>
                        ) : null}
                    </section>

                    {/* 右側：輿情數據 */}
                    <section className="bg-[#161B22] border border-gray-800 rounded-xl p-6 shadow-xl flex flex-col">
                        <h3 className="text-xl font-bold text-[#EAB308] mb-6 flex items-center gap-2">
                            <MessageSquare size={20} />
                            多維度社群情緒與即時新聞監控
                        </h3>

                        {sentimentLoading ? (
                            <div className="flex-1 min-h-[160px]">
                                <LoadingState text={`正在並行搜尋 PTT、Yahoo 與 鉅亨網輿情... (即將完成)`} />
                            </div>
                        ) : sentimentData ? (
                            <div className="space-y-4 flex-1 overflow-y-auto pr-2 custom-scrollbar max-h-[500px]">
                                <SentimentBlock title="鉅亨網 (Anue) 最新新聞" content={sentimentData.anue} color="border-yellow-600" />
                                <SentimentBlock title="Yahoo 股市動態" content={sentimentData.yahoo} color="border-[#EAB308]" />
                                <SentimentBlock title="PTT 鄉民討論 (Stock版)" content={sentimentData.ptt} color="border-green-600" />
                            </div>
                        ) : (
                            <div className="text-gray-500 italic">尚未載入數據</div>
                        )}
                    </section>

                </div>
            )}

        </div>
    );
}

function DataMetric({ label, value }: { label: string, value: string | number }) {
    return (
        <div className="bg-[#0E1117] p-3 rounded border border-gray-800">
            <div className="text-xs text-gray-500 mb-1">{label}</div>
            <div className="text-lg font-bold text-[#EAB308] font-mono">{value}</div>
        </div>
    );
}

function SentimentBlock({ title, content, color }: { title: string, content: string, color: string }) {
    return (
        <div className={`pl-4 py-1 border-l-4 ${color}`}>
            <h4 className="text-sm font-semibold text-gray-400 mb-2">{title}</h4>
            <div className="text-sm text-gray-300 whitespace-pre-wrap font-mono leading-relaxed">
                {content || "無相關資料"}
            </div>
        </div>
    );
}
