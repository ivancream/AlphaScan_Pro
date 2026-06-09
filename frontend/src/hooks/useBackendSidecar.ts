/**
 * useBackendSidecar
 *
 * 管理 FastAPI 後端作為 Tauri sidecar 的生命週期。
 * - 僅在 Tauri 環境（桌面 App）中啟動 sidecar
 * - 瀏覽器開發時自動跳過（假設後端已手動啟動）
 * - sidecar 啟動後輪詢 /api/health，確認 FastAPI 完全就緒後才設 backendStatus = 'ready'
 *
 * 打包 sidecar 步驟（手動執行一次）：
 *   cd 專案根目錄
 *   pyinstaller backend.spec --clean
 *   copy dist\alphascan-backend.exe frontend\src-tauri\binaries\alphascan-backend-aarch64-pc-windows-msvc.exe
 */

import { useEffect, useRef } from 'react';
import { useAppStore } from '@/store/useAppStore';

const IS_TAURI = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

const HEALTH_URL = 'http://127.0.0.1:8000/api/health';
const HEALTH_INTERVAL_MS = 600;   // 每 600ms 查一次
const HEALTH_TIMEOUT_MS = 60_000; // 最多等 60 秒

/** 輪詢 /api/health，直到回傳 ready:true 或超時 */
async function waitUntilReady(signal: AbortSignal): Promise<void> {
  const deadline = Date.now() + HEALTH_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (signal.aborted) return;
    try {
      const res = await fetch(HEALTH_URL, { signal });
      if (res.ok) {
        const data = await res.json();
        if (data?.ready === true) return;
      }
    } catch {
      // 後端還沒起來，忽略 fetch 錯誤
    }
    // 等一下再試
    await new Promise<void>((resolve) => {
      const t = setTimeout(resolve, HEALTH_INTERVAL_MS);
      signal.addEventListener('abort', () => { clearTimeout(t); resolve(); }, { once: true });
    });
  }
  throw new Error(`Backend health-check timed out after ${HEALTH_TIMEOUT_MS / 1000}s`);
}

export function useBackendSidecar() {
  const setBackendStatus = useAppStore((s) => s.setBackendStatus);
  const childRef = useRef<unknown>(null);

  useEffect(() => {
    // 非 Tauri 環境（瀏覽器開發）：假設後端已手動啟動，直接標記 ready
    if (!IS_TAURI) {
      setBackendStatus('ready');
      return;
    }

    const abortController = new AbortController();
    let killed = false;

    async function startSidecar() {
      setBackendStatus('starting');
      try {
        // 1. 動態導入 Tauri shell plugin（只在 Tauri runtime 環境可用）
        const { Command } = await import('@tauri-apps/plugin-shell');

        // 2. Spawn FastAPI sidecar
        const child = await Command.sidecar('binaries/alphascan-backend').spawn();
        if (killed) {
          child.kill();
          return;
        }
        childRef.current = child;
        console.log('[sidecar] FastAPI 後端已啟動，PID:', child.pid);

        // 3. 等到 /api/health 回傳 ready:true
        await waitUntilReady(abortController.signal);

        if (!abortController.signal.aborted) {
          setBackendStatus('ready');
          console.log('[sidecar] 後端就緒，開放前端操作');
        }
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        if (!abortController.signal.aborted) {
          setBackendStatus('error', msg);
          console.error('[sidecar] 後端啟動失敗:', msg);
        }
      }
    }

    void startSidecar();

    return () => {
      killed = true;
      abortController.abort();
      if (childRef.current) {
        const child = childRef.current as { kill: () => void };
        child.kill();
        console.log('[sidecar] FastAPI 後端已關閉');
      }
    };
  }, [setBackendStatus]);
}
