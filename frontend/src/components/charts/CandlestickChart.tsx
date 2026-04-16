import React, { useEffect, useMemo, useRef } from 'react';
import {
    createChart,
    ColorType,
    IChartApi,
    CandlestickSeries,
    LineSeries,
    HistogramSeries,
    CrosshairMode,
    ISeriesApi,
    SeriesType
} from 'lightweight-charts';
import { useHistoricalData } from '@/hooks/useHistoricalData';
import { LoadingState } from '../ui/LoadingState';
import { IndicatorType } from '@/types/chart';

interface Props {
    symbol: string;
    indicator1: IndicatorType;
    indicator2: IndicatorType;
}

type ChartDatum = {
    time: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
    ma5?: number | null;
    ma10?: number | null;
    ma20?: number | null;
    ma60?: number | null;
    bb_upper?: number | null;
    bb_lower?: number | null;
    k?: number | null;
    d?: number | null;
    rsi?: number | null;
    macd?: number | null;
    macd_signal?: number | null;
    macd_hist?: number | null;
    bias?: number | null;
    obv?: number | null;
    rs?: number | null;
    rs_ma?: number | null;
};

/** 穩定空陣列參考，避免 useEffect 依賴每次 render 都變成新 [] 而無限觸發 */
const EMPTY_CHART_DATA: ChartDatum[] = [];

function isFiniteNumber(value: number | null | undefined): value is number {
    return typeof value === 'number' && Number.isFinite(value);
}

function toLineData(points: ChartDatum[], accessor: (point: ChartDatum) => number | null | undefined) {
    return points
        .map((point) => {
            const value = accessor(point);
            return isFiniteNumber(value) ? { time: point.time, value } : null;
        })
        .filter((point): point is { time: string; value: number } => point !== null);
}

export const CandlestickChart = ({ symbol, indicator1, indicator2 }: Props) => {
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const seriesRefs = useRef<ISeriesApi<SeriesType>[]>([]);

    const { data, isLoading, isError } = useHistoricalData(symbol, 400);
    const chartData = useMemo(() => {
        const rows = data?.data;
        return (Array.isArray(rows) && rows.length > 0 ? rows : EMPTY_CHART_DATA) as ChartDatum[];
    }, [data]);

    const renderIndicator = (
        chart: IChartApi,
        type: IndicatorType,
        scaleId: string,
        margins: { top: number; bottom: number },
        points: ChartDatum[],
    ) => {
        if (type === 'None') return;

        const common = { priceScaleId: scaleId, priceLineVisible: false };
        let mainSeries: ISeriesApi<SeriesType> | null = null;

        switch (type) {
            case 'Volume': {
                const vol = chart.addSeries(HistogramSeries, { ...common, color: '#26a69a' });
                vol.setData(points.map((point) => ({
                    time: point.time,
                    value: point.volume,
                    color: point.close >= point.open ? 'rgba(244, 63, 94, 0.4)' : 'rgba(16, 185, 129, 0.4)',
                })));
                mainSeries = vol;
                break;
            }
            case 'KD': {
                const kSeries = chart.addSeries(LineSeries, { ...common, color: '#F97316', lineWidth: 2 });
                const dSeries = chart.addSeries(LineSeries, { ...common, color: '#0EA5E9', lineWidth: 2 });
                kSeries.setData(toLineData(points, (point) => point.k));
                dSeries.setData(toLineData(points, (point) => point.d));
                mainSeries = kSeries;
                seriesRefs.current.push(dSeries);
                break;
            }
            case 'MACD': {
                const hist = chart.addSeries(HistogramSeries, { ...common });
                const macdLine = chart.addSeries(LineSeries, { ...common, color: '#F43F5E', lineWidth: 2 });
                const signalLine = chart.addSeries(LineSeries, { ...common, color: '#3B82F6', lineWidth: 2 });
                hist.setData(points
                    .map((point) => isFiniteNumber(point.macd_hist)
                        ? {
                            time: point.time,
                            value: point.macd_hist,
                            color: point.macd_hist >= 0 ? 'rgba(244, 63, 94, 0.5)' : 'rgba(16, 185, 129, 0.5)',
                        }
                        : null)
                    .filter((point): point is { time: string; value: number; color: string } => point !== null));
                macdLine.setData(toLineData(points, (point) => point.macd));
                signalLine.setData(toLineData(points, (point) => point.macd_signal));
                mainSeries = hist;
                seriesRefs.current.push(macdLine, signalLine);
                break;
            }
            case 'RSI': {
                const rsi = chart.addSeries(LineSeries, { ...common, color: '#A855F7', lineWidth: 2 });
                rsi.setData(toLineData(points, (point) => point.rsi));
                mainSeries = rsi;
                break;
            }
            case 'Bias': {
                const bias = chart.addSeries(LineSeries, { ...common, color: '#FACC15', lineWidth: 2 });
                bias.setData(toLineData(points, (point) => point.bias));
                mainSeries = bias;
                break;
            }
            case 'OBV': {
                const obv = chart.addSeries(LineSeries, { ...common, color: '#2DD4BF', lineWidth: 2 });
                obv.setData(toLineData(points, (point) => point.obv));
                mainSeries = obv;
                break;
            }
            case 'RS': {
                const rs = chart.addSeries(LineSeries, { ...common, color: '#F43F5E', lineWidth: 2 });
                const rsMA = chart.addSeries(LineSeries, { ...common, color: 'rgba(244, 63, 94, 0.4)', lineWidth: 1, lineStyle: 2 });
                rs.setData(toLineData(points, (point) => point.rs));
                rsMA.setData(toLineData(points, (point) => point.rs_ma));
                mainSeries = rs;
                seriesRefs.current.push(rsMA);
                break;
            }
        }

        if (mainSeries) {
            mainSeries.priceScale().applyOptions({ scaleMargins: margins });
            seriesRefs.current.push(mainSeries);
        }
    };

    useEffect(() => {
        if (!chartContainerRef.current || chartData.length === 0) return;

        // 1. 初始化圖表
        const chart = createChart(chartContainerRef.current, {
            layout: {
                background: { type: ColorType.Solid, color: '#0B0E11' },
                textColor: '#9CA3AF',
            },
            grid: {
                vertLines: { color: '#1F2937' },
                horzLines: { color: '#1F2937' },
            },
            width: chartContainerRef.current.clientWidth,
            height: 700,
            crosshair: {
                mode: CrosshairMode.Normal,
            },
            timeScale: {
                borderColor: '#374151',
                timeVisible: true,
                rightOffset: 15,
                barSpacing: 6,
            },
        });
        chartRef.current = chart;

        // --- 主圖配置 (K線 + MA + BB) ---
        const candlestickSeries = chart.addSeries(CandlestickSeries, {
            upColor: '#F43F5E',
            downColor: '#10B981',
            borderVisible: false,
            wickUpColor: '#F43F5E',
            wickDownColor: '#10B981',
            priceLineVisible: false,
        });
        candlestickSeries.setData(chartData.map((point) => ({
            time: point.time, open: point.open, high: point.high, low: point.low, close: point.close
        })));
        seriesRefs.current.push(candlestickSeries);

        // 主圖垂直空間: 0 ~ 50%
        candlestickSeries.priceScale().applyOptions({
            scaleMargins: { top: 0.1, bottom: 0.5 },
        });

        // 均線
        const maColors: Record<5 | 10 | 20 | 60, string> = {
            5: '#EAB308',
            10: '#3B82F6',
            20: '#A855F7',
            60: '#10B981',
        };
        ([5, 10, 20, 60] as const).forEach((period) => {
            const line = chart.addSeries(LineSeries, {
                color: maColors[period],
                lineWidth: 2,
                priceLineVisible: false,
            });
            line.setData(
                toLineData(chartData, (point) => {
                    switch (period) {
                        case 5: return point.ma5;
                        case 10: return point.ma10;
                        case 20: return point.ma20;
                        case 60: return point.ma60;
                    }
                }),
            );
            seriesRefs.current.push(line);
        });

        // 布林
        const bbOptions = { color: 'rgba(255, 255, 255, 0.6)', lineWidth: 1 as const, lineStyle: 2, priceLineVisible: false };
        const bbUpper = chart.addSeries(LineSeries, bbOptions);
        const bbLower = chart.addSeries(LineSeries, bbOptions);
        bbUpper.setData(toLineData(chartData, (point) => point.bb_upper));
        bbLower.setData(toLineData(chartData, (point) => point.bb_lower));
        seriesRefs.current.push(bbUpper, bbLower);

        // --- 副圖 1 配置 (60% ~ 78%) ---
        renderIndicator(chart, indicator1, 'pane1', { top: 0.6, bottom: 0.22 }, chartData);

        // --- 副圖 2 配置 (82% ~ 100%) ---
        renderIndicator(chart, indicator2, 'pane2', { top: 0.82, bottom: 0.05 }, chartData);

        chart.timeScale().fitContent();

        const handleResize = () => {
            if (chartContainerRef.current && chartRef.current) {
                chartRef.current.applyOptions({ width: chartContainerRef.current.clientWidth });
            }
        };
        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            chartRef.current?.remove();
            seriesRefs.current = [];
        };
    }, [chartData, indicator1, indicator2]);

    if (isLoading) return <div className="h-[700px] flex items-center justify-center bg-[#0B0E11]"><LoadingState text={`正在同步行情...`} /></div>;
    if (isError) return <div className="h-[700px] flex items-center justify-center bg-[#0B0E11] text-red-500">API 連線異常</div>;

    return (
        <div className="w-full relative">
            {/* 動態指標標籤列表 */}
            <div className="absolute top-4 left-6 z-10 flex flex-col gap-1 pointer-events-none">
                <div className="flex items-baseline gap-2 mb-1">
                    <span className="text-2xl font-black text-white">{symbol}</span>
                    <span className="text-[10px] text-gray-500 font-mono tracking-tighter">TECHNICAL VERSION 4.0</span>
                </div>
                <div className="flex flex-wrap gap-x-4 gap-y-1">
                    <IndicatorTag label="MA5" color="#EAB308" />
                    <IndicatorTag label="MA10" color="#3B82F6" />
                    <IndicatorTag label="MA20" color="#A855F7" />
                    <IndicatorTag label="MA60" color="#10B981" />
                    <IndicatorTag label="BOLL" color="#FFFFFF" isDashed />
                </div>
                <div className="flex gap-4 mt-2 border-t border-gray-800 pt-1">
                    <span className="text-[10px] font-bold text-gray-400">P1: {indicator1}</span>
                    <span className="text-[10px] font-bold text-gray-400">P2: {indicator2}</span>
                </div>
            </div>

            <div ref={chartContainerRef} className="w-full" />
        </div>
    );
};

function IndicatorTag({ label, color, isDashed = false }: { label: string, color: string, isDashed?: boolean }) {
    return (
        <div className="flex items-center gap-1.5 text-[10px] text-gray-400 font-bold">
            <span className={`w-2.5 h-0.5 rounded-full`} style={{ backgroundColor: color, borderBottom: isDashed ? `1px dashed ${color}` : 'none' }}></span>
            {label}
        </div>
    );
}
