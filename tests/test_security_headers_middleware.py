import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette import status

from app.security.headers import (
    MAX_REQUEST_BODY_SIZE_BYTES,
    SecurityHeadersAndBodySizeMiddleware,
)


@pytest.fixture
def middleware_app():
    test_app = FastAPI()
    test_app.add_middleware(SecurityHeadersAndBodySizeMiddleware)

    @test_app.get("/ping")
    def ping():
        return {"status": "ok"}

    @test_app.post("/upload")
    async def upload(request: Request):
        data = await request.body()
        return {"received_bytes": len(data)}

    return test_app


def test_security_headers_present_on_response(middleware_app):
    client = TestClient(middleware_app)
    response = client.get("/ping")

    assert response.status_code == 200
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


def test_request_body_under_limit_accepted(middleware_app):
    client = TestClient(middleware_app)
    payload = b"test payload" * 100
    response = client.post("/upload", content=payload)

    assert response.status_code == 200
    assert response.json()["received_bytes"] == len(payload)
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


def test_request_body_over_limit_via_content_length_header_rejected(middleware_app):
    client = TestClient(middleware_app)
    headers = {"Content-Length": str(MAX_REQUEST_BODY_SIZE_BYTES + 1)}
    response = client.post("/upload", headers=headers, content=b"a")

    assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    assert "exceeds 25 MB limit" in response.json()["detail"]
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


def test_main_app_includes_security_headers():
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/health")

    assert response.status_code in (200, 503)
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
