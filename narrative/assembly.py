"""将已审核的逐镜头视频按分镜顺序交给 FFmpeg 合成。"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import httpx

from narrative.schemas import PrioritizedStoryboard
from narrative.video_execution import ShotVideoTaskLink
from video.schemas import JobStatus, VideoGenerationJob


class EpisodeAssemblyNotReady(ValueError):
    """镜头未完成、未审查或被拒绝，不能生成最终成片。"""


@dataclass(frozen=True)
class EpisodeAssemblyPlan:
    project_id: str
    episode_number: int
    ordered_jobs: tuple[VideoGenerationJob, ...]
    output_path: Path


def build_episode_assembly_plan(
    storyboard: PrioritizedStoryboard,
    links: Sequence[ShotVideoTaskLink],
    jobs: Sequence[VideoGenerationJob],
    output_path: Path,
) -> EpisodeAssemblyPlan:
    """用分镜 order，而不是任务创建顺序，确定成片镜头顺序。"""
    link_by_shot = {link.shot_id: link for link in links}
    job_by_id = {job.job_id: job for job in jobs}
    ordered_jobs: list[VideoGenerationJob] = []
    missing: list[str] = []
    invalid: list[str] = []
    for shot in storyboard.shots:
        link = link_by_shot.get(shot.shot_id)
        job = job_by_id.get(link.video_job_id) if link is not None else None
        if job is None:
            missing.append(shot.shot_id)
            continue
        if job.status != JobStatus.COMPLETED or not job.output_url:
            invalid.append(f"{shot.shot_id}（尚未完成）")
            continue
        if job.output_review is None:
            invalid.append(f"{shot.shot_id}（未人工评审）")
            continue
        if not job.output_review.accepted:
            invalid.append(f"{shot.shot_id}（人工拒绝）")
            continue
        ordered_jobs.append(job)
    if missing or invalid:
        details = []
        if missing:
            details.append("缺少视频任务：" + ", ".join(missing))
        if invalid:
            details.append("不可合成镜头：" + ", ".join(invalid))
        raise EpisodeAssemblyNotReady("；".join(details))
    return EpisodeAssemblyPlan(
        project_id=storyboard.project_id,
        episode_number=storyboard.episode_number,
        ordered_jobs=tuple(ordered_jobs),
        output_path=output_path,
    )


class FfmpegEpisodeAssembler:
    """下载 Provider 成片 URL 后使用 concat demuxer 无重编码拼接。"""

    def __init__(
        self,
        *,
        ffmpeg_binary: str = "ffmpeg",
        client: httpx.Client | None = None,
        command_runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> None:
        self.ffmpeg_binary = ffmpeg_binary
        self._client = client or httpx.Client(timeout=120.0, follow_redirects=True)
        self._command_runner = command_runner

    def assemble(self, plan: EpisodeAssemblyPlan) -> Path:
        if shutil.which(self.ffmpeg_binary) is None:
            raise RuntimeError("未找到 ffmpeg。请安装 FFmpeg 并确保其在 PATH 中。")
        work_dir = plan.output_path.parent / ".sources"
        work_dir.mkdir(parents=True, exist_ok=True)
        local_sources = [
            self._download(job.output_url, work_dir / f"{index:02d}-{job.job_id}.mp4")
            for index, job in enumerate(plan.ordered_jobs, start=1)
        ]
        concat_file = work_dir / "concat.txt"
        # concat demuxer 的单引号转义格式；命令以列表运行，不进入 shell。
        concat_file.write_text(
            "".join(
                f"file '{path.resolve().as_posix().replace("'", "'\\\\''")}'\n"
                for path in local_sources
            ),
            encoding="utf-8",
        )
        plan.output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self.ffmpeg_binary,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            str(plan.output_path),
        ]
        result = self._command_runner(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "未知 FFmpeg 错误").strip()
            raise RuntimeError(f"FFmpeg 合成失败：{message}")
        if not plan.output_path.exists():
            raise RuntimeError("FFmpeg 命令成功但未找到输出文件。")
        return plan.output_path

    def _download(self, url: str | None, destination: Path) -> Path:
        if not url:
            raise EpisodeAssemblyNotReady("已完成任务缺少 output_url。")
        try:
            with self._client.stream("GET", url) as response:
                response.raise_for_status()
                with destination.open("wb") as output:
                    for chunk in response.iter_bytes():
                        output.write(chunk)
        except httpx.HTTPError as error:
            raise RuntimeError(f"下载 Provider 视频失败：{url}；{error}") from error
        return destination
