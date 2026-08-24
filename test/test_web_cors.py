import pytest
from fastapi.testclient import TestClient

from api import app


@pytest.mark.parametrize("origin", [
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "http://localhost:5174",
])
def test_vue_development_origin_can_call_project_api(origin: str):
    client = TestClient(app)

    response = client.options(
        "/narrative/projects",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
