import React from 'react';
import { RefreshCw, CheckCircle2, AlertCircle, Clock, Wifi } from 'lucide-react';
import { useIntradayStatus, useIntradayRefresh } from '@/hooks/useIntraday';

/**
 * 盤中即時更新控制面板
 * 
 * 功能:
 * - 顯示上次更新時間
 * - 顯示當前狀態 (idle / running / done / error)
 * - 手動觸發更新按鈕
 * - 盤中時段自動顯示狀態燈號
 */
export const IntradayRefreshBar = () => {
    const { data: status, isLoading: isStatusLoading } = useIntradayStatus();
    const { mutate: triggerRefresh, isPending } = useIntradayRefresh();

    const isRunning = status?.status === 'running' || isPending;
    const isDone = status?.status === 'done';
    const isError = status?.status === 'error';

    // 格式化上次更新時間
    const formatLastUpdated = (isoStr: string | null | undefined) => {
        if (!isoStr) return '尚未更新';
        try {
            const d = new Date(isoStr);
            return d.toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        } catch {
            return isoStr;
        }
    };

    if (isStatusLoading) return null;

    return (
        <div className="flex items-center gap-3 bg-[#161B22] border border-gray-800 rounded-lg px-4 py-2.5">

            {/* 盤中狀態指示燈 */}
            <div className="flex items-center gap-1.5">
                {status?.is_market_hours ? (
                    <Wifi size={14} className="text-green-400 animate-pulse" />
                ) : (
                    <Wifi size={14} className="text-gray-600" />
                )}
                <span className={`text-xs font-medium ${status?.is_market_hours ? 'text-green-400' : 'text-gray-500'}`}>
                    {status?.is_market_hours ? '盤中' : '收盤'}
                </span>
            </div>

            <div className="w-px h-5 bg-gray-700" />

            {/* 更新狀態 */}
            <div className="flex items-center gap-1.5">
                {isRunning ? (
                    <RefreshCw size={14} className="text-blue-400 animate-spin" />
                ) : isDone ? (
                    <CheckCircle2 size={14} className="text-green-400" />
                ) : isError ? (
                    <AlertCircle size={14} className="text-red-400" />
                ) : (
                    <Clock size={14} className="text-gray-500" />
                )}
                <span className="text-xs text-gray-400 font-mono max-w-[200px] truncate">
                    {isRunning
                        ? status?.message || '更新中...'
                        : isDone
                            ? `${status?.stocks_updated} 檔 / ${status?.elapsed_sec}s`
                            : isError
                                ? status?.message
                                : '待命中'
                    }
                </span>
            </div>

            <div className="w-px h-5 bg-gray-700" />

            {/* 上次更新時間 */}
            <span className="text-xs text-gray-500">
                {formatLastUpdated(status?.last_updated)}
            </span>

            <div className="w-px h-5 bg-gray-700" />

            {/* 手動觸發按鈕 */}
            <button
                onClick={() => triggerRefresh()}
                disabled={isRunning}
                className={`flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-bold transition-all ${
                    isRunning
                        ? 'bg-blue-900/30 text-blue-400 cursor-not-allowed border border-blue-800/50'
                        : 'bg-[#EAB308]/10 text-[#EAB308] hover:bg-[#EAB308]/20 border border-[#EAB308]/30 hover:border-[#EAB308]/60'
                }`}
                title="立即更新盤中價格資料"
            >
                <RefreshCw size={12} className={isRunning ? 'animate-spin' : ''} />
                {isRunning ? '更新中' : '立即更新'}
            </button>
        </div>
    );
};
