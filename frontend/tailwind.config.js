/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        base: 'rgb(var(--color-base) / <alpha-value>)',
        surface: 'rgb(var(--color-surface) / <alpha-value>)',
        overlay: 'rgb(var(--color-overlay) / <alpha-value>)',
        muted: 'rgb(var(--color-muted) / <alpha-value>)',
        subtle: 'rgb(var(--color-subtle) / <alpha-value>)',
        'on-base': 'rgb(var(--color-text) / <alpha-value>)',
        love: 'rgb(var(--color-love) / <alpha-value>)',
        gold: 'rgb(var(--color-gold) / <alpha-value>)',
        rose: 'rgb(var(--color-rose) / <alpha-value>)',
        pine: 'rgb(var(--color-pine) / <alpha-value>)',
        foam: 'rgb(var(--color-foam) / <alpha-value>)',
        iris: 'rgb(var(--color-iris) / <alpha-value>)',
        'hl-low': 'rgb(var(--color-highlight-low) / <alpha-value>)',
        'hl-med': 'rgb(var(--color-highlight-med) / <alpha-value>)',
        'hl-high': 'rgb(var(--color-highlight-high) / <alpha-value>)',
      },
    },
  },
  plugins: [],
}
