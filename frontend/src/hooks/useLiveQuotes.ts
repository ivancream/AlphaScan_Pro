import { useEffect, useMemo, useRef, useState } from 'react';
import type { LiveQuote, LiveSocketEvent } from '@/types/quote';

type ConnectionState = 'connecting' | 'open' | 'closed' | 'error';

const WS_URL = 'ws://localhost:8000/ws/live-quotes';
const RECONNECT_MS = 2500;
const THROTTLE_MS = 500;

export function useLiveQuotes(symbols?: string[]) {
  const [connectionState, setConnectionState] = useState<ConnectionState>('connecting');
  const [quotes, setQuotes] = useState<Record<string, LiveQuote>>({});
  const [lastHeartbeat, setLastHeartbeat] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<number | null>(null);
  const bufferRef = useRef<Record<string, LiveQuote>>({});
  const throttleTimerRef = useRef<number | null>(null);
  const symbolKey = useMemo(
    () =>
      (symbols ?? [])
        .map((item) => String(item ?? '').trim().toUpperCase())
        .filter(Boolean)
        .join(','),
    [symbols],
  );

  useEffect(() => {
    const flushBufferedQuotes = () => {
      const buffered = bufferRef.current;
      if (Object.keys(buffered).length === 0) {
        return;
      }
      setQuotes((prev) => ({ ...prev, ...buffered }));
      bufferRef.current = {};
    };

    const scheduleFlush = () => {
      if (throttleTimerRef.current !== null) {
        return;
      }
      throttleTimerRef.current = window.setTimeout(() => {
        flushBufferedQuotes();
        throttleTimerRef.current = null;
      }, THROTTLE_MS);
    };

    const connect = () => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        return;
      }

      setConnectionState('connecting');
      const query = symbolKey.length > 0
        ? `?symbols=${encodeURIComponent(symbolKey)}`
        : '';
      const ws = new WebSocket(`${WS_URL}${query}`);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnectionState('open');
        setError(null);
      };

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data) as LiveSocketEvent;
          if (message.type === 'snapshot') {
            const snapshotMap = Object.fromEntries(
              message.payload.map((item) => [item.stock_id, item])
            );
            setQuotes(snapshotMap);
            return;
          }
          if (message.type === 'quote') {
            bufferRef.current[message.payload.stock_id] = message.payload;
            scheduleFlush();
            return;
          }
          if (message.type === 'heartbeat') {
            setLastHeartbeat(message.ts);
            return;
          }
          if (message.type === 'error') {
            setError(`${message.code}: ${message.message}`);
          }
        } catch {
          setError('即時報價訊息解析失敗');
        }
      };

      ws.onerror = () => {
        setConnectionState('error');
        setError('WebSocket 連線錯誤');
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
      if (throttleTimerRef.current) {
        window.clearTimeout(throttleTimerRef.current);
      }
      if (reconnectRef.current) {
        window.clearTimeout(reconnectRef.current);
      }
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [symbolKey]);

  const quoteList = useMemo(() => Object.values(quotes), [quotes]);

  return {
    connectionState,
    lastHeartbeat,
    error,
    quotesByStockId: quotes,
    quoteList,
  };
}
