import React from 'react';
import { useWatchlist, useRemoveFromWatchlist } from '@/hooks/useWatchlist';
import { useLiveQuotes } from '@/hooks/useLiveQuotes';
import { LoadingState } from '@/components/ui/LoadingState';
import { Trash2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAppStore } from '@/store/useAppStore';
import { cleanStockSymbol, toStockDetailPath } from '@/lib/stocks';

type WatchlistRow = {
    _ticker?: string;
    代號: string;
    名稱: string;
    產業: string;
    收盤價: number;
    '今日漲跌幅(%)': number;
    '成交量(張)': number;
    '資料日期': string;
};

export default function WatchlistPage() {
    const { data: watchlist, isLoading, isError, refetch } = useWatchlist();
    const { mutate: removeStock } = useRemoveFromWatchlist();
    const { connectionState, quotesByStockId, error: liveError, lastHeartbeat } = useLiveQuotes();
    const navigate = useNavigate();
    const setSymbol = useAppStore(state => state.setSymbol);

    const handleRowClick = (item: WatchlistRow) => {
        const symbol = cleanStockSymbol(item['_ticker'] || item['代號']);
        setSymbol(symbol);
        navigate(toStockDetailPath(symbol));
    };

    if (isLoading) {
        return (
            <div className="p-6">
                <LoadingState text="正在載入自選股清單..." />
            </div>
        );
    }

    if (isError) {
        return (
            <div className="p-6">
                <div className="rounded-xl border border-red-800 bg-red-950/30 p-6 text-red-300 space-y-3">
                    <h3 className="text-lg font-semibold">自選股清單載入失敗</h3>
                    <p className="text-sm text-red-200">請檢查後端 API 狀態後重試。</p>
                    <button
                        onClick={() => refetch()}
                        className="px-4 py-2 rounded-md bg-red-700 hover:bg-red-600 text-white text-sm"
                    >
                        重試
                    </button>
                </div>
            </div>
        );
    }

    return (
        <div className="p-6 space-y-6 animate-in fade-in duration-500 text-gray-200">
            <div className="flex justify-between items-center border-b border-gray-800 pb-4">
                <div>
                    <h2 className="text-3xl font-bold text-white tracking-widest flex items-center gap-3">
                        <span className="w-1.5 h-8 bg-blue-500 rounded-full inline-block"></span>
                        自選股雷達
                    </h2>
                    <div className="mt-2 text-xs text-gray-400 space-x-4">
                        <span>即時連線: <span className={connectionState === 'open' ? 'text-emerald-400' : 'text-amber-400'}>{connectionState}</span></span>
                        <span>最後心跳: {lastHeartbeat ?? '尚未收到'}</span>
                        {liveError ? <span className="text-red-400">即時錯誤: {liveError}</span> : null}
                    </div>
                </div>
            </div>

            <div className="bg-[#161B22] border border-gray-800 rounded-xl overflow-hidden shadow-xl">
                {!watchlist || watchlist.length === 0 ? (
                    <div className="p-12 text-center text-gray-500">
                        目前沒有自選標的，請至「波段多/空方」加入！
                    </div>
                ) : (
                    <table className="w-full text-left text-sm text-gray-300">
                        <thead className="bg-[#0E1117] text-gray-400 text-xs uppercase font-semibold border-b border-gray-800">
                            <tr>
                                <th className="px-6 py-4">代號</th>
                                <th className="px-6 py-4">名稱</th>
                                <th className="px-6 py-4">產業</th>
                                <th className="px-6 py-4">收盤價</th>
                                <th className="px-6 py-4">漲幅%</th>
                                <th className="px-6 py-4">成交量(張)</th>
                                <th className="px-6 py-4">成交額(億)</th>
                                <th className="px-6 py-4 text-xs opacity-50">資料日期</th>
                                <th className="px-6 py-4 text-right">操作</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-800">
                            {watchlist.map((item: WatchlistRow) => {
                                const live = quotesByStockId[item['代號']];
                                const close = live?.last_price ?? Number(item['收盤價']);
                                const chg = live?.change_pct ?? Number(item['今日漲跌幅(%)']);
                                const volume = live?.volume ? Math.floor(live.volume / 1000) : Number(item['成交量(張)']);
                                const isUp = chg > 0;
                                const isDown = chg < 0;
                                const amount = ((close || 0) * (volume || 0) * 1000) / 1e8;

                                return (
                                    <tr key={item['代號']} className="hover:bg-[#1E293B] transition-colors group">
                                        <td 
                                            className="px-6 py-4 text-[#EAB308] font-mono font-bold hover:underline hover:text-yellow-300 cursor-pointer"
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                handleRowClick(item);
                                            }}
                                        >
                                            {item['代號']} ↗
                                        </td>
                                        <td className="px-6 py-4 font-medium text-white">{item['名稱']}</td>
                                        <td className="px-6 py-4 text-gray-400">{item['產業']}</td>
                                        <td className={`px-6 py-4 font-mono font-bold ${isUp ? 'text-red-400' : isDown ? 'text-green-400' : ''}`}>
                                            {Number(close).toFixed(2)}
                                        </td>
                                        <td className={`px-6 py-4 font-mono font-bold ${isUp ? 'text-red-400' : isDown ? 'text-green-400' : ''}`}>
                                            {isUp ? '+' : ''}{chg.toFixed(2)}%
                                        </td>
                                        <td className="px-6 py-4 font-mono text-sm">{Number(volume).toLocaleString()}</td>
                                        <td className="px-6 py-4 font-mono text-sm text-amber-400">{Number(amount).toFixed(2)}</td>
                                        <td className="px-6 py-4 font-mono text-gray-500 text-xs">
                                            {item['資料日期']}
                                        </td>
                                        <td className="px-6 py-4 text-right">
                                            <button 
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    removeStock(item['代號']);
                                                }}
                                                className="text-gray-500 hover:text-red-500 transition-colors p-2 rounded-full hover:bg-black"
                                            >
                                                <Trash2 size={16} />
                                            </button>
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                )}
            </div>
        </div>
    );
}
