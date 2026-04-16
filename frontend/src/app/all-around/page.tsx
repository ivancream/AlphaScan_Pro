import React, { useEffect, useState } from 'react';
import { AllAroundTicker } from '@/components/ui/AllAroundTicker';
import { useAllAroundStore } from '@/store/useAllAroundStore';

const CONNECTION_BADGE: Record<string, { label: string; cls: string }> = {
  open:         { label: '● 串流中',    cls: 'text-emerald-400' },
  connecting:   { label: '◌ 連線中...',  cls: 'text-amber-400 animate-pulse' },
  disconnected: { label: '○ 已斷線',    cls: 'text-gray-500' },
  error:        { label: '✕ 連線錯誤',   cls: 'text-red-400' },
};

/**
 * 全方位流水報價（進階）：全市場 Tick 虛擬化列表。
 * 大盤氣氛首頁已改為加權／台指期／權值股摘要，本頁保留原即時流水功能。
 */
export default function AllAroundFeedPage() {
  const ticks           = useAllAroundStore((s) => s.ticks);
  const connectionState = useAllAroundStore((s) => s.connectionState);
  const volumeThreshold = useAllAroundStore((s) => s.volumeThreshold);
  const tickCount       = useAllAroundStore((s) => s.tickCount);
  const connect         = useAllAroundStore((s) => s.connect);
  const disconnect      = useAllAroundStore((s) => s.disconnect);
  const setThreshold    = useAllAroundStore((s) => s.setVolumeThreshold);

  const [localThreshold, setLocalThreshold] = useState(volumeThreshold);

  useEffect(() => {
    connect();
    return () => { disconnect(); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const badge = CONNECTION_BADGE[connectionState] ?? CONNECTION_BADGE.disconnected;
  const largeTrades = ticks.filter((t) => t.volume >= volumeThreshold).length;

  return (
    <div className="flex flex-col h-full bg-[#080D14] text-gray-200">

      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800 bg-[#0A0F1E] shrink-0">
        <div className="flex items-center gap-4">
          <h2 className="text-lg font-bold tracking-widest text-white flex items-center gap-2">
            <span className="w-1.5 h-6 bg-cyan-400 rounded-full inline-block" />
            全方位報價監控
          </h2>
          <span className={`text-xs font-mono ${badge.cls}`}>{badge.label}</span>
        </div>

        <div className="flex items-center gap-6 text-xs font-mono text-gray-400">
          <span>
            累計 <span className="text-white font-bold">{tickCount.toLocaleString()}</span> 筆
          </span>
          <span>
            顯示 <span className="text-cyan-300 font-bold">{ticks.length}</span> / 500
          </span>
          <span>
            大單 <span className="text-yellow-300 font-bold">{largeTrades}</span> 筆
          </span>
        </div>
      </div>

      <div className="flex items-center gap-6 px-4 py-2 border-b border-gray-800/60 bg-[#0C1118] shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-400 whitespace-nowrap">大單高亮 ≥</span>
          <input
            type="range"
            min={1}
            max={500}
            value={localThreshold}
            onChange={(e) => setLocalThreshold(Number(e.target.value))}
            onMouseUp={() => setThreshold(localThreshold)}
            onTouchEnd={() => setThreshold(localThreshold)}
            className="w-36 accent-yellow-400"
          />
          <span className="text-xs font-mono text-yellow-300 w-12">
            {localThreshold} 張
          </span>
        </div>

        <div className="flex items-center gap-4 text-[10px] font-mono ml-4">
          <span><span className="text-sky-300 font-bold bg-sky-900/40 px-1 rounded">現貨</span></span>
          <span><span className="text-orange-300 font-bold bg-orange-900/40 px-1 rounded">期貨</span></span>
          <span><span className="text-red-300 font-bold bg-red-900/30 px-1 rounded">認購</span></span>
          <span><span className="text-green-300 font-bold bg-green-900/30 px-1 rounded">認售</span></span>
          <span className="ml-2 border-l border-gray-700 pl-3">成交：<span className="text-red-400">漲紅</span> / <span className="text-green-400">跌綠</span> / <span className="text-gray-300">平白</span></span>
          <span>量：<span className="text-red-400">外紅</span> / <span className="text-green-400">內綠</span></span>
          <span><span className="text-yellow-300 font-bold bg-yellow-500/10 px-1 rounded">高亮</span> = 大單</span>
        </div>

        {connectionState !== 'open' && (
          <button
            onClick={connect}
            className="ml-auto px-3 py-1 text-xs rounded bg-cyan-800 hover:bg-cyan-700 text-white transition-colors"
          >
            重新連線
          </button>
        )}
      </div>

      <div className="flex-1 overflow-hidden">
        <AllAroundTicker
          ticks={ticks}
          volumeThreshold={volumeThreshold}
          height="100%"
        />
      </div>

    </div>
  );
}
