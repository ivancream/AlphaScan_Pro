/**
 * 選股模組：使用者可調整的篩選門檻與勾選狀態（預設值等同原系統行為）。
 */

const LS_LONG = 'alphascan.selection.long.v1';
const LS_SHORT = 'alphascan.selection.short.v1';

export type LongThresholds = {
    /** 爆量表態：量比須大於此值（原預設 2） */
    minVolRatio: number;
    /** 通道擴張：上軌斜率須大於此值（原預設 0） */
    minUpperBandSlope: number;
    /** 浪子·月線斜率須大於此值 %（原預設 0.8） */
    minMonthlySlopePct: number;
    /** 浪子·布林位階須小於此值（原預設 4，即排除 ≥4） */
    maxBbLevelExclusive: number;
    /** 浪子·近 10 根日 K 高點相對收盤之跌幅(%) 須 ≥ 此值（原預設 10） */
    minDrawdownFromHighPct: number;
};

export type LongSelectionStored = {
    longFilters: { req_ma: boolean; req_vol: boolean; req_slope: boolean };
    wandererFilters: { req_slope: boolean; req_bb_level: boolean; req_drawdown: boolean };
    thresholds: LongThresholds;
};

export type ShortSelectionStored = {
    filters: {
        req_ma: boolean;
        req_slope: boolean;
        req_chips: boolean;
        req_near_band: boolean;
    };
};

export const DEFAULT_LONG_THRESHOLDS: LongThresholds = {
    minVolRatio: 2,
    minUpperBandSlope: 0,
    minMonthlySlopePct: 0.8,
    maxBbLevelExclusive: 4,
    minDrawdownFromHighPct: 10,
};

export const DEFAULT_LONG_SELECTION: LongSelectionStored = {
    longFilters: { req_ma: true, req_vol: true, req_slope: true },
    wandererFilters: { req_slope: true, req_bb_level: true, req_drawdown: true },
    thresholds: { ...DEFAULT_LONG_THRESHOLDS },
};

export const DEFAULT_SHORT_SELECTION: ShortSelectionStored = {
    filters: {
        req_ma: true,
        req_slope: true,
        req_chips: true,
        req_near_band: true,
    },
};

function isFiniteNumber(n: unknown): n is number {
    return typeof n === 'number' && Number.isFinite(n);
}

function clampThresholds(t: Partial<LongThresholds>): LongThresholds {
    const d = DEFAULT_LONG_THRESHOLDS;
    return {
        minVolRatio: isFiniteNumber(t.minVolRatio) ? Math.max(0, t.minVolRatio) : d.minVolRatio,
        minUpperBandSlope: isFiniteNumber(t.minUpperBandSlope) ? t.minUpperBandSlope : d.minUpperBandSlope,
        minMonthlySlopePct: isFiniteNumber(t.minMonthlySlopePct) ? t.minMonthlySlopePct : d.minMonthlySlopePct,
        maxBbLevelExclusive: isFiniteNumber(t.maxBbLevelExclusive) ? Math.max(0.1, t.maxBbLevelExclusive) : d.maxBbLevelExclusive,
        minDrawdownFromHighPct: isFiniteNumber(t.minDrawdownFromHighPct)
            ? Math.min(100, Math.max(0, t.minDrawdownFromHighPct))
            : d.minDrawdownFromHighPct,
    };
}

export function loadLongSelectionParams(): LongSelectionStored {
    try {
        const raw = localStorage.getItem(LS_LONG);
        if (!raw) return { ...DEFAULT_LONG_SELECTION, thresholds: { ...DEFAULT_LONG_THRESHOLDS } };
        const parsed = JSON.parse(raw) as Partial<LongSelectionStored>;
        const lf = parsed.longFilters;
        const wf = parsed.wandererFilters;
        const th = parsed.thresholds;
        return {
            longFilters: {
                req_ma: typeof lf?.req_ma === 'boolean' ? lf.req_ma : DEFAULT_LONG_SELECTION.longFilters.req_ma,
                req_vol: typeof lf?.req_vol === 'boolean' ? lf.req_vol : DEFAULT_LONG_SELECTION.longFilters.req_vol,
                req_slope: typeof lf?.req_slope === 'boolean' ? lf.req_slope : DEFAULT_LONG_SELECTION.longFilters.req_slope,
            },
            wandererFilters: {
                req_slope: typeof wf?.req_slope === 'boolean' ? wf.req_slope : DEFAULT_LONG_SELECTION.wandererFilters.req_slope,
                req_bb_level: typeof wf?.req_bb_level === 'boolean' ? wf.req_bb_level : DEFAULT_LONG_SELECTION.wandererFilters.req_bb_level,
                req_drawdown:
                    typeof wf?.req_drawdown === 'boolean'
                        ? wf.req_drawdown
                        : DEFAULT_LONG_SELECTION.wandererFilters.req_drawdown,
            },
            thresholds: clampThresholds(th ?? {}),
        };
    } catch {
        return { ...DEFAULT_LONG_SELECTION, thresholds: { ...DEFAULT_LONG_THRESHOLDS } };
    }
}

export function saveLongSelectionParams(p: LongSelectionStored): void {
    try {
        localStorage.setItem(LS_LONG, JSON.stringify(p));
    } catch {
        /* ignore quota / private mode */
    }
}

export function loadShortSelectionParams(): ShortSelectionStored {
    try {
        const raw = localStorage.getItem(LS_SHORT);
        if (!raw) return { ...DEFAULT_SHORT_SELECTION };
        const parsed = JSON.parse(raw) as Partial<ShortSelectionStored>;
        const f = parsed.filters;
        return {
            filters: {
                req_ma: typeof f?.req_ma === 'boolean' ? f.req_ma : DEFAULT_SHORT_SELECTION.filters.req_ma,
                req_slope: typeof f?.req_slope === 'boolean' ? f.req_slope : DEFAULT_SHORT_SELECTION.filters.req_slope,
                req_chips: typeof f?.req_chips === 'boolean' ? f.req_chips : DEFAULT_SHORT_SELECTION.filters.req_chips,
                req_near_band: typeof f?.req_near_band === 'boolean' ? f.req_near_band : DEFAULT_SHORT_SELECTION.filters.req_near_band,
            },
        };
    } catch {
        return { ...DEFAULT_SHORT_SELECTION };
    }
}

export function saveShortSelectionParams(p: ShortSelectionStored): void {
    try {
        localStorage.setItem(LS_SHORT, JSON.stringify(p));
    } catch {
        /* ignore */
    }
}
