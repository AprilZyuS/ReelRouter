from fastapi import FastAPI
from fastapi.testclient import TestClient

from video.api_router import (
    create_video_runtime,
    get_video_service,
    get_video_workflow,
    router,
)
from video.repository import InMemoryVideoJobRepository


def make_client() -> TestClient:
    """测试使用内存 Repository，不依赖 Docker 中的 MySQL。"""
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


def make_text_to_video_payload(**overrides) -> dict:
    payload = {
        "prompt": "一只橙色小猫在窗边打盹。",
        "mode": "text_to_video",
        "duration_seconds": 5,
        "budget_usd": 1.0,
        "min_quality_score": 6,
    }
    payload.update(overrides)
    return payload


def make_high_cost_payload() -> dict:
    return make_text_to_video_payload(
        prompt="一支电影感的城市夜景短片。",
        duration_seconds=12,
        budget_usd=2.0,
        min_quality_score=8,
    )


def test_low_cost_job_is_submitted_through_workflow():
    client = make_client()

    response = client.post("/video/jobs", json=make_text_to_video_payload())

    body = response.json()
    assert response.status_code == 201
    assert body["status"] == "submitted"
    assert body["thread_id"]
    assert body["selection"]["model_id"] == "mock-balanced"
    assert body["selection"]["estimated_cost_usd"] == 0.25
    assert "成本最低" in body["selection"]["reason"]
    assert body["job" ]["status"] == "queued"
    assert body["job" ]["cost"] == {"estimated_usd": 0.25, "reported_usd": None, "source": "estimated"}
    assert body["interrupt"] is None


def test_image_to_video_job_is_submitted_through_workflow():
    client = make_client()
    payload = make_text_to_video_payload(
        prompt="让参考图中的手表缓慢旋转。",
        mode="image_to_video",
        reference_image_url="https://example.com/watch.png",
    )

    response = client.post("/video/jobs", json=payload)

    assert response.status_code == 201
    assert response.json()["status"] == "submitted"
    assert response.json()["selection"]["model_id"] == "mock-balanced"
    assert response.json()["job"]["status"] == "queued"


def test_high_cost_job_waits_for_human_review_before_submission():
    client = make_client()

    response = client.post("/video/jobs", json=make_high_cost_payload())

    body = response.json()
    assert response.status_code == 202
    assert body["status"] == "awaiting_human_review"
    assert body["selection"]["model_id"] == "mock-premium"
    assert body["job"] is None
    assert body["interrupt"]["options"] == ["approve", "reject"]


def test_human_approval_submits_high_cost_job():
    client = make_client()
    created = client.post("/video/jobs", json=make_high_cost_payload())
    thread_id = created.json()["thread_id"]

    response = client.post(
        f"/video/jobs/{thread_id}/approval",
        json={"action": "approve", "feedback": "预算已确认。"},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "submitted"
    assert body["approval_status"] == "approved"
    assert body["job" ]["status"] == "queued"
    assert body["job" ]["cost"] == {"estimated_usd": 1.44, "reported_usd": None, "source": "estimated"}


def test_human_rejection_ends_high_cost_job_without_submission():
    client = make_client()
    created = client.post("/video/jobs", json=make_high_cost_payload())
    thread_id = created.json()["thread_id"]

    response = client.post(
        f"/video/jobs/{thread_id}/approval",
        json={"action": "reject", "feedback": "成本过高。"},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "rejected"
    assert body["approval_status"] == "rejected"
    assert body["job"] is None
    assert body["error"] == "成本过高。"


def test_create_video_job_returns_bad_request_when_budget_is_too_low():
    client = make_client()
    payload = make_text_to_video_payload(
        budget_usd=0.09,
        min_quality_score=1,
    )

    response = client.post("/video/jobs", json=payload)

    assert response.status_code == 400
    assert "预算" in response.json()["detail"]


def test_get_unknown_video_job_returns_not_found():
    client = make_client()

    response = client.get("/video/jobs/unknown-job-id")

    assert response.status_code == 404
    assert "不存在任务" in response.json()["detail"]


def test_polling_video_job_changes_status_to_completed():
    client = make_client()
    created = client.post("/video/jobs", json=make_text_to_video_payload())
    job_id = created.json()["job"]["job_id"]

    first_poll = client.get(f"/video/jobs/{job_id}")
    second_poll = client.get(f"/video/jobs/{job_id}")

    assert first_poll.status_code == 200
    assert first_poll.json()["status"] == "processing"
    assert first_poll.json()["output_url"] is None
    assert second_poll.status_code == 200
    assert second_poll.json()["status"] == "completed"
    assert second_poll.json()["output_url"].endswith(f"/{job_id}.mp4")


def test_unknown_workflow_approval_returns_not_found():
    client = make_client()

    response = client.post(
        "/video/jobs/not-a-real-thread/approval",
        json={"action": "approve"},
    )

    assert response.status_code == 404
