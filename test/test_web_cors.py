from fastapi.testclient import TestClient

from api import app


def test_vue_development_origin_can_call_video_api():
    client = TestClient(app)

    response = client.options(
        "/video/jobs",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
