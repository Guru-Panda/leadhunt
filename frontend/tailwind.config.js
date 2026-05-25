/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // Primary indigo — kept for brand consistency
        primary: '#6366f1',
        'primary-dark': '#4f46e5',
        'primary-light': '#a5b4fc',
        // Accents for vibrancy
        accent: {
          fuchsia: '#d946ef',
          cyan:    '#06b6d4',
          amber:   '#f59e0b',
          emerald: '#10b981',
          rose:    '#f43f5e',
        },
      },
      backgroundImage: {
        'gradient-brand':  'linear-gradient(135deg, #6366f1 0%, #d946ef 100%)',
        'gradient-purple': 'linear-gradient(180deg, #f5f3ff 0%, #ffffff 100%)',
        'gradient-mesh':   'radial-gradient(at 20% 0%, rgba(99,102,241,0.08) 0%, transparent 40%), radial-gradient(at 80% 100%, rgba(217,70,239,0.06) 0%, transparent 40%)',
      },
      boxShadow: {
        'card':     '0 1px 3px 0 rgba(0,0,0,0.04), 0 1px 2px 0 rgba(0,0,0,0.02)',
        'card-lg':  '0 10px 25px -3px rgba(99,102,241,0.10), 0 4px 6px -2px rgba(0,0,0,0.04)',
        'glow':     '0 0 0 1px rgba(99,102,241,0.15), 0 8px 25px -5px rgba(99,102,241,0.25)',
      },
    },
  },
  plugins: [],
}
