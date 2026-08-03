/**
 * LocalSavesPanel —— 本地 CK3 存档浏览器（Phase 2A，规范五/十二.1/十二.2）。
 *
 * - 挂载时探测后端 /api/health；后端未启动则整块不渲染（前端继续走 Mock 演示）。
 * - 展示本机 save games 目录中的存档：文件名、大小、修改时间、是否 autosave、解析状态。
 * - 提供：解析并浏览人物 / 重新扫描 / 选择其他目录 / 打开存档目录 / 手动导入文件。
 * - 选择存档后：解析 → 写入 store 的 backendMode + activeSaveId → 跳转人物选择页
 *   （选择页按真实模式从后端拉取全量人物索引）。
 */
import { useEffect, useState } from "react";
import { navigate, ROUTES } from "../lib/router";
import { useStore } from "../store";
import { api, API_BASE, checkBackendAvailable, type LocalSaveSummary } from "../lib/api";
import { setActiveSaveId } from "../lib/realRepository";
import MuseumSurface from "./MuseumSurface";
import SealButton from "./SealButton";

function formatSize(n: number): string {
  if (n >= 1024 * 1024 * 1024) return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${n} B`;
}

function formatDate(s: string): string {
  try {
    return new Date(s).toLocaleString();
  } catch {
    return s;
  }
}

export default function LocalSavesPanel() {
  const [available, setAvailable] = useState<boolean | null>(null);
  const [saves, setSaves] = useState<LocalSaveSummary[]>([]);
  const [savesDir, setSavesDir] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [otherDir, setOtherDir] = useState("");
  const [importing, setImporting] = useState(false);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const [list, settings] = await Promise.all([
        api.listLocalSaves(),
        fetch(`${API_BASE}/api/settings/paths`).then((r) => r.json()),
      ]);
      setSaves(list.saves);
      setSavesDir(settings.saves_dir ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    let pollTimer: number | undefined;
    checkBackendAvailable()
      .then((ok) => {
        if (cancelled) return;
        setAvailable(ok);
        if (!ok) return;
        refresh();
        // 启动目录监听，并轮询状态；出现新增/覆盖事件时自动重新扫描（规范十二.2）。
        fetch(`${API_BASE}/api/local-saves/watch/start`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ interval: 2 }),
        }).catch(() => {});
        pollTimer = window.setInterval(() => {
          fetch(`${API_BASE}/api/local-saves/watch/status`)
            .then((r) => r.json())
            .then((st: { recent_events?: Array<{ type: string }> }) => {
              if (st.recent_events && st.recent_events.length > 0) refresh();
            })
            .catch(() => {});
        }, 3000);
      })
      .catch(() => !cancelled && setAvailable(false));
    return () => {
      cancelled = true;
      if (pollTimer) window.clearInterval(pollTimer);
      fetch(`${API_BASE}/api/local-saves/watch/stop`, {
        method: "POST",
      }).catch(() => {});
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleParse(s: LocalSaveSummary) {
    setBusyId(s.saveId);
    setError(null);
    try {
      const result = await api.parseSave(s.saveId);
      // 切换到真实后端模式并重置索引，使选择页重新从后端拉取全量人物。
      useStore.setState({
        backendMode: true,
        indexLoaded: false,
        characterIndex: [],
        saveMeta: null,
        selectedCharacterId: null,
        profileCache: {},
      });
      setActiveSaveId(s.saveId, result.meta);
      navigate(ROUTES.savesCharacters(s.saveId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  }

  async function handleRescan() {
    setLoading(true);
    try {
      const r = await api.rescanLocalSaves();
      setSaves(r.saves);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleApplyDir() {
    if (!otherDir.trim()) return;
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/settings/paths`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ saves_dir: otherDir.trim() }),
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 160));
      }
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleImport(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    setImporting(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", f);
      const res = await fetch(`${API_BASE}/api/local-saves/import`, {
        method: "POST",
        body: form,
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t.slice(0, 160));
      }
      await refresh();
    } catch (e2) {
      setError(e2 instanceof Error ? e2.message : String(e2));
    } finally {
      setImporting(false);
      e.target.value = "";
    }
  }

  function openDir() {
    if (savesDir) {
      try {
        window.open(`file://${savesDir}`, "_blank");
      } catch {
        /* 浏览器可能阻止 file:// 打开，忽略 */
      }
    }
  }

  // 后端不可用：整块不渲染，前端继续走 Mock 演示流程。
  if (available === false || available === null) return null;

  return (
    <MuseumSurface variant="raised" className="p-5">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-serif text-base font-bold text-ink-900">本机存档</h3>
        <div className="flex items-center gap-2">
          <SealButton variant="ghost" onClick={handleRescan} disabled={loading}>
            重新扫描
          </SealButton>
          <label className="cursor-pointer text-sm text-cinnabar-700 underline-offset-2 hover:underline">
            手动导入
            <input
              type="file"
              accept=".ck3"
              className="hidden"
              onChange={handleImport}
              disabled={importing}
            />
          </label>
        </div>
      </div>

      {savesDir && (
        <p className="mt-1 text-xs text-ink-500">
          存档目录：<span className="font-mono">{savesDir}</span>{" "}
          <button
            type="button"
            onClick={openDir}
            className="text-cinnabar-700 underline-offset-2 hover:underline"
          >
            打开
          </button>
        </p>
      )}

      {error && (
        <p className="mt-2 rounded-md bg-cinnabar-700/10 px-3 py-2 text-xs text-cinnabar-700">
          {error}
        </p>
      )}

      <div className="mt-3 space-y-2">
        {saves.length === 0 && !loading && (
          <p className="text-sm text-ink-500">未在该目录发现 .ck3 存档。</p>
        )}
        {saves.map((s) => (
          <div
            key={s.saveId}
            className="flex items-center justify-between gap-3 rounded-lg border border-ink-300/50 bg-paper-50 px-3 py-2"
          >
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="truncate font-medium text-ink-900">{s.fileName}</span>
                {s.isAutosave && (
                  <span className="rounded bg-cinnabar-700/10 px-1.5 py-0.5 text-[10px] text-cinnabar-700">
                    autosave
                  </span>
                )}
              </div>
              <div className="mt-0.5 text-xs text-ink-500">
                {formatSize(s.sizeBytes)} · {formatDate(s.modifiedAt)}
                {s.lastParseStatus === "parsed" && (
                  <span className="ml-2 text-emerald-700">已解析</span>
                )}
              </div>
            </div>
            <SealButton
              variant="primary"
              onClick={() => handleParse(s)}
              disabled={busyId === s.saveId}
            >
              {busyId === s.saveId ? "解析中…" : "解析并浏览"}
            </SealButton>
          </div>
        ))}
      </div>

      <div className="mt-4 flex items-end gap-2 border-t border-ink-300/40 pt-3">
        <input
          type="text"
          value={otherDir}
          onChange={(e) => setOtherDir(e.target.value)}
          placeholder="选择其他存档目录（绝对路径）"
          className="min-w-0 flex-1 rounded-md border border-ink-300 bg-paper-50 px-3 py-1.5 text-sm text-ink-800 outline-none focus:border-cinnabar-500"
        />
        <SealButton variant="ghost" onClick={handleApplyDir}>
          应用目录
        </SealButton>
      </div>
    </MuseumSurface>
  );
}
