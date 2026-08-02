/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // ── 东方数字史馆配色（单一事实来源：src/index.css 的 :root 变量）──
      // 所有颜色以 RGB 通道形式定义，使 Tailwind 的 /opacity 修饰符可用。
      colors: {
        paper: {
          50: "rgb(var(--paper-50) / <alpha-value>)",
          100: "rgb(var(--paper-100) / <alpha-value>)",
          200: "rgb(var(--paper-200) / <alpha-value>)",
        },
        ink: {
          950: "rgb(var(--ink-950) / <alpha-value>)",
          800: "rgb(var(--ink-800) / <alpha-value>)",
          600: "rgb(var(--ink-600) / <alpha-value>)",
          400: "rgb(var(--ink-400) / <alpha-value>)",
        },
        cinnabar: {
          800: "rgb(var(--cinnabar-800) / <alpha-value>)",
          700: "rgb(var(--cinnabar-700) / <alpha-value>)",
          600: "rgb(var(--cinnabar-600) / <alpha-value>)",
        },
        gold: {
          700: "rgb(var(--gold-700) / <alpha-value>)",
          500: "rgb(var(--gold-500) / <alpha-value>)",
          300: "rgb(var(--gold-300) / <alpha-value>)",
        },
        jade: {
          700: "rgb(var(--jade-700) / <alpha-value>)",
          500: "rgb(var(--jade-500) / <alpha-value>)",
        },
        indigo: {
          700: "rgb(var(--indigo-700) / <alpha-value>)",
          500: "rgb(var(--indigo-500) / <alpha-value>)",
        },
        // 语义色：证据置信度 + 错误（不仅靠颜色，组件另配图标/形状）
        confirmed: "rgb(var(--confidence-confirmed) / <alpha-value>)",
        inferred: "rgb(var(--confidence-inferred) / <alpha-value>)",
        uncertain: "rgb(var(--confidence-uncertain) / <alpha-value>)",
        danger: "rgb(var(--color-error) / <alpha-value>)",
      },
      fontFamily: {
        serif: [
          '"Noto Serif SC"',
          '"Source Han Serif SC"',
          '"Songti SC"',
          '"STSong"',
          '"SimSun"',
          "Georgia",
          "serif",
        ],
        sans: [
          '"PingFang SC"',
          '"Microsoft YaHei"',
          '"Source Han Sans SC"',
          "system-ui",
          "-apple-system",
          "sans-serif",
        ],
      },
      borderRadius: {
        xl: "0.875rem",
        "2xl": "1.25rem",
      },
      keyframes: {
        "fade-in-up": {
          from: { opacity: "0", transform: "translateY(10px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "seal-stamp": {
          "0%": { opacity: "0", transform: "scale(1.6) rotate(-8deg)" },
          "60%": { opacity: "1", transform: "scale(0.92) rotate(2deg)" },
          "100%": { opacity: "1", transform: "scale(1) rotate(0)" },
        },
        "ink-draw": {
          from: { transform: "scaleX(0)" },
          to: { transform: "scaleX(1)" },
        },
        "slow-spin": {
          to: { transform: "rotate(360deg)" },
        },
      },
      animation: {
        "fade-in-up": "fade-in-up var(--motion-normal) var(--ease-page) both",
        "seal-stamp": "seal-stamp 480ms cubic-bezier(0.34,1.56,0.64,1) both",
        "ink-draw": "ink-draw var(--motion-ceremonial) var(--ease-soft) both",
        "slow-spin": "slow-spin 1100ms linear infinite",
      },
    },
  },
  plugins: [],
};
