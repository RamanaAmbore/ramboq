/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{html,js,svelte,ts}'],
  theme: {
    extend: {
      colors: {
        // RamboQuant public theme — navy/gold
        primary:   '#1a2744',   // deep navy
        text:      '#1e3050',   // dark blue-grey
        bg:        '#f8f9fb',   // cool off-white
        accent:    '#b8830a',   // gold
        secondary: '#2a3d60',   // mid navy
        muted:     '#5a7090',   // steel blue-grey
      },
      fontFamily: {
        sans: ['ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      backgroundColor: {
        page: '#f7f7f5',
      },
    },
  },
  plugins: [],
};
