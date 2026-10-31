/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ['class'],
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        background: '#090d16',
        surface: {
          DEFAULT: '#0f172a',
          hover: '#131d35',
          active: '#182442',
          card: '#0d1527',
          subtle: '#111c33',
        },
        border: {
          DEFAULT: '#1e293b',
          subtle: '#172238',
          strong: '#334155',
        },
        risk: {
          red: {
            DEFAULT: '#ef4444',
            light: '#f87171',
            dark: '#b91c1c',
            bg: 'rgba(239, 68, 68, 0.1)',
            border: 'rgba(239, 68, 68, 0.3)',
          },
          yellow: {
            DEFAULT: '#f59e0b',
            light: '#fbbf24',
            dark: '#d97706',
            bg: 'rgba(245, 158, 11, 0.1)',
            border: 'rgba(245, 158, 11, 0.3)',
          },
          green: {
            DEFAULT: '#10b981',
            light: '#34d399',
            dark: '#059669',
            bg: 'rgba(16, 185, 129, 0.1)',
            border: 'rgba(16, 185, 129, 0.3)',
          },
          blue: {
            DEFAULT: '#38bdf8',
            light: '#7dd3fc',
            dark: '#0284c7',
            bg: 'rgba(56, 189, 248, 0.1)',
            border: 'rgba(56, 189, 248, 0.3)',
          },
        },
        brand: {
          DEFAULT: '#38bdf8',
          dark: '#0284c7',
          glow: 'rgba(56, 189, 248, 0.15)',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'Consolas', 'monospace'],
      },
      boxShadow: {
        'glow-cyan': '0 0 20px -5px rgba(56, 189, 248, 0.25)',
        'glow-red': '0 0 20px -5px rgba(239, 68, 68, 0.3)',
        'glow-green': '0 0 20px -5px rgba(16, 185, 129, 0.3)',
      },
    },
  },
  plugins: [],
}
