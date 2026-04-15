import { useEffect, useRef, useMemo } from 'react';
import {
  createChart,
  ColorType,
  IChartApi,
  AreaSeries,
  CrosshairMode,
} from 'lightweight-charts';
import type { UnifiedTick } from '@/types/quote';

interface Props {
  ticks: UnifiedTick[];
  referencePrice?: number;
}

function ticksToSeriesData(ticks: UnifiedTick[]) {
  const map = new Map<string, number>();
  for (let i = ticks.length - 1; i >= 0; i--) {
    const t = ticks[i];
    map.set(t.ts, t.price);
  }
  return Array.from(map.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([time, value]) => ({ time, value }));
}

export function IntradayChart({ ticks, referencePrice }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ReturnType<IChartApi['addSeries']> | null>(null);
  const refLineRef = useRef<ReturnType<IChartApi['addSeries']> | null>(null);

  const seriesData = useMemo(() => ticksToSeriesData(ticks), [ticks]);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#0B0E11' },
        textColor: '#6B7280',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(107, 114, 128, 0.08)' },
        horzLines: { color: 'rgba(107, 114, 128, 0.08)' },
      },
      crosshair: { mode: CrosshairMode.Magnet },
      rightPriceScale: {
        borderColor: 'rgba(107, 114, 128, 0.2)',
        scaleMargins: { top: 0.08, bottom: 0.08 },
      },
      timeScale: {
        borderColor: 'rgba(107, 114, 128, 0.2)',
        timeVisible: true,
        secondsVisible: false,
      },
      handleScale: false,
      handleScroll: false,
    });
    chartRef.current = chart;

    const series = chart.addSeries(AreaSeries, {
      lineColor: '#22D3EE',
      topColor: 'rgba(34, 211, 238, 0.28)',
      bottomColor: 'rgba(34, 211, 238, 0.02)',
      lineWidth: 2,
      priceLineVisible: true,
      lastValueVisible: true,
    });
    seriesRef.current = series;

    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      chart.applyOptions({ width, height });
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      refLineRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!seriesRef.current || seriesData.length === 0) return;
    seriesRef.current.setData(seriesData as Parameters<typeof seriesRef.current.setData>[0]);
    chartRef.current?.timeScale().fitContent();
  }, [seriesData]);

  useEffect(() => {
    if (!seriesRef.current || referencePrice == null) return;
    seriesRef.current.applyOptions({
      baseLineVisible: false,
    });
    seriesRef.current.createPriceLine({
      price: referencePrice,
      color: 'rgba(234, 179, 8, 0.5)',
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: true,
      title: '平盤',
    });
  }, [referencePrice]);

  return <div ref={containerRef} className="w-full h-full min-h-[280px]" />;
}
