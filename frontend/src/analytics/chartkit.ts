import { useSyncExternalStore } from "react";

import { paletteFor, type Palette } from "@/analytics/theme";

// ---- dark mode -----------------------------------------------------------------------------------------------

function subscribe(callback: () => void) {
  const observer = new MutationObserver(callback);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => observer.disconnect();
}
const isDark = () => document.documentElement.classList.contains("dark");

/** The palette for the current theme. Re-renders when the theme toggle changes the html class. */
export function usePalette(): Palette {
  return paletteFor(useSyncExternalStore(subscribe, isDark, () => false));
}

/** Axis, grid, tooltip and legend defaults shared by every chart. Callers add series and axes data. */
export function baseOption(p: Palette): Record<string, unknown> {
  return {
    backgroundColor: "transparent",
    textStyle: { fontFamily: "Inter Variable, Inter, system-ui, sans-serif", color: p.textSecondary },
    color: p.series,
    animationDuration: 300,
    aria: { enabled: true, decal: { show: false } },
    grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
    legend: { top: 0, type: "scroll", icon: "roundRect", itemWidth: 12, itemHeight: 8, itemGap: 16, textStyle: { color: p.textSecondary, fontSize: 12 }, inactiveColor: p.grid },
    tooltip: {
      confine: true,
      backgroundColor: p.surface,
      borderColor: p.grid,
      textStyle: { color: p.text, fontSize: 12 },
      extraCssText: "box-shadow:0 4px 16px rgba(0,0,0,.18);border-radius:8px;",
    },
  };
}

export const axisStyle = (p: Palette) => ({
  axisLine: { lineStyle: { color: p.grid } },
  axisTick: { show: false },
  axisLabel: { color: p.textSecondary, fontSize: 11 },
  splitLine: { lineStyle: { color: p.grid, width: 1 } },
  nameTextStyle: { color: p.textSecondary, fontSize: 11 },
});

