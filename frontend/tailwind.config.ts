import type { Config } from "tailwindcss";

// Design tokens from PLAN.md Phase 7. Colour pairs were chosen for WCAG AA contrast (4.5:1 for text).
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["class"],
  theme: {
    container: { center: true, padding: { DEFAULT: "1rem", md: "1.5rem" }, screens: { "2xl": "1200px" } },
    extend: {
      colors: {
        navy: { DEFAULT: "#0B1F3A", 50: "#F1F4F9", 100: "#DEE5F0", 200: "#B9C7DD", 300: "#8AA0C2", 400: "#5A769F", 500: "#3A5680", 600: "#264066", 700: "#18304F", 800: "#10253F", 900: "#0B1F3A" },
        teal: { DEFAULT: "#0E7C86", 50: "#ECF8F9", 100: "#CDEDEF", 200: "#9CDADE", 500: "#13929D", 600: "#0E7C86", 700: "#0B646C", 800: "#094E55" },
        stone: { 50: "#FAF9F7", 100: "#F3F1ED", 200: "#E7E4DE", 300: "#D5D1C9", 400: "#A8A39A", 500: "#78746C", 600: "#5C5851", 700: "#45423D", 800: "#2E2C29", 900: "#1B1A18" },
        risk: { high: "#B42318", medium: "#B54708", low: "#067647" },
      },
      fontFamily: {
        sans: ['"Inter Variable"', "Inter", "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
      fontSize: {
        sm: ["0.875rem", "1.5"],
        base: ["1rem", "1.6"],
        lg: ["1.125rem", "1.6"],
        xl: ["1.5rem", "1.3"],
        "2xl": ["2rem", "1.2"],
        "3xl": ["3rem", "1.1"],
        "4xl": ["3.75rem", "1.05"],
      },
      maxWidth: { content: "1200px" },
      boxShadow: { card: "0 1px 2px rgba(11,31,58,.06), 0 8px 24px -12px rgba(11,31,58,.18)" },
    },
  },
  plugins: [],
} satisfies Config;
