import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import BiographyPanel from "../BiographyPanel";
import { api, type BiographyJobData, type BiographyRecord, type OutlineRecord } from "../../lib/api";

/**
 * BiographyPanel（Phase 3B）：
 *  - 挂载只加载提纲/记录列表，绝不自动调用生成；
 *  - 需先有可用提纲（非 stale）才能生成；
 *  - 点击「生成正文」→ 异步任务 → 轮询进度 → 完成后展示；
 *  - 模型不可达 → 结构化错误提示（不影响档案浏览）；
 *  - needs_revision 记录如实展示「需修订」。
 */

const outlineRec: OutlineRecord = {
  id: 7,
  character_id: "c1",
  style: "serious_biography",
  status: "success",
  outline: {
    profileId: "c1",
    style: "serious_biography",
    chapters: [
      { id: "ch1", title: "出身", summary: "早年。", eventIds: ["e1"] },
      { id: "ch2", title: "巅峰", summary: "立业。", eventIds: ["e2"] },
    ],
  },
  error_code: null,
  error_message: null,
  retry_count: 0,
  warnings: null,
  compression_version: "2",
  prompt_version: "outline.zh-Hans.v2",
  created_at: "2026-08-04T00:00:00Z",
  stale: false,
};

const staleOutline: OutlineRecord = { ...outlineRec, id: 6, stale: true };

const biographyRec: BiographyRecord = {
  id: "b1",
  character_id: "c1",
  outline_id: 7,
  style: "serious_biography",
  status: "completed",
  revision_count: 0,
  biography: {
    profileId: "c1",
    style: "serious_biography",
    chapters: [
      { id: "ch1", title: "出身", content: "据推断，其人早年生平未见详录。", eventIds: ["e1"] },
    ],
    generatedAt: "2026-08-04T00:00:00Z",
    modelName: "fake",
    factCheck: { status: "pass", issues: [] },
    profileDigest: null,
  },
  factCheck: { status: "pass", issues: [] },
  model_name: "fake",
  prompt_version: "biography-chapter.zh-Hans.v1",
  compression_version: "2",
  created_at: "2026-08-04T00:00:00Z",
  stale: false,
};

const completedJob: BiographyJobData = {
  jobId: "j1",
  saveId: "s1",
  characterId: "c1",
  status: "completed",
  totalChapters: 2,
  completedChapters: 2,
  currentChapter: 2,
  currentChapterTitle: "巅峰",
  retryCount: 0,
  factCheckIssueCount: 0,
  biographyId: "b2",
  recordStatus: "completed",
  error: null,
};

beforeEach(() => {
  vi.spyOn(api, "listOutlines").mockResolvedValue({
    saveId: "s1",
    characterId: "c1",
    count: 1,
    records: [outlineRec],
  });
  vi.spyOn(api, "listBiographies").mockResolvedValue({
    saveId: "s1",
    characterId: "c1",
    count: 1,
    records: [biographyRec],
  });
  vi.spyOn(api, "startBiography").mockResolvedValue({
    saveId: "s1",
    characterId: "c1",
    jobId: "j1",
    status: "pending",
  });
  vi.spyOn(api, "getBiographyJob").mockResolvedValue(completedJob);
  vi.spyOn(api, "cancelBiographyJob").mockResolvedValue({ jobId: "j1", cancelled: true });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("BiographyPanel", () => {
  it("挂载时只加载列表，不自动调用生成", async () => {
    render(<BiographyPanel saveId="s1" characterId="c1" />);
    // 已有记录可见。
    expect(await screen.findByText(/其人早年生平未见详录/)).toBeInTheDocument();
    expect(api.listOutlines).toHaveBeenCalledTimes(1);
    expect(api.startBiography).not.toHaveBeenCalled();
    // 默认选中可用提纲。
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: /依据提纲/ })).toHaveValue("7"),
    );
  });

  it("无可用的非 stale 提纲 → 按钮禁用并提示", async () => {
    vi.mocked(api.listOutlines).mockResolvedValue({
      saveId: "s1",
      characterId: "c1",
      count: 1,
      records: [staleOutline],
    });
    render(<BiographyPanel saveId="s1" characterId="c1" />);
    expect(await screen.findByText("暂无可用提纲")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "生成正文" })).toBeDisabled();
  });

  it("点击「生成正文」→ POST → 轮询任务 → 展示完成结果", async () => {
    render(<BiographyPanel saveId="s1" characterId="c1" />);
    await screen.findByRole("combobox", { name: /依据提纲/ });
    fireEvent.click(screen.getByRole("button", { name: "生成正文" }));

    expect(await screen.findByText(/已生成并保存/)).toBeInTheDocument();
    expect(api.startBiography).toHaveBeenCalledWith("s1", "c1", {
      outlineId: 7,
      includeInferred: true,
      includeUncertain: true,
      maxEvents: 24,
    });
    expect(api.getBiographyJob).toHaveBeenCalledWith("j1");
    // 完成后重新拉取记录列表。
    expect(api.listBiographies).toHaveBeenCalled();
  });

  it("任务失败（模型不可达）→ 结构化错误提示，不伪装成功", async () => {
    vi.mocked(api.getBiographyJob).mockResolvedValue({
      ...completedJob,
      status: "error",
      biographyId: null,
      recordStatus: "error",
      error: { code: "provider_unreachable", message: "模型服务不可达，请确认本地模型服务已启动。" },
    });
    render(<BiographyPanel saveId="s1" characterId="c1" />);
    await screen.findByRole("combobox", { name: /依据提纲/ });
    fireEvent.click(screen.getByRole("button", { name: "生成正文" }));
    expect(await screen.findByText("正文生成失败")).toBeInTheDocument();
    // 提示给出可操作建议（本地模型服务默认端口）。
    expect(
      screen.getByText(/请确认本地模型服务已启动（默认 http:\/\/127\.0\.0\.1:8080）/),
    ).toBeInTheDocument();
  });

  it("needs_revision 记录 → 如实展示「需修订」徽标与提示", async () => {
    vi.mocked(api.listBiographies).mockResolvedValue({
      saveId: "s1",
      characterId: "c1",
      count: 1,
      records: [
        {
          ...biographyRec,
          status: "needs_revision",
          biography: {
            ...biographyRec.biography!,
            factCheck: {
              status: "needs_revision",
              issues: [
                { rule: "fabricated_dialogue", severity: "error", message: "正文出现虚构对白", suggestedFix: "删除对白" },
              ],
            },
          },
          factCheck: {
            status: "needs_revision",
            issues: [
              { rule: "fabricated_dialogue", severity: "error", message: "正文出现虚构对白", suggestedFix: "删除对白" },
            ],
          },
        },
      ],
    });
    render(<BiographyPanel saveId="s1" characterId="c1" />);
    expect(await screen.findByText(/需修订（1 处提示）/)).toBeInTheDocument();
    expect(screen.getByText(/正文出现虚构对白/)).toBeInTheDocument();
  });
});
