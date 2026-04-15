import { useQuery } from '@tanstack/react-query';
import axios from 'axios';

const api = axios.create({ baseURL: 'http://localhost:8000/api/v1' });

export const useFloorBounceScan = (showMode: string, requireVol: boolean, filterInactive: boolean, enabled: boolean) => {
    return useQuery({
        queryKey: ['floorBounceScan', showMode, requireVol, filterInactive],
        queryFn: async () => {
            const { data } = await api.get(`/floor-bounce/scan`, {
                params: { show_mode: showMode, require_vol: requireVol, filter_inactive: filterInactive }
            });
            return data.results;
        },
        enabled: enabled,
        staleTime: 1000 * 60 * 15,
    });
};

export const useFloorBounceChart = (stockCode: string, enabled: boolean) => {
    return useQuery({
        queryKey: ['floorBounceChart', stockCode],
        queryFn: async () => {
            const { data } = await api.get(`/floor-bounce/chart/${stockCode}`);
            return data;
        },
        enabled: enabled && !!stockCode,
        staleTime: 1000 * 60 * 15,
    });
};
