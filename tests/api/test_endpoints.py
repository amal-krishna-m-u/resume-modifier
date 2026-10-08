"""HTTP behaviour: status codes, the error envelope, and SSE (spec-04 §3, §8)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FACT = {
    "id": "acme-new",
    "frontmatter": {
        "id": "acme-new",
        "type": "fact",
        "parent": "acme-engineer",
        "title": "A new fact",
        "tags": ["python"],
        "depth": "working",
        "verifiable": True,
        "visibility": "public",
    },
    "body": "The body text.",
}


# -- health ----------------------------------------------------------------


def test_health_reports_every_subsystem(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert set(body) == {"backend", "render", "corpus", "kb"}
    assert body["corpus"]["entries"] >= 1


def test_health_flags_whether_kb_could_be_published(client: TestClient) -> None:
    """Adding a remote to `kb/` is the single action that would publish the
    career record, and nothing else in the design prevents it (OQ-9)."""
    kb = client.get("/api/health").json()["kb"]
    assert kb["versioned"] is True
    assert kb["has_remote"] is False


# -- knowledge base --------------------------------------------------------


def test_index_lists_entries(client: TestClient) -> None:
    body = client.get("/api/kb/index").json()
    assert body["derived"] is True
    assert any(e["id"] == "acme-engineer" for e in body["entries"])


def test_read_returns_the_hash_a_save_must_echo(client: TestClient) -> None:
    body = client.get("/api/kb/role/acme-engineer").json()
    assert body["hash"] and body["raw"].startswith("---")


def test_create_then_update_round_trip(client: TestClient) -> None:
    created = client.post("/api/kb/fact", json=FACT)
    assert created.status_code == 200, created.text
    base_hash = created.json()["hash"]

    updated = client.put(
        "/api/kb/fact/acme-new",
        json={**FACT, "body": "Revised.", "base_hash": base_hash},
    )
    assert updated.status_code == 200
    assert "Revised." in client.get("/api/kb/fact/acme-new").json()["raw"]


def test_a_stale_save_returns_409_with_both_versions(client: TestClient) -> None:
    """So the UI can show a comparison rather than telling the user their work
    is gone (AC-R13.4)."""
    client.post("/api/kb/fact", json=FACT)
    response = client.put("/api/kb/fact/acme-new", json={**FACT, "base_hash": "0" * 64})
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "conflict"
    assert body["remedy"]
    assert "current" in body["detail"]


def test_invalid_content_returns_422_with_per_field_errors(client: TestClient) -> None:
    bad = {**FACT, "frontmatter": {**FACT["frontmatter"], "parent": "ghost"}}
    response = client.post("/api/kb/fact", json=bad)
    assert response.status_code == 422
    assert response.json()["detail"][0]["field"] == "parent"


def test_a_traversal_id_is_refused(client: TestClient) -> None:
    response = client.post("/api/kb/fact", json={**FACT, "id": "../../../etc/passwd"})
    assert response.status_code == 400
    assert response.json()["remedy"]


def test_deleting_a_referenced_entry_returns_409(client: TestClient) -> None:
    client.post("/api/kb/fact", json=FACT)
    response = client.delete("/api/kb/role/acme-engineer")
    assert response.status_code == 409
    assert "acme-new" in response.json()["message"]


def test_missing_entry_returns_404(client: TestClient) -> None:
    assert client.get("/api/kb/fact/nope").status_code == 404


def test_history_and_revert(client: TestClient) -> None:
    created = client.post("/api/kb/fact", json=FACT)
    client.put(
        "/api/kb/fact/acme-new",
        json={**FACT, "body": "Second version.", "base_hash": created.json()["hash"]},
    )
    commits = client.get("/api/kb/fact/acme-new/history").json()["commits"]
    assert len(commits) >= 2

    reverted = client.post("/api/kb/fact/acme-new/revert", json={"sha": commits[-1]["sha"]})
    assert reverted.status_code == 200
    assert "The body text." in client.get("/api/kb/fact/acme-new").json()["raw"]


def test_dry_run_validation_writes_nothing(client: TestClient, project: Path) -> None:
    raw = (
        "---\nid: acme-dry\ntype: fact\nparent: ghost\ntitle: Dry\n"
        "tags: [python]\ndepth: working\nverifiable: true\nvisibility: public\n---\n\nB.\n"
    )
    body = client.post(
        "/api/kb/validate", json={"type": "fact", "id": "acme-dry", "raw": raw}
    ).json()
    assert body["ok"] is False
    assert not (project / "kb" / "facts" / "acme-dry.md").exists()


def test_taxonomy_round_trip(client: TestClient) -> None:
    current = client.get("/api/taxonomy").json()
    terms = {**current["terms"], "kubernetes": {"label": "Kubernetes", "facet": "tech"}}
    response = client.put("/api/taxonomy", json={"terms": terms, "base_hash": current["hash"]})
    assert response.status_code == 200
    assert "kubernetes" in client.get("/api/taxonomy").json()["terms"]


def test_a_taxonomy_edit_that_breaks_the_kb_is_reverted(client: TestClient) -> None:
    """taxonomy.yaml is referenced by every entry, so a bad write breaks all of
    them at once. Rolled back rather than left on disk."""
    current = client.get("/api/taxonomy").json()
    response = client.put(
        "/api/taxonomy", json={"terms": {"python": {"label": "P"}}, "base_hash": current["hash"]}
    )
    assert response.status_code == 422
    assert client.get("/api/taxonomy").json()["terms"] == current["terms"]


# -- runs ------------------------------------------------------------------


def test_runs_list_is_empty_initially(client: TestClient) -> None:
    assert client.get("/api/runs").json()["runs"] == []


def test_a_run_without_text_is_refused(client: TestClient) -> None:
    response = client.post("/api/runs", json={})
    assert response.status_code == 400
    assert response.json()["remedy"]


def test_missing_run_returns_404(client: TestClient) -> None:
    assert client.get("/api/runs/nope").status_code == 404


# -- SSE -------------------------------------------------------------------


async def test_sse_routes_stream_events(project: Path) -> None:
    """Streaming rather than polling (AC-R14.2).

    Exercised against the ASGI app directly rather than through TestClient:
    an SSE stream never ends, and TestClient blocks on close waiting for a
    response that by design never completes. Pulling one frame and walking
    away is what a browser does anyway.
    """
    import asyncio

    from resume_tailor.api.app import create_app

    app = create_app(project)
    context = app.state.context

    for channel, publish in (
        (context.hub.kb, lambda: context.hub.kb.publish("kb-change", {"path": "x.md"})),
        (
            context.hub.run("r1"),
            lambda: context.hub.publish_stage("r1", "selector", "done", {"input": 19204}),
        ),
    ):
        stream = channel.subscribe()
        assert "open" in await asyncio.wait_for(anext(stream), timeout=2)
        publish()
        frame = await asyncio.wait_for(anext(stream), timeout=2)
        assert frame.startswith("event: ")
        await stream.aclose()


def test_sse_endpoints_are_registered(client: TestClient) -> None:
    paths = client.app.openapi()["paths"]
    assert "/api/events" in paths
    assert "/api/runs/{run_id}/events" in paths


def test_events_carry_token_counts(client: TestClient) -> None:
    """Cost accrues visibly during a run rather than being discovered when a
    rate limit lands (RK-2)."""
    from resume_tailor.api.events import format_event

    frame = format_event("stage", {"stage": "selector", "status": "done", "input": 19204})
    assert frame.startswith("event: stage\ndata: ")
    assert json.loads(frame.split("data: ", 1)[1])["input"] == 19204


def test_a_slow_subscriber_is_dropped_not_awaited() -> None:
    """A browser tab that stops reading must never stall a pipeline run."""
    import asyncio

    from resume_tailor.api.events import Channel

    async def exercise() -> None:
        channel = Channel(maxsize=2)
        stream = channel.subscribe()
        await anext(stream)
        for i in range(50):
            channel.publish("stage", {"i": i})  # must not raise or block

    asyncio.run(exercise())


# -- chat revision (R5) ----------------------------------------------------


def test_chat_before_a_draft_exists_is_refused(client: TestClient) -> None:
    client.post("/api/runs", json={"text": "A posting."})
    runs = client.get("/api/runs").json()["runs"]
    response = client.post(f"/api/runs/{runs[0]['id']}/chat", json={"message": "shorter"})
    assert response.status_code == 404
    assert response.json()["remedy"]


def test_an_empty_chat_message_is_refused(client: TestClient, project: Path) -> None:
    from resume_tailor.pipeline.artifacts import Run

    run = Run.create(project / "runs", "chat-run")
    run.write("draft", {"sections": []})
    response = client.post("/api/runs/chat-run/chat", json={"message": "   "})
    assert response.status_code == 400


def test_chat_history_is_empty_before_any_turn(client: TestClient, project: Path) -> None:
    from resume_tailor.pipeline.artifacts import Run

    Run.create(project / "runs", "fresh")
    assert client.get("/api/runs/fresh/chat").json()["turns"] == []


def test_identity_reports_contact_sets(client: TestClient) -> None:
    """The UI renders one export button per configured set (R17)."""
    body = client.get("/api/identity").json()
    assert body["configured"] is True
    assert body["contact_sets"] == ["default"]


# -- in-progress runs stay visible -----------------------------------------


async def test_a_new_subscriber_is_replayed_recent_events() -> None:
    """Found by using it: navigating away from a running job and back showed
    an empty progress panel until the next stage happened to finish — which on
    the selection stage is a minute of looking at nothing while the run is
    healthy."""
    import asyncio

    from resume_tailor.api.events import Channel

    channel = Channel()
    channel.publish("stage", {"stage": "analyst", "status": "done"})
    channel.publish("stage", {"stage": "selector", "status": "running"})

    stream = channel.subscribe()
    assert "open" in await asyncio.wait_for(anext(stream), timeout=2)

    replayed = [
        await asyncio.wait_for(anext(stream), timeout=2),
        await asyncio.wait_for(anext(stream), timeout=2),
    ]
    assert "analyst" in replayed[0]
    assert "selector" in replayed[1]
    await stream.aclose()


async def test_the_replay_buffer_is_bounded() -> None:
    """A long-lived channel must not grow without limit."""
    from resume_tailor.api.events import Channel

    channel = Channel(history_size=4)
    for i in range(50):
        channel.publish("stage", {"i": i})
    assert len(channel._history) == 4


async def test_a_fresh_attempt_clears_the_replay() -> None:
    """Otherwise a re-run shows the previous attempt's stages as its own."""
    import asyncio

    from resume_tailor.api.events import Channel

    channel = Channel()
    channel.publish("stage", {"stage": "analyst", "status": "done"})
    channel.reset()

    stream = channel.subscribe()
    assert "open" in await asyncio.wait_for(anext(stream), timeout=2)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(stream), timeout=0.3)
    await stream.aclose()


def test_the_runs_list_marks_which_are_live(client: TestClient, project: Path) -> None:
    """On disk a half-finished run and an abandoned one look identical, so
    liveness has to come from the process that owns the task."""
    from resume_tailor.pipeline.artifacts import Run

    Run.create(project / "runs", "quiet")
    rows = {row["id"]: row for row in client.get("/api/runs").json()["runs"]}
    assert rows["quiet"]["running"] is False
    assert rows["quiet"]["complete"] is False

    client.app.state.context.active_runs.add("quiet")
    rows = {row["id"]: row for row in client.get("/api/runs").json()["runs"]}
    assert rows["quiet"]["running"] is True


def test_run_detail_reports_liveness_and_completion(client: TestClient, project: Path) -> None:
    from resume_tailor.pipeline.artifacts import Run

    run = Run.create(project / "runs", "detail")
    assert client.get("/api/runs/detail").json()["complete"] is False

    run.write("validation", {"verdict": "clean", "clean": True})
    body = client.get("/api/runs/detail").json()
    assert body["complete"] is True
    assert body["running"] is False


# -- exports are downloadable and identifiable ------------------------------


def test_exports_carry_a_meaningful_filename(client: TestClient, project: Path) -> None:
    """Without this the browser saves every export as `export.pdf`, so the
    second becomes `export (1).pdf` and nobody can tell which posting either
    was for."""
    from resume_tailor.pipeline.artifacts import Run

    run = Run.create(project / "runs", "2026-10-07-acme-backend")
    run.write(
        "draft",
        {
            "sections": [
                {
                    "kind": "experience",
                    "role_id": "acme-engineer",
                    "bullets": [{"text": "Built it.", "sources": ["acme-pipeline"]}],
                }
            ]
        },
    )
    response = client.get("/api/runs/2026-10-07-acme-backend/export.tex")
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert "2026-10-07-acme-backend" in disposition
    assert disposition.endswith('.tex"')


def test_exporting_a_run_with_no_draft_is_refused(client: TestClient, project: Path) -> None:
    from resume_tailor.pipeline.artifacts import Run

    Run.create(project / "runs", "nodraft")
    response = client.get("/api/runs/nodraft/export.tex")
    assert response.status_code == 404
    assert response.json()["remedy"]


def test_pdf_preview_is_inline_and_download_is_attachment(
    client: TestClient, project: Path
) -> None:
    """An attachment disposition forces a save dialog, which makes an <iframe>
    show nothing — so the in-app preview needs its own."""
    from resume_tailor.pipeline.artifacts import Run
    from resume_tailor.render.compile import available

    if not available():
        pytest.skip("tectonic is not installed")

    run = Run.create(project / "runs", "preview-run")
    run.write(
        "draft",
        {
            "sections": [
                {
                    "kind": "experience",
                    "role_id": "acme-engineer",
                    "bullets": [{"text": "Built it.", "sources": ["acme-pipeline"]}],
                }
            ]
        },
    )
    inline = client.get("/api/runs/preview-run/export.pdf?inline=true")
    assert inline.status_code == 200
    assert inline.headers["content-disposition"].startswith("inline")

    download = client.get("/api/runs/preview-run/export.pdf")
    assert download.headers["content-disposition"].startswith("attachment")


def test_an_unknown_contact_set_is_a_404_with_a_remedy(client: TestClient, project: Path) -> None:
    """Found by driving the UI: it asked for a set before identity had loaded,
    and the server answered with a bare 500 — no code, no remedy, and nothing
    to say the request itself was wrong."""
    from resume_tailor.pipeline.artifacts import Run

    run = Run.create(project / "runs", "bad-set")
    run.write("draft", {"sections": []})

    response = client.get("/api/runs/bad-set/export.tex?contact_set=nonexistent")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "not_found"
    assert "default" in body["remedy"]  # names the sets that do exist


# -- which facts real runs lean on -----------------------------------------


def test_usage_counts_how_often_runs_select_each_fact(client: TestClient, project: Path) -> None:
    """Which entries to expand first is a better question than which are
    thinnest: a thin entry every run leans on matters more than a thin one no
    posting ever matches."""
    from resume_tailor.pipeline.artifacts import Run

    for name, strength in (("a", "strong"), ("b", "weak")):
        run = Run.create(project / "runs", name)
        run.write("merged", {"facts": [{"fact_id": "acme-pipeline", "strength": strength}]})

    body = client.get("/api/kb/usage").json()
    assert body["runs"] == 2
    assert body["facts"]["acme-pipeline"] == {"runs": 2, "strong": 1}


def test_a_corrupt_run_does_not_hide_the_others(client: TestClient, project: Path) -> None:
    from resume_tailor.pipeline.artifacts import Run

    good = Run.create(project / "runs", "good")
    good.write("merged", {"facts": [{"fact_id": "acme-pipeline", "strength": "strong"}]})
    bad = Run.create(project / "runs", "bad")
    bad.path("merged").write_text("{ not json", encoding="utf-8")

    body = client.get("/api/kb/usage").json()
    assert body["runs"] == 1
    assert "acme-pipeline" in body["facts"]


def test_usage_with_no_runs_is_empty_not_an_error(client: TestClient) -> None:
    assert client.get("/api/kb/usage").json() == {"runs": 0, "facts": {}}


# -- run titles --------------------------------------------------------------


def test_runs_are_listed_by_a_human_title(client: TestClient, project: Path) -> None:
    from resume_tailor.pipeline.artifacts import Run

    run = Run.create(project / "runs", "2026-10-07-visa-untitled")
    run.write("requirements", {"role_title": "SW Engineer (GenAI)", "requirements": []})
    run.write("meta", {"company": "Visa"})

    row = client.get("/api/runs").json()["runs"][0]
    assert row["title"] == "SW Engineer (GenAI)"
    assert row["company"] == "Visa"


def test_a_run_can_be_renamed_without_moving_it(client: TestClient, project: Path) -> None:
    """The folder name is permanent — applications and snapshots refer to it —
    so renaming sets a display title and touches nothing else."""
    from resume_tailor.pipeline.artifacts import Run

    Run.create(project / "runs", "2026-10-07-x")
    body = client.patch("/api/runs/2026-10-07-x", json={"title": "Visa — GenAI role"}).json()
    assert body["title"] == "Visa — GenAI role"
    assert (project / "runs" / "2026-10-07-x").is_dir()

    cleared = client.patch("/api/runs/2026-10-07-x", json={"title": ""}).json()
    assert cleared["title"] != "Visa — GenAI role"  # falls back to the computed one


def test_a_new_run_is_named_from_its_posting(client: TestClient) -> None:
    run_id = client.post(
        "/api/runs", json={"text": "Senior Backend Engineer\nWe hire.", "company": "Acme"}
    ).json()["run_id"]
    assert "untitled" not in run_id
    assert "acme" in run_id and "senior-backend-engineer" in run_id


def test_an_absurd_title_is_refused(client: TestClient, project: Path) -> None:
    from resume_tailor.pipeline.artifacts import Run

    Run.create(project / "runs", "r")
    assert client.patch("/api/runs/r", json={"title": "x" * 500}).status_code == 400


# -- nothing is downloadable mid-revision ------------------------------------


def _drafted_run(project: Path, name: str):
    from resume_tailor.pipeline.artifacts import Run

    run = Run.create(project / "runs", name)
    run.write(
        "draft",
        {
            "sections": [
                {
                    "kind": "experience",
                    "role_id": "acme-engineer",
                    "bullets": [{"text": "Built it.", "sources": ["acme-pipeline"]}],
                }
            ]
        },
    )
    return run


def test_export_is_refused_while_a_revision_is_running(client: TestClient, project: Path) -> None:
    """Between the Writer finishing and the Validator finishing, draft.json is
    the NEW draft and validation.json the OLD verdict. Exporting then would
    apply old cuts to new text and could hand over claims nobody has checked —
    the one thing the validator exists to prevent."""
    _drafted_run(project, "mid-revision")
    client.app.state.context.active_runs.add("mid-revision")

    for path in ("export.tex", "export.pdf"):
        response = client.get(f"/api/runs/mid-revision/{path}")
        assert response.status_code == 409, path
        assert response.json()["code"] == "run_busy"
        assert response.json()["remedy"]


def test_export_works_again_once_the_revision_ends(client: TestClient, project: Path) -> None:
    _drafted_run(project, "after-revision")
    client.app.state.context.active_runs.add("after-revision")
    assert client.get("/api/runs/after-revision/export.tex").status_code == 409
    client.app.state.context.active_runs.discard("after-revision")
    assert client.get("/api/runs/after-revision/export.tex").status_code == 200


def test_a_second_revision_is_refused_while_one_is_running(
    client: TestClient, project: Path
) -> None:
    _drafted_run(project, "double")
    client.app.state.context.active_runs.add("double")
    response = client.post("/api/runs/double/chat", json={"message": "again"})
    assert response.status_code == 409 and response.json()["code"] == "run_busy"
