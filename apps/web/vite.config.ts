import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

// 把 @shiguan/save-schema 直接别名到 TS 契约源文件，
// 让 Vite 以源码方式转译（避免 node_modules 内 .ts 不被 esbuild 处理的问题）。
const saveSchemaSrc = fileURLToPath(
  new URL("../../packages/save-schema/src/types.ts", import.meta.url),
);

// fixtures/mock 目录：Mock 数据（带 FixtureEnvelope 包裹）的 JSON 由此载入。
const mockDir = fileURLToPath(new URL("../../fixtures/mock", import.meta.url));

// 同时允许 dev server 读取项目根以外的 fixture 文件。
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
    fs: {
      allow: [projectRoot],
    },
  },
  build: {
    target: "es2020",
    outDir: "dist",
  },
});
