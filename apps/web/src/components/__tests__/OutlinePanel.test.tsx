import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import OutlinePanel from "../OutlinePanel";
import { api, type LlmHealth } from "../../lib/api";

/**
 * OutlinePanel（Phase 3A 5.11）：
 *  - 挂载只做健康探测（ping），绝不自动生成；
 *  - 点击「生成提纲」才发起生成并展示章节 / 错误提示；
 *  - 错误提示按 errorCode 给出可操作建议。
 */
const healthOk: LlmHealth = {
  configured: true,
  provider: "openai_compatible",
  baseUrlRedacted: "http://127.0.0.1:8080",
  model: "qwen",
  local: true,
  reachable: true,
  errorCode: null,
  message: null,
};

function successResult(chapters: Array<{ id: string; title: string; summary: string; eventIds: string[] }>) {
  return {
    saveId: "s1",
    characterId: "c1",
    recordId: 1,
    valid: true,
    retryCount: 0,
    warnings: [],
    outline: { profileId: "c1", style: "serious_biography", chapters },
    compressed: null,
    error: null,
    stale: false,
  };
}

beforeEach(() => {
  vi.spyOn(api, "getLlmHealth").mockResolvedValue(healthOk);
  vi.spyOn(api, "generateOutline").mockResolvedValue(
    successResult([
      { id: "c1", title: "出身", summary: "早年经历简介。", eventIds: ["e1"] },
      { id: "c2", title: "巅峰", summary: "立业与传家。", eventIds: ["e2", "e3"] },
    ]),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("OutlinePanel", () => {
  it("挂载时只探测模型健康，不自动调用生成", async () => {
    render(<OutlinePanel saveId="s1" characterId="c1" />);
    expect(await screen.findByText(/openai_compatible/)).toBeInTheDocument();
    expect(api.getLlmHealth).toHaveBeenCalledTimes(1);
    expect(api.generateOutline).not.toHaveBeenCalled();
    expect(screen.queryByText("生成中…")).not.toBeInTheDocument();
  });

  it("点击「生成提纲」→ 携带当前设置 POST → 展示章节", async () => {
    render(<OutlinePanel saveId="s1" characterId="c1" />);
    fireEvent.click(screen.getByRole("button", { name: "生成提纲" }));
    expect(await screen.findByText(/出身/)).toBeInTheDocument();
    expect(screen.getByText(/巅峰/)).toBeInTheDocument();
    expect(screen.getByText("e3")).toBeInTheDocument();
    expect(api.generateOutline).toHaveBeenCalledWith(
      "s1",
      "c1",
      {
        style: "serious_biography",
        includeInferred: true,
        includeUncertain: true,
        maxEvents: 24,
      },
      expect.anything(),
    );
  });

  it("可切换文风并随请求发送", async () => {
    render(<OutlinePanel saveId="s1" characterId="c1" />);
    fireEvent.change(screen.getByRole("combobox", { name: /文风/ }), {
      target: { value: "cold_historian" },
    });
    fireEvent.click(screen.getByRole("button", { name: "生成提纲" }));
    await waitFor(() => expect(api.generateOutline).toHaveBeenCalled());
    const params = vi.mocked(api.generateOutline).mock.calls[0][2];
    expect(params.style).toBe("cold_historian");
  });

  it("未配置模型 → 展示可操作错误提示", async () => {
    vi.mocked(api.generateOutline).mockResolvedValue({
      saveId: "s1",
      characterId: "c1",
      recordId: 2,
      valid: false,
      retryCount: 0,
      warnings: [],
      outline: null,
      compressed: null,
      error: { code: "provider_not_configured", message: "未配置模型提供者（LLM_PROVIDER 未设置或无效）。" },
      stale: false,
    });
    render(<OutlinePanel saveId="s1" characterId="c1" />);
    fireEvent.click(screen.getByRole("button", { name: "生成提纲" }));
    expect(await screen.findByText("提纲生成失败")).toBeInTheDocument();
    // 提示给出可操作建议（.env 配置）。
    expect(
      screen.getByText(/请在 .env 中设置 LLM_PROVIDER/),
    ).toBeInTheDocument();
  });

  it("模型引用非本人物事件 → 拒绝展示（invalid_event_reference）", async () => {
    vi.mocked(api.generateOutline).mockResolvedValue({
      saveId: "s1",
      characterId: "c1",
      recordId: 3,
      valid: false,
      retryCount: 1,
      warnings: [],
      outline: null,
      compressed: null,
      error: { code: "invalid_event_reference", message: "章节「c1」引用了不存在的或非本人物的事件 id：ghost" },
      stale: false,
    });
    render(<OutlinePanel saveId="s1" characterId="c1" />);
    fireEvent.click(screen.getByRole("button", { name: "生成提纲" }));
    expect(await screen.findByText("提纲生成失败")).toBeInTheDocument();
    expect(screen.getByText(/ghost/)).toBeInTheDocument();
  });

  it("后端不可达（请求异常）→ 显示请求错误", async () => {
    vi.mocked(api.generateOutline).mockRejectedValue(new Error("后端请求失败（500）"));
    render(<OutlinePanel saveId="s1" characterId="c1" />);
    fireEvent.click(screen.getByRole("button", { name: "生成提纲" }));
    expect(await screen.findByText(/后端请求失败（500）/)).toBeInTheDocument();
  });

  it("模型不可达 → 状态提示（health.reachable=false）", async () => {
    vi.mocked(api.getLlmHealth).mockResolvedValue({
      ...healthOk,
      reachable: false,
      message: "模型服务不可达",
    });
    render(<OutlinePanel saveId="s1" characterId="c1" />);
    expect(await screen.findByText(/模型不可达/)).toBeInTheDocument();
  });
});
