/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{html,js,svelte,ts}'],
  theme: {
    extend: {
      colors: {
        // RamboQuant theme colors
        primary:   '#2f4f4f',   // primaryColor — dark teal (bull logo)
        text:      '#315062',   // textColor — dark blue-grey
        bg:        '#f7f7f5',   // backgroundColor — off-white
        accent:    '#ef9309',   // orange — footer separator, highlights
        secondary: '#4a7070',   // lighter teal for hover states
        muted:     '#6b8e8e',   // muted teal for secondary text
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
