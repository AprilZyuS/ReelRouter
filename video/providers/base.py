"""视频生成供应商的统一接口约定。"""

from typing import Protocol

from video.schemas import (
    VideoGenerationJob,
    VideoModelProfile,
    VideoRequest,
)


class VideoProvider(Protocol):
    """
    所有视频生成 Provider 必须提供的能力。

    这是接口约定，而非具体实现：MockVideoProvider 和未来的真实
    Provider 只要实现相同的方法签名，就能被 VideoGenerationService 使用。
    """

    def submit(
        self,
        request: VideoRequest,
        model: VideoModelProfile,
    ) -> VideoGenerationJob:
        """提交视频生成任务，并返回初始任务状态。"""
        ...

    def poll(self, job: VideoGenerationJob) -> VideoGenerationJob:
        """根据已持久化任务查询最新状态，不能依赖本进程内缓存。"""
        ...
