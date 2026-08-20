from uuid import uuid4

from video.costing import estimate_generation_cost
from video.schemas import (
    CostRecord,
    CostSource,
    JobStatus,
    VideoGenerationJob,
    VideoModelProfile,
    VideoRequest,
)


class MockVideoProvider:
    """模拟真实视频 API 的异步提交与轮询行为，不发起网络请求。"""

    def __init__(self) -> None:
        self._jobs: dict[str, VideoGenerationJob] = {}

    def estimate_cost(self, request: VideoRequest, model: VideoModelProfile) -> float:
        return estimate_generation_cost(request, model)

    def submit(
        self,
        request: VideoRequest,
        model: VideoModelProfile,
    ) -> VideoGenerationJob:
        """提交一个生成任务，并立即返回处于排队状态的任务对象。"""
        job_id = str(uuid4())
        estimated_cost = self.estimate_cost(request, model)
        job = VideoGenerationJob(
            job_id=job_id,
            model_id=model.model_id,
            status=JobStatus.QUEUED,
            cost=CostRecord(
                estimated_usd=estimated_cost,
                reported_usd=None,
                source=CostSource.ESTIMATED,
            ),
        )
        self._jobs[job_id] = job
        return job

    def poll(self, job_id: str) -> VideoGenerationJob:
        """查询任务，并用状态机模拟一次异步处理进度。"""
        try:
            job = self._jobs[job_id]
        except KeyError as error:
            raise ValueError(f"不存在任务：{job_id}") from error

        if job.status == JobStatus.QUEUED:
            job.status = JobStatus.PROCESSING
        elif job.status == JobStatus.PROCESSING:
            job.status = JobStatus.COMPLETED
            job.output_url = f"https://example.com/videos/{job.job_id}.mp4"
        return job