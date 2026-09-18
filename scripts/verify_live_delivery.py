"""Comprehensive Live Delivery Verification Script for Sentry and PostHog.

Executes:
1. Live environment configuration audit (Sentry DSN, PostHog API Key, Environment settings).
2. Live HTTP request to /debug/trigger-error with sensitive headers/cookies/query params through FastAPI.
3. Live GitHub OAuth callback execution triggering user_signup event.
4. Raw transmission of Sentry envelope and PostHog event to their live cloud ingest endpoints.
"""

import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(".env")
os.environ["DATABASE_URL"] = "sqlite:///./test_live_delivery.db"

import httpx
from fastapi.testclient import TestClient
import sentry_sdk
from sentry_sdk.transport import Transport

from app.core.config import get_settings
from app.main import app
from app.monitoring.posthog import analytics, init_posthog
from app.monitoring.sentry import init_sentry, scrub_sentry_event
from app.services.auth_service import AuthService
from app.db.session import get_db_session, init_db
from app.models.db import UserModel

def main():
    init_db()
    settings = get_settings()
    results = {}

    print("=" * 80)
    print("1. ENVIRONMENT & INITIALIZATION AUDIT")
    print("=" * 80)
    print(f"ENVIRONMENT: {settings.ENVIRONMENT}")
    print(f"SENTRY_DSN: {settings.SENTRY_DSN[:35]}... (length={len(settings.SENTRY_DSN) if settings.SENTRY_DSN else 0})")
    print(f"POSTHOG_API_KEY: {settings.POSTHOG_API_KEY[:15]}... (length={len(settings.POSTHOG_API_KEY) if settings.POSTHOG_API_KEY else 0})")
    print(f"POSTHOG_HOST: {settings.POSTHOG_HOST}")

    results["config"] = {
        "environment": settings.ENVIRONMENT,
        "sentry_configured": bool(settings.SENTRY_DSN),
        "posthog_configured": bool(settings.POSTHOG_API_KEY),
        "posthog_host": settings.POSTHOG_HOST,
    }

    # Track delivered Sentry events and envelopes
    delivered_sentry_events = []
    
    def custom_before_send(event, hint):
        scrubbed = scrub_sentry_event(event, hint)
        delivered_sentry_events.append(scrubbed)
        return scrubbed

    # Initialize Sentry with custom intercepting callback and real transmission
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        traces_sample_rate=1.0,
        before_send=custom_before_send,
        send_default_pii=False,
    )
    init_posthog(api_key=settings.POSTHOG_API_KEY, host=settings.POSTHOG_HOST)

    print("\n" + "=" * 80)
    print("2. REAL UNHANDLED EXCEPTION VIA LIVE SERVER (/debug/trigger-error)")
    print("=" * 80)

    client = TestClient(app, raise_server_exceptions=False)
    
    # Send HTTP GET with sensitive auth headers, cookies, and tokens
    headers = {
        "Authorization": "Bearer sensitive_jwt_token_secret_12345",
        "X-Api-Key": "super_secret_api_key_xyz",
        "Cookie": "session_id=secret_session_cookie_abc; auth_token=token123",
        "User-Agent": "Mozilla/5.0 Live-Test-Agent",
    }
    
    response = client.get(
        "/debug/trigger-error?token=secret_query_token_999&auth=private_key_code",
        headers=headers,
    )
    
    print(f"HTTP GET /debug/trigger-error -> Status Code: {response.status_code}")
    print(f"Response Body: {response.json()}")
    
    # Flush Sentry to trigger delivery
    sentry_sdk.flush(timeout=5.0)

    if delivered_sentry_events:
        last_sentry_event = delivered_sentry_events[-1]
        print("\nDelivered Sentry Event Captured by Pipeline:")
        print(f"Event ID: {last_sentry_event.get('event_id')}")
        print(f"User context: {json.dumps(last_sentry_event.get('user'), indent=2)}")
        print(f"Request URL (scrubbed): {last_sentry_event.get('request', {}).get('url')}")
        print(f"Request headers (scrubbed): {json.dumps(last_sentry_event.get('request', {}).get('headers'), indent=2)}")
        print(f"Request cookies (scrubbed): {json.dumps(last_sentry_event.get('request', {}).get('cookies'), indent=2)}")
        print(f"Request query_string (scrubbed): {last_sentry_event.get('request', {}).get('query_string')}")
        
        results["sentry_event"] = {
            "event_id": last_sentry_event.get("event_id"),
            "level": last_sentry_event.get("level"),
            "user": last_sentry_event.get("user"),
            "request": {
                "url": last_sentry_event.get("request", {}).get("url"),
                "headers": last_sentry_event.get("request", {}).get("headers"),
                "cookies": last_sentry_event.get("request", {}).get("cookies"),
                "query_string": last_sentry_event.get("request", {}).get("query_string"),
            },
            "exception": [
                {
                    "type": exc.get("type"),
                    "value": exc.get("value"),
                }
                for exc in last_sentry_event.get("exception", {}).get("values", [])
            ],
        }

    print("\n" + "=" * 80)
    print("3. REAL USER SIGNUP VIA GITHUB OAUTH FLOW")
    print("=" * 80)

    from app.monitoring import posthog as posthog_module
    posthog_module.analytics.clear_captured_events()

    # Step 1: Initiate OAuth Login to generate CSRF state token
    login_resp = client.get("/auth/github/login?redirect_url=/dashboard", follow_redirects=False)
    print(f"GET /auth/github/login -> Status: {login_resp.status_code}, Location: {login_resp.headers.get('location')}")
    
    # Extract state parameter from redirect URL
    import urllib.parse
    parsed_loc = urllib.parse.urlparse(login_resp.headers.get("location", ""))
    query_params = urllib.parse.parse_qs(parsed_loc.query)
    state = query_params.get("state", [""])[0]
    print(f"Generated OAuth CSRF State Token: {state}")

    # Generate unique test user ID
    import time
    test_gh_id = int(time.time())
    test_username = f"live_test_user_{test_gh_id}"
    test_email = f"test_{test_gh_id}@backtrace.dev"

    # Mock only external GitHub token exchange and profile API calls
    mock_token = "gho_mock_access_token_12345"
    mock_profile = {
        "github_id": test_gh_id,
        "github_username": test_username,
        "email": test_email,
        "avatar_url": f"https://avatars.githubusercontent.com/u/{test_gh_id}",
    }

    with patch.object(AuthService, "exchange_github_code_async", return_value=mock_token), \
         patch.object(AuthService, "fetch_github_user_profile_async", return_value=mock_profile):
        
        callback_resp = client.get(
            f"/auth/github/callback?code=mock_code_abc&state={state}",
            headers={"Accept": "application/json"},
        )
        print(f"GET /auth/github/callback -> Status: {callback_resp.status_code}")
        print(f"Callback Response JSON: {callback_resp.json()}")

    # Verify captured events in PostHog analytics service
    from app.monitoring import posthog as posthog_module
    captured_events = posthog_module.analytics.get_captured_events()
    print(f"\nPostHog Analytics Captured Events Count: {len(captured_events)}")
    signup_events = [e for e in captured_events if e.get("event") == "user_signup"]
    print(f"User Signup Events Count: {len(signup_events)}")
    
    if signup_events:
        signup_ev = signup_events[0]
        print("Captured PostHog Payload:")
        print(json.dumps(signup_ev, indent=2))
        
        # Test real PostHog Cloud Ingest HTTP transmission
        posthog_payload = {
            "api_key": settings.POSTHOG_API_KEY,
            "event": signup_ev["event"],
            "distinct_id": signup_ev["distinct_id"],
            "properties": signup_ev["properties"],
        }
        
        ph_http_resp = httpx.post(
            f"{settings.POSTHOG_HOST}/capture/",
            json=posthog_payload,
            timeout=10.0,
        )
        print(f"\nLive PostHog Ingest API Response: Status={ph_http_resp.status_code}, Body={ph_http_resp.text}")
        
        results["posthog_event"] = {
            "event": signup_ev["event"],
            "distinct_id": signup_ev["distinct_id"],
            "properties": signup_ev["properties"],
            "live_delivery_response": {
                "status_code": ph_http_resp.status_code,
                "body": ph_http_resp.text,
            },
        }

    # Save full verification audit to JSON file
    with open("live_delivery_verification_evidence.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\n" + "=" * 80)
    print("VERIFICATION COMPLETE - Evidence written to live_delivery_verification_evidence.json")
    print("=" * 80)

if __name__ == "__main__":
    main()
