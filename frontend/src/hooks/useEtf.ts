import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import axios from 'axios';


const api = axios.create({ baseURL: 'http://localhost:8000/api/v1' });

export const useEtfList = () => {
    return useQuery({
        queryKey: ['etfList'],
        queryFn: async () => {
            const { data } = await api.get(`/etfs/list`);
            return data.etfs;
        },
        staleTime: Infinity,
    });
};

export const useEtfDates = (etfCode: string, enabled: boolean) => {
    return useQuery({
        queryKey: ['etfDates', etfCode],
        queryFn: async () => {
            const { data } = await api.get(`/etfs/${etfCode}/dates`);
            return data.dates;
        },
        enabled: enabled && !!etfCode,
        staleTime: 1000 * 60 * 60, // 1 hr
    });
};

export const useEtfHoldings = (etfCode: string, date: string, enabled: boolean) => {
    return useQuery({
        queryKey: ['etfHoldings', etfCode, date],
        queryFn: async () => {
            const { data } = await api.get(`/etfs/${etfCode}/holdings?date=${date}`);
            return data.holdings;
        },
        enabled: enabled && !!etfCode && !!date,
        staleTime: 1000 * 60 * 60, // 1 hr
    });
};

export const useAllEtfDates = () => {
    return useQuery({
        queryKey: ['allEtfDates'],
        queryFn: async () => {
            const { data } = await api.get(`/etfs/all/dates`);
            return data.dates;
        },
        staleTime: 1000 * 60 * 60,
    });
};

export const useEtfCrossAnalysis = (startDate: string, endDate: string, enabled: boolean) => {
    return useQuery({
        queryKey: ['etfCrossAnalysis', startDate, endDate],
        queryFn: async () => {
            const { data } = await api.get(`/etfs/cross-analysis?start_date=${startDate}&end_date=${endDate}`);
            return data;
        },
        enabled: enabled && !!startDate && !!endDate,
        staleTime: 1000 * 60 * 60,
    });
};

export const useEtfUpdate = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async ({ etfCode, targetDate }: { etfCode: string, targetDate?: string }) => {
            const dateParam = targetDate ? `?target_date=${targetDate}` : '';
            const { data } = await api.post(`/etfs/trigger-update/${etfCode}${dateParam}`);
            return data;
        },
        onSuccess: (data, variables) => {
            // Invalidate queries so that dropdown dates update
            queryClient.invalidateQueries({ queryKey: ['etfDates', variables.etfCode] });
            queryClient.invalidateQueries({ queryKey: ['allEtfDates'] });
        }
    });
};


export const useEtfUpdateAll = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: async (targetDate?: string) => {
            const dateParam = targetDate ? `?target_date=${targetDate}` : '';
            const { data } = await api.post(`/etfs/trigger-update-all${dateParam}`);
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['etfDates'] });
            queryClient.invalidateQueries({ queryKey: ['allEtfDates'] });
        }
    });
};




export const streamEtfReport = async (
    buyListCsv: string,
    sellListCsv: string,
    onChunk: (text: string) => void,
    onFinish: () => void
) => {
    try {
        const response = await fetch('http://localhost:8000/api/v1/etfs/stream-report', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                buy_list_csv: buyListCsv,
                sell_list_csv: sellListCsv
            })
        });

        if (!response.body) throw new Error('ReadableStream not supported');

        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });
            const lines = chunk.split('\n\n');
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const content = line.substring(6).replace(/<br>/g, '\n');
                    onChunk(content);
                }
            }
        }
        onFinish();
    } catch (error) {
        console.error('Stream error:', error);
        onChunk('\n[連線異常，串流中斷]');
        onFinish();
    }
};
