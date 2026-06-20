/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        cis: {
          critical: "#DC2626",
          high: "#EA580C",
          moderate: "#CA8A04",
          low: "#16A34A",
        },
      },
    },
  },
  plugins: [],
};
