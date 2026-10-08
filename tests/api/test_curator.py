"""The knowledge-base chat (AC-R13.2, AC-R13.3, spec-04 §6.8).

The assistant proposes; the person accepts; accepting goes through the same
validated write path as the form. Each test below names a way this could go
wrong for someone who is trusting the chat not to make mistakes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from resume_tailor.config import Config
from resume_tailor.kb.compose import apply_changes, compose_entry, join_todo, split_todo
from resume_tailor.kb.loader import load_corpus, parse_entry
from resume_tailor.kb.write import Conflict, ValidationFailed, WriteError, content_hash
from resume_tailor.pipeline.curator import (
    ChatStore,
    accept,
    build_proposal,
    conversation_block,
    curate,
    reject,
    supersede,
)
from resume_tailor.runtime.fake import FakeRunner


def tree(kb: Path) -> dict[str, str]:
    """Every file under kb/, for asserting that nothing was written."""
    return {
        str(p.relative_to(kb)): p.read_text(encoding="utf-8")
        for p in sorted(kb.rglob("*"))
        if p.is_file() and ".git" not in p.parts
    }


def kb_of(project: Path) -> Path:
    return project / "kb"


FACT = {
    "op": "create",
    "type": "fact",
    "id": "acme-new",
    "reason": "a separate achievement",
    "fields": {
        "title": "A new achievement",
        "parent": "acme-engineer",
        "tags": ["python"],
        "depth": "working",
    },
    "body": "Built the thing and measured it.",
}


# ---------------------------------------------------------------- compose


def test_compose_matches_the_house_style() -> None:
    """A change should show in git as the change, not as a reformat."""
    text = compose_entry(
        "fact",
        {
            "id": "x-y",
            "parent": "acme",
            "title": "A: tricky title",
            "tags": ["a", "b"],
            "metrics": [{"value": "40%", "what": "less toil"}],
        },
        "Body.",
    )
    assert "tags: [a, b]" in text
    assert 'title: "A: tricky title"' in text  # quoted only because it must be
    assert '  - {value: "40%", what: less toil}' in text
    assert text.index("id:") < text.index("type:") < text.index("title:")


def test_compose_quotes_what_yaml_would_misread() -> None:
    text = compose_entry("fact", {"id": "x", "title": "yes", "parent": "p"}, "b")
    assert 'title: "yes"' in text  # bare `yes` is a boolean to YAML


def test_split_and_join_todo_round_trip() -> None:
    body = "Real prose.\n\n<!-- TODO: add the scale and the failure modes -->\n"
    text, note = split_todo(body)
    assert text == "Real prose." and note == "add the scale and the failure modes"
    assert "TODO" in join_todo(text, note)
    assert join_todo(text, None) == "Real prose."


def test_appending_cannot_lose_existing_text_or_the_todo(kb: Path) -> None:
    path = kb / "facts" / "acme-pipeline.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\n<!-- TODO: say what made it hard -->\n",
        encoding="utf-8",
    )
    entry = parse_entry(path)
    _, body = apply_changes(entry.frontmatter, entry.body, {"body_append": "New detail."})
    assert "Built the pipeline." in body
    assert "New detail." in body
    assert "TODO: say what made it hard" in body, (
        "the note is cleared by the user, not by a proposal"
    )


def test_add_tags_never_duplicates_or_removes(kb: Path) -> None:
    entry = parse_entry(kb / "facts" / "acme-pipeline.md")
    fm, _ = apply_changes(entry.frontmatter, entry.body, {"add_tags": ["python", "go"]})
    assert list(fm["tags"]) == ["python", "rag", "go"]


def test_identity_cannot_be_changed_by_an_update(kb: Path) -> None:
    """Ids are permanent. A model that "renames" an entry creates an orphan."""
    entry = parse_entry(kb / "facts" / "acme-pipeline.md")
    fm, _ = apply_changes(
        entry.frontmatter, entry.body, {"fields": {"id": "other", "type": "role"}}
    )
    assert fm["id"] == "acme-pipeline" and fm["type"] == "fact"


def test_frontmatter_comments_survive_an_update(kb: Path) -> None:
    path = kb / "facts" / "acme-pipeline.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "depth: working", "# keep this note\ndepth: working"
        ),
        encoding="utf-8",
    )
    from resume_tailor.kb.write import compose

    entry = parse_entry(path)
    fm, body = apply_changes(entry.frontmatter, entry.body, {"add_tags": ["go"]})
    assert "# keep this note" in compose(fm, body)


# -------------------------------------------------------------- proposals


def test_a_valid_create_is_pre_validated(project: Path) -> None:
    proposal = build_proposal(kb_of(project), FACT)
    assert proposal["errors"] == []
    assert proposal["status"] == "pending"
    assert parse_entry(kb_of(project) / "facts" / "acme-new.md", proposal["raw"]).id == "acme-new"


def test_nothing_is_written_by_proposing(project: Path) -> None:
    """The whole point. Proposing is reading; only accepting writes."""
    before = tree(kb_of(project))
    build_proposal(kb_of(project), FACT)
    assert tree(kb_of(project)) == before


def test_creating_an_id_that_exists_is_an_error(project: Path) -> None:
    proposal = build_proposal(kb_of(project), {**FACT, "id": "acme-engineer", "type": "role"})
    assert any(e["code"] == "exists" for e in proposal["errors"])


def test_a_dangling_parent_is_reported_before_you_look(project: Path) -> None:
    bad = {**FACT, "fields": {**FACT["fields"], "parent": "ghost"}}
    assert any(
        "parent" in (e["field"] or "") for e in build_proposal(kb_of(project), bad)["errors"]
    )


def test_a_new_role_and_a_fact_under_it_in_one_message(project: Path) -> None:
    """Without the overlay the fact would always report a parent that "does
    not exist", because the role it hangs off is itself only a proposal."""
    role = {
        "op": "create",
        "type": "role",
        "id": "newco-engineer",
        "reason": "new job",
        "fields": {
            "title": "Engineer",
            "org": "NewCo",
            "dates": {"start": "2026-06"},
            "tags": ["python"],
            "depth": "working",
        },
        "body": "Backend work at NewCo.",
    }
    fact = {**FACT, "id": "newco-thing", "fields": {**FACT["fields"], "parent": "newco-engineer"}}

    role_proposal = build_proposal(kb_of(project), role)
    fact_proposal = build_proposal(
        kb_of(project), fact, (("role", "newco-engineer", role_proposal["raw"]),)
    )
    assert role_proposal["errors"] == []
    assert fact_proposal["errors"] == []
    assert fact_proposal["depends_on"] == ["newco-engineer"]


def test_update_shows_exactly_what_changes(project: Path) -> None:
    from ..conftest import write_entry

    write_entry(
        kb_of(project),
        "facts",
        "acme-pipeline",
        """
        id: acme-pipeline
        type: fact
        parent: acme-engineer
        title: Ingestion pipeline
        tags: [python]
        depth: working
        verifiable: true
        visibility: public
    """,
        "Built the pipeline.",
    )

    proposal = build_proposal(
        kb_of(project),
        {
            "op": "update",
            "type": "fact",
            "id": "acme-pipeline",
            "add_tags": ["rag"],
            "body_append": "Evaluated it against a labelled set.",
        },
    )
    assert proposal["errors"] == []
    assert [c["field"] for c in proposal["fields_changed"]] == ["tags"]
    assert proposal["body_before"] == "Built the pipeline."
    assert proposal["body_added"] == "Evaluated it against a labelled set."
    assert proposal["body_after"].endswith("labelled set.")
    assert proposal["base_hash"], "needed to refuse a stale accept"


def test_updating_something_that_does_not_exist_is_an_error(project: Path) -> None:
    proposal = build_proposal(
        kb_of(project), {"op": "update", "type": "fact", "id": "nope", "body_append": "x"}
    )
    assert proposal["errors"]


def test_an_update_that_changes_nothing_is_flagged(project: Path) -> None:
    proposal = build_proposal(
        kb_of(project),
        {"op": "update", "type": "role", "id": "acme-engineer", "add_tags": ["python"]},
    )
    assert any(e["code"] == "noop" for e in proposal["errors"])


def test_an_unknown_tag_warns_and_does_not_block(project: Path) -> None:
    """Tags describe and do not gate (P5)."""
    proposal = build_proposal(
        kb_of(project), {**FACT, "fields": {**FACT["fields"], "tags": ["python", "kubernetes"]}}
    )
    assert proposal["errors"] == []
    assert any(w["code"] == "tag-unknown" for w in proposal["warnings"])


def test_an_invented_field_is_refused_not_ignored(project: Path) -> None:
    """A made-up field silently doing nothing is how a wrong visibility ships."""
    proposal = build_proposal(
        kb_of(project), {**FACT, "fields": {**FACT["fields"], "visibilty": "nda"}}
    )
    assert proposal["errors"]


@pytest.mark.parametrize("hostile", ["../../etc/passwd", "a/b", "A B", ".."])
def test_a_hostile_id_is_refused(project: Path, hostile: str) -> None:
    before = tree(kb_of(project))
    proposal = build_proposal(kb_of(project), {**FACT, "id": hostile})
    assert proposal["errors"]
    assert tree(kb_of(project)) == before


def test_an_unknown_operation_is_refused(project: Path) -> None:
    assert build_proposal(kb_of(project), {**FACT, "op": "delete"})["errors"]


def test_deletion_is_not_something_the_assistant_can_propose(project: Path) -> None:
    """Deleting is the one action with no undo short of git history; it stays a
    deliberate, manual act in the editor."""
    proposal = build_proposal(
        kb_of(project), {"op": "delete", "type": "fact", "id": "acme-engineer"}
    )
    assert proposal["errors"] and not proposal["raw"]


# ------------------------------------------------------------------ curate


def scripted(reply: dict) -> FakeRunner:
    return FakeRunner({"curator": reply})


async def test_a_curator_turn_produces_validated_proposals(project: Path) -> None:
    corpus = load_corpus(kb_of(project))
    turn = await curate(
        scripted({"reply": "Here you go.", "questions": ["How many users?"], "proposals": [FACT]}),
        corpus,
        kb_of(project),
        Config(),
        [],
        "I built a thing.",
    )
    assert turn["text"] == "Here you go."
    assert turn["questions"] == ["How many users?"]
    assert turn["proposals"][0]["errors"] == []


async def test_curating_writes_nothing(project: Path) -> None:
    before = tree(kb_of(project))
    corpus = load_corpus(kb_of(project))
    await curate(
        scripted({"reply": "x", "proposals": [FACT]}), corpus, kb_of(project), Config(), [], "hi"
    )
    assert tree(kb_of(project)) == before


async def test_the_corpus_is_sent_before_the_conversation(project: Path) -> None:
    """Prompt caching: the stable corpus is the prefix (spec-03 §6)."""
    runner = scripted({"reply": "x", "proposals": []})
    await curate(runner, load_corpus(kb_of(project)), kb_of(project), Config(), [], "hello there")
    prompt = runner.calls["curator"][0]
    assert prompt.index("# KNOWLEDGE BASE") < prompt.index("hello there")
    assert "# TAXONOMY" in prompt


async def test_a_message_with_no_proposals_is_fine(project: Path) -> None:
    """Asking questions, or just talking, is a valid turn."""
    turn = await curate(
        scripted({"reply": "Tell me more.", "questions": ["Where?"], "proposals": []}),
        load_corpus(kb_of(project)),
        kb_of(project),
        Config(),
        [],
        "I did a thing.",
    )
    assert turn["proposals"] == [] and turn["questions"] == ["Where?"]


async def test_a_malformed_proposal_does_not_sink_the_turn(project: Path) -> None:
    turn = await curate(
        scripted({"reply": "ok", "proposals": ["not a dict", {"op": "create"}, FACT]}),
        load_corpus(kb_of(project)),
        kb_of(project),
        Config(),
        [],
        "x",
    )
    assert len(turn["proposals"]) == 2  # the junk string is dropped, the rest kept
    assert turn["proposals"][0]["errors"] and not turn["proposals"][1]["errors"]


def test_the_curator_can_see_what_happened_to_earlier_proposals() -> None:
    """One that cannot see a rejection proposes it again, and one that cannot
    see an acceptance proposes a duplicate of what now exists."""
    history = [
        {"role": "user", "text": "I built X"},
        {
            "role": "assistant",
            "text": "Proposing.",
            "questions": [],
            "proposals": [{"op": "create", "type": "fact", "entry_id": "x", "status": "rejected"}],
        },
    ]
    block = conversation_block(history)
    assert "rejected" in block and "I built X" in block


def test_a_revised_proposal_supersedes_the_old_one() -> None:
    """Otherwise revising by chat leaves the old version to be accepted by
    mistake — exactly the error this chat exists to prevent."""
    old = {
        "role": "assistant",
        "proposals": [{"op": "create", "entry_id": "x", "status": "pending"}],
    }
    new = {
        "role": "assistant",
        "proposals": [{"op": "create", "entry_id": "x", "status": "pending"}],
    }
    supersede([old], new)
    assert old["proposals"][0]["status"] == "superseded"


# ----------------------------------------------------------- accept/reject


def stored(project: Path, *proposals: dict) -> tuple[ChatStore, list[dict]]:
    store = ChatStore(project / "chats")
    built, overlay = [], []
    for raw in proposals:
        proposal = build_proposal(kb_of(project), raw, tuple(overlay))
        built.append(proposal)
        if proposal["raw"] and proposal["op"] == "create":
            overlay.append((proposal["type"], proposal["entry_id"], proposal["raw"]))
    store.append({"role": "assistant", "text": "x", "questions": [], "proposals": built})
    return store, built


def log(project: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(kb_of(project)), "log", "--oneline"], capture_output=True, text=True
    ).stdout


def test_accepting_writes_and_commits_to_the_kb_repo(project: Path) -> None:
    store, [proposal] = stored(project, FACT)
    result = accept(kb_of(project), store, proposal["id"], cache_dir=project / ".cache")
    assert result["status"] == "accepted" and result["commit"]
    assert (kb_of(project) / "facts" / "acme-new.md").is_file()
    assert "via chat" in log(project) and "acme-new" in log(project)


def test_accepting_goes_through_the_validated_write_path(project: Path) -> None:
    """AC-R13.3. A proposal made valid and then broken must still be refused."""
    store, [proposal] = stored(project, FACT)
    (kb_of(project) / "roles" / "acme-engineer.md").unlink()  # parent vanishes
    with pytest.raises(ValidationFailed):
        accept(kb_of(project), store, proposal["id"], cache_dir=None)
    assert not (kb_of(project) / "facts" / "acme-new.md").exists()


def test_a_proposal_with_errors_cannot_be_accepted(project: Path) -> None:
    store, [proposal] = stored(project, {**FACT, "fields": {**FACT["fields"], "parent": "ghost"}})
    assert proposal["errors"]
    with pytest.raises(ValidationFailed):
        accept(kb_of(project), store, proposal["id"], cache_dir=None)


def test_a_stale_update_is_a_conflict_not_an_overwrite(project: Path) -> None:
    """An update records the hash it was built against. If the file changed
    since — a text editor, another accepted proposal — accepting must not
    silently overwrite that."""
    from ..conftest import write_entry

    write_entry(
        kb_of(project),
        "facts",
        "acme-pipeline",
        """
        id: acme-pipeline
        type: fact
        parent: acme-engineer
        title: Ingestion pipeline
        tags: [python]
        depth: working
        verifiable: true
        visibility: public
    """,
        "Built it.",
    )
    store, [proposal] = stored(
        project, {"op": "update", "type": "fact", "id": "acme-pipeline", "body_append": "More."}
    )
    path = kb_of(project) / "facts" / "acme-pipeline.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nEdited in vim.\n", encoding="utf-8")

    with pytest.raises(Conflict):
        accept(kb_of(project), store, proposal["id"], cache_dir=None)
    assert "Edited in vim." in path.read_text(encoding="utf-8")


def test_a_dependent_proposal_waits_for_the_one_it_needs(project: Path) -> None:
    role = {
        "op": "create",
        "type": "role",
        "id": "newco-engineer",
        "reason": "job",
        "fields": {
            "title": "Engineer",
            "org": "NewCo",
            "dates": {"start": "2026-06"},
            "tags": ["python"],
            "depth": "working",
        },
        "body": "Work at NewCo.",
    }
    fact = {**FACT, "id": "newco-thing", "fields": {**FACT["fields"], "parent": "newco-engineer"}}
    store, [role_p, fact_p] = stored(project, role, fact)

    with pytest.raises(WriteError, match="newco-engineer"):
        accept(kb_of(project), store, fact_p["id"], cache_dir=None)

    accept(kb_of(project), store, role_p["id"], cache_dir=None)
    accept(kb_of(project), store, fact_p["id"], cache_dir=None)
    assert (kb_of(project) / "facts" / "newco-thing.md").is_file()


def test_a_proposal_cannot_be_accepted_twice(project: Path) -> None:
    store, [proposal] = stored(project, FACT)
    accept(kb_of(project), store, proposal["id"], cache_dir=None)
    with pytest.raises(WriteError, match="already accepted"):
        accept(kb_of(project), store, proposal["id"], cache_dir=None)


def test_rejecting_writes_nothing_and_cannot_later_be_accepted(project: Path) -> None:
    before = tree(kb_of(project))
    store, [proposal] = stored(project, FACT)
    assert reject(store, proposal["id"])["status"] == "rejected"
    assert tree(kb_of(project)) == before
    with pytest.raises(WriteError, match="already rejected"):
        accept(kb_of(project), store, proposal["id"], cache_dir=None)


def test_the_conversation_survives_a_restart(project: Path) -> None:
    """Held on disk, so returning to the page after navigating away shows what
    happened — the same lesson as run progress."""
    store, [proposal] = stored(project, FACT)
    reloaded = ChatStore(project / "chats")
    assert reloaded.find(proposal["id"]) is not None


def test_a_new_conversation_archives_the_old_one(project: Path) -> None:
    store, _ = stored(project, FACT)
    archived = store.archive()
    assert archived and archived.is_file()
    assert store.load() == []


def test_hash_helper_is_stable() -> None:
    assert content_hash("a") == content_hash("a") != content_hash("b")


# ======================================================================== API

import time  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from resume_tailor.runtime.base import BackendAuthError  # noqa: E402

REPLY = {
    "reply": "I'd record this as a separate achievement.",
    "questions": ["How many users did it serve?"],
    "proposals": [FACT],
}


def wait_idle(client: TestClient, timeout: float = 6.0) -> dict:
    """The assistant works in the background; poll until it has answered."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get("/api/kb/chat").json()
        if not body["running"]:
            return body
        time.sleep(0.05)
    raise AssertionError("the assistant never finished")


@pytest.fixture
def backend(monkeypatch):
    def install(runner: FakeRunner) -> None:
        monkeypatch.setattr("resume_tailor.api.app.build_backend", lambda _config: runner)

    return install


def test_the_conversation_starts_empty(client: TestClient) -> None:
    assert client.get("/api/kb/chat").json() == {"turns": [], "running": False, "scope": "kb"}


def test_sending_a_message_records_it_and_the_answer(client: TestClient, backend) -> None:
    backend(scripted(REPLY))
    assert client.post("/api/kb/chat", json={"message": "I built a thing."}).json() == {
        "running": True
    }
    turns = wait_idle(client)["turns"]
    assert [t["role"] for t in turns] == ["user", "assistant"]
    assert turns[0]["text"] == "I built a thing."
    assert turns[1]["proposals"][0]["entry_id"] == "acme-new"


def test_the_persons_message_is_visible_while_the_assistant_works(
    client: TestClient, backend
) -> None:
    """It is written before the model is called, so it is on screen — and still
    there after navigating away — while the answer is pending."""
    backend(scripted(REPLY))
    client.post("/api/kb/chat", json={"message": "I built a thing."})
    first = client.get("/api/kb/chat").json()
    assert first["turns"][0]["text"] == "I built a thing."
    wait_idle(client)


def test_nothing_is_written_until_you_accept(client: TestClient, backend, project: Path) -> None:
    before = tree(kb_of(project))
    backend(scripted(REPLY))
    client.post("/api/kb/chat", json={"message": "I built a thing."})
    wait_idle(client)
    assert tree(kb_of(project)) == before


def test_accepting_over_http_writes_the_entry(client: TestClient, backend, project: Path) -> None:
    backend(scripted(REPLY))
    client.post("/api/kb/chat", json={"message": "I built a thing."})
    proposal = wait_idle(client)["turns"][1]["proposals"][0]

    response = client.post(f"/api/kb/chat/proposals/{proposal['id']}/accept")
    assert response.status_code == 200
    assert response.json()["proposal"]["status"] == "accepted"
    assert (kb_of(project) / "facts" / "acme-new.md").is_file()
    assert client.get("/api/kb/index").json()["entries"], "the index reflects the write"


def test_accepting_an_invalid_proposal_is_a_422_with_reasons(client: TestClient, backend) -> None:
    bad = {**FACT, "fields": {**FACT["fields"], "parent": "ghost"}}
    backend(scripted({"reply": "x", "proposals": [bad]}))
    client.post("/api/kb/chat", json={"message": "x"})
    proposal = wait_idle(client)["turns"][1]["proposals"][0]

    response = client.post(f"/api/kb/chat/proposals/{proposal['id']}/accept")
    assert response.status_code == 422
    assert response.json()["remedy"]


def test_rejecting_marks_it_and_writes_nothing(client: TestClient, backend, project: Path) -> None:
    backend(scripted(REPLY))
    client.post("/api/kb/chat", json={"message": "x"})
    proposal = wait_idle(client)["turns"][1]["proposals"][0]
    before = tree(kb_of(project))

    assert (
        client.post(f"/api/kb/chat/proposals/{proposal['id']}/reject").json()["proposal"]["status"]
        == "rejected"
    )
    assert tree(kb_of(project)) == before


def test_a_failing_backend_shows_up_as_an_error_not_endless_thinking(
    client: TestClient, backend
) -> None:
    """The person is watching a box that says "thinking". A failure that only
    reached a log would leave it saying that forever."""
    backend(
        FakeRunner({"curator": {}}, fail_on={"curator": BackendAuthError("claude_sdk", "a login")})
    )
    client.post("/api/kb/chat", json={"message": "x"})
    body = wait_idle(client)
    assert body["running"] is False
    assert "claude_sdk" in body["turns"][-1]["error"]


def test_a_second_message_while_busy_is_refused(client: TestClient) -> None:
    client.app.state.context.chat_running.add("kb")
    response = client.post("/api/kb/chat", json={"message": "again"})
    assert response.status_code == 400
    assert response.json()["remedy"]


def test_an_empty_message_is_refused(client: TestClient) -> None:
    assert client.post("/api/kb/chat", json={"message": "  "}).status_code == 400


def test_starting_over_archives_the_conversation(client: TestClient, backend) -> None:
    backend(scripted(REPLY))
    client.post("/api/kb/chat", json={"message": "x"})
    wait_idle(client)
    assert client.delete("/api/kb/chat").json()["archived"].startswith("kb-chat-")
    assert client.get("/api/kb/chat").json()["turns"] == []


def test_the_chat_routes_do_not_shadow_entry_routes(client: TestClient) -> None:
    """`/kb/chat` shares a prefix with `/kb/{type}/{id}`; both must still work."""
    assert client.get("/api/kb/role/acme-engineer").status_code == 200
    assert client.get("/api/kb/chat").status_code == 200


# ============================================================ scoped + focused

from resume_tailor.pipeline.curator import focus_block  # noqa: E402


def test_each_entry_has_its_own_conversation(client: TestClient, backend) -> None:
    """Showing the whole history inside every entry's editor would be noise, and
    "add that it served 2,000 users" only means something beside its entry."""
    backend(scripted({"reply": "ok", "proposals": []}))
    client.post("/api/kb/chat", json={"message": "about the role", "scope": "acme-engineer"})
    wait_idle_scope(client, "acme-engineer")

    assert len(client.get("/api/kb/chat?scope=acme-engineer").json()["turns"]) == 2
    assert client.get("/api/kb/chat").json()["turns"] == []  # the global one is untouched


def wait_idle_scope(client: TestClient, scope: str, timeout: float = 6.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/kb/chat?scope={scope}").json()
        if not body["running"]:
            return body
        time.sleep(0.05)
    raise AssertionError("the assistant never finished")


def test_one_entry_being_busy_does_not_block_another(client: TestClient) -> None:
    client.app.state.context.chat_running.add("acme-engineer")
    assert (
        client.post("/api/kb/chat", json={"message": "x", "scope": "acme-engineer"}).status_code
        == 400
    )
    # a different scope is free
    client.app.state.context.chat_running.discard("acme-engineer")
    assert (
        client.post("/api/kb/chat", json={"message": "x", "scope": "other-entry"}).status_code
        == 200
    )


@pytest.mark.parametrize("hostile", ["../../etc/passwd", "a/b", "A B", "..", "x.json", ""])
def test_a_hostile_scope_cannot_escape_the_chats_directory(
    client: TestClient, project: Path, hostile: str
) -> None:
    """The scope becomes part of a filename and arrives in a URL."""
    response = client.get("/api/kb/chat", params={"scope": hostile})
    assert response.status_code in (400, 422) or hostile == ""
    assert not any(project.glob("**/passwd*"))
    assert [p.name for p in (project / "chats").glob("*")] in ([], ["kb-chat.json"])


def test_accepting_finds_the_proposal_in_its_own_scope(
    client: TestClient, backend, project: Path
) -> None:
    backend(scripted({"reply": "x", "proposals": [FACT]}))
    client.post("/api/kb/chat", json={"message": "x", "scope": "acme-engineer"})
    proposal = wait_idle_scope(client, "acme-engineer")["turns"][1]["proposals"][0]

    wrong = client.post(f"/api/kb/chat/proposals/{proposal['id']}/accept")  # global scope
    assert wrong.status_code == 404
    right = client.post(f"/api/kb/chat/proposals/{proposal['id']}/accept?scope=acme-engineer")
    assert right.status_code == 200


def test_the_open_entry_is_given_to_the_assistant(project: Path) -> None:
    """Without it "add that this handled 2,000 users" is unanswerable, and the
    assistant guesses which entry or interrogates the person about it."""
    block = focus_block(kb_of(project), {"entry": "acme-engineer"})
    assert "acme-engineer" in block and "update" in block


def test_adding_a_new_entry_says_so(project: Path) -> None:
    block = focus_block(kb_of(project), {"new": "fact", "parent": "acme-engineer"})
    assert "new fact" in block and "acme-engineer" in block and "create" in block


def test_a_focus_on_something_that_does_not_exist_is_ignored(project: Path) -> None:
    assert focus_block(kb_of(project), {"entry": "ghost"}) == ""
    assert focus_block(kb_of(project), None) == ""
    assert focus_block(kb_of(project), {"new": "sandwich"}) == ""


async def test_the_focus_reaches_the_prompt(project: Path) -> None:
    runner = scripted({"reply": "x", "proposals": []})
    await curate(
        runner,
        load_corpus(kb_of(project)),
        kb_of(project),
        Config(),
        [],
        "add detail",
        {"entry": "acme-engineer"},
    )
    prompt = runner.calls["curator"][0]
    assert "# FOCUS" in prompt
    assert prompt.index("# FOCUS") < prompt.index("add detail")


def test_archiving_names_the_scope(project: Path) -> None:
    store = ChatStore(project / "chats", "acme-engineer")
    store.append({"role": "user", "text": "x"})
    archived = store.archive()
    assert archived and archived.name.startswith("kb-chat--acme-engineer-")


# ---- shape tolerance (found live with Codex) ----------------------------------


def test_string_metrics_are_dropped_and_the_person_is_told() -> None:
    """Codex returned `add_metrics: ["200 questions (…)"]`. Dropping them silently
    while the reply said "recorded the metric" is exactly the false claim the
    curator exists to avoid."""
    from resume_tailor.pipeline.curator import sanitise

    clean, dropped = sanitise(
        {
            "op": "update",
            "type": "fact",
            "id": "x",
            "add_metrics": ["200 questions (eval set)", {"value": "5", "what": "reviewers"}],
        }
    )
    assert clean["add_metrics"] == [{"value": "5", "what": "reviewers"}]
    assert dropped == ["200 questions (eval set)"]


def test_malformed_field_shapes_do_not_crash() -> None:
    from resume_tailor.pipeline.curator import sanitise

    clean, _ = sanitise(
        {"op": "update", "type": "fact", "id": "x", "fields": "oops", "add_tags": "ml", "body": 3}
    )
    assert clean["fields"] == {} and clean["add_tags"] == [] and clean["body"] is None
