import { useEffect, useMemo, useRef, useState } from 'react';
import {
  createChart,
  ColorType,
  IChartApi,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  CrosshairMode,
  ISeriesApi,
  SeriesType,
  type MouseEventParams,
} from 'lightweight-charts';
import { useHistoricalData } from '@/hooks/useHistoricalData';
import { LoadingState } from '../ui/LoadingState';
import { IndicatorType } from '@/types/chart';

interface Props {
  symbol: string;
  indicator1: IndicatorType;
  indicator2: IndicatorType;
  heightClassName?: string;
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

function priceDigits(value: number | null | undefined) {
  if (!isFiniteNumber(value)) return 2;
  return value < 10 ? 2 : value < 1000 ? 1 : 0;
}

function formatPrice(value: number | null | undefined) {
  if (!isFiniteNumber(value)) return '-';
  return value.toLocaleString('zh-TW', {
    minimumFractionDigits: priceDigits(value),
    maximumFractionDigits: priceDigits(value),
  });
}

function formatVolume(value: number | null | undefined) {
  if (!isFiniteNumber(value)) return '-';
  return value.toLocaleString('zh-TW');
}

export const CandlestickChart = ({ symbol, indicator1, indicator2, heightClassName = 'h-full min-h-[620px]' }: Props) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRefs = useRef<ISeriesApi<SeriesType>[]>([]);
  const [hoverDatum, setHoverDatum] = useState<ChartDatum | null>(null);

  const { data, isLoading, isError } = useHistoricalData(symbol, 400);
  const chartData = useMemo(() => {
    const rows = data?.data;
    return (Array.isArray(rows) && rows.length > 0 ? rows : EMPTY_CHART_DATA) as ChartDatum[];
  }, [data]);

  const latest = hoverDatum ?? chartData[chartData.length - 1] ?? null;
  const latestChange = latest ? latest.close - latest.open : null;
  const latestChangePct = latest && latest.open ? (latestChange! / latest.open) * 100 : null;
  const isUp = (latestChange ?? 0) >= 0;

  const renderIndicator = (
    chart: IChartApi,
    type: IndicatorType,
    scaleId: string,
    margins: { top: number; bottom: number },
    points: ChartDatum[],
  ) => {
    if (type === 'None') return;

    const common = { priceScaleId: scaleId, priceLineVisible: false, lastValueVisible: false };
    let mainSeries: ISeriesApi<SeriesType> | null = null;

    switch (type) {
      case 'Volume': {
        const vol = chart.addSeries(HistogramSeries, { ...common });
        vol.setData(points.map((point) => ({
          time: point.time,
          value: point.volume,
          color: point.close >= point.open ? 'rgba(255, 74, 74, 0.45)' : 'rgba(0, 210, 135, 0.45)',
        })));
        mainSeries = vol;
        break;
      }
      case 'KD': {
        const kSeries = chart.addSeries(LineSeries, { ...common, color: '#F4C542', lineWidth: 2 });
        const dSeries = chart.addSeries(LineSeries, { ...common, color: '#43D5FF', lineWidth: 2 });
        kSeries.setData(toLineData(points, (point) => point.k));
        dSeries.setData(toLineData(points, (point) => point.d));
        mainSeries = kSeries;
        seriesRefs.current.push(dSeries);
        break;
      }
      case 'MACD': {
        const hist = chart.addSeries(HistogramSeries, { ...common });
        const macdLine = chart.addSeries(LineSeries, { ...common, color: '#FF4A4A', lineWidth: 2 });
        const signalLine = chart.addSeries(LineSeries, { ...common, color: '#43D5FF', lineWidth: 2 });
        hist.setData(points
          .map((point) => isFiniteNumber(point.macd_hist)
            ? {
                time: point.time,
                value: point.macd_hist,
                color: point.macd_hist >= 0 ? 'rgba(255, 74, 74, 0.48)' : 'rgba(0, 210, 135, 0.48)',
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
        const rsi = chart.addSeries(LineSeries, { ...common, color: '#C084FC', lineWidth: 2 });
        rsi.setData(toLineData(points, (point) => point.rsi));
        mainSeries = rsi;
        break;
      }
      case 'Bias': {
        const bias = chart.addSeries(LineSeries, { ...common, color: '#F4C542', lineWidth: 2 });
        bias.setData(toLineData(points, (point) => point.bias));
        mainSeries = bias;
        break;
      }
      case 'OBV': {
        const obv = chart.addSeries(LineSeries, { ...common, color: '#43D5FF', lineWidth: 2 });
        obv.setData(toLineData(points, (point) => point.obv));
        mainSeries = obv;
        break;
      }
      case 'RS': {
        const rs = chart.addSeries(LineSeries, { ...common, color: '#FF4A4A', lineWidth: 2 });
        const rsMA = chart.addSeries(LineSeries, { ...common, color: 'rgba(255, 74, 74, 0.42)', lineWidth: 1, lineStyle: 2 });
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

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#12141B' },
        textColor: '#8A93A3',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(148, 163, 184, 0.08)' },
        horzLines: { color: 'rgba(148, 163, 184, 0.08)' },
      },
      width: chartContainerRef.current.clientWidth,
      height: chartContainerRef.current.clientHeight,
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: 'rgba(244, 197, 66, 0.62)',
          labelBackgroundColor: '#F4C542',
          width: 1,
          style: 3,
        },
        horzLine: {
          color: 'rgba(244, 197, 66, 0.62)',
          labelBackgroundColor: '#F4C542',
          width: 1,
          style: 3,
        },
      },
      rightPriceScale: {
        borderColor: 'rgba(148, 163, 184, 0.18)',
        scaleMargins: { top: 0.08, bottom: 0.48 },
      },
      timeScale: {
        borderColor: 'rgba(148, 163, 184, 0.18)',
        timeVisible: true,
        rightOffset: 14,
        barSpacing: 6,
      },
    });
    chartRef.current = chart;

    const candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#FF4A4A',
      downColor: '#00D287',
      borderUpColor: '#FF4A4A',
      borderDownColor: '#00D287',
      wickUpColor: '#FF8A8A',
      wickDownColor: '#7EF2C2',
      priceLineVisible: false,
      lastValueVisible: true,
    });
    candlestickSeries.setData(chartData.map((point) => ({
      time: point.time,
      open: point.open,
      high: point.high,
      low: point.low,
      close: point.close,
    })));
    seriesRefs.current.push(candlestickSeries);

    candlestickSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.08, bottom: 0.5 },
    });

    const maColors: Record<5 | 10 | 20 | 60, string> = {
      5: '#F4C542',
      10: '#43D5FF',
      20: '#C084FC',
      60: '#00D287',
    };
    ([5, 10, 20, 60] as const).forEach((period) => {
      const line = chart.addSeries(LineSeries, {
        color: maColors[period],
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      line.setData(
        toLineData(chartData, (point) => {
          switch (period) {
            case 5:
              return point.ma5;
            case 10:
              return point.ma10;
            case 20:
              return point.ma20;
            case 60:
              return point.ma60;
          }
        }),
      );
      seriesRefs.current.push(line);
    });

    const bbOptions = {
      color: 'rgba(244, 247, 251, 0.48)',
      lineWidth: 1 as const,
      lineStyle: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    };
    const bbUpper = chart.addSeries(LineSeries, bbOptions);
    const bbLower = chart.addSeries(LineSeries, bbOptions);
    bbUpper.setData(toLineData(chartData, (point) => point.bb_upper));
    bbLower.setData(toLineData(chartData, (point) => point.bb_lower));
    seriesRefs.current.push(bbUpper, bbLower);

    renderIndicator(chart, indicator1, 'pane1', { top: 0.6, bottom: 0.22 }, chartData);
    renderIndicator(chart, indicator2, 'pane2', { top: 0.82, bottom: 0.05 }, chartData);

    const dataByTime = new Map(chartData.map((point) => [point.time, point]));
    const handleCrosshairMove = (param: MouseEventParams) => {
      const time = param.time ? String(param.time) : '';
      setHoverDatum(dataByTime.get(time) ?? null);
    };
    chart.subscribeCrosshairMove(handleCrosshairMove);
    chart.timeScale().fitContent();

    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      chart.applyOptions({ width, height });
    });
    ro.observe(chartContainerRef.current);

    return () => {
      chart.unsubscribeCrosshairMove(handleCrosshairMove);
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRefs.current = [];
    };
  }, [chartData, indicator1, indicator2]);

  if (isLoading) {
    return (
      <div className={`${heightClassName} flex items-center justify-center bg-[var(--as-bg)]`}>
        <LoadingState text={`載入 ${symbol} K 線資料...`} />
      </div>
    );
  }

  if (isError) {
    return (
      <div className={`${heightClassName} flex items-center justify-center bg-[var(--as-bg)] text-red-300`}>
        K 線資料讀取失敗
      </div>
    );
  }

  return (
    <div className={`relative w-full overflow-hidden bg-[var(--as-bg)] ${heightClassName}`}>
      <div className="pointer-events-none absolute left-4 right-4 top-4 z-10 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-baseline gap-2">
            <span className="market-number text-2xl font-black text-white">{symbol}</span>
            <span className="text-[10px] font-bold uppercase tracking-[0.28em] text-[var(--as-muted)]">K Line</span>
          </div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
            <IndicatorTag label="MA5" color="#F4C542" />
            <IndicatorTag label="MA10" color="#43D5FF" />
            <IndicatorTag label="MA20" color="#C084FC" />
            <IndicatorTag label="MA60" color="#00D287" />
            <IndicatorTag label="BOLL" color="#F4F7FB" isDashed />
          </div>
        </div>

        <div className="market-card min-w-[330px] px-3 py-2">
          <div className="flex items-center justify-between gap-3">
            <span className="text-[11px] font-bold text-[var(--as-muted)]">{latest?.time ?? '-'}</span>
            <span className={`market-number text-sm font-black ${isUp ? 'text-up' : 'text-down'}`}>
              {latestChange != null ? `${latestChange >= 0 ? '+' : ''}${formatPrice(latestChange)}` : '-'}
              {latestChangePct != null ? ` (${latestChangePct >= 0 ? '+' : ''}${latestChangePct.toFixed(2)}%)` : ''}
            </span>
          </div>
          <div className="mt-2 grid grid-cols-5 gap-2 text-[10px]">
            <QuoteCell label="開" value={formatPrice(latest?.open)} />
            <QuoteCell label="高" value={formatPrice(latest?.high)} cls="text-up" />
            <QuoteCell label="低" value={formatPrice(latest?.low)} cls="text-down" />
            <QuoteCell label="收" value={formatPrice(latest?.close)} />
            <QuoteCell label="量" value={formatVolume(latest?.volume)} />
          </div>
        </div>
      </div>

      <div ref={chartContainerRef} className="h-full w-full" />
    </div>
  );
};

function IndicatorTag({ label, color, isDashed = false }: { label: string; color: string; isDashed?: boolean }) {
  return (
    <div className="flex items-center gap-1.5 text-[10px] font-bold text-slate-400">
      <span
        className="h-0.5 w-3 rounded-full"
        style={{ backgroundColor: isDashed ? 'transparent' : color, borderBottom: isDashed ? `1px dashed ${color}` : 'none' }}
      />
      {label}
    </div>
  );
}

function QuoteCell({ label, value, cls = 'text-white' }: { label: string; value: string; cls?: string }) {
  return (
    <div>
      <div className="font-semibold text-[var(--as-muted)]">{label}</div>
      <div className={`market-number mt-0.5 truncate text-xs font-black ${cls}`}>{value}</div>
    </div>
  );
}
