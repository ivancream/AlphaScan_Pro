import React, { useState, useMemo } from 'react';
import { LoadingState } from '@/components/ui/LoadingState';
import { GitMerge, ArrowLeftRight, TrendingUp, TrendingDown } from 'lucide-react';

import { API_V1_BASE } from '@/lib/apiBase';
import { QuantMetricsPanel } from '@/components/double-sword/QuantMetricsPanel';
import type { CorrelationSpreadPoint, CorrelationSpreadResponse, TopCorrelationResult } from '@/types';

// ── 型別定義 ──────────────────────────────────────────────
type CorrelationResult = TopCorrelationResult;

interface CorrelationResponse {
  stock_id: string;
  stock_name: string;
  calc_date: string;
  lookback_days: number;
  /** 僅 Pearson、未經雙刀 ADF/EG 建置表 */
  pearson_only?: boolean;
  results: CorrelationResult[];
}

type SpreadPoint = CorrelationSpreadPoint;
type SpreadResponse = CorrelationSpreadResponse;

// 相關係數的顏色判斷
function corrColor(corr: number): string {
  if (corr >= 0.9) return 'text-red-400';
  if (corr >= 0.8) return 'text-orange-400';
  if (corr >= 0.7) return 'text-yellow-400';
  return 'text-gray-400';
}

// 相關係數進度條寬度
function corrBarWidth(corr: number): string {
  return `${Math.max(0, Math.min(100, corr * 100)).toFixed(1)}%`;
}

// ── 股價比值折線圖（純 SVG） ──────────────────────────────
function SpreadChart({ series, meanFull, stdFull, meanRecent, stockA, stockB }: {
  series: SpreadPoint[];
  meanFull: number;
  stdFull: number;
  meanRecent: number;
  stockA: string;
  stockB: string;
}) {
  const W = 900;
  const H = 260;
  const PAD = { top: 20, right: 36, bottom: 40, left: 64 };

  // 確保 Y 軸範圍能涵蓋到 ±2.2 個標準差或實際極端值
  const ratios = series.map(d => d.ratio);
  const minR = Math.min(...ratios, meanFull - 2.2 * stdFull) * 0.995;
  const maxR = Math.max(...ratios, meanFull + 2.2 * stdFull) * 1.005;

  const xScale = (i: number) =>
    PAD.left + (i / (series.length - 1)) * (W - PAD.left - PAD.right);

  const yScale = (v: number) =>
    PAD.top + ((maxR - v) / (maxR - minR)) * (H - PAD.top - PAD.bottom);

  // 構建折線路徑
  const linePath = series
    .map((d, i) => `${i === 0 ? 'M' : 'L'}${xScale(i).toFixed(1)},${yScale(d.ratio).toFixed(1)}`)
    .join(' ');

  // 水平參考線
  const yFull = yScale(meanFull);
  const yRecent = yScale(meanRecent);

  // X 軸日期標籤（只顯示每 10 個）
  const xLabels = series.filter((_, i) => i % Math.ceil(series.length / 8) === 0 || i === series.length - 1);

  // Y 軸刻度
  const yTicks = 5;
  const yTickValues = Array.from({ length: yTicks }, (_, i) => minR + (maxR - minR) * (i / (yTicks - 1)));

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full"
      style={{ height: 260 }}
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* 背景格線 */}
      {yTickValues.map((tv, i) => (
        <line
          key={i}
          x1={PAD.left} y1={yScale(tv).toFixed(1)}
          x2={W - PAD.right} y2={yScale(tv).toFixed(1)}
          stroke="#1f2937" strokeWidth="1"
        />
      ))}

      {/* Y 軸刻度數字 */}
      {yTickValues.map((tv, i) => (
        <text
          key={i}
          x={PAD.left - 6}
          y={yScale(tv) + 4}
          textAnchor="end"
          fontSize="10"
          fill="#6b7280"
        >
          {tv.toFixed(3)}
        </text>
      ))}

      {/* X 軸日期 */}
      {xLabels.map((d, i) => {
        const idx = series.indexOf(d);
        return (
          <text
            key={i}
            x={xScale(idx)}
            y={H - PAD.bottom + 16}
            textAnchor="middle"
            fontSize="9"
            fill="#6b7280"
          >
            {d.date.slice(5)}
          </text>
        );
      })}

      {/* Z-Score 警戒線帶 */}
      {/* +2.0σ */}
      <line x1={PAD.left} y1={yScale(meanFull + 2 * stdFull).toFixed(1)} x2={W - PAD.right} y2={yScale(meanFull + 2 * stdFull).toFixed(1)} stroke="#ef4444" strokeWidth="1" strokeDasharray="2 4" opacity="0.5" />
      <text x={W - PAD.right + 4} y={yScale(meanFull + 2 * stdFull) + 3} fontSize="8" fill="#ef4444" opacity="0.8">+2σ</text>
      
      {/* -2.0σ */}
      <line x1={PAD.left} y1={yScale(meanFull - 2 * stdFull).toFixed(1)} x2={W - PAD.right} y2={yScale(meanFull - 2 * stdFull).toFixed(1)} stroke="#22c55e" strokeWidth="1" strokeDasharray="2 4" opacity="0.5" />
      <text x={W - PAD.right + 4} y={yScale(meanFull - 2 * stdFull) + 3} fontSize="8" fill="#22c55e" opacity="0.8">-2σ</text>

      {/* 60 日均值線（基準） */}
      <line
        x1={PAD.left} y1={yFull.toFixed(1)}
        x2={W - PAD.right} y2={yFull.toFixed(1)}
        stroke="#f97316" strokeWidth="1.5" strokeDasharray="6 3"
      />
      <text x={W - PAD.right + 4} y={yFull + 3} fontSize="9" fill="#f97316">
        均值
      </text>

      {/* 近 10 日均值線（青） */}
      <line
        x1={PAD.left} y1={yRecent.toFixed(1)}
        x2={W - PAD.right} y2={yRecent.toFixed(1)}
        stroke="#22d3ee" strokeWidth="1.5" strokeDasharray="4 4"
      />
      <text x={W - PAD.right + 4} y={yRecent + 3} fontSize="9" fill="#22d3ee">
        近期
      </text>

      {/* 比值折線 */}
      <path d={linePath} fill="none" stroke="#F9A825" strokeWidth="2" strokeLinejoin="round" />

      {/* 柱狀色塊（比回朔均值高=紅/A偏強、低=綠/B偏強） */}
      {series.map((d, i) => {
        const x = xScale(i);
        const y0 = yScale(meanFull);   // 基準：整段回朔均值
        const y1 = yScale(d.ratio);
        const color = d.above_mean ? '#ef444455' : '#22c55e55';
        return (
          <rect
            key={i}
            x={x - 3}
            y={Math.min(y0, y1)}
            width={6}
            height={Math.abs(y0 - y1)}
            fill={color}
          />
        );
      })}

      {/* 重畫折線（確保在柱狀上層） */}
      <path d={linePath} fill="none" stroke="#F9A825" strokeWidth="2" strokeLinejoin="round" />
    </svg>
  );
}


export default function CorrelationPage() {
  const [activeTab, setActiveTab] = useState<'corr' | 'spread'>('corr');

  // 相關係數查詢 state
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [data, setData] = useState<CorrelationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 配對比較 state
  const [stockA, setStockA] = useState('');
  const [stockB, setStockB] = useState('');
  const [spreadDays, setSpreadDays] = useState(60);
  const [recentDays, setRecentDays] = useState(10);
  const [spreadLoading, setSpreadLoading] = useState(false);
  const [spreadData, setSpreadData] = useState<SpreadResponse | null>(null);
  const [spreadError, setSpreadError] = useState<string | null>(null);

  const handleSearch = async (stockId: string) => {
    const sid = stockId.trim();
    if (!sid) return;

    setIsLoading(true);
    setError(null);
    setData(null);

    try {
      const res = await fetch(`${API_V1_BASE}/correlation/${sid}?top_n=10`);
      if (!res.ok) {
        const errData = await res.json().catch(() => ({ detail: '請求失敗' }));
        throw new Error(errData.detail || `HTTP ${res.status}`);
      }
      const json: CorrelationResponse = await res.json();
      setData(json);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '未知錯誤，請稍後再試');
    } finally {
      setIsLoading(false);
    }
  };

  // 點擊相關係數結果列，自動帶入配對比較
  const handleClickPeer = (peerId: string) => {
    if (data) {
      setStockA(data.stock_id);
      setStockB(peerId);
      setActiveTab('spread');
    }
  };

  const handleSpreadSearch = async () => {
    const a = stockA.trim();
    const b = stockB.trim();
    if (!a || !b) return;

    setSpreadLoading(true);
    setSpreadError(null);
    setSpreadData(null);

    try {
      const res = await fetch(
        `${API_V1_BASE}/correlation/spread?stock_a=${a}&stock_b=${b}&days=${spreadDays}&recent_days=${recentDays}`
      );
      if (!res.ok) {
        const errData = await res.json().catch(() => ({ detail: '請求失敗' }));
        throw new Error(errData.detail || `HTTP ${res.status}`);
      }
      const json: SpreadResponse = await res.json();
      setSpreadData(json);
    } catch (err: unknown) {
      setSpreadError(err instanceof Error ? err.message : '未知錯誤，請稍後再試');
    } finally {
      setSpreadLoading(false);
    }
  };

  // 計算最新比值與趨勢
  const latestSpread = spreadData ? spreadData.series[spreadData.series.length - 1] : null;
  const spreadDeviation = latestSpread && spreadData
    ? ((latestSpread.ratio - spreadData.ratio_mean_full) / spreadData.ratio_mean_full * 100)
    : null;
  const latestZScore = latestSpread ? latestSpread.z_score : null;

  return (
    <div className="p-6 space-y-6 animate-in fade-in duration-500 text-gray-200">

      {/* ── 標題區 ─────────────────────────────────────── */}
      <div className="border-b border-gray-800 pb-4">
        <h2 className="text-3xl font-bold text-white tracking-widest flex items-center gap-3">
          <span className="w-1.5 h-8 bg-[#F9A825] rounded-full inline-block"></span>
          雙刀戰法 — 相關係數分析
        </h2>
        <p className="text-gray-400 mt-2 ml-4">
          統計過去 60 個交易日 Pearson 相關係數，並支援配對走勢分歧分析。
        </p>
      </div>

      {/* ── 分頁切換 ────────────────────────────────────── */}
      <div className="flex gap-1 bg-[#0E1117] rounded-xl p-1 w-fit border border-gray-800">
        <button
          onClick={() => setActiveTab('corr')}
          className={`flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-bold transition-all ${
            activeTab === 'corr'
              ? 'bg-[#F9A825] text-black'
              : 'text-gray-400 hover:text-white'
          }`}
        >
          <GitMerge size={15} />
          相關係數排行
        </button>
        <button
          onClick={() => setActiveTab('spread')}
          className={`flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-bold transition-all ${
            activeTab === 'spread'
              ? 'bg-[#F9A825] text-black'
              : 'text-gray-400 hover:text-white'
          }`}
        >
          <ArrowLeftRight size={15} />
          配對走勢比較
        </button>
      </div>

      {/* ══ TAB 1：相關係數排行 ══════════════════════════════ */}
      {activeTab === 'corr' && (
        <div className="space-y-6">
          {/* 搜尋框 */}
          <div className="flex gap-3 items-center">
            <input
              type="text"
              placeholder="輸入股票代號..."
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch(inputValue)}
              className="bg-[#0E1117] border border-gray-700 rounded-lg px-4 py-2 text-sm text-gray-300 outline-none focus:border-[#F9A825] focus:ring-1 focus:ring-[#F9A825]/30 w-44 transition-all"
              autoFocus
            />
            <button
              onClick={() => handleSearch(inputValue)}
              disabled={isLoading}
              className="bg-[#F9A825] text-black font-bold px-4 py-2 rounded-lg text-sm hover:bg-[#f0c040] transition-colors disabled:opacity-50"
            >
              查詢
            </button>
            {data && (
              <span className="text-xs text-gray-500">點擊任一筆結果 → 自動帶入配對比較分析</span>
            )}
          </div>

          {isLoading && <div className="p-12"><LoadingState text="計算相關係數中..." /></div>}

          {error && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-6 text-red-400 text-sm">
              <span className="font-bold">查詢失敗：</span>{error}
            </div>
          )}

          {!isLoading && !error && !data && (
            <div className="flex flex-col items-center justify-center py-24 text-gray-700">
              <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" className="mb-4">
                <path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/>
              </svg>
              <p className="text-lg">輸入股票代號以查詢相關係數前 10 名</p>
            </div>
          )}

          {data && (
            <>
              <div className="flex gap-6 items-center flex-wrap">
                <div className="bg-[#161B22] border border-gray-800 rounded-xl px-6 py-4 flex flex-col gap-1">
                  <span className="text-gray-500 text-xs uppercase tracking-wider">目標股票</span>
                  <div className="flex items-baseline gap-2">
                    <span className="text-2xl font-black text-white">{data.stock_id}</span>
                    <span className="text-[#F9A825] font-medium">{data.stock_name}</span>
                  </div>
                </div>
                <div className="bg-[#161B22] border border-gray-800 rounded-xl px-6 py-4 flex flex-col gap-1">
                  <span className="text-gray-500 text-xs uppercase tracking-wider">計算基準日</span>
                  <span className="text-xl font-mono text-white">{data.calc_date}</span>
                </div>
                <div className="bg-[#161B22] border border-gray-800 rounded-xl px-6 py-4 flex flex-col gap-1">
                  <span className="text-gray-500 text-xs uppercase tracking-wider">回測區間</span>
                  <span className="text-xl font-mono text-white">{data.lookback_days} 個交易日</span>
                </div>
              </div>

              {data.pearson_only && (
                <div className="rounded-xl border border-amber-600/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-100/90">
                  此檔尚未寫入雙刀配對庫（或無通過 ADF／EG 篩選），以下為即時以日線報酬計算之{' '}
                  <strong>Pearson 相關係數</strong>
                  （共同交易日 ≥ {data.lookback_days}）。表格內 <strong>最新 Z-Score</strong> 與{' '}
                  <strong>比值 mean／std</strong> 係依近 {data.lookback_days} 日收盤價比值即時推算；若該配對另通過
                  ADF／EG 檢定，會一併顯示半衰期、綜合分等欄位。
                </div>
              )}

              <div className="bg-[#161B22] border border-gray-800 rounded-xl overflow-hidden shadow-2xl">
                <div className="p-4 bg-[#1C2128] border-b border-gray-800 flex items-center gap-2">
                  <GitMerge size={18} stroke="#F9A825" />
                  <h3 className="font-bold text-white">相關係數前 10 排行</h3>
                  <span className="ml-auto text-xs text-gray-500">Pearson Correlation · 60 個交易日收盤價</span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse">
                    <thead className="bg-[#0E1117] text-gray-400 text-xs uppercase tracking-wider">
                      <tr>
                        <th className="px-6 py-4 font-semibold w-16">排名</th>
                        <th className="px-6 py-4 font-semibold">股票代號</th>
                        <th className="px-6 py-4 font-semibold">股票名稱</th>
                        <th className="px-6 py-4 font-semibold text-right w-28">相關係數</th>
                        <th className="px-6 py-4 font-semibold w-48">相關程度</th>
                        <th className="px-6 py-4 font-semibold text-center w-32">最新 Z-Score</th>
                        <th className="px-6 py-4 font-semibold text-center w-28">配對分析</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-800">
                      {data.results.map((row) => (
                        <tr
                          key={row.peer_id}
                          className="hover:bg-[#1C2128] transition-colors"
                        >
                          <td className="px-6 py-4">
                            <span className={`font-mono font-black text-lg ${row.rank === 1 ? 'text-[#F9A825]' : row.rank <= 3 ? 'text-gray-300' : 'text-gray-600'}`}>
                              #{row.rank}
                            </span>
                          </td>
                          <td className="px-6 py-4 font-mono font-bold text-white text-sm">{row.peer_id}</td>
                          <td className="px-6 py-4 text-gray-300">{row.peer_name}</td>
                          <td className={`px-6 py-4 text-right font-mono font-black text-base ${corrColor(row.correlation)}`}>
                            {row.correlation.toFixed(4)}
                          </td>
                          <td className="px-6 py-4">
                            <div className="flex items-center gap-3">
                              <div className="flex-1 bg-gray-800 rounded-full h-1.5">
                                <div
                                  className="h-1.5 rounded-full bg-[#F9A825] transition-all duration-500"
                                  style={{ width: corrBarWidth(row.correlation) }}
                                />
                              </div>
                              <span className="text-gray-500 text-xs w-10 text-right">
                                {(row.correlation * 100).toFixed(1)}%
                              </span>
                            </div>
                          </td>
                          <td className="px-6 py-4 text-center">
                            {row.current_z_score !== undefined && row.current_z_score !== null ? (
                              <span className={`px-2 py-0.5 rounded text-sm font-bold font-mono ${
                                row.current_z_score >= 2 ? 'ring-1 ring-red-500/50 text-red-400 bg-red-500/10' :
                                row.current_z_score <= -2 ? 'ring-1 ring-green-500/50 text-green-400 bg-green-500/10' :
                                row.current_z_score > 0 ? 'text-red-400/70' : 'text-green-400/70'
                              }`}>
                                {row.current_z_score > 0 ? '+' : ''}{row.current_z_score.toFixed(2)}
                              </span>
                            ) : (
                              <span className="text-gray-600 text-sm">—</span>
                            )}
                          </td>
                          <td className="px-6 py-4 text-center">
                            <button
                              onClick={() => handleClickPeer(row.peer_id)}
                              className="bg-[#1E293B] hover:bg-[#334155] border border-gray-700 text-gray-300 hover:text-[#F9A825] text-xs px-3 py-1.5 rounded-lg transition-all font-bold"
                            >
                              分析
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="px-6 py-3 bg-[#0E1117] border-t border-gray-800 text-xs text-gray-600">
                  點擊「分析」按鈕可直接進行配對走勢比較
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {/* ══ TAB 2：配對走勢比較 ══════════════════════════════ */}
      {activeTab === 'spread' && (
        <div className="space-y-6">
          {/* 輸入區 */}
          <div className="bg-[#161B22] border border-gray-800 rounded-xl p-5">
            <div className="flex flex-wrap gap-4 items-end">
              <div className="flex flex-col gap-1">
                <label className="text-xs text-gray-500 font-black uppercase tracking-widest">股票 A（主）</label>
                <input
                  type="text"
                  placeholder="輸入股票代號..."
                  value={stockA}
                  onChange={(e) => setStockA(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSpreadSearch()}
                  className="bg-[#0E1117] border border-gray-700 rounded-lg px-4 py-2 text-sm text-gray-300 outline-none focus:border-[#F9A825] w-36 transition-all"
                />
              </div>
              <div className="text-gray-600 mb-2 text-lg font-black">/</div>
              <div className="flex flex-col gap-1">
                <label className="text-xs text-gray-500 font-black uppercase tracking-widest">股票 B（分母）</label>
                <input
                  type="text"
                  placeholder="輸入股票代號..."
                  value={stockB}
                  onChange={(e) => setStockB(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSpreadSearch()}
                  className="bg-[#0E1117] border border-gray-700 rounded-lg px-4 py-2 text-sm text-gray-300 outline-none focus:border-[#F9A825] w-36 transition-all"
                />
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-xs text-gray-500 font-black uppercase tracking-widest">回溯天數</label>
                <select
                  value={spreadDays}
                  onChange={(e) => setSpreadDays(Number(e.target.value))}
                  className="bg-[#0E1117] border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-300 outline-none focus:border-[#F9A825] transition-all"
                >
                  <option value={30}>30 交易日</option>
                  <option value={60}>60 交易日</option>
                  <option value={120}>120 交易日</option>
                </select>
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-xs text-gray-500 font-black uppercase tracking-widest">近期均值天數</label>
                <select
                  value={recentDays}
                  onChange={(e) => setRecentDays(Number(e.target.value))}
                  className="bg-[#0E1117] border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-300 outline-none focus:border-[#F9A825] transition-all"
                >
                  <option value={5}>5 天</option>
                  <option value={10}>10 天</option>
                  <option value={20}>20 天</option>
                </select>
              </div>
              <button
                onClick={handleSpreadSearch}
                disabled={spreadLoading || !stockA || !stockB}
                className="bg-[#F9A825] text-black font-bold px-6 py-2 rounded-lg text-sm hover:bg-[#f0c040] transition-colors disabled:opacity-50 mb-0.5"
              >
                開始比較
              </button>
            </div>
          </div>

          {spreadLoading && <div className="p-12"><LoadingState text="載入比值序列中..." /></div>}

          {spreadError && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-6 text-red-400 text-sm">
              <span className="font-bold">查詢失敗：</span>{spreadError}
            </div>
          )}

          {!spreadLoading && !spreadError && !spreadData && (
            <div className="flex flex-col items-center justify-center py-20 text-gray-700">
              <ArrowLeftRight size={48} strokeWidth={0.8} className="mb-4" />
              <p className="text-lg">輸入兩支股票代號，比較過去走勢的相對強弱</p>
              <p className="text-sm mt-2 text-gray-600">
                比值 = A 股收盤價 ÷ B 股收盤價 ；柱狀高於近期均值為<span className="text-red-400"> 紅（A 相對強）</span>，低於則為<span className="text-green-400"> 綠（B 相對強）</span>
              </p>
            </div>
          )}

          {spreadData && latestSpread && (
            <div className="space-y-5">
              <QuantMetricsPanel {...spreadData} />

              {/* 摘要卡片 */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="bg-[#161B22] border border-gray-800 rounded-xl p-4">
                  <div className="text-gray-500 text-xs uppercase tracking-wider mb-1">最新比值</div>
                  <div className={`text-2xl font-black font-mono ${latestSpread.above_recent ? 'text-red-400' : 'text-green-400'}`}>
                    {latestSpread.ratio.toFixed(4)}
                  </div>
                  <div className="text-gray-500 text-xs mt-1">
                    {latestSpread.date}
                  </div>
                </div>
                <div className="bg-[#161B22] border border-gray-800 rounded-xl p-4">
                  <div className="text-gray-500 text-xs uppercase tracking-wider mb-1">{spreadData.days} 日均值</div>
                  <div className="text-xl font-black font-mono text-orange-400">{spreadData.ratio_mean_full.toFixed(4)}</div>
                  <div className="text-gray-500 text-xs mt-1">整段區間基準</div>
                </div>
                <div className="bg-[#161B22] border border-gray-800 rounded-xl p-4">
                  <div className="text-gray-500 text-xs uppercase tracking-wider mb-1">近期走勢動能</div>
                  <div className="text-xl font-black font-mono text-cyan-400">{spreadData.ratio_mean_recent.toFixed(4)}</div>
                  <div className="text-gray-500 text-xs mt-1">近 {spreadData.recent_days} 日動態均值</div>
                </div>
                <div className="bg-[#161B22] border border-gray-800 rounded-xl p-4">
                  <div className="flex justify-between items-center mb-1">
                    <div className="text-gray-500 text-xs uppercase tracking-wider">Z-Score 發散指標</div>
                    {latestZScore !== null && Math.abs(latestZScore) >= 1.5 && (
                      <span className="animate-pulse bg-red-500/20 text-red-400 text-[10px] px-1.5 py-0.5 rounded border border-red-500/30">極端</span>
                    )}
                  </div>
                  <div className={`text-xl font-black font-mono flex items-center gap-1 ${latestZScore && latestZScore > 0 ? 'text-red-400' : 'text-green-400'}`}>
                    {latestZScore && latestZScore > 0 ? <TrendingUp size={18} /> : <TrendingDown size={18} />}
                    {latestZScore ? (latestZScore > 0 ? `+${latestZScore.toFixed(2)}σ` : `${latestZScore.toFixed(2)}σ`) : '—'}
                  </div>
                  <div className="text-gray-500 text-[11px] mt-1 pr-1 truncate">
                    {latestZScore && latestZScore > 2 
                      ? `高度偏離！${spreadData.stock_a} 極度偏強` 
                      : latestZScore && latestZScore < -2 
                        ? `高度偏離！${spreadData.stock_b} 極度偏強`
                        : "處於歷史正常震盪區間"}
                  </div>
                </div>
              </div>

              {/* 比值走勢圖 */}
              <div className="bg-[#161B22] border border-gray-800 rounded-xl overflow-hidden shadow-2xl">
                <div className="p-4 bg-[#1C2128] border-b border-gray-800 flex items-center gap-3">
                  <ArrowLeftRight size={18} stroke="#F9A825" />
                  <h3 className="font-bold text-white">
                    {spreadData.stock_a} <span className="text-gray-400 font-normal text-sm">{spreadData.stock_a_name}</span>
                    <span className="text-gray-600 mx-2 font-normal">/</span>
                    {spreadData.stock_b} <span className="text-gray-400 font-normal text-sm">{spreadData.stock_b_name}</span>
                    <span className="text-gray-500 ml-2 font-normal text-sm">收盤比值</span>
                  </h3>
                  <div className="ml-auto flex gap-4 text-xs text-gray-500 items-center">
                    <span><span className="inline-block w-6 h-0.5 mr-1 align-middle" style={{borderTop:'1px dashed #ef4444'}}></span>+2σ 極端值</span>
                    <span><span className="inline-block w-6 h-0.5 bg-orange-400 mr-1 align-middle" style={{borderTop:'1.5px dashed #f97316'}}></span>基準區間平均</span>
                    <span><span className="inline-block w-6 h-0.5 bg-cyan-400 mr-1 align-middle" style={{borderTop:'1.5px dashed #22d3ee'}}></span>短期動能平均</span>
                  </div>
                </div>
                <div className="p-4 bg-[#0B0E11]">
                  <SpreadChart
                    series={spreadData.series}
                    meanFull={spreadData.ratio_mean_full}
                    stdFull={spreadData.ratio_std_full}
                    meanRecent={spreadData.ratio_mean_recent}
                    stockA={spreadData.stock_a}
                    stockB={spreadData.stock_b}
                  />
                </div>
              </div>

              {/* 明細表（最後 15 筆） */}
              <div className="bg-[#161B22] border border-gray-800 rounded-xl overflow-hidden">
                <div className="p-4 bg-[#1C2128] border-b border-gray-800">
                  <h3 className="font-bold text-white text-sm">近期明細（最新 15 個交易日）</h3>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm text-left border-collapse">
                    <thead className="bg-[#0E1117] text-gray-500 text-xs uppercase">
                      <tr>
                        <th className="px-5 py-3">日期</th>
                        <th className="px-5 py-3 text-right">{spreadData.stock_a} 收盤</th>
                        <th className="px-5 py-3 text-right">{spreadData.stock_b} 收盤</th>
                        <th className="px-5 py-3 text-right">比值 (A/B)</th>
                        <th className="px-5 py-3 text-right">Z-Score</th>
                        <th className="px-5 py-3 text-center">短期動向</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-800">
                      {[...spreadData.series].reverse().slice(0, 15).map((d) => (
                        <tr key={d.date} className="hover:bg-[#1C2128] transition-colors">
                          <td className="px-5 py-3 font-mono text-gray-400">{d.date}</td>
                          <td className="px-5 py-3 text-right font-mono text-white">{d.close_a.toFixed(2)}</td>
                          <td className="px-5 py-3 text-right font-mono text-white">{d.close_b.toFixed(2)}</td>
                          <td className="px-5 py-3 text-right font-mono font-bold text-[#F9A825]">{d.ratio.toFixed(4)}</td>
                          <td className="px-5 py-3 text-right font-mono">
                            <span className={`px-2 py-0.5 rounded text-xs font-bold ${Math.abs(d.z_score) >= 2 ? 'ring-1 ring-red-500/50' : ''} ${d.z_score > 0 ? 'text-red-400' : 'text-green-400'}`}>
                              {d.z_score > 0 ? '+' : ''}{d.z_score.toFixed(2)}
                            </span>
                          </td>
                          <td className="px-5 py-3 text-center">
                            <span className={`px-2 py-0.5 rounded text-xs font-bold ${d.above_recent ? 'bg-red-500/20 text-red-400' : 'bg-green-500/20 text-green-400'}`}>
                              {d.above_recent ? 'A 偏強 (動能向上)' : 'B 偏強 (動能向下)'}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* 解讀說明 */}
              <div className="bg-[#0B1120] border border-blue-900/40 rounded-xl p-5 text-sm text-gray-400">
                <p className="font-bold text-blue-300 mb-2">配對交易解讀邏輯</p>
                <ul className="space-y-1 text-xs leading-relaxed">
                  <li>• <span className="text-white font-bold">訊號指標（Z-Score）</span>：當 Z-Score &gt; +2 或 &lt; -2 時，代表比值偏離歷史均線達到統計上的「極端狀態（機率小於5%）」，此時潛在的均值回歸（Mean Reversion）機率大增。</li>
                  <li>• <span className="text-red-400">極端高估（Z-Score &gt; 2）</span>：{spreadData.stock_a} 處於過熱極端狀況，考慮「空 A、多 B」，等待比值下跌。</li>
                  <li>• <span className="text-green-400">極端低估（Z-Score &lt; -2）</span>：{spreadData.stock_b} 處於過熱極端狀況，考慮「多 A、空 B」，等待比值反彈。</li>
                  <li>• <span className="text-cyan-400">進場時機確認（結合近期均值）</span>：當 Z-Score 處於極端狀態，且比值<span className="font-bold underline">跌破/突破近期（{spreadData.recent_days}日）均線</span>時，代表均值回歸的動能正式確認發動（避免接到正在單邊噴出的刀子）。</li>
                </ul>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
