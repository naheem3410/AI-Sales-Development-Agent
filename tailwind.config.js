/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['var(--font-sans)', 'sans-serif'],
        mono: ['var(--font-mono)', 'monospace'],
        display: ['var(--font-display)', 'sans-serif'],
      },
      colors: {
        brand: {
          50:  '#f0f4ff',
          100: '#dde6ff',
          200: '#c3d0ff',
          300: '#9db1ff',
          400: '#7287fd',
          500: '#5865f2',
          600: '#4a55e5',
          700: '#3d47cc',
          800: '#323ba5',
          900: '#2d3583',
          950: '#1c2050',
        },
        surface: {
          0:   '#ffffff',
          50:  '#f8f9fc',
          100: '#f0f2f8',
          200: '#e4e7f0',
          300: '#d0d5e8',
        },
        ink: {
          DEFAULT: '#0f1117',
          muted: '#4a4f6a',
          subtle: '#8890b0',
          ghost: '#c2c8e0',
        },
        status: {
          approved:    '#16a34a',
          review:      '#d97706',
          rejected:    '#dc2626',
          running:     '#2563eb',
          complete:    '#16a34a',
          failed:      '#dc2626',
        }
      },
      borderRadius: {
        'xl':  '0.75rem',
        '2xl': '1rem',
        '3xl': '1.5rem',
      },
      boxShadow: {
        'card':  '0 1px 3px 0 rgb(15 17 23 / 0.06), 0 1px 2px -1px rgb(15 17 23 / 0.06)',
        'card-hover': '0 4px 12px 0 rgb(15 17 23 / 0.10), 0 2px 4px -1px rgb(15 17 23 / 0.06)',
        'modal': '0 20px 60px -10px rgb(15 17 23 / 0.20)',
      },
      animation: {
        'fade-in':    'fadeIn 0.4s ease forwards',
        'slide-up':   'slideUp 0.4s ease forwards',
        'pulse-soft': 'pulseSoft 2s ease-in-out infinite',
        'spin-slow':  'spin 3s linear infinite',
      },
      keyframes: {
        fadeIn: {
          from: { opacity: '0' },
          to:   { opacity: '1' },
        },
        slideUp: {
          from: { opacity: '0', transform: 'translateY(12px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
        pulseSoft: {
          '0%, 100%': { opacity: '1' },
          '50%':      { opacity: '0.5' },
        },
      },
    },
  },
  plugins: [],
}
