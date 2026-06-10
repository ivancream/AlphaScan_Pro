import { useEffect, useMemo, useRef, useState } from 'react';

import { API_V1_BASE, wsUrl } from '@/lib/apiBase';
import type {
  MonitorConnectionState,
  MonitorMicroSnapshot,
  MonitorReadyPayload,
  MonitorSignalEvent,
  MonitorSocketMessage,
  MonitorThresholds,
} from '@/types/intradayMonitor';

const MAX_EVENTS = 500;
const RECONNECT_MS = 2500;

export interface IntradayMonitorConfig extends MonitorThresholds {
  symbols: string[];
}

function normalizeSymbols(symbols: string[]): string[] {
  return Array.from(
    new Set(
      symbols
        .map((item) => String(item ?? '').trim().toUpperCase().replace('.TW', '').replace('.TWO', ''))
        .filter(Boolean),
    ),
  );
}

function buildQuery(config: IntradayMonitorConfig): string {
  const params = new URLSearchParams();
  const symbols = normalizeSymbols(config.symbols);
  if (symbols.length > 0) {
    params.set('symbols', symbols.join(','));
  }
  params.set('stock_lot_threshold', String(config.stockLotThreshold));
  params.set('warrant_lot_threshold', String(config.warrantLotThreshold));
  params.set('move_window_sec', String(config.moveWindowSec));
  params.set('move_pct_threshold', String(config.movePctThreshold));
  params.set('continuous_window_sec', String(config.continuousWindowSec));
  params.set('continuous_min_count', String(config.continuousMinCount));
  params.set('include_warrants', String(config.includeWarrants));
  params.set('max_warrants_per_stock', String(config.maxWarrantsPerStock));
  if (config.includeIndexFutures !== undefined) params.set('include_index_futures', String(config.includeIndexFutures));
  if (config.futuresLotThreshold !== undefined) params.set('futures_lot_threshold', String(config.futuresLotThreshold));
  if (config.futuresConsecutiveMinCount !== undefined) params.set('futures_consecutive_min_count', String(config.futuresConsecutiveMinCount));
  if (config.futuresConsecutiveMinVolume !== undefined) params.set('futures_consecutive_min_volume', String(config.futuresConsecutiveMinVolume));
  if (config.futuresReversalMinLots !== undefined) params.set('futures_reversal_min_lots', String(config.futuresReversalMinLots));
  if (config.futuresVwapDeviationPct !== undefined) params.set('futures_vwap_deviation_pct', String(config.futuresVwapDeviationPct));
  if (config.futuresWallLots !== undefined) params.set('futures_wall_lots', String(config.futuresWallLots));
  if (config.scalpEnabled !== undefined) params.set('scalp_enabled', String(config.scalpEnabled));
  if (config.scalpConsecutiveWindowSec !== undefined) params.set('scalp_consecutive_window_sec', String(config.scalpConsecutiveWindowSec));
  if (config.scalpConsecutiveMinCount !== undefined) params.set('scalp_consecutive_min_count', String(config.scalpConsecutiveMinCount));
  if (config.scalpConsecutiveMinVolume !== undefined) params.set('scalp_consecutive_min_volume', String(config.scalpConsecutiveMinVolume));
  if (config.scalpReversalMinLots !== undefined) params.set('scalp_reversal_min_lots', String(config.scalpReversalMinLots));
  if (config.scalpVwapDeviationPct !== undefined) params.set('scalp_vwap_deviation_pct', String(config.scalpVwapDeviationPct));
  if (config.scalpWallLots !== undefined) params.set('scalp_wall_lots', String(config.scalpWallLots));
  if (config.scalpWallAvgVolumeMultiple !== undefined) params.set('scalp_wall_avg_volume_multiple', String(config.scalpWallAvgVolumeMultiple));
  if (config.scalpNoNewExtremeSec !== undefined) params.set('scalp_no_new_extreme_sec', String(config.scalpNoNewExtremeSec));
  if (config.scalpSpoofMinLots !== undefined) params.set('scalp_spoof_min_lots', String(config.scalpSpoofMinLots));
  if (config.scalpSpoofDropPct !== undefined) params.set('scalp_spoof_drop_pct', String(config.scalpSpoofDropPct));
  return params.toString();
}

export function useIntradayMonitor(config: IntradayMonitorConfig, enabled: boolean) {
  const [events, setEvents] = useState<MonitorSignalEvent[]>([]);
  const [connectionState, setConnectionState] = useState<MonitorConnectionState>('closed');
  const [ready, setReady] = useState<MonitorReadyPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [eventCount, setEventCount] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<number | null>(null);
  const manualCloseRef = useRef(false);

  const query = useMemo(() => buildQuery(config), [config]);

  useEffect(() => {
    if (!enabled) {
      manualCloseRef.current = true;
      wsRef.current?.close();
      wsRef.current = null;
      setConnectionState('closed');
      return;
    }

    manualCloseRef.current = false;
    let cancelled = false;

    const loadReplay = async () => {
      try {
        const res = await fetch(`${API_V1_BASE}/intraday-monitor/events?limit=120`);
        if (!res.ok) return;
        const data = (await res.json()) as { items?: MonitorSignalEvent[] };
        if (cancelled || !Array.isArray(data.items)) return;
        const replayItems = data.items;
        setEvents((prev) => {
          const seen = new Set<string>();
          const merged: MonitorSignalEvent[] = [];
          for (const item of [...prev, ...replayItems]) {
            if (!item?.id || seen.has(item.id)) continue;
            seen.add(item.id);
            merged.push(item);
          }
          return merged.slice(0, MAX_EVENTS);
        });
      } catch {
        // Replay is best-effort; live Shioaji WebSocket remains primary.
      }
    };

    const clearReconnect = () => {
      if (reconnectRef.current !== null) {
        window.clearTimeout(reconnectRef.current);
        reconnectRef.current = null;
      }
    };

    const connect = () => {
      clearReconnect();
      setConnectionState('connecting');
      setError(null);

      const url = `${wsUrl('/ws/intraday-monitor')}?${query}`;
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnectionState('open');
      };

      ws.onmessage = (message) => {
        try {
          const data = JSON.parse(message.data) as MonitorSocketMessage;
          if (data.type === 'ready') {
            setReady(data.payload);
            return;
          }
          if (data.type === 'signal') {
            setEvents((prev) => [data.payload, ...prev].slice(0, MAX_EVENTS));
            setEventCount((prev) => prev + 1);
          }
        } catch {
          setError('訊號格式解析失敗');
        }
      };

      ws.onerror = () => {
        setConnectionState('error');
        setError('監控 WebSocket 發生錯誤');
      };

      ws.onclose = () => {
        setConnectionState('closed');
        if (!manualCloseRef.current) {
          reconnectRef.current = window.setTimeout(connect, RECONNECT_MS);
        }
      };
    };

    void loadReplay();
    connect();

    return () => {
      cancelled = true;
      manualCloseRef.current = true;
      clearReconnect();
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [enabled, query]);

  const clearEvents = () => {
    setEvents([]);
    setEventCount(0);
  };

  return {
    events,
    connectionState,
    ready,
    error,
    eventCount,
    clearEvents,
  };
}

export function useMonitorMicroSnapshot(symbol: string | null, enabled = true) {
  const [snapshot, setSnapshot] = useState<MonitorMicroSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!symbol || !enabled) {
      setSnapshot(null);
      return;
    }

    let cancelled = false;
    let timer: number | null = null;

    const load = async () => {
      try {
        const res = await fetch(`${API_V1_BASE}/intraday-monitor/micro/${encodeURIComponent(symbol)}`);
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        const data = (await res.json()) as MonitorMicroSnapshot;
        if (!cancelled) {
          setSnapshot(data);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : '細節資料讀取失敗');
        }
      } finally {
        if (!cancelled) {
          timer = window.setTimeout(load, 3000);
        }
      }
    };

    void load();

    return () => {
      cancelled = true;
      if (timer !== null) {
        window.clearTimeout(timer);
      }
    };
  }, [symbol, enabled]);

  return { snapshot, error };
}
