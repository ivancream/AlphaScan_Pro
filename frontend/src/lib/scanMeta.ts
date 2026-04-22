/**
 * 盤中掃描 / 選股結果列：K 線基準日與「最後掃描」顯示用。
 */

export function formatTaipeiScanTime(iso: string | null | undefined): string {
    if (iso == null || iso === '') return '—';
    try {
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return String(iso);
        return d.toLocaleString('zh-TW', {
            timeZone: 'Asia/Taipei',
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false,
        });
    } catch {
        return String(iso);
    }
}

/** GET /scanner/results 的 source 欄位 */
export function scannerResultsSourceLabel(source: string | null | undefined): string {
    switch (source) {
        case 'cache':
            return '記憶體快取';
        case 'db':
            return '資料庫備援';
        case 'empty':
            return '尚無掃描資料';
        default:
            return source && source.length > 0 ? source : '—';
    }
}
