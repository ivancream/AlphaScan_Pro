import { Link } from 'react-router-dom';
import { Search, LineChart, GitMerge, Waves, ArrowRight } from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';
import { cleanStockSymbol, toStockDetailPath } from '@/lib/stocks';

/**
 * /stock — 個股入口說明頁（未指定代號時）
 * 有「當前標的」時可直接前往該檔個股頁。
 */
export default function StockHubPage() {
    const selectedSymbol = useAppStore((s) => s.selectedSymbol);
    const sym = cleanStockSymbol(selectedSymbol);

    return (
        <div className="max-w-2xl mx-auto px-6 py-16 text-gray-200 animate-in fade-in duration-500">
            <div className="flex items-center gap-3 mb-2">
                <LineChart className="text-cyan-400" size={28} />
                <h1 className="text-2xl font-black text-white tracking-widest">個股情報中心</h1>
            </div>
            <p className="text-gray-400 mt-3 leading-relaxed">
                在此可檢視單一標的的<strong className="text-gray-300">即時走勢</strong>、
                <strong className="text-gray-300">技術分析（K 線）</strong>、
                <strong className="text-gray-300">相關係數</strong>與
                <strong className="text-gray-300">可轉債</strong>等資訊。
            </p>

            <div className="mt-10 space-y-4 rounded-2xl border border-gray-800 bg-[#161B22] p-6">
                <h2 className="text-sm font-bold text-[#EAB308] uppercase tracking-widest flex items-center gap-2">
                    <Search size={16} />
                    如何開啟個股頁
                </h2>
                <ol className="list-decimal list-inside space-y-3 text-sm text-gray-400">
                    <li>
                        使用頂部搜尋列輸入<strong className="text-white">股票代號</strong>（如 2330）或
                        <strong className="text-white">公司名稱關鍵字</strong>，按 <kbd className="px-1.5 py-0.5 rounded bg-[#0E1117] border border-gray-700 font-mono text-xs">Enter</kbd>
                    </li>
                    <li>在多方／空方選股、資金流向熱力圖、自選清單等頁面，點擊<strong className="text-white">代號</strong>連結</li>
                    <li>點擊右上角<strong className="text-white">當前標的</strong>徽章（已選標的時）</li>
                </ol>
            </div>

            <div className="mt-8 grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
                <div className="rounded-xl border border-gray-800 bg-[#0E1117] p-4">
                    <Waves className="text-cyan-400 mb-2" size={20} />
                    <div className="font-bold text-white">即時動態</div>
                    <p className="text-gray-500 mt-1 text-xs">逐筆與報價快照</p>
                </div>
                <div className="rounded-xl border border-gray-800 bg-[#0E1117] p-4">
                    <LineChart className="text-amber-400 mb-2" size={20} />
                    <div className="font-bold text-white">技術分析</div>
                    <p className="text-gray-500 mt-1 text-xs">K 線與指標</p>
                </div>
                <div className="rounded-xl border border-gray-800 bg-[#0E1117] p-4">
                    <GitMerge className="text-amber-400 mb-2" size={20} />
                    <div className="font-bold text-white">關聯分析</div>
                    <p className="text-gray-500 mt-1 text-xs">相關係數排行</p>
                </div>
            </div>

            {sym ? (
                <div className="mt-12 flex flex-col sm:flex-row items-start sm:items-center gap-4">
                    <Link
                        to={toStockDetailPath(sym)}
                        className="inline-flex items-center gap-2 bg-cyan-600 hover:bg-cyan-500 text-white font-bold px-6 py-3 rounded-xl transition-colors"
                    >
                        開啟 {sym} 個股頁
                        <ArrowRight size={18} />
                    </Link>
                    <span className="text-xs text-gray-500">已記住您目前的標的</span>
                </div>
            ) : (
                <p className="mt-12 text-sm text-gray-500">
                    尚未選擇標的時，請先於頂部搜尋輸入代號或名稱。
                </p>
            )}
        </div>
    );
}
