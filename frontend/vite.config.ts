import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Served by FastAPI at /app/. In `npm run dev`, API calls are proxied to the backend.
export default defineConfig({
  base: "/app/",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/lti": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
});
