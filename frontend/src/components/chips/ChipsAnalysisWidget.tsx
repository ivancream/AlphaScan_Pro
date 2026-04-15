import React, { useState, useRef } from 'react';
import { useChipsAnalysis } from '@/hooks/useChips';
import { LoadingState } from '@/components/ui/LoadingState';
import { BarChartHorizontal, Plus, Image as ImageIcon, BrainCircuit, X, Activity, Star, History } from 'lucide-react';
import { useWatchlist, useAddToWatchlist, useRemoveFromWatchlist } from '@/hooks/useWatchlist';
import { useSimpleBacktest } from '@/hooks/useBacktest';

interface ChipsAnalysisWidgetProps {
    symbol: string;
    isShort?: boolean;
    techData?: any;
    title?: string;
}

export const ChipsAnalysisWidget = ({ symbol, isShort = false, techData, title = "籌碼綜合深度診斷" }: ChipsAnalysisWidgetProps) => {
    const [files, setFiles] = useState<File[]>([]);
    const [previews, setPreviews] = useState<string[]>([]);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const { analyzeChips, isAnalyzing, reportStream } = useChipsAnalysis();

    const { data: watchlist } = useWatchlist();
    const { mutate: addStock } = useAddToWatchlist();
    const { mutate: removeStock } = useRemoveFromWatchlist();

    const stockId = symbol.replace('.TW', '').replace('.TWO', '');
    const isWatched = watchlist?.some((w: any) => w['代號'] === stockId);

    // 回測資料
    const strategyStr = isShort ? "core_short" : "core_long";
    const { data: backtest } = useSimpleBacktest(stockId, strategyStr);

    const toggleWatchlist = () => {
        if (isWatched) {
            removeStock(stockId);
        } else {
            addStock(stockId);
        }
    };

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files) {
            const newFiles = Array.from(e.target.files);
            setFiles(prev => [...prev, ...newFiles]);
            newFiles.forEach(file => {
                const reader = new FileReader();
                reader.onloadend = () => {
                    setPreviews(prev => [...prev, reader.result as string]);
                };
                reader.readAsDataURL(file);
            });
        }
    };

    const removeFile = (index: number) => {
        setFiles(prev => prev.filter((_, i) => i !== index));
        setPreviews(prev => prev.filter((_, i) => i !== index));
    };

    return (
        <div className="bg-[#161B22] border border-gray-800 rounded-xl p-6 shadow-2xl space-y-6">
            <div className="flex justify-between items-center border-b border-gray-800 pb-4">
                <div className="flex gap-4 items-center">
                    <h3 className="text-xl font-bold text-white flex items-center gap-2">
                        <BarChartHorizontal className="text-[#F9A825]" size={20} />
                        {title}
                    </h3>
                    <button
                        onClick={toggleWatchlist}
                        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-sm font-bold transition-all ${
                            isWatched 
                                ? 'bg-blue-900/20 text-blue-400 border-blue-800/50 hover:bg-blue-900/40' 
                                : 'bg-[#0E1117] text-gray-400 border-gray-700 hover:text-white'
                        }`}
                    >
                        <Star size={16} className={isWatched ? 'fill-blue-400' : ''} />
                        {isWatched ? '已在自選雷達' : '加入自選雷達'}
                    </button>
                </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="space-y-4">
                    {/* 回測摘要區域 */}
                    {backtest && !backtest.error && (
                        <div className="bg-[#0E1117] border border-gray-700/50 rounded-lg p-3 flex items-center justify-between shadow-inner">
                            <div className="flex items-center gap-2 text-sm">
                                <History size={16} className="text-[#EAB308]" />
                                <span className="text-gray-300">近一年同策略勝率 (持有5日)</span>
                            </div>
                            {backtest.signal_count === 0 ? (
                                <span className="text-gray-500 text-sm font-mono tracking-wider">尚無足夠歷史訊號</span>
                            ) : (
                                <div className="flex gap-4">
                                    <span className="text-sm">
                                        次数 <span className="text-white font-bold">{backtest.signal_count}</span>
                                    </span>
                                    <span className="text-sm">
                                        勝率 <span className={`font-bold ${backtest.win_rate_5d > 50 ? 'text-red-400' : 'text-green-400'}`}>{backtest.win_rate_5d}%</span>
                                    </span>
                                    <span className="text-sm">
                                        均報 <span className={`font-bold ${backtest.avg_return_5d > 0 ? 'text-red-400' : 'text-green-400'}`}>{backtest.avg_return_5d > 0 ? '+' : ''}{backtest.avg_return_5d}%</span>
                                    </span>
                                </div>
                            )}
                        </div>
                    )}

                    <p className="text-sm text-gray-400">請上傳包含主力買賣超、三大法人或分點資訊之截圖，AI 模型將結合技術指標進行多維度深度診斷。</p>
                    <div
                        onClick={() => fileInputRef.current?.click()}
                        className="border-2 border-dashed border-gray-700 hover:border-[#F9A825] rounded-xl py-12 text-center cursor-pointer bg-[#0E1117] transition-all group"
                    >
                        <ImageIcon className="mx-auto text-gray-600 mb-2 group-hover:text-[#F9A825] transition-colors" size={40} />
                        <p className="text-gray-400 group-hover:text-white">點擊或拖放籌碼分點圖表</p>
                        <input type="file" multiple hidden ref={fileInputRef} onChange={handleFileChange} accept="image/*" />
                    </div>

                    {previews.length > 0 && (
                        <div className="grid grid-cols-4 gap-3">
                            {previews.map((src, idx) => (
                                <div key={idx} className="relative group aspect-square rounded-lg border border-gray-700 overflow-hidden shadow-inner bg-black">
                                    <img src={src} className="w-full h-full object-cover" />
                                    <button onClick={() => removeFile(idx)} className="absolute top-1 right-1 bg-red-500 rounded-full p-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                        <X size={10} />
                                    </button>
                                </div>
                            ))}
                        </div>
                    )}

                    <button
                        onClick={() => analyzeChips(symbol, files, isShort, techData)}
                        disabled={isAnalyzing || files.length === 0}
                        className="w-full bg-gradient-to-r from-[#F9A825] to-[#F57F17] hover:brightness-110 text-black font-black tracking-widest py-3 rounded-lg shadow-lg flex items-center justify-center gap-2 transition disabled:opacity-50"
                    >
                        {isAnalyzing ? <Activity className="animate-spin" size={18} /> : <BrainCircuit size={18} />}
                        {isAnalyzing ? '特徵辨識推論中...' : '啟動 AI 籌碼診斷模型'}
                    </button>
                </div>

                <div className="bg-[#0E1117] border border-gray-800 rounded-xl p-6 min-h-[300px] overflow-auto custom-scrollbar shadow-inner relative">
                    <div className="absolute top-0 right-0 w-32 h-32 bg-[#EAB308]/5 rounded-full blur-[60px] pointer-events-none"></div>
                    {isAnalyzing && !reportStream && <LoadingState text="正在掃描圖表特徵並檢索主力動量..." />}
                    {reportStream ? (
                        <div className="prose prose-invert max-w-none text-gray-300 text-[0.95rem] leading-relaxed whitespace-pre-wrap relative z-10">
                            {reportStream}
                            {isAnalyzing && <span className="inline-block w-2 h-5 ml-1 bg-[#F9A825] animate-pulse rounded" />}
                        </div>
                    ) : (
                        <div className="h-full flex flex-col items-center justify-center text-gray-600 italic text-sm py-12">
                            <BrainCircuit className="mb-3 opacity-20" size={48} />
                            等待籌碼數據輸入以啟動分析
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};
