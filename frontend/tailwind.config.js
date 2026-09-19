/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"IBM Plex Sans Arabic"', '"Inter"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      colors: {
        ink: { DEFAULT: '#0d1117', soft: '#161b22', line: '#232b36' },
        brand: { 50:'#eef4ff',100:'#d9e5ff',300:'#8fb3ff',400:'#5f8dff',
                 500:'#3b6df0',600:'#2a53c8',700:'#1f3f9b' },
      },
      keyframes: {
        rise: { '0%': { opacity: 0, transform: 'translateY(6px)' },
                '100%': { opacity: 1, transform: 'none' } },
        pulseDot: { '0%,100%': { opacity: .35 }, '50%': { opacity: 1 } },
      },
      animation: { rise: 'rise .22s ease-out', pulseDot: 'pulseDot 1.2s ease-in-out infinite' },
    },
  },
  plugins: [],
}
