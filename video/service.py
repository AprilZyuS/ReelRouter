from dataclasses import dataclass

from video.model_router import ModelSelection, select_model as select_video_model
from video.output_review import VideoOutputReview
from video.providers.base import VideoProvider
from video.schemas import JobStatus, VideoGenerationJob, VideoRequest
from video.repository import VideoJobRepository


@dataclass(frozen=True)
class GenerationSubmission:
    """一次提交生成任务后的结果。"""

    selection: ModelSelection
    job: VideoGenerationJob


class VideoGenerationService:
    """编排模型选择、任务提交、查询与完成视频的人审。"""

    def __init__(self, provider: VideoProvider, repository: VideoJobRepository,) -> None:
        self.provider = provider
        # v1 先放在进程内；持久化存储是后续部署阶段的工作。
        self.repository = repository

    def select_for_request(self, request: VideoRequest) -> ModelSelection:
        return select_video_model(request)

    def submit_selected(
        self,
        request: VideoRequest,
        selection: ModelSelection,
    ) -> VideoGenerationJob:
        job = self.provider.submit(request, selection.model)
        self.repository.save(job)
        return job

    def create_job(self, request: VideoRequest) -> GenerationSubmission:
        selection = self.select_for_request(request)
        job = self.submit_selected(request, selection)
        return GenerationSubmission(selection=selection, job=job)

    def get_job(self, job_id: str) -> VideoGenerationJob:
        previous_job = self.repository.get(job_id)
        if previous_job is None:
            raise ValueError(f"不存在任务：{job_id}")

        job = self.provider.poll(job_id)

        # Provider 不知道平台内部的人审结果，因此把旧的人审结果带回来。
        if previous_job.output_review is not None:
            job.output_review = previous_job.output_review

        # 关键：Provider 返回的新状态必须写回 Repository。
        self.repository.save(job)
        return job

    def review_completed_job(
        self,
        job_id: str,
        review: VideoOutputReview,
    ) -> VideoGenerationJob:
        job = self.repository.get(job_id)
        if job is None:
            raise ValueError(f"不存在任务：{job_id}")

        if job.status != JobStatus.COMPLETED or not job.output_url:
            raise ValueError("视频任务尚未完成，不能评审输出。")
        job.output_review = review
        self.repository.save(job)
        return job