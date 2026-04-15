import { useQuery } from '@tanstack/react-query';
import axios from 'axios';

const api = axios.create({ baseURL: 'http://localhost:8000/api/v1' });

export const useSwingLong = (enabled: boolean, params?: { req_ma: boolean, req_vol: boolean, req_slope: boolean }) => {
    return useQuery({
        queryKey: ['swingLongScan', params],
        queryFn: async () => {
            const { data } = await api.get(`/swing/long`, { params });
            return data.results;
        },
        enabled: enabled,
        staleTime: 1000 * 60 * 15, // 15 min cache for heavy scanning
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
    });
};
