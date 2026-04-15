import React, { useState, useEffect } from 'react';
import { useWarrantPositions, useBranchTrading } from '@/hooks/useChips';
import { useAppStore } from '@/store/useAppStore';
import { LoadingState } from '@/components/ui/LoadingState';

export default function ChipsPage() {
    const selectedSymbol = useAppStore((state) => state.selectedSymbol);
    const [symbolInput, setSymbolInput] = useState(selectedSymbol);
    const [activeTab, setActiveTab] = useState<'warrants' | 'branchTrading'>('warrants');

    const { positions, isLoading: isPositionsLoading, fetchPositions } = useWarrantPositions();
    const { trades, isLoading: isTradesLoading, fetchTrades } = useBranchTrading();

    useEffect(() => {
        if (activeTab === 'warrants') {
            fetchPositions(symbolInput);
        } else {
            fetchTrades(symbolInput);
        }
    }, [activeTab]);

    useEffect(() => {
        setSymbolInput(selectedSymbol);
        fetchPositions(selectedSymbol);
        fetchTrades(selectedSymbol);
    }, [selectedSymbol]);

    const handleRefresh = () => {
        if (activeTab === 'warrants') fetchPositions(symbolInput);
        else fetchTrades(symbolInput);
    };

    return (
        <div className="p-6 space-y-8 animate-in fade-in duration-500 text-gray-200">
            <div className="border-b border-gray-800 pb-4">
                <div className="flex justify-between items-end">
                    <div>
                        <h2 className="text-3xl font-bold text-white tracking-widest flex items-center gap-3">
                            <span className="w-1.5 h-8 bg-[#F9A825] rounded-full inline-block"></span>
                            籌碼大戶監控
                        </h2>
                        <p className="text-gray-400 mt-2 ml-4">
                            整合權證分點與個股關鍵分點進出明細。如需更新資料，請直接將截圖提供給 AI。
                        </p>
                    </div>

                    <div className="flex gap-4 items-center mb-1">
                        <div className="bg-[#0E1117] border border-gray-800 rounded-lg p-1 flex">
                            <button
                                onClick={() => setActiveTab('warrants')}
                                className={`px-4 py-1.5 rounded-md text-sm font-bold transition-all ${activeTab === 'warrants' ? 'bg-[#F9A825] text-black' : 'text-gray-400 hover:text-white'}`}
                            >
                                權證分點
                            </button>
                            <button
                                onClick={() => setActiveTab('branchTrading')}
                                className={`px-4 py-1.5 rounded-md text-sm font-bold transition-all ${activeTab === 'branchTrading' ? 'bg-[#F9A825] text-black' : 'text-gray-400 hover:text-white'}`}
                            >
                                關鍵分點 (個股)
                            </button>
                        </div>
                        <input
                            type="text"
                            placeholder="搜尋代號..."
                            value={symbolInput}
                            onChange={(e) => setSymbolInput(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && handleRefresh()}
                            className="bg-[#0E1117] border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-300 outline-none focus:border-[#F9A825] w-32"
                        />
                        <button
                            onClick={handleRefresh}
                            className="bg-[#1C2128] border border-gray-700 p-2 rounded-lg text-[#F9A825] hover:bg-[#2D333B] transition-colors"
                        >
                            <span className="material-symbols-outlined text-xl">refresh</span>
                        </button>
                    </div>
                </div>
            </div>

            <div className="grid grid-cols-1 gap-8">
                {activeTab === 'warrants' ? (
                    /* 權證分點表格 */
                    <div className="bg-[#161B22] border border-gray-800 rounded-xl overflow-hidden shadow-2xl">
                        <div className="p-4 bg-[#1C2128] border-b border-gray-800 flex items-center gap-2">
                            <span className="material-symbols-outlined text-[#F9A825]">token</span>
                            <h3 className="font-bold text-white">權證分點庫存明細</h3>
                        </div>
                        <div className="overflow-x-auto">
                            {isPositionsLoading ? (
                                <div className="p-12"><LoadingState text="載入權證數據中..." /></div>
                            ) : (
                                <table className="w-full text-left border-collapse">
                                    <thead className="bg-[#0E1117] text-gray-400 text-xs uppercase tracking-wider">
                                        <tr>
                                            <th className="px-6 py-4 font-semibold">日期</th>
                                            <th className="px-6 py-4 font-semibold">標的</th>
                                            <th className="px-6 py-4 font-semibold">類型</th>
                                            <th className="px-6 py-4 font-semibold">核心分點</th>
                                            <th className="px-6 py-4 font-semibold text-right">買超金額 (萬)</th>
                                            <th className="px-6 py-4 font-semibold text-right">推估損益 (萬)</th>
                                            <th className="px-6 py-4 font-semibold">狀態</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-gray-800">
                                        {positions.length > 0 ? (
                                            positions.map((pos, idx) => (
                                                <tr key={idx} className="hover:bg-[#1C2128] transition-colors group">
                                                    <td className="px-6 py-4 text-gray-400 font-mono text-sm">
                                                        {pos.snapshot_date?.includes('T') ? pos.snapshot_date.split('T')[0] : pos.snapshot_date}
                                                    </td>
                                                    <td className="px-6 py-4">
                                                        <div className="flex flex-col">
                                                            <span className="text-white font-bold">{pos.stock_name}</span>
                                                            <span className="text-gray-500 text-xs font-mono">{pos.stock_id}</span>
                                                        </div>
                                                    </td>
                                                    <td className="px-6 py-4">
                                                        <span className={`px-2 py-0.5 rounded text-[10px] ${pos.type === '認購' ? 'bg-red-500/20 text-red-400' : 'bg-green-500/20 text-green-400'}`}>
                                                            {pos.type}
                                                        </span>
                                                    </td>
                                                    <td className="px-6 py-4 text-[#F9A825] font-medium">{pos.branch_name}</td>
                                                    <td className="px-6 py-4 text-right text-white font-mono">{pos.amount_k.toLocaleString()}</td>
                                                    <td className={`px-6 py-4 text-right font-mono ${pos.est_pnl >= 0 ? 'text-red-400' : 'text-green-400'}`}>
                                                        {pos.est_pnl >= 0 ? '+' : ''}{pos.est_pnl.toLocaleString()}
                                                    </td>
                                                    <td className="px-6 py-4">
                                                        <span className={`px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-tighter ${pos.est_pnl >= 0 ? 'bg-red-500/10 text-red-500' : 'bg-green-500/10 text-green-500'}`}>
                                                            {pos.est_pnl >= 0 ? '贏家佈局' : '高手被套'}
                                                        </span>
                                                    </td>
                                                </tr>
                                            ))
                                        ) : (
                                            <tr><td colSpan={7} className="px-6 py-12 text-center text-gray-600">無權證數據</td></tr>
                                        )}
                                    </tbody>
                                </table>
                            )}
                        </div>
                    </div>
                ) : (
                    /* 關鍵分點 (個股) 表格 */
                    <div className="bg-[#161B22] border border-gray-800 rounded-xl overflow-hidden shadow-2xl">
                        <div className="p-4 bg-[#1C2128] border-b border-gray-800 flex items-center gap-2">
                            <span className="material-symbols-outlined text-[#F9A825]">account_balance</span>
                            <h3 className="font-bold text-white">關鍵分點進出明細</h3>
                        </div>
                        <div className="overflow-x-auto">
                            {isTradesLoading ? (
                                <div className="p-12"><LoadingState text="載入分點數據中..." /></div>
                            ) : (
                                <table className="w-full text-left border-collapse">
                                    <thead className="bg-[#0E1117] text-gray-400 text-xs uppercase tracking-wider">
                                        <tr>
                                            <th className="px-6 py-4 font-semibold">日期</th>
                                            <th className="px-6 py-4 font-semibold">標的</th>
                                            <th className="px-6 py-4 font-semibold">關鍵分點</th>
                                            <th className="px-6 py-4 font-semibold text-right">買進 (張)</th>
                                            <th className="px-6 py-4 font-semibold text-right">賣出 (張)</th>
                                            <th className="px-6 py-4 font-semibold text-right">買賣超</th>
                                            <th className="px-6 py-4 font-semibold text-right">均價</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-gray-800">
                                        {trades.length > 0 ? (
                                            trades.map((trade, idx) => (
                                                <tr key={idx} className="hover:bg-[#1C2128] transition-colors group">
                                                    <td className="px-6 py-4 text-gray-400 font-mono text-sm">
                                                        {trade.snapshot_date?.includes('T') ? trade.snapshot_date.split('T')[0] : trade.snapshot_date}
                                                    </td>
                                                    <td className="px-6 py-4">
                                                        <div className="flex flex-col">
                                                            <span className="text-white font-bold">{trade.stock_name}</span>
                                                            <span className="text-gray-500 text-xs font-mono">{trade.stock_id}</span>
                                                        </div>
                                                    </td>
                                                    <td className="px-6 py-4 text-[#F9A825] font-medium">{trade.branch_name}</td>
                                                    <td className="px-6 py-4 text-right text-white font-mono">{trade.buy_vol?.toLocaleString()}</td>
                                                    <td className="px-6 py-4 text-right text-white font-mono">{trade.sell_vol?.toLocaleString()}</td>
                                                    <td className={`px-6 py-4 text-right font-mono font-bold ${trade.net_vol >= 0 ? 'text-red-400' : 'text-green-400'}`}>
                                                        {trade.net_vol >= 0 ? '+' : ''}{trade.net_vol?.toLocaleString()}
                                                    </td>
                                                    <td className="px-6 py-4 text-right text-gray-300 font-mono">
                                                        {trade.avg_buy_price > 0 ? trade.avg_buy_price.toFixed(1) : trade.avg_sell_price.toFixed(1)}
                                                    </td>
                                                </tr>
                                            ))
                                        ) : (
                                            <tr><td colSpan={7} className="px-6 py-12 text-center text-gray-600">無個股分點數據</td></tr>
                                        )}
                                    </tbody>
                                </table>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
