'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { UnifiedTick } from '@/types/quote';

import { wsUrl } from '@/lib/apiBase';

type ConnectionState = 'connecting' | 'open' | 'closed' | 'error';

const RECONNECT_MS = 2500;
/** 與畫面一致：只保留最新 N 筆，避免 state 膨脹 */
const MAX_TICKS = 50;
const FLUSH_MS = 100;

function normalizeSymbol(raw: string): string {
  const s = String(raw ?? '').trim().toUpperCase().replace(/\.(TW|TWO)$/i, '');
  return s;
}

function symbolMatches(a: string, b: string): boolean {
  const na = normalizeSymbol(a);
  const nb = normalizeSymbol(b);
  if (!na || !nb) return false;
  if (na === nb) return true;
  const da = na.replace(/\D/g, '');
  const db = nb.replace(/\D/g, '');
  return !!da && !!db && da === db;
}

/**
 * 單一個股逐筆成交（all-around WS + symbols 篩選）。
 * 以節流寫入 state，避免每筆 tick 觸發整頁重繪卡死。
 */
export function useStockTape(symbol: string) {
  const normalizedSymbol = useMemo(() => normalizeSymbol(symbol), [symbol]);
  const [connectionState, setConnectionState] = useState<ConnectionState>('connecting');
  const [ticks, setTicks] = useState<UnifiedTick[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<number | null>(null);
  const bufferRef = useRef<UnifiedTick[]>([]);
  const flushTimerRef = useRef<number | null>(null);

  const flushBuffer = useCallback(() => {
    flushTimerRef.current = null;
    const batch = bufferRef.current;
    bufferRef.current = [];
    if (batch.length === 0) return;

    setTicks((prev) => {
      const merged = [...batch.reverse(), ...prev];
      return merged.length > MAX_TICKS ? merged.slice(0, MAX_TICKS) : merged;
    });
  }, []);

  const scheduleFlush = useCallback(() => {
    if (flushTimerRef.current != null) return;
    flushTimerRef.current = window.setTimeout(flushBuffer, FLUSH_MS);
  }, [flushBuffer]);

  useEffect(() => {
    if (!normalizedSymbol) return;

    const connect = () => {
      if (wsRef.current?.readyState === WebSocket.OPEN) return;

      setConnectionState('connecting');
      const params = new URLSearchParams({
        symbols: normalizedSymbol,
        include_futures: 'false',
        history_limit: '50',
      });
      const ws = new WebSocket(`${wsUrl('/ws/all-around-ticker')}?${params.toString()}`);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnectionState('open');
      };

      ws.onmessage = (event) => {
        try {
          const tick = JSON.parse(event.data) as UnifiedTick;
          bufferRef.current.push(tick);
          scheduleFlush();
        } catch {
          // ignore malformed message
        }
      };

      ws.onerror = () => {
        setConnectionState('error');
      };

      ws.onclose = () => {
        setConnectionState('closed');
        if (wsRef.current !== ws) {
          return;
        }
        if (reconnectRef.current) {
          window.clearTimeout(reconnectRef.current);
        }
        reconnectRef.current = window.setTimeout(connect, RECONNECT_MS);
      };
    };

    connect();

    return () => {
      if (flushTimerRef.current) {
        window.clearTimeout(flushTimerRef.current);
        flushTimerRef.current = null;
      }
      bufferRef.current = [];
      if (reconnectRef.current) {
        window.clearTimeout(reconnectRef.current);
        reconnectRef.current = null;
      }
      wsRef.current?.close();
      wsRef.current = null;
      setTicks([]);
    };
  }, [normalizedSymbol, scheduleFlush]);

  const stockTicks = useMemo(
    () => ticks.filter((tick) => tick.asset_type === '現貨' && symbolMatches(tick.symbol, normalizedSymbol)),
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
