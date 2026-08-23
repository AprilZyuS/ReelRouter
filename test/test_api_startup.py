import importlib
import sys


def test_video_api_module_does_not_require_legacy_deepseek_key_at_startup(monkeypatch):
    """仅使用视频 API 时，不应被早期调研练习的环境变量阻断。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    sys.modules.pop("api", None)

    api = importlib.import_module("api")

    assert any(route.path == "/health" for route in api.app.routes)
    assert any(route.path == "/video/jobs" for route in api.app.routes)
