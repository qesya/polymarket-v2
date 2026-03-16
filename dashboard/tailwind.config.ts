import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        surface:  '#0f1117',
        card:     '#1a1d27',
        border:   '#2a2d3a',
        muted:    '#6b7280',
        accent:   '#3b82f6',
      },
      fontFamily: { mono: ['JetBrains Mono', 'Fira Code', 'monospace'] },
    },
  },
  plugins: [],
} satisfies Config
