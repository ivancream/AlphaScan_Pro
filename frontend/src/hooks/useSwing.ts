import { useQuery } from '@tanstack/react-query';
import axios, { isAxiosError } from 'axios';

const SWING_SCAN_TIMEOUT_MS = 90_000;
const SWING_SCAN_MAX_RETRIES = 2;

const api = axios.create({
    baseURL: 'http://localhost:8000/api/v1',
    timeout: SWING_SCAN_TIMEOUT_MS,
});

const shouldRetrySwingScan = (failureCount: number, error: unknown): boolean => {
    if (failureCount >= SWING_SCAN_MAX_RETRIES) return false;
    if (!isAxiosError(error)) return false;

    const status = error.response?.status;
    // 4xx 視為請求參數或業務錯誤，不重試；5xx/timeout/network 重試
    if (typeof status === 'number' && status >= 400 && status < 500) return false;
    return true;
};

export const useSwingLong = (enabled: boolean, params?: { req_ma: boolean, req_vol: boolean, req_slope: boolean }) => {
    return useQuery({
        queryKey: ['swingLongScan', params],
        queryFn: async () => {
            const { data } = await api.get(`/swing/long`, { params });
            return data.results;
        },
        enabled: enabled,
        staleTime: 1000 * 60 * 15, // 15 min cache for heavy scanning
        retry: shouldRetrySwingScan,
        retryDelay: (attemptIndex) => Math.min(1500 * 2 ** attemptIndex, 8000),
    });
};

export const useSwingShort = (enabled: boolean, params?: { req_ma: boolean, req_slope: boolean, req_chips: boolean, req_near_band: boolean }) => {
    return useQuery({
        queryKey: ['swingShortScan', params],
        queryFn: async () => {
            const { data } = await api.get(`/swing/short`, { params });
            return data.results;
        },
        enabled: enabled,
        staleTime: 1000 * 60 * 15,
        retry: shouldRetrySwingScan,
        retryDelay: (attemptIndex) => Math.min(1500 * 2 ** attemptIndex, 8000),
    });
};

export const useSwingWanderer = (enabled: boolean, params?: { req_slope: boolean, req_bb_level: boolean }) => {
    return useQuery({
        queryKey: ['swingWandererScan', params],
        queryFn: async () => {
            const { data } = await api.get(`/swing/wanderer`, { params });
            return data.results;
        },
        enabled: enabled,
        staleTime: 1000 * 60 * 15,
        retry: shouldRetrySwingScan,
        retryDelay: (attemptIndex) => Math.min(1500 * 2 ** attemptIndex, 8000),
    });
};
