import { useQuery } from '@tanstack/react-query';
import axios from 'axios';

import { API_V1_BASE } from '@/lib/apiBase';

const api = axios.create({ baseURL: API_V1_BASE });

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
}

/**
 * 大盤氣氛專用：單一 REST 取得加權指數、台指期、權值股彙總（不訂閱全方位 WebSocket）。
 */
export function useTaiexMarketBrief(refetchMs: number = 15000) {
  return useQuery({
    queryKey: ['taiexMarketBrief'],
    queryFn: async () => {
      const { data } = await api.get<TaiexOverviewPayload>('/market/taiex-overview');
      return data;
    },
    staleTime: 8_000,
    refetchInterval: refetchMs,
    refetchOnWindowFocus: true,
  });
}
