// Chart palette. The categorical order, steps and status colours come from the validated reference palette
// (checked with the dataviz validator: adjacent CVD separation, lightness band and normal-vision floor).
// The brand teal is used for chrome and for the single highlighted series colour, not as a categorical slot,
// because it falls below the validator's chroma floor.

export interface Palette {
  dark: boolean;
  series: string[]; // categorical slots in fixed order
  text: string;
  textSecondary: string;
  grid: string;
  axis: string;
  surface: string;
  good: string;
  warning: string;
  serious: string;
  critical: string;
  ramp: string[]; // sequential, light to strong for light mode and surface to bright for dark mode
  divergingMid: string;
  reference: string; // targets and previous-period overlays
}

export const LIGHT: Palette = {
  dark: false,
  series: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
  text: "#0b1f3a",
  textSecondary: "#52514e",
  grid: "#e7e4de",
  axis: "#78746c",
  surface: "#ffffff",
  good: "#0ca30c",
  warning: "#fab219",
  serious: "#ec835a",
  critical: "#d03b3b",
  ramp: ["#cde2fb", "#86b6ef", "#3987e5", "#256abf", "#184f95", "#0d366b"],
  divergingMid: "#f0efec",
  reference: "#78746c",
};

export const DARK: Palette = {
  dark: true,
  series: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
  text: "#e6edf7",
  textSecondary: "#c3ccd9",
  grid: "#2a3c58",
  axis: "#8a98ad",
  surface: "#101c30",
  good: "#0ca30c",
  warning: "#fab219",
  serious: "#ec835a",
  critical: "#d03b3b",
  ramp: ["#16253d", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4"],
  divergingMid: "#383835",
  reference: "#8a98ad",
};

export const paletteFor = (dark: boolean): Palette => (dark ? DARK : LIGHT);

/** Provider colours stay fixed so a filter never repaints a survivor. */
export const PROVIDER_SLOT: Record<string, number> = { groq: 0, gemini: 1, cache: 2, local: 3 };
export const PLAN_SLOT: Record<string, number> = { starter: 0, professional: 1, enterprise: 2 };

export const RISK_LEVELS = ["low", "medium", "medium_high", "high"] as const;
export const RISK_LABEL: Record<string, string> = { low: "Low", medium: "Medium", medium_high: "Medium-high", high: "High" };
export const riskColor = (p: Palette, level: string) => ({ low: p.good, medium: p.warning, medium_high: p.serious, high: p.critical })[level] ?? p.axis;
