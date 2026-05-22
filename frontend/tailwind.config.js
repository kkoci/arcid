/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        arc: {
          bg: "#0b0d12",
          panel: "#11151c",
          ink: "#e7eaf2",
          dim: "#8a93a6",
          accent: "#5eead4",
          danger: "#f87171",
        },
      },
      fontFamily: {
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
