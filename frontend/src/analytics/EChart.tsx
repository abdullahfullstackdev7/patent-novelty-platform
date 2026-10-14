import { BarChart, HeatmapChart, LineChart, PieChart } from "echarts/charts";
import { AriaComponent, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent, VisualMapComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef, type MutableRefObject } from "react";


echarts.use([BarChart, LineChart, PieChart, HeatmapChart, GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, VisualMapComponent, AriaComponent, CanvasRenderer]);

export type EChartsInstance = echarts.ECharts;
export type Option = echarts.EChartsCoreOption;

// ---- component -----------------------------------------------------------------------------------------------

export function EChart({
  option,
  height,
  label,
  chartRef,
}: {
  option: Option;
  height: number;
  label: string;
  chartRef?: MutableRefObject<EChartsInstance | null>;
}) {
  const host = useRef<HTMLDivElement>(null);
  const instance = useRef<EChartsInstance | null>(null);

  useEffect(() => {
    if (!host.current) return;
    const chart = echarts.init(host.current, undefined, { renderer: "canvas" });
    instance.current = chart;
    if (chartRef) chartRef.current = chart;
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(host.current);
    return () => {
      observer.disconnect();
      chart.dispose();
      instance.current = null;
      if (chartRef) chartRef.current = null;
    };
  }, [chartRef]);

  useEffect(() => {
    instance.current?.setOption(option, true);
  }, [option]);

  return <div ref={host} role="img" aria-label={label} style={{ height, width: "100%" }} />;
}
