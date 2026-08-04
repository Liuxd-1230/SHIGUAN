import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  type BiographyJobData,
  type BiographyRecord,
  type OutlineRecord,
} from "../lib/api";
import MuseumSurface from "./MuseumSurface";
import SealButton from "./SealButton";
import InkDivider from "./InkDivider";

/**
 * AI 传记正文面板（Phase 3B）。
 *
 * 分层：史料摘要（确定性）→ AI 提纲（OutlinePanel）→ AI 正文（本面板）。
 * 约束：
 *  - 以已生成提纲为依据（outlineId 必选），打开页面不自动调用模型。
 *  - 生成走后端异步任务：进度经 GET /biography/jobs/{id} 轮询；可取消。
 *  - 模型不可达 / 未配置 → 结构化错误提示，不影响档案浏览。
 *  - needs_revision（有限修复耗尽）如实展示「需修订」徽标，不伪装成功。
 */
export default function BiographyPanel({
  saveId,
  characterId,
}: {
  saveId: string;
  characterId: string;
}) {
  const [outlines, setOutlines] = useState<OutlineRecord[]>([]);
  const [selectedOutlineId, setSelectedOutlineId] = useState<number | null>(null);
  const [records, setRecords] = useState<BiographyRecord[]>([]);
  const [job, setJob] = useState<BiographyJobData | null>(null);
  const [starting, setStarting] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      const [o, b] = await Promise.all([
        api.listOutlines(saveId, characterId),
        api.listBiographies(saveId, characterId),
      ]);
      setOutlines(o.records);
      setRecords(b.records);
      setSelectedOutlineId((prev) => {
        const usable = o.records.filter((r) => !r.stale && r.outline);
        if (prev != null && usable.some((r) => r.id === prev)) return prev;
        return usable.length > 0 ? usable[0].id : null;
      });
    } catch {
      // 面板故障不影响档案浏览；仅静默保留空状态。
    }
  }, [saveId, characterId]);

  useEffect(() => {
    void load();
    return () => {
      if (pollRef.current != null) window.clearInterval(pollRef.current);
    };
  }, [load]);

  const stopPolling = useCallback(() => {
    if (pollRef.current != null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const pollJob = useCallback(
    async (jobId: string) => {
      try {
        const j = await api.getBiographyJob(jobId);
        setJob(j);
        if (j.status === "completed" || j.status === "error" || j.status === "cancelled") {
          stopPolling();
          if (j.status === "completed") void load();
        }
      } catch {
        stopPolling();
        setJob(null);
        setRequestError("无法查询生成任务进度，请刷新页面后重试。");
      }
    },
    [load, stopPolling],
  );

  async function start() {
    if (selectedOutlineId == null) return;
    setStarting(true);
    setRequestError(null);
    try {
      const res = await api.startBiography(saveId, characterId, {
        outlineId: selectedOutlineId,
        includeInferred: true,
        includeUncertain: true,
        maxEvents: 24,
      });
      setJob({
        jobId: res.jobId,
        saveId,
        characterId,
        status: "pending",
        totalChapters: 0,
        completedChapters: 0,
        currentChapter: 0,
        currentChapterTitle: "",
        retryCount: 0,
        factCheckIssueCount: 0,
        biographyId: null,
        recordStatus: null,
        error: null,
      });
      stopPolling();
      pollRef.current = window.setInterval(() => void pollJob(res.jobId), 800);
      await pollJob(res.jobId);
    } catch (err) {
      setRequestError(err instanceof Error ? err.message : String(err));
    } finally {
      setStarting(false);
    }
  }

  async function cancel() {
    if (!job || job.status !== "running") return;
    try {
      await api.cancelBiographyJob(job.jobId);
    } catch {
      // 取消失败不阻塞；轮询会收敛到终态。
    }
  }

  const usableOutlines = outlines.filter((r) => !r.stale && r.outline);
  const busy = job !== null && (job.status === "pending" || job.status === "running");

  return (
    <MuseumSurface variant="raised" className="p-4 sm:p-5">
      <div>
        <h2 className="font-serif text-lg font-bold text-ink-900">AI 传记正文</h2>
        <p className="mt-1 text-xs text-ink-500">
          以已生成提纲为依据逐章生成，正文经确定性事实校验后才保存。
        </p>
      </div>

      <InkDivider className="my-3" />

      {/* 提纲选择 + 生成 */}
      <div className="flex flex-wrap items-end gap-3">
        <label className="block min-w-[16rem]">
          <span className="text-xs font-semibold text-ink-700">依据提纲</span>
          <select
            value={selectedOutlineId ?? ""}
            onChange={(e) => setSelectedOutlineId(Number(e.target.value))}
            disabled={busy || usableOutlines.length === 0}
            className="mt-1 w-full rounded-lg border border-ink-400/50 bg-paper-50 px-2 py-2 text-sm text-ink-900"
          >
            {usableOutlines.length === 0 && <option value="">暂无可用提纲</option>}
            {usableOutlines.map((o) => (
              <option key={o.id} value={o.id}>
                提纲 #{o.id}（{o.style}，{o.outline?.chapters.length ?? 0} 章）
              </option>
            ))}
          </select>
        </label>
        <SealButton
          variant="primary"
          seal
          onClick={() => void start()}
          disabled={busy || selectedOutlineId == null || usableOutlines.length === 0}
          aria-busy={busy}
        >
          {starting || job?.status === "pending" ? "提交中…" : "生成正文"}
        </SealButton>
      </div>

      {/* 请求层错误 */}
      {requestError && (
        <div
          role="alert"
          className="mt-4 rounded-lg border border-danger/40 bg-danger/5 px-3 py-2 text-sm text-danger-700"
        >
          {requestError}
        </div>
      )}

      {/* 任务进度 */}
      {busy && <JobProgress job={job} onCancel={() => void cancel()} />}
      {job && (job.status === "error" || job.status === "cancelled") && (
        <JobTerminal job={job} />
      )}
      {job && job.status === "completed" && job.biographyId && (
        <div className="mt-4 text-sm text-emerald-700">
          ✅ 已生成并保存（重试 {job.retryCount} 次，
          {job.factCheckIssueCount} 条事实校验提示）
        </div>
      )}

      {/* 历史记录 */}
      <div className="mt-5">
        <h3 className="text-sm font-semibold text-ink-700">生成记录</h3>
        {records.length === 0 ? (
          <p className="mt-2 text-xs text-ink-500">
            尚无正文记录。先在「AI 提纲」生成提纲，再选择提纲生成正文。
          </p>
        ) : (
          <div className="mt-2 space-y-3">
            {records.map((rec) => (
              <BiographyRecordCard key={rec.id} rec={rec} />
            ))}
          </div>
        )}
      </div>
    </MuseumSurface>
  );
}

function JobProgress({
  job,
  onCancel,
}: {
  job: BiographyJobData;
  onCancel: () => void;
}) {
  const total = Math.max(job.totalChapters, 1);
  const done = Math.min(job.completedChapters, total);
  const pct = Math.round((done / total) * 100);
  return (
    <div className="mt-4 rounded-lg border border-ink-400/40 bg-paper-100/60 px-3 py-3">
      <div className="flex items-center justify-between text-xs text-ink-600">
        <span>
          正在生成第 {Math.max(job.currentChapter, 1)} 章「{job.currentChapterTitle || "…"}」
        </span>
        <span>
          {done}/{total} 章 · {pct}%
        </span>
      </div>
      <div
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="正文生成进度"
        className="mt-2 h-2 overflow-hidden rounded-full bg-ink-400/20"
      >
        <div
          className="h-full rounded-full bg-cinnabar-700/80 transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="mt-2 flex items-center justify-between">
        <span className="text-[11px] text-ink-500">
          {job.retryCount > 0 ? `已自动修正 ${job.retryCount} 次` : ""}
        </span>
        <SealButton
          variant="ghost"
          className="min-h-[2rem] px-2 py-1 text-xs"
          onClick={onCancel}
        >
          取消生成
        </SealButton>
      </div>
    </div>
  );
}

function JobTerminal({ job }: { job: BiographyJobData }) {
  if (job.status === "cancelled") {
    return (
      <div className="mt-4 text-sm text-ink-600">已取消本次生成（未保存半成品）。</div>
    );
  }
  const hints: Record<string, string> = {
    provider_not_configured:
      "请在 .env 中设置 LLM_PROVIDER 并确认 LLM_BASE_URL / LLM_MODEL。",
    provider_unreachable: "请确认本地模型服务已启动（默认 http://127.0.0.1:8080）。",
    provider_timeout: "模型响应超时，请稍后重试。",
    outline_stale: "所选提纲基于旧存档，请重新生成提纲后再试。",
    insufficient_timeline: "该人物时间线事件过少，无法生成正文。",
  };
  return (
    <div
      role="alert"
      className="mt-4 rounded-lg border border-danger/40 bg-danger/5 px-3 py-2 text-sm text-danger-700"
    >
      <p className="font-semibold">正文生成失败</p>
      <p className="mt-1">{job.error?.message ?? "未知错误"}</p>
      {job.error && hints[job.error.code] && (
        <p className="mt-1 text-xs text-ink-600">{hints[job.error.code]}</p>
      )}
    </div>
  );
}

function BiographyRecordCard({ rec }: { rec: BiographyRecord }) {
  const bio = rec.biography;
  const needsRevision = rec.status === "needs_revision";
  return (
    <div
      className={`rounded-lg border px-3 py-2 ${
        needsRevision
          ? "border-amber-500/50 bg-amber-500/5"
          : "border-ink-400/40 bg-paper-100/60"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2 text-xs text-ink-600">
        <span className="font-semibold text-ink-900">
          {new Date(rec.created_at).toLocaleString()}
        </span>
        {needsRevision ? (
          <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-amber-800">
            需修订（{bio?.factCheck?.issues.length ?? 0} 处提示）
          </span>
        ) : (
          <span className="rounded bg-emerald-500/20 px-1.5 py-0.5 text-emerald-800">
            已校验通过
          </span>
        )}
        {rec.stale && (
          <span className="text-amber-700">⚠ 基于旧存档</span>
        )}
        {rec.revision_count > 0 && <span>自动修正 {rec.revision_count} 次</span>}
      </div>

      {bio && (
        <div className="mt-2 space-y-3">
          {bio.chapters.map((ch, i) => (
            <div key={ch.id}>
              <p className="text-sm font-semibold text-ink-900">
                {i + 1}. {ch.title}
              </p>
              <p className="mt-0.5 whitespace-pre-line text-sm leading-relaxed text-ink-700">
                {ch.content}
              </p>
            </div>
          ))}
        </div>
      )}

      {needsRevision && bio?.factCheck && bio.factCheck.issues.length > 0 && (
        <ul className="mt-2 space-y-1 border-t border-ink-400/30 pt-2">
          {bio.factCheck.issues.slice(0, 5).map((iss) => (
            <li key={`${iss.rule}-${iss.message}`} className="text-xs text-ink-600">
              · {iss.message}
            </li>
          ))}
          {bio.factCheck.issues.length > 5 && (
            <li className="text-xs text-ink-500">
              …另有 {bio.factCheck.issues.length - 5} 条提示
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
