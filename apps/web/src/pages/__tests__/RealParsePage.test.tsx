import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import RealParsePage from "../RealParsePage";
import { api } from "../../lib/api";
import { ROUTES } from "../../lib/router";
import { setActiveSaveId } from "../../lib/realRepository";
import { resetStore } from "../../test/helpers";
import { useStore } from "../../store";

const SAVE_ID = "save_real_001";

beforeEach(() => {
  resetStore();
  setActiveSaveId(null, null);
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

function mockApi({
  inspectFail,
  parseFail,
}: { inspectFail?: Error; parseFail?: Error } = {}) {
  vi.spyOn(api, "inspectSave").mockImplementation(
    async (_sid: string, _signal?: AbortSignal) => {
      if (inspectFail) throw inspectFail;
      return { saveId: SAVE_ID, kind: "binary_zip", encoding: "zip" };
    },
  );
  vi.spyOn(api, "modsForSave").mockImplementation(
    async (_sid: string, _signal?: AbortSignal) => ({
      saveId: SAVE_ID,
      report: { total: 0, incompatible: [], missing: [] },
    }),
  );
  vi.spyOn(api, "parseSave").mockImplementation(
    async (_sid: string, _signal?: AbortSignal) => {
      if (parseFail) throw parseFail;
      return {
        saveId: SAVE_ID,
        meta: { gameVersion: "1.13", date: "1066.1.1" },
        player_name: null,
        mod_count: 0,
        mods: { total: 0, incompatible: [], missing: [] },
        character_count: 40000,
        dead_character_count: 0,
        encoding: "utf-8",
        unknown_token_count: 0,
        header_parse_ok: true,
        parse_ms: 1,
        sample: [],
        game_data: {},
        localization: { loaded_languages: ["simp_chinese"], entry_count: 1 },
      };
    },
  );
}

describe("RealParsePage（真实后端驱动解析过程页）", () => {
  it("三个阶段按真实后端顺序推进，成功后切换真实模式并进入选择页", async () => {
    mockApi();
    render(<RealParsePage saveId={SAVE_ID} successSealMs={0} />);

    // ① 初检（真实后端 inspect）。
    await waitFor(() => expect(api.inspectSave).toHaveBeenCalledTimes(1));
    expect(screen.getByText("检测文件类型与编码")).toBeInTheDocument();

    // ② Mod 报告。
    await waitFor(() => expect(api.modsForSave).toHaveBeenCalledTimes(1));
    expect(screen.getByText("核对 Mod 与本地化")).toBeInTheDocument();

    // ③ 解析（melt + 索引）。
    await waitFor(() => expect(api.parseSave).toHaveBeenCalledTimes(1));
    expect(screen.getByText("解析存档并建立索引")).toBeInTheDocument();

    // 成功后：后端模式开启、激活存档、进入选择页。
    await waitFor(() => expect(useStore.getState().backendMode).toBe(true));
    await waitFor(() =>
      expect(window.location.pathname).toBe(ROUTES.savesCharacters(SAVE_ID)),
    );
  });

  it("后端失败：当前阶段标记错误、后续阶段标记跳过，展示重试", async () => {
    mockApi({ inspectFail: new Error("读取文件失败：格式不受支持") });
    render(<RealParsePage saveId={SAVE_ID} />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    // 错误同时出现在「阶段错误」与「错误摘要」中。
    expect(screen.getAllByText(/读取文件失败/).length).toBeGreaterThan(0);
    // 后续阶段不执行。
    expect(api.modsForSave).not.toHaveBeenCalled();
    expect(api.parseSave).not.toHaveBeenCalled();

    const retry = screen.getByRole("button", { name: /重试/ });
    expect(retry).toBeInTheDocument();
  });

  it("点击重试后重新按顺序执行三个阶段并成功", async () => {
    mockApi({ inspectFail: new Error("初次失败") });
    render(<RealParsePage saveId={SAVE_ID} successSealMs={0} />);

    await screen.findByRole("alert");

    // 第二次运行不再失败。
    vi.mocked(api.inspectSave).mockImplementation(async () => ({
      saveId: SAVE_ID,
      kind: "binary_zip",
    }));
    fireEvent.click(screen.getByRole("button", { name: /重试/ }));

    await waitFor(() =>
      expect(window.location.pathname).toBe(ROUTES.savesCharacters(SAVE_ID)),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(useStore.getState().backendMode).toBe(true);
  });

  it("提示大型存档首次解析耗时较长（降低等待焦虑）", () => {
    mockApi();
    render(<RealParsePage saveId={SAVE_ID} successSealMs={0} />);
    // 顶部说明包含「首次解析可能需要 1–3 分钟」的提示文案。
    expect(
      screen.getByText(/大型存档首次解析可能需要 1–3 分钟/),
    ).toBeInTheDocument();
  });
});
