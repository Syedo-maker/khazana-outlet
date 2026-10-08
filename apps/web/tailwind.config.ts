import type { Config } from "tailwindcss";

/**
 * Design tokens for Khazana Outlet.
 *
 * Deliberate choices, because the default Tailwind palette is what makes
 * every generated interface look the same:
 *
 * - The palette is a deep green with a warm amber accent, picked to read as
 *   a trade platform rather than a consumer discount site. No purple, no
 *   indigo, no gradients.
 * - Radii stop at 8px. Maximum rounding signals a toy.
 * - Semantic colour names only. A component never says bg-green-800, it says
 *   bg-brand, so a rebrand is one file.
 * - The type scale is small and fixed. Six sizes is enough for a dashboard
 *   and it stops hierarchy drifting per screen.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#14402f",
          hover: "#0e2e22",
          subtle: "#e8efe9",
        },
        accent: {
          DEFAULT: "#9a5b06",
          subtle: "#fdf3e2",
        },
        surface: {
          DEFAULT: "#ffffff",
          alt: "#f5f3ee",
          sunk: "#ebe7df",
        },
        ink: {
          DEFAULT: "#16211d",
          soft: "#4c5a54",
          faint: "#6e7d76",
        },
        line: "#d9d4ca",
        ok: "#1c6b45",
        warn: "#8a6100",
        danger: "#9b2226",
      },
      fontFamily: {
        // System stack: no webfont request on a slow connection. Urdu falls
        // back to the platform Nastaliq or naskh font, which is almost always
        // better than a webfont the device has to download.
        sans: [
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        urdu: ["Noto Nastaliq Urdu", "Jameel Noori Nastaleeq", "serif"],
      },
      fontSize: {
        xs: ["0.8125rem", { lineHeight: "1.4" }],
        sm: ["0.875rem", { lineHeight: "1.5" }],
        base: ["1rem", { lineHeight: "1.6" }],
        lg: ["1.125rem", { lineHeight: "1.4" }],
        xl: ["1.375rem", { lineHeight: "1.3" }],
        "2xl": ["1.75rem", { lineHeight: "1.2" }],
        "3xl": ["2.25rem", { lineHeight: "1.15" }],
      },
      borderRadius: {
        none: "0",
        sm: "2px",
        DEFAULT: "4px",
        md: "6px",
        lg: "8px",
      },
      spacing: {
        // The scale is 4px based. Nothing in this codebase uses an arbitrary
        // pixel value.
        "0.5": "0.125rem",
        "18": "4.5rem",
      },
      maxWidth: {
        prose: "68ch",
        shell: "80rem",
      },
      boxShadow: {
        // One shadow, used sparingly. Layered shadows compete with content
        // and cost frames on a low end Android device.
        card: "0 1px 2px rgba(22, 33, 29, 0.06)",
      },
      minHeight: {
        // Touch target floor. Every interactive element meets it.
        touch: "2.75rem",
      },
    },
  },
  plugins: [],
};

export default config;
