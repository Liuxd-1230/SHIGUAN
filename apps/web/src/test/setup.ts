import "@testing-library/jest-dom";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// 每个测试后清理 DOM，避免串扰。
afterEach(() => {
  cleanup();
});

// jsdom 不具备 IntersectionObserver：提供无操作桩，
// 使依赖它的组件（传记页双向滚动同步）能正常渲染。
class MockIntersectionObserver {
  constructor(_cb: IntersectionObserverCallback) {}
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }
}
// @ts-expect-error 注入测试桩
globalThis.IntersectionObserver = MockIntersectionObserver;

// jsdom 默认没有 matchMedia：提供最小实现（默认不减弱动效、非桌面）。
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

// jsdom 未实现 scrollIntoView。
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
