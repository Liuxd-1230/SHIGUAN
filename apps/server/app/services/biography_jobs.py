"""异步正文生成任务管理（Phase 3B 异步任务 API）。

- `start()`：后台线程运行 worker（逐章生成）；job 状态 pending → running →
  completed / error / cancelled。
- `get()`：快照进度（currentChapter / totalChapters / completedChapters /
  retryCount / factCheckIssueCount）。
- `cancel()`：置取消标志，worker 在下一章前检查并退出。

job 只保存运行时状态；worker 返回落库结果（biographyId 等），
**绝不把** API Key / 完整 Prompt / 原始存档 / 本地路径放进 job 状态。
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

# job 状态（对外语义）：
#   pending    已创建，线程待启动
#   running    正在逐章生成
#   completed  全部章节已生成（recordStatus 区分 completed / needs_revision）
#   error      Provider/校验级失败（未产出可保存正文）
#   cancelled  用户取消（不保存）
JOB_STATUSES = ("pending", "running", "completed", "error", "cancelled")


@dataclass
class BiographyJob:
    job_id: str
    save_id: str
    character_id: str
    status: str = "pending"
    total_chapters: int = 0
    completed_chapters: int = 0
    current_chapter_index: int = 0
    current_chapter_title: str = ""
    retry_count: int = 0
    fact_check_issue_count: int = 0
    biography_id: Optional[str] = None
    record_status: Optional[str] = None  # completed / needs_revision / error
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    _cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _thread: Optional[threading.Thread] = field(default=None, repr=False)


class BiographyJobManager:
    """进程内 job 注册表（FastAPI 线程池中安全）。"""

    def __init__(self) -> None:
        self._jobs: dict[str, BiographyJob] = {}
        self._lock = threading.Lock()

    def start(
        self,
        *,
        worker: Callable[[BiographyJob], dict],
        save_id: str,
        character_id: str,
    ) -> BiographyJob:
        """创建 job 并在后台线程运行 worker。

        worker(job) 负责逐章生成并更新 job 进度字段，返回落库结果 dict：
          {status, biography_id?, record_status?, retry_count, fact_check_issue_count,
           error_code?, error_message?}
        """
        job = BiographyJob(
            job_id=uuid.uuid4().hex,
            save_id=save_id,
            character_id=character_id,
            status="pending",
        )
        with self._lock:
            self._jobs[job.job_id] = job

        def _run() -> None:
            job.status = "running"
            try:
                outcome = worker(job) or {}
                if job._cancel_event.is_set():
                    job.status = "cancelled"
                    return
                job.status = outcome.get("status", "error")
                job.biography_id = outcome.get("biography_id")
                job.record_status = outcome.get("record_status")
                job.retry_count = outcome.get("retry_count", job.retry_count)
                job.fact_check_issue_count = outcome.get(
                    "fact_check_issue_count", job.fact_check_issue_count
                )
                job.error_code = outcome.get("error_code")
                job.error_message = outcome.get("error_message")
                if job.status == "error":
                    job.record_status = "error"
            except Exception as exc:  # noqa: BLE001
                job.status = "error"
                job.record_status = "error"
                job.error_code = "internal_error"
                job.error_message = f"正文生成任务异常：{type(exc).__name__}"

        job._thread = threading.Thread(target=_run, name="biography-job", daemon=True)
        job._thread.start()
        return job

    def get(self, job_id: str) -> Optional[dict]:
        """返回 job 的对外快照（不含线程/事件对象）。"""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return {
                "jobId": job.job_id,
                "saveId": job.save_id,
                "characterId": job.character_id,
                "status": job.status,
                "totalChapters": job.total_chapters,
                "completedChapters": job.completed_chapters,
                "currentChapter": job.current_chapter_index,
                "currentChapterTitle": job.current_chapter_title,
                "retryCount": job.retry_count,
                "factCheckIssueCount": job.fact_check_issue_count,
                "biographyId": job.biography_id,
                "recordStatus": job.record_status,
                "error": (
                    {"code": job.error_code, "message": job.error_message}
                    if job.error_code is not None
                    else None
                ),
            }

    def cancel(self, job_id: str) -> Optional[str]:
        """请求取消；返回取消前的状态（None = job 不存在）。"""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            job._cancel_event.set()
            return job.status

    def update_progress(
        self,
        job_id: str,
        *,
        total: int,
        completed: int,
        current_index: int,
        current_title: str,
        retry_count: int,
        fact_check_issue_count: int,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.total_chapters = total
            job.completed_chapters = completed
            job.current_chapter_index = current_index
            job.current_chapter_title = current_title
            job.retry_count = retry_count
            job.fact_check_issue_count = fact_check_issue_count

    def is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            return bool(job is not None and job._cancel_event.is_set())


# 进程内单例。
_job_manager = BiographyJobManager()


def biography_job_manager() -> BiographyJobManager:
    return _job_manager
