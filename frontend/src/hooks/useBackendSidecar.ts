/**
 * useBackendSidecar
 *
 * 管理 FastAPI 後端作為 Tauri sidecar 的生命週期。
 * - 僅在 Tauri 環境（桌面 App）中啟動 sidecar
 * - 瀏覽器開發時自動跳過（假設後端已手動啟動）
 *
 * 使用方式：在 App.tsx 的根層級呼叫此 Hook。
 *
 * 打包 sidecar 步驟（手動執行一次）：
 *   cd backend
 *   pip install pyinstaller
 *   pyinstaller ../backend.spec
 *   # 將產出的 dist/alphascan-backend.exe 複製至：
 *   # frontend/src-tauri/binaries/alphascan-backend-aarch64-pc-windows-msvc.exe
 */

import { useEffect, useRef } from 'react';

const IS_TAURI = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

export function useBackendSidecar() {
  const childRef = useRef<unknown>(null);

  useEffect(() => {
    if (!IS_TAURI) return;

    let killed = false;

    async function startSidecar() {
      try {
        const { Command } = await import('@tauri-apps/plugin-shell');
        const child = await Command.sidecar('binaries/alphascan-backend').spawn();
        if (killed) {
          child.kill();
          return;
        }
        childRef.current = child;
        console.log('[sidecar] FastAPI 後端已啟動，PID:', child.pid);
      } catch (err) {
        console.warn('[sidecar] 後端啟動失敗（可能尚未打包）:', err);
      }
    }

    void startSidecar();

    return () => {
      killed = true;
      if (childRef.current) {
        const child = childRef.current as { kill: () => void };
        child.kill();
        console.log('[sidecar] FastAPI 後端已關閉');
      }
    };
  }, []);
}
