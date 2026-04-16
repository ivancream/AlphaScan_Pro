'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import type { UnifiedTick } from '@/types/quote';

import { wsUrl } from '@/lib/apiBase';

type ConnectionState = 'connecting' | 'open' | 'closed' | 'error';

const RECONNECT_MS = 2500;
const MAX_TICKS = 240;

export function useStockTape(symbol: string) {
  const normalizedSymbol = useMemo(() => String(symbol ?? '').trim().toUpperCase(), [symbol]);
  const [connectionState, setConnectionState] = useState<ConnectionState>('connecting');
  const [ticks, setTicks] = useState<UnifiedTick[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<number | null>(null);

  useEffect(() => {
    if (!normalizedSymbol) return;

    const connect = () => {
      if (wsRef.current?.readyState === WebSocket.OPEN) return;

      setConnectionState('connecting');
      const params = new URLSearchParams({
        symbols: normalizedSymbol,
        include_futures: 'true',
        history_limit: '180',
      });
      const ws = new WebSocket(`${wsUrl('/ws/all-around-ticker')}?${params.toString()}`);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnectionState('open');
      };

      ws.onmessage = (event) => {
        try {
          const tick = JSON.parse(event.data) as UnifiedTick;
          setTicks((prev) => {
            const next = [tick, ...prev];
            return next.length > MAX_TICKS ? next.slice(0, MAX_TICKS) : next;
          });
        } catch {
          // ignore malformed message
        }
      };

      ws.onerror = () => {
        setConnectionState('error');
      };

      ws.onclose = () => {
        setConnectionState('closed');
        if (reconnectRef.current) {
          window.clearTimeout(reconnectRef.current);
        }
        reconnectRef.current = window.setTimeout(connect, RECONNECT_MS);
      };
    };

    connect();

    return () => {
      if (reconnectRef.current) {
        window.clearTimeout(reconnectRef.current);
      }
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [normalizedSymbol]);

  const stockTicks = useMemo(
    () => ticks.filter((tick) => tick.asset_type === '現貨' && tick.symbol === normalizedSymbol),
    [ticks, normalizedSymbol],
  );

  const futuresTicks = useMemo(
    () => ticks.filter((tick) => tick.asset_type === '期貨'),
    [ticks],
  );

  return {
    connectionState,
    stockTicks,
    futuresTicks,
    latestStockTick: stockTicks[0],
    latestFuturesTicks: futuresTicks.slice(0, 6),
  };
}
