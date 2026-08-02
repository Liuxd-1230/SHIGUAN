/* 史官 SHIGUAN 前端 ESLint 配置（经典 .eslintrc，兼容 ESLint 8）。
 * 目标：在保持可读性的前提下守住基本质量与无障碍红线。
 * 风格性规则多为 warn，避免阻塞；真正会引入 bug 的规则设为 error。
 */
module.exports = {
  root: true,
  env: { browser: true, es2022: true, node: true },
  parser: "@typescript-eslint/parser",
  parserOptions: {
    ecmaVersion: 2022,
    sourceType: "module",
    ecmaFeatures: { jsx: true },
  },
  settings: { react: { version: "detect" } },
  plugins: ["@typescript-eslint", "react", "react-hooks", "jsx-a11y"],
  extends: [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
    "plugin:react/recommended",
    "plugin:react-hooks/recommended",
    "plugin:jsx-a11y/recommended",
  ],
  rules: {
    // React 17+ 新 JSX 转换，无需显式 import React
    "react/react-in-jsx-scope": "off",
    "react/prop-types": "off",
    // 显式 any 在原型期允许（后续接真实解析时会收紧）
    "@typescript-eslint/no-explicit-any": "off",
    // 未使用变量：warn（与 tsconfig noUnusedLocals 互补，便于增量清理）
    "@typescript-eslint/no-unused-vars": [
      "warn",
      { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
    ],
    // Hooks 依赖：建议但不阻塞
    "react-hooks/exhaustive-deps": "warn",
  },
  overrides: [
    {
      // 测试文件放宽 any（RTL/fixture 常需 any 造型）
      files: ["**/*.test.{ts,tsx}", "src/test/**/*.ts"],
      rules: {
        "@typescript-eslint/no-explicit-any": "off",
        "react-hooks/rules-of-hooks": "off",
      },
    },
  ],
  ignorePatterns: ["dist", "node_modules", "*.log", "vt.*"],
};
