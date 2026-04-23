import type { CorrelationSpreadResponse } from '@/types';

type QuantMetricsPanelProps = Pick<
  CorrelationSpreadResponse,
  | 'stock_a'
  | 'stock_b'
  | 'is_cointegrated'
  | 'composite_score'
  | 'hedge_ratio'
  | 'half_life'
  | 'adf_p_value'
  | 'eg_p_value'
>;

function fmtMetric(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return 'N/A';
  return Number(v).toFixed(digits);
}

function scoreColor(score?: number): string {
  if (score === null || score === undefined || Number.isNaN(score)) return 'text-gray-400';
  if (score >= 80) return 'text-green-400';
  if (score >= 60) return 'text-yellow-400';
  return 'text-gray-300';
}

function scoreLabel(score?: number): string {
  if (score === null || score === undefined || Number.isNaN(score)) return 'N/A';
  if (score >= 80) return '極佳';
  if (score >= 60) return '良好';
  return '普通/歷史相關';
}

function pValueColor(p?: number): string {
  if (p === null || p === undefined || Number.isNaN(p)) return 'text-gray-400';
  return p < 0.05 ? 'text-green-400' : 'text-gray-400';
}

export function QuantMetricsPanel(props: QuantMetricsPanelProps) {
  const {
    stock_a,
    stock_b,
    is_cointegrated,
    composite_score,
    hedge_ratio,
    half_life,
    adf_p_value,
    eg_p_value,
  } = props;

  return (
    <div
      className={`bg-[#111827] border border-gray-800 rounded-xl p-5 shadow-xl transition-opacity ${
        is_cointegrated ? 'opacity-100' : 'opacity-75'
      }`}
    >
      <div className="flex items-center justify-between gap-3 mb-4">
        <h3 className="text-sm font-bold text-white tracking-wide">量化配對指標 (Quant Metrics)</h3>
        <span
          className={`text-xs font-bold px-2.5 py-1 rounded-full border ${
            is_cointegrated
              ? 'text-green-300 bg-green-500/15 border-green-500/40'
              : 'text-gray-300 bg-gray-500/10 border-gray-500/30'
          }`}
        >
          {is_cointegrated ? '✅ 高度協整配對' : '⚠️ 未達協整標準（僅歷史走勢）'}
        </span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <div className="bg-[#0B1220] border border-gray-800 rounded-lg p-3">
          <div className="text-[11px] text-gray-500 uppercase tracking-wider">綜合評分</div>
          <div className={`text-xl font-black ${scoreColor(composite_score)}`}>
            {fmtMetric(composite_score, 2)}
          </div>
          <div className="text-[11px] text-gray-600">評級：{scoreLabel(composite_score)}</div>
        </div>

        <div className="bg-[#0B1220] border border-gray-800 rounded-lg p-3">
          <div className="text-[11px] text-gray-500 uppercase tracking-wider">對沖比例 Beta</div>
          <div className="text-xl font-black text-cyan-300">{fmtMetric(hedge_ratio, 4)}</div>
          <div className="text-[11px] text-gray-600">
            配置參考：1 張主股 配 {fmtMetric(hedge_ratio, 2)} 張配對股
          </div>
          <div className="text-[11px] text-gray-600">
            多/空 1 張 {stock_a}，需反向 {fmtMetric(hedge_ratio, 2)} 張 {stock_b}
          </div>
        </div>

        <div className="bg-[#0B1220] border border-gray-800 rounded-lg p-3">
          <div className="text-[11px] text-gray-500 uppercase tracking-wider">半衰期</div>
          <div className="text-xl font-black text-purple-300">{fmtMetric(half_life, 2)}</div>
          <div className="text-[11px] text-gray-600">交易日</div>
        </div>

        <div className="bg-[#0B1220] border border-gray-800 rounded-lg p-3">
          <div className="text-[11px] text-gray-500 uppercase tracking-wider">ADF p-value</div>
          <div className={`text-xl font-black ${pValueColor(adf_p_value)}`}>{fmtMetric(adf_p_value, 4)}</div>
          <div className="text-[11px] text-gray-600">顯著門檻：0.05</div>
        </div>

        <div className="bg-[#0B1220] border border-gray-800 rounded-lg p-3">
          <div className="text-[11px] text-gray-500 uppercase tracking-wider">EG p-value</div>
          <div className={`text-xl font-black ${pValueColor(eg_p_value)}`}>{fmtMetric(eg_p_value, 4)}</div>
          <div className="text-[11px] text-gray-600">顯著門檻：0.05</div>
        </div>
      </div>
    </div>
  );
}

