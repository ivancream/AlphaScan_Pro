/**
 * 全方位報價 Zustand Store
 *
 * 設計重點（高頻場景）：
 * 1. WebSocket 連線與重連邏輯封裝在 store 內，元件只需呼叫 connect / disconnect
 * 2. 節流 (100ms flush)：每 100ms 才批次寫入 state，避免每筆 tick 觸發 re-render
 * 3. FIFO 500 上限：陣列最舊端截斷，不需頻繁 GC
 * 4. ticks 陣列排序：index 0 = 最新，符合「由上到下最新」的看盤慣例
 */
import { create } from 'zustand';
import type { UnifiedTick } from '@/types/quote';

import { wsUrl } from '@/lib/apiBase';
const MAX_TICKS     = 500;
const FLUSH_MS      = 100;   // 節流間隔
const RECONNECT_MS  = 3000;

type ConnectionState = 'disconnected' | 'connecting' | 'open' | 'error';

interface AllAroundState {
  ticks:            UnifiedTick[];
  connectionState:  ConnectionState;
  volumeThreshold:  number;   // 大單高亮門檻（張/口）
  tickCount:        number;   // 累計 tick 數（全局計數，不受 500 限制）

  setVolumeThreshold: (n: number) => void;
  connect:    () => void;
  disconnect: () => void;
}

// 模組層級變數（不放進 state，避免 Zustand 追蹤）
let _ws:             WebSocket | null = null;
let _reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let _flushTimer:     ReturnType<typeof setTimeout> | null = null;
let _pendingBatch:   UnifiedTick[] = [];   // 節流緩衝

function _clearReconnect() {
  if (_reconnectTimer) {
    clearTimeout(_reconnectTimer);
    _reconnectTimer = null;
  }
}

function _clearFlush() {
  if (_flushTimer) {
    clearTimeout(_flushTimer);
    _flushTimer = null;
  }
}

/** 將 _pendingBatch 批次寫入 state（100ms 節流觸發）*/
function _flush() {
  _flushTimer = null;
  const batch = _pendingBatch;
  _pendingBatch = [];
  if (batch.length === 0) return;

  useAllAroundStore.setState((state) => {
    // 新 ticks 插到最前方（newest-first），然後截斷到 MAX_TICKS
    const merged = [...batch.reverse(), ...state.ticks];
    return {
      ticks:     merged.length > MAX_TICKS ? merged.slice(0, MAX_TICKS) : merged,
      tickCount: state.tickCount + batch.length,
    };
  });
}

/** 接收一筆 tick，加入緩衝並排程 flush */
function _enqueueTick(tick: UnifiedTick) {
  _pendingBatch.push(tick);
  if (!_flushTimer) {
    _flushTimer = setTimeout(_flush, FLUSH_MS);
  }
}

export const useAllAroundStore = create<AllAroundState>((set, get) => ({
  ticks:           [],
  connectionState: 'disconnected',
  volumeThreshold: 50,
  tickCount:       0,

  setVolumeThreshold: (n) => set({ volumeThreshold: n }),

  connect: () => {
    if (_ws?.readyState === WebSocket.OPEN) return;
    _clearReconnect();

    set({ connectionState: 'connecting' });

    const ws = new WebSocket(wsUrl('/ws/all-around-ticker'));
    _ws = ws;

    ws.onopen = () => {
      set({ connectionState: 'open' });
    };

    ws.onmessage = (event) => {
      try {
        const tick = JSON.parse(event.data) as UnifiedTick;
        _enqueueTick(tick);
      } catch {
        // 解析失敗忽略
      }
    };

    ws.onerror = () => {
      set({ connectionState: 'error' });
    };

    ws.onclose = () => {
      set({ connectionState: 'disconnected' });
      _reconnectTimer = setTimeout(() => {
        // 只在頁面仍需連線時重連（disconnect 後 _ws 會是 null）
        if (_ws !== null) {
          get().connect();
        }
      }, RECONNECT_MS);
    };
  },

  disconnect: () => {
    _clearReconnect();
    _clearFlush();
    _pendingBatch = [];
    _ws?.close();
    _ws = null;
    set({ connectionState: 'disconnected' });
  },
}));
