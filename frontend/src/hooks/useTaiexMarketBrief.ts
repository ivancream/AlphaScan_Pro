import { useQuery } from '@tanstack/react-query';
import axios from 'axios';

import { API_V1_BASE } from '@/lib/apiBase';

const api = axios.create({ baseURL: API_V1_BASE });

function buildFallbackPayload(reason?: string): TaiexOverviewPayload {
  return {
    updated_at: new Date().toISOString(),
    market_bias: '盤整',
    taiex: { last: null, change_pct: null, series: [] },
    futures: { symbol: null, last: null, change_pct: null, basis_points: null, series: [] },
    stocks: [],
    error: reason ?? 'market_brief_api_unavailable',
    data_source: 'yfinance',
    series_source: null,
  };
}

export interface IntradayStrip {
  last: number | null;
  change_pct: number | null;
  series: number[];
}

export interface FuturesStrip {
  symbol: string | null;
  last: number | null;
  change_pct: number | null;
  basis_points: number | null;
  series: number[];
}

export interface WeightStockRow {
  stock_id: string;
  name: string;
  last: number | null;
  change_pct: number | null;
  weight_pct: number;
  contrib_points: number | null;
}

export interface TaiexOverviewPayload {
  updated_at: string;
  market_bias: string;
  taiex: IntradayStrip;
  futures: FuturesStrip;
  stocks: WeightStockRow[];
  error?: string | null;
  /** sinopac = 永豐盤中 snapshots；yfinance = 降級 */
  data_source?: string;
  /** 走勢圖序列來源（可能仍為 yfinance 分鐘線） */
  series_source?: string | null;
}

/**
 * 大盤氣氛專用：單一 REST 取得加權指數、台指期、權值股彙總（不訂閱全方位 WebSocket）。
 */
export function useTaiexMarketBrief(refetchMs: number = 15000) {
  return useQuery({
    queryKey: ['taiexMarketBrief'],
    queryFn: async () => {
      try {
        const { data } = await api.get<TaiexOverviewPayload>('/market/taiex-overview');
        return data;
      } catch (err) {
        // 後端或代理短暫異常時，回傳降級結構避免整頁進入 error state。
        if (axios.isAxiosError(err)) {
          const status = err.response?.status;
          const detail =
            typeof err.response?.data === 'string'
              ? err.response.data
              : err.response?.data?.detail ?? err.message;
          return buildFallbackPayload(`market_brief_failed(status=${status ?? 'n/a'}): ${detail}`);
        }
        return buildFallbackPayload(String(err));
      }
    },
    staleTime: 8_000,
    refetchInterval: refetchMs,
    refetchOnWindowFocus: true,
    retry: 1,
  });
}
