/**
 * HTTP API 基底（不含 /api/v1）。
 * - 開發（Vite :1420）或後端同埠提供前端：空字串 → 走同源 /api、/ws（靠 Vite proxy 或同機）
 * - 其餘：直連 http://localhost:8000
 */
function defaultBase(): string {
    if (typeof window === 'undefined') return 'http://localhost:8000';
    const { protocol, hostname, port } = window.location;
    if (port === '1420' || port === '8000') return '';
    return `${protocol}//${hostname}:8000`;
}

export const API_BASE = import.meta.env.VITE_API_BASE ?? defaultBase();

/** axios baseURL，已含 /api/v1 */
export const API_V1_BASE = `${API_BASE}/api/v1`;

/** 組出 WebSocket 完整 URL，path 須以 / 開頭，例如 /ws/live-quotes */
export function wsUrl(path: string): string {
    if (typeof window === 'undefined') return `ws://localhost:8000${path}`;
    if (API_BASE === '') {
        const { protocol, host } = window.location;
        const wsProto = protocol === 'https:' ? 'wss:' : 'ws:';
        return `${wsProto}//${host}${path}`;
    }
    return API_BASE.replace(/^http/, 'ws') + path;
}
