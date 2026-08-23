import time

from video.providers.runway_provider import RunwayProvider
from video.runway_config import RunwaySettings
from video.schemas import (
    GenerationMode,
    JobStatus,
    VideoModelProfile,
    VideoRequest,
)

provider = RunwayProvider(RunwaySettings.from_environment())

model = VideoModelProfile(
    model_id="runway-gen4.5",
    provider="runway",
    supported_modes=frozenset({
        GenerationMode.TEXT_TO_VIDEO,
        GenerationMode.IMAGE_TO_VIDEO,
    }),
    cost_per_second=0.12,
    estimated_latency_seconds=60,
    quality_score=9,
    min_duration_seconds=2,
    max_duration_seconds=10,
)

request = VideoRequest(
    prompt="一只橙色小猫坐在窗边，阳光洒进房间，镜头缓慢推进。",
    mode=GenerationMode.TEXT_TO_VIDEO,
    duration_seconds=2,
    budget_usd=0.30,
    min_quality_score=9,
)

job = provider.submit(request, model)
print(f"已提交：{job.job_id}，预估成本：${job.cost.estimated_usd}")

for _ in range(12):  # 最多等约 60 秒
    time.sleep(5)
    job = provider.poll(job)
    print(f"当前状态：{job.status.value}")

    if job.status == JobStatus.COMPLETED:
        print("视频地址：", job.output_url)
        break

    if job.status == JobStatus.FAILED:
        print("生成失败。")
        break
else:
    print("一分钟内尚未完成；任务已提交，可稍后继续查询。")
