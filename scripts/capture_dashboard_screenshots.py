"""
Script to capture evidence screenshots of the redesigned dashboard at 1440px and 390px.
Saves images to scratch/dashboard/dashboard_1440px.png and scratch/dashboard/dashboard_390px.png.
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

from app.models.db import UserModel
from app.ui.components import dashboard_view


def generate_screenshots():
    out_dir = Path("scratch/dashboard")
    out_dir.mkdir(parents=True, exist_ok=True)

    user = UserModel(id=1, github_id=99999, github_username="alexdev", email="alex@example.com")

    class MockJob:
        def __init__(self, id, repo_url, repo_name, status, runs, verified, total, exec_time, dt_delta_hours):
            self.id = id
            self.repo_url = repo_url
            self.repo_name = repo_name
            self.status = status
            self.runs = runs
            self.execution_time_seconds = exec_time
            self.created_at = datetime.fromtimestamp(1761270000 - dt_delta_hours * 3600, tz=timezone.utc)
            self.graph_data = {"nodes": [{"tier": i + 1} for i in range(total)]}
            self.markdown_output = None
            self.milestone_attempts = [
                type("Attempt", (), {"status": "structurally_verified"}) for _ in range(verified)
            ]
        def __getitem__(self, item):
            return getattr(self, item)

    past_jobs = [
        MockJob(
            id=101,
            repo_url="https://github.com/expressjs/express",
            repo_name="express",
            status="completed",
            runs=3,
            verified=2,
            total=7,
            exec_time=14.2,
            dt_delta_hours=2,
        ),
        MockJob(
            id=102,
            repo_url="https://github.com/tiangolo/fastapi",
            repo_name="fastapi",
            status="completed",
            runs=1,
            verified=5,
            total=5,
            exec_time=8.6,
            dt_delta_hours=24,
        ),
        MockJob(
            id=103,
            repo_url="https://github.com/pallets/flask",
            repo_name="flask",
            status="running",
            runs=1,
            verified=1,
            total=6,
            exec_time=4.1,
            dt_delta_hours=48,
        ),
    ]

    os.environ["STRIPE_BILLING_ENABLED"] = "true"
    html = dashboard_view(
        current_user=user,
        billing_status={"tier": "free", "monthly_usage": 2, "monthly_quota": 5},
        past_jobs=past_jobs,
    )

    css_path = Path("static/style.css")
    css_content = css_path.read_text(encoding="utf-8") if css_path.exists() else ""
    if css_content and '<link rel="stylesheet" href="/static/style.css">' in html:
        html = html.replace(
            '<link rel="stylesheet" href="/static/style.css">',
            f'<style>\n{css_content}\n</style>'
        )

    temp_html_path = out_dir / "preview.html"
    temp_html_path.write_text(html, encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # 1. Desktop screenshot at 1440px width
        context_1440 = browser.new_context(viewport={"width": 1440, "height": 900})
        page_1440 = context_1440.new_page()
        page_1440.goto(temp_html_path.resolve().as_uri(), wait_until="networkidle")
        page_1440.wait_for_timeout(500)
        path_1440 = out_dir / "dashboard_1440px.png"
        page_1440.screenshot(path=str(path_1440), full_page=True)
        print(f"Captured 1440px screenshot: {path_1440.resolve()}")
        context_1440.close()

        # 2. Mobile screenshot at 390px width
        context_390 = browser.new_context(viewport={"width": 390, "height": 844})
        page_390 = context_390.new_page()
        page_390.goto(temp_html_path.resolve().as_uri(), wait_until="networkidle")
        page_390.wait_for_timeout(500)
        path_390 = out_dir / "dashboard_390px.png"
        page_390.screenshot(path=str(path_390), full_page=True)
        print(f"Captured 390px screenshot: {path_390.resolve()}")
        context_390.close()

        browser.close()


if __name__ == "__main__":
    generate_screenshots()
