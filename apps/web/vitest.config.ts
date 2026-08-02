import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

// 复用与 vite.config.ts 相同的别名，确保测试与运行时解析一致。
const saveSchemaSrc = fileURLToPath(
  new URL("../../packages/save-schema/src/types.ts", import.meta.url),
);
const mockDir = fileURLToPath(new URL("../../fixtures/mock", import.meta.url));
const projectRoot = fileURLToPath(new URL("../..", import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@shiguan/save-schema": saveSchemaSrc,
      "@mock": mockDir,
    },
  },
  server: {
    fs: { allow: [projectRoot] },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    css: false,
  },
});
