from types import SimpleNamespace

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient

from narrative.api_router import _raise_domain_error, get_narrative_runtime, router
from narrative.screenplay_reviewer import ScreenplayReviewOutputError
from narrative.schemas import EpisodePlan, NarrativeProjectProfile, NovelManuscript


class FakeRepository:
    def __init__(
        self,
        profile: NarrativeProjectProfile | None = None,
        plans: list[EpisodePlan] | None = None,
    ) -> None:
        self.profile = profile
        self.plans = plans or []

    def get_project_profile(self, project_id: str):
        if self.profile is not None and self.profile.project_id == project_id:
            return self.profile
        return None

    def list_episode_plans(self, project_id: str):
        return [plan for plan in self.plans if plan.project_id == project_id]

    def get_screenplay(self, project_id: str, episode_number: int):
        return None

    def get_episode_summary(self, project_id: str, episode_number: int):
        return None

    def get_prioritized_storyboard(self, project_id: str, episode_number: int):
        return None


class FakeGenerationService:
    def __init__(self, profile: NarrativeProjectProfile) -> None:
        self.profile = profile
        self.calls = 0

    def generate_and_ingest(self, request):
        self.calls += 1
        manuscript = NovelManuscript(
            project_id=request.project_id,
            title=request.title,
            logline="一封匿名来信让主角重返港口。",
            manuscript="雨夜来信。" * 200,
            style_bible=request.visual_style,
            planned_episode_count=2,
        )
        return SimpleNamespace(
            profile=self.profile,
            manuscript=manuscript,
            document=SimpleNamespace(document_id=self.profile.manuscript_document_id),
            ingestion=SimpleNamespace(chunk_count=2),
        )


def make_profile() -> NarrativeProjectProfile:
    return NarrativeProjectProfile(
        project_id="demo-project",
        manuscript_document_id="novel-demo-v1",
        title="雨夜来信",
        logline="一封匿名来信让主角重返港口。",
        style_bible="冷色调悬疑电影感。",
        planned_episode_count=2,
        keywords=["匿名来信", "港口"],
        genre="都市悬疑",
        episode_duration_seconds=45,
        episode_budget_usd=8.0,
    )


def make_client():
    profile = make_profile()
    generation_service = FakeGenerationService(profile)
    runtime = SimpleNamespace(
        repository=FakeRepository(profile),
        generation_service=generation_service,
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_narrative_runtime] = lambda: runtime
    return TestClient(app), generation_service


def valid_project_payload(**overrides):
    data = {
        "project_id": "demo-project",
        "title": "雨夜来信",
        "keywords": ["匿名来信", "港口"],
        "genre": "都市悬疑",
        "visual_style": "冷色调悬疑电影感。",
        "episode_duration_seconds": 45,
        "episode_budget_usd": 8.0,
        "enable_assembly": True,
        "confirm_paid_call": True,
    }
    data.update(overrides)
    return data


def test_create_project_requires_explicit_paid_call_confirmation():
    client, generation_service = make_client()

    response = client.post("/narrative/projects", json=valid_project_payload(confirm_paid_call=False))

    assert response.status_code == 400
    assert "确认" in response.json()["detail"]
    assert generation_service.calls == 0


def test_create_project_returns_manuscript_and_project_memory_metadata():
    client, generation_service = make_client()

    response = client.post("/narrative/projects", json=valid_project_payload())

    assert response.status_code == 201
    assert response.json()["profile"]["project_id"] == "demo-project"
    assert response.json()["manuscript"]["title"] == "雨夜来信"
    assert response.json()["chunk_count"] == 2
    assert generation_service.calls == 1


def test_get_project_exposes_profile_and_current_episode_plans():
    client, _ = make_client()

    response = client.get("/narrative/projects/demo-project")

    assert response.status_code == 200
    assert response.json()["profile"]["keywords"] == ["匿名来信", "港口"]
    assert response.json()["episodes"] == []
    assert response.json()["episode_readiness"] == []


def test_episode_two_is_locked_until_episode_one_is_reviewed_and_approved():
    first = EpisodePlan(
        project_id="demo-project", episode_number=1, title="第 1 集",
        source_chapter_start=1, source_chapter_end=1, target_duration_seconds=45,
        episode_goal="主角收到来信。", closing_hook="她决定去港口。",
        source_chunk_ids=["chunk-1"],
    )
    second = EpisodePlan(
        project_id="demo-project", episode_number=2, title="第 2 集",
        source_chapter_start=1, source_chapter_end=1, target_duration_seconds=45,
        episode_goal="主角进入仓库。", closing_hook="陌生人出现。",
        source_chunk_ids=["chunk-1"],
    )
    app = FastAPI()
    app.include_router(router)
    runtime = SimpleNamespace(repository=FakeRepository(make_profile(), [first, second]))
    app.dependency_overrides[get_narrative_runtime] = lambda: runtime

    response = TestClient(app).post(
        "/narrative/projects/demo-project/episodes/screenplay",
        json={"confirm_paid_call": True, "episode_number": 2},
    )

    assert response.status_code == 409
    assert "第 1 集" in response.json()["detail"]


def test_invalid_reviewer_model_output_is_reported_as_upstream_failure():
    try:
        _raise_domain_error(ScreenplayReviewOutputError("Reviewer 返回的内容不是合法 JSON。"))
    except HTTPException as error:
        assert error.status_code == 502
        assert "Reviewer" in error.detail
    else:
        raise AssertionError("模型输出错误应转换为 HTTP 502。")
