from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from video.api_router import (
    create_video_runtime,
    get_video_service,
    get_video_workflow,
    router,
)
from video.repository import InMemoryVideoJobRepository
from video.output_review import VideoOutputReview


def make_client() -> TestClient:
    """测试使用独立的内存运行时，不依赖 MySQL。"""
    service, workflow = create_video_runtime(
        InMemoryVideoJobRepository()
    )

    app = FastAPI()
    app.include_router(router)

    app.dependency_overrides[get_video_service] = (
        lambda: service
    )
    app.dependency_overrides[get_video_workflow] = (
        lambda: workflow
    )

    return TestClient(app)


def create_completed_job(client: TestClient) -> str:
    created = client.post(
        "/video/jobs",
        json={
            "prompt": "一只橙色小猫在窗边打盹。",
            "mode": "text_to_video",
            "duration_seconds": 5,
            "budget_usd": 1.0,
            "min_quality_score": 6,
        },
    )
    job_id = created.json()["job"]["job_id"]
    client.get(f"/video/jobs/{job_id}")
    completed = client.get(f"/video/jobs/{job_id}")
    assert completed.json()["status"] == "completed"
    return job_id


def test_video_output_review_requires_scores_from_one_to_five():
    with pytest.raises(ValueError, match="visual_quality_score"):
        VideoOutputReview(
            accepted=True,
            visual_quality_score=6,
            prompt_alignment_score=5,
            feedback="",
        )


def test_rejected_video_output_review_requires_feedback():
    with pytest.raises(ValueError, match="feedback"):
        VideoOutputReview(
            accepted=False,
            visual_quality_score=2,
            prompt_alignment_score=1,
            feedback="   ",
        )


def test_api_saves_completed_video_output_review():
    client = make_client()
    job_id = create_completed_job(client)

    response = client.post(
        f"/video/jobs/{job_id}/output-review",
        json={
            "accepted": True,
            "visual_quality_score": 4,
            "prompt_alignment_score": 5,
            "feedback": "镜头运动自然，和提示词一致。",
        },
    )

    assert response.status_code == 200
    assert response.json()["output_review"] == {
        "accepted": True,
        "visual_quality_score": 4,
        "prompt_alignment_score": 5,
        "feedback": "镜头运动自然，和提示词一致。",
    }


def test_api_rejects_review_before_video_is_completed():
    client = make_client()
    created = client.post(
        "/video/jobs",
        json={
            "prompt": "一只橙色小猫在窗边打盹。",
            "mode": "text_to_video",
            "duration_seconds": 5,
            "budget_usd": 1.0,
            "min_quality_score": 6,
        },
    )
    job_id = created.json()["job"]["job_id"]

    response = client.post(
        f"/video/jobs/{job_id}/output-review",
        json={
            "accepted": True,
            "visual_quality_score": 5,
            "prompt_alignment_score": 5,
            "feedback": "",
        },
    )

    assert response.status_code == 409
    assert "尚未完成" in response.json()["detail"]


def test_api_rejects_invalid_output_review_score():
    client = make_client()
    job_id = create_completed_job(client)

    response = client.post(
        f"/video/jobs/{job_id}/output-review",
        json={
            "accepted": True,
            "visual_quality_score": 6,
            "prompt_alignment_score": 5,
            "feedback": "",
        },
    )

    assert response.status_code == 422