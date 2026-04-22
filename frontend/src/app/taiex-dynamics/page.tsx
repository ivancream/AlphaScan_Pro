import React, { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { Activity, ArrowDownRight, ArrowUpRight, Gauge, LineChart, Minus } from 'lucide-react';
import { useTaiexMarketBrief } from '@/hooks/useTaiexMarketBrief';
import { LoadingState } from '@/components/ui/LoadingState';
import { toStockDetailPath } from '@/lib/stocks';

function Sparkline({ series, positive }: { series: number[]; positive: boolean | null }) {
  const w = 240;
  const h = 72;
  const path = useMemo(() => {
    if (!series.length) return '';
    const min = Math.min(...series);
    const max = Math.max(...series);
    const span = max - min || 1;
    return series
      .map((v, i) => {
        const x = series.length === 1 ? w / 2 : (i / (series.length - 1)) * w;
        const y = h - 4 - ((v - min) / span) * (h - 8);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(' ');
  }, [series]);

  if (!series.length) {
    return <div className="h-[72px] flex items-center text-xs text-gray-600">暫無分鐘走勢</div>;
  }

  const stroke =
    positive === true ? 'rgb(248 113 113)' : positive === false ? 'rgb(74 222 128)' : 'rgb(148 163 184)';

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full max-w-[280px] h-[72px]" preserveAspectRatio="none">
      <polyline fill="none" stroke={stroke} strokeWidth="1.5" points={path} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function ChgBadge({ pct, compact }: { pct: number | null | undefined; compact?: boolean }) {
  if (pct == null || Number.isNaN(pct)) {
    return <span className="text-gray-500 font-mono text-xs">—</span>;
  }
  const up = pct > 0;
  const down = pct < 0;
  const cls = up ? 'text-red-400' : down ? 'text-emerald-400' : 'text-gray-300';
  const Icon = up ? ArrowUpRight : down ? ArrowDownRight : Minus;
  return (
    <span className={`inline-flex items-center gap-0.5 font-mono font-bold ${compact ? 'text-xs' : 'text-lg gap-1'} ${cls}`}>
      {!compact && <Icon size={18} />}
      {compact && <Icon size={14} />}
      {up ? '+' : ''}
      {pct.toFixed(2)}%
    </span>
  );
}

function BiasPill({ bias }: { bias: string }) {
  const map: Record<string, string> = {
    偏多: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40',
    偏空: 'bg-rose-500/15 text-rose-300 border-rose-500/40',
    盤整: 'bg-slate-600/30 text-slate-300 border-slate-500/40',
    中性: 'bg-amber-500/10 text-amber-200 border-amber-500/35',
  };
  const cls = map[bias] ?? map.中性;
  return (
    <span className={`inline-flex items-center gap-2 px-4 py-1.5 rounded-full border text-sm font-bold tracking-widest ${cls}`}>
      <Gauge size={16} />
      大盤判讀：{bias}
    </span>
  );
}

export default function TaiexDynamicsPage() {
  const { data, isLoading, isError, error, dataUpdatedAt } = useTaiexMarketBrief(15000);

  const updatedLabel = dataUpdatedAt
    ? new Date(dataUpdatedAt).toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : '—';

  const twPositive = data?.taiex.change_pct != null ? data.taiex.change_pct > 0 : null;
  const futPositive = data?.futures.change_pct != null ? data.futures.change_pct > 0 : null;

  return (
    <div className="flex flex-col gap-6 p-6 text-gray-200 min-h-full bg-[#080D14]">
      <header className="flex flex-col lg:flex-row lg:items-end lg:justify-between gap-4 border-b border-gray-800/80 pb-4">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-widest flex items-center gap-3">
            <span className="w-1.5 h-7 bg-cyan-400 rounded-full inline-block" />
            大盤氣氛
          </h1>
          <p className="text-sm text-gray-500 mt-2 max-w-2xl">
            加權指數、台指期與主要權值股一次呈現，快速判斷多空與期現結構。
            {data ? (
              data.data_source === 'sinopac' ? (
                <>
                  表頭數字為
                  <span className="text-cyan-300/90"> 永豐 Shioaji 盤中 snapshots</span>
                  （加權 TSE001、TXF 近月、權值股批次）。
                  {data.series_source === 'yfinance' ? (
                    <> 下方走勢小圖仍為 Yahoo 1 分鐘線輔助，可能與表頭有短暫時間差。</>
                  ) : null}
                </>
              ) : (
                <>
                  目前為 Yahoo Finance 降級（常見延遲）；表頭漲跌多為
                  <span className="text-gray-400"> 日線相對前一日</span>
                  。請確認 .env 已設定 SINOPAC_API_KEY／SECRET 並重啟後端以使用永豐盤中。
                </>
              )
            ) : (
              <span className="text-gray-600">載入摘要中…</span>
            )}{' '}
            權重與貢獻度為近似值。
          </p>
        </div>
        <div className="flex flex-col items-start lg:items-end gap-2">
          {data?.market_bias != null && <BiasPill bias={data.market_bias} />}
          <span className="text-[11px] text-gray-600 font-mono">
            資料更新 {updatedLabel}
            {data?.error ? <span className="text-amber-600/90 ml-2">（部分來源異常）</span> : null}
          </span>
        </div>
      </header>

      {isLoading && (
        <div className="py-20">
          <LoadingState text="載入大盤摘要中…" />
        </div>
      )}

      {isError && (
        <div className="rounded-xl border border-red-500/30 bg-red-950/20 p-4 text-red-300 text-sm">
          無法載入大盤資料：{error instanceof Error ? error.message : String(error)}
        </div>
      )}

      {!isLoading && data && (
        <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
          {/* 加權指數 */}
          <section className="xl:col-span-5 rounded-2xl border border-gray-800 bg-[#0A0F1E] p-5 shadow-xl">
            <div className="flex items-center justify-between gap-3 mb-4">
              <h2 className="text-sm font-black text-gray-400 uppercase tracking-[0.2em] flex items-center gap-2">
                <LineChart size={16} className="text-cyan-400" />
                加權指數（TAIEX）
              </h2>
              <span className="text-[10px] text-gray-600 font-mono">^TWII · 1 分</span>
            </div>
            <div className="flex flex-wrap items-end gap-6">
              <div>
                <div className="text-4xl font-mono font-bold text-white tracking-tight">
                  {data.taiex.last != null ? data.taiex.last.toLocaleString('zh-TW', { maximumFractionDigits: 2 }) : '—'}
                </div>
                <div className="mt-2">
                  <ChgBadge pct={data.taiex.change_pct} />
                  <span className="text-xs text-gray-600 ml-2">與前一交易日收盤比較（日線）</span>
                </div>
              </div>
              <Sparkline series={data.taiex.series} positive={twPositive} />
            </div>
          </section>

          {/* 台指期 */}
          <section className="xl:col-span-4 rounded-2xl border border-gray-800 bg-[#0A0F1E] p-5 shadow-xl">
            <div className="flex items-center justify-between gap-3 mb-4">
              <h2 className="text-sm font-black text-gray-400 uppercase tracking-[0.2em] flex items-center gap-2">
                <Activity size={16} className="text-orange-400" />
                台指期（近月）
              </h2>
              <span className="text-[10px] text-gray-600 font-mono truncate max-w-[140px]" title={data.futures.symbol ?? ''}>
                {data.futures.symbol ?? '未取得代碼'}
              </span>
            </div>
            {data.futures.last == null && !data.futures.series.length ? (
              <p className="text-sm text-gray-500">無法取得期貨分鐘線（Yahoo 代碼可能變更）。仍可比對現貨與權值股。</p>
            ) : (
              <div className="flex flex-wrap items-end gap-6">
                <div>
                  <div className="text-3xl font-mono font-bold text-white">
                    {data.futures.last != null ? data.futures.last.toLocaleString('zh-TW', { maximumFractionDigits: 2 }) : '—'}
                  </div>
                  <div className="mt-2">
                    <ChgBadge pct={data.futures.change_pct} />
                  </div>
                  <div className="mt-3 text-xs text-gray-400 space-y-1">
                    <div>
                      期現價差（點）：{' '}
                      <span className="font-mono text-white">
                        {data.futures.basis_points != null
                          ? `${data.futures.basis_points > 0 ? '+' : ''}${data.futures.basis_points.toFixed(2)}`
                          : '—'}
                      </span>
                    </div>
                    <div className="text-gray-600">
                      正價差：期貨高於現貨，通常解讀為短線偏多情緒較熱。
                      {data.futures.symbol === 'IX0126.TW' && (
                        <span className="block mt-1 text-amber-600/90">
                          目前使用 TIP 台指期相關指數代碼，與加權指數刻度不同，價差僅供相對參考。
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <Sparkline series={data.futures.series} positive={futPositive} />
              </div>
            )}
          </section>

          {/* 判讀提示（右側窄欄） */}
          <aside className="xl:col-span-3 rounded-2xl border border-gray-800/90 bg-gradient-to-b from-[#0d1524] to-[#080d14] p-5 text-sm text-gray-400 leading-relaxed">
            <h3 className="text-xs font-bold text-gray-500 uppercase tracking-widest mb-3">怎麼看</h3>
            <ul className="space-y-2 list-disc list-inside marker:text-cyan-600">
              <li>加權與台指期<strong className="text-gray-300">同向走強</strong>且<strong className="text-gray-300">正價差擴大</strong> → 偏多機率較高。</li>
              <li>現貨相對弱、<strong className="text-gray-300">逆價差</strong>（期低於現）→ 留意偏空或避險買盤。</li>
              <li>下方權值股<strong className="text-gray-300">貢獻點數</strong>加總約略反映「誰在拉／殺指数」。</li>
            </ul>
            <Link
              to="/all-around"
              className="mt-5 inline-block text-xs text-cyan-500/90 hover:text-cyan-400 underline-offset-4 hover:underline"
            >
              進階：全方位流水報價 →
            </Link>
          </aside>

          {/* 權值股 */}
          <section className="xl:col-span-12 rounded-2xl border border-gray-800 bg-[#0A0F1E] overflow-hidden shadow-xl">
            <div className="px-5 py-4 border-b border-gray-800 flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-sm font-black text-gray-400 uppercase tracking-[0.2em]">
                主要權值股 · 漲跌與估算貢獻
              </h2>
              <span className="text-[10px] text-gray-600">點擊列可開個股頁</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-[10px] uppercase tracking-widest text-gray-600 border-b border-gray-800/80">
                    <th className="px-5 py-3 font-bold">代號</th>
                    <th className="px-3 py-3 font-bold">名稱</th>
                    <th className="px-3 py-3 font-bold text-right">成交</th>
                    <th className="px-3 py-3 font-bold text-right">漲跌幅</th>
                    <th className="px-3 py-3 font-bold text-right">近似權重</th>
                    <th className="px-5 py-3 font-bold text-right">估算貢獻（點）</th>
                  </tr>
                </thead>
                <tbody>
                  {data.stocks.map((row) => (
                    <tr
                      key={row.stock_id}
                      className="border-b border-gray-800/50 hover:bg-white/[0.03] transition-colors"
                    >
                      <td className="px-5 py-3 font-mono text-cyan-300/90">
                        <Link to={toStockDetailPath(row.stock_id)} className="hover:underline">
                          {row.stock_id}
                        </Link>
                      </td>
                      <td className="px-3 py-3 text-gray-200">{row.name}</td>
                      <td className="px-3 py-3 text-right font-mono text-gray-200">
                        {row.last != null ? row.last.toFixed(2) : '—'}
                      </td>
                      <td className="px-3 py-3 text-right">
                        <ChgBadge pct={row.change_pct} compact />
                      </td>
                      <td className="px-3 py-3 text-right font-mono text-gray-400">{row.weight_pct.toFixed(1)}%</td>
                      <td className="px-5 py-3 text-right font-mono text-amber-200/90">
                        {row.contrib_points != null
                          ? `${row.contrib_points > 0 ? '+' : ''}${row.contrib_points.toFixed(3)}`
                          : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
