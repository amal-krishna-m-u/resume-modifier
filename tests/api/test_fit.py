"""Fit is a lookup, not a pipeline run — it must not start agents."""

from __future__ import annotations

from fastapi.testclient import TestClient

from resume_tailor.api.app import create_app
from resume_tailor.pipeline.artifacts import Run


def test_fit_returns_the_closest_completed_resume(project, tmp_path) -> None:
    run = Run.create(project / "runs", "backend-go")
    run.write(
        "posting",
        "Backend engineer. Required: Go, PostgreSQL, Kubernetes, and Kafka in production.",
    )
    run.write(
        "draft",
        {
            "summary": "Go APIs and PostgreSQL.",
            "sections": [
                {
                    "kind": "experience",
                    "bullets": [{"text": "Shipped Go services on PostgreSQL.", "sources": ["a"]}],
                }
            ],
        },
    )
    run.write("validation", {"verdict": "clean", "cuts": []})
    run.write("requirements", {"role_title": "Backend engineer"})

    with TestClient(create_app(project)) as client:
        r = client.post(
            "/api/fit",
            json={
                "text": "Lead backend role. Must have Go, PostgreSQL, and Kubernetes experience."
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["library_size"] == 1
    match = body["matches"][0]
    assert match["id"] == run.id
    assert match["recommend"] is True
    assert any("kubernetes" in g["text"].lower() for g in match["absent"])
