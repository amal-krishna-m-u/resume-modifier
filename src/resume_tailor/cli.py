"""`rt` — the command line over the knowledge base and, later, the pipeline.

Exists ahead of the web UI on purpose: plain files are the state (spec-01 P1),
so validating and inspecting them must not require a running server.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import typer

from .applications import db as appdb
from .applications import record as apprecord
from .applications import views
from .applications.promote import PromotionConflict, promote, verify
from .config import Config
from .kb.identity import load_identity
from .kb.index import write_index
from .kb.loader import load_corpus
from .kb.paths import repo_root
from .kb.validate import validate_kb
from .pipeline.artifacts import Run, guess_role, run_slug
from .pipeline.orchestrator import Pipeline
from .pipeline.report import render_gap_report
from .render.compile import (
    CompileError,
    TectonicMissing,
    check_overflow,
    compile_pdf,
    healthcheck,
)
from .render.document import VisibilityViolation, apply_validation, document_from_draft
from .render.latex import Geometry, render_baseline, render_document
from .runtime import BackendError, ContextExceeded, build_backend

app = typer.Typer(no_args_is_help=True, add_completion=False, help=__doc__)
kb_app = typer.Typer(no_args_is_help=True, help="Inspect and validate the knowledge base.")
app.add_typer(kb_app, name="kb")

ROOT_OPTION = typer.Option(
    None, "--root", help="Project root; defaults to the nearest ancestor holding kb/."
)


def _resolve(root: Path | None) -> tuple[Path, Path, Path]:
    """Project root: `--root`, then `RESUME_TAILOR_ROOT`, then a `kb/` walk.

    The walk starts at the working directory and, if that is not inside the
    project, at the parent of the venv (`sys.prefix`). That is what lets a
    `~/bin/rt` symlink start and stop this tool from any directory.
    """
    if root is None:
        env = os.environ.get("RESUME_TAILOR_ROOT")
        if env:
            root = Path(env)
        else:
            walked = repo_root()
            venv_parent = Path(sys.prefix).resolve().parent
            if (walked / "kb").is_dir():
                root = walked
            elif (venv_parent / "kb").is_dir():
                root = venv_parent
            else:
                root = walked
    base = root.resolve()
    kb_dir = base / "kb"
    if not kb_dir.is_dir():
        typer.secho(f"no kb/ directory under {base}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)
    return base, kb_dir, base / ".cache"


@kb_app.command("validate")
def kb_validate(
    root: Path | None = ROOT_OPTION,
    warnings_as_errors: bool = typer.Option(False, "--strict", help="Treat warnings as failures."),
) -> None:
    """Check every entry against the ten rules in spec-01 §4."""
    base, kb_dir, _ = _resolve(root)
    corpus = load_corpus(kb_dir)
    report = validate_kb(kb_dir, corpus)

    for issue in report.errors:
        typer.secho(f"  {issue}", fg=typer.colors.RED)
    for issue in report.warnings:
        typer.secho(f"  {issue}", fg=typer.colors.YELLOW)

    typer.echo(
        f"\n{len(corpus.entries)} entries · {len(report.errors)} errors · "
        f"{len(report.warnings)} warnings"
    )

    if report.errors or (warnings_as_errors and report.warnings):
        raise typer.Exit(1)
    typer.secho("OK", fg=typer.colors.GREEN)


@kb_app.command("index")
def kb_index(root: Path | None = ROOT_OPTION) -> None:
    """Rebuild `.cache/index.json`. Safe to run at any time."""
    _, kb_dir, cache_dir = _resolve(root)
    corpus = load_corpus(kb_dir)
    if corpus.parse_errors:
        typer.secho(
            f"{len(corpus.parse_errors)} file(s) failed to parse and are absent from the "
            "index; run `rt kb validate`",
            fg=typer.colors.YELLOW,
            err=True,
        )
    target = write_index(corpus, cache_dir)
    typer.echo(f"wrote {target} ({len(corpus.entries)} entries)")


@kb_app.command("stats")
def kb_stats(root: Path | None = ROOT_OPTION) -> None:
    """Corpus size and shape — the numbers OQ-2 is tracked against."""
    _, kb_dir, _ = _resolve(root)
    corpus = load_corpus(kb_dir)

    for entry_type in ("role", "fact", "project", "blog", "education", "certification", "award"):
        rows = corpus.of_type(entry_type)
        if rows:
            typer.echo(f"  {entry_type:<14} {len(rows):>4}")

    tokens = corpus.estimated_tokens()
    typer.echo(f"\n  taxonomy terms {len(corpus.taxonomy):>4}")
    typer.echo(f"  declared skills{len(corpus.skills):>5}")
    typer.echo(f"\n  entries        {len(corpus.entries):>4}")
    typer.echo(f"  est. tokens  {tokens:>6}  (chars/4 — an estimate, not a count)")

    # OQ-2's provisional trigger for revisiting full-corpus selection.
    if len(corpus.entries) >= 500 or tokens >= 100_000:
        typer.secho(
            "\n  Past the OQ-2 trigger (500 entries / 100K tokens). Re-examine whether "
            "full-corpus selection still holds.",
            fg=typer.colors.YELLOW,
        )

    for depth in ("expert", "working", "exposure"):
        count = sum(1 for e in corpus.entries if e.meta.depth == depth)
        if count:
            typer.echo(f"  depth:{depth:<9} {count:>4}")

    hidden = [e.id for e in corpus.entries if e.meta.visibility != "public"]
    if hidden:
        typer.echo(f"\n  non-public (never exported): {', '.join(hidden)}")


@app.command("render")
def render(
    root: Path | None = ROOT_OPTION,
    out: Path | None = typer.Option(None, "--out", help="Output directory; default runs/baseline."),
    contact_set: str | None = typer.Option(
        None, "--contact-set", help="Render only this set; default renders every configured set."
    ),
    summary_file: Path | None = typer.Option(
        None, "--summary-file", help="Prose for the Summary section. Tailored per JD from M4 on."
    ),
    pdf: bool = typer.Option(True, "--pdf/--no-pdf", help="Compile with Tectonic."),
    budget: int = typer.Option(1, "--budget", help="Page budget; overflow is reported, never cut."),
) -> None:
    """Render the whole knowledge base to LaTeX and PDF — no agents involved.

    This is the baseline: everything, in knowledge-base order, with no selection
    and no rewriting. It is what proves AC-R7.1 and the reference the template
    is checked against.
    """
    base, kb_dir, _ = _resolve(root)
    corpus = load_corpus(kb_dir)
    if corpus.parse_errors:
        typer.secho(
            "knowledge base has parse errors; run `rt kb validate`", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(1)

    identity_path = kb_dir / "identity.yaml"
    if not identity_path.is_file():
        typer.secho(
            "kb/identity.yaml not found — copy kb/identity.example.yaml to it and fill it in",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2)
    identity = load_identity(identity_path)

    sets = [contact_set] if contact_set else identity.set_names
    for name in sets:
        if name not in identity.contacts:
            typer.secho(
                f"no contact set named {name!r}; have: {', '.join(sorted(identity.contacts))}",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(2)

    outdir = (out or base / "runs" / "baseline").resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    summary = summary_file.read_text(encoding="utf-8").strip() if summary_file else None

    # The defaults ARE the source document's measurements, so there is no
    # "corrected" variant to opt out of.
    geometry = Geometry()

    for name in sets:
        try:
            doc, tex = render_baseline(corpus, identity, name, summary=summary, geometry=geometry)
        except VisibilityViolation as exc:
            typer.secho(f"  {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(1) from exc

        tex_path = outdir / f"resume-{name}.tex"
        tex_path.write_text(tex, encoding="utf-8")
        typer.echo(f"  {tex_path.relative_to(base)}  ({len(doc.sources)} sources)")

        if not pdf:
            continue
        try:
            result = compile_pdf(tex_path, outdir)
        except TectonicMissing as exc:
            typer.secho(f"  {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(2) from exc
        except CompileError as exc:
            typer.secho(f"  {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(1) from exc

        typer.echo(f"  {result.pdf.relative_to(base)}")
        overflow = check_overflow(result, doc, budget=budget)
        colour = typer.colors.YELLOW if overflow.over else typer.colors.GREEN
        typer.secho(f"      {overflow.summary()}", fg=colour)
        for title, lead in overflow.candidates[:5]:
            typer.echo(f"        cut candidate: {title} - {lead}")
        for warning in result.overfull[:3]:
            typer.secho(f"      {warning}", fg=typer.colors.YELLOW)


@app.command("health")
def health(
    root: Path | None = ROOT_OPTION,
    backend: str | None = typer.Option(None, "--backend", help="Check this backend instead."),
) -> None:
    """Model backend, render toolchain and corpus status (spec-04 §3)."""
    base, kb_dir, _ = _resolve(root)
    config = Config.load(base)

    typer.secho("render", bold=True)
    for key, value in healthcheck().items():
        typer.echo(f"  {key:<14} {value}")

    corpus = load_corpus(kb_dir)
    tokens = corpus.estimated_tokens()
    typer.secho("\ncorpus", bold=True)
    typer.echo(f"  {'entries':<14} {len(corpus.entries)}")
    typer.echo(f"  {'est. tokens':<14} {tokens:,}  (chars/4 — an estimate)")

    typer.secho("\nmodel backend", bold=True)
    name = backend or config.backend_name()
    if config.source:
        typer.echo(f"  {'config':<14} {config.source.relative_to(base)}")
    try:
        runner = build_backend(config, name)
    except BackendError as exc:
        typer.secho(f"  {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    report = asyncio.run(runner.healthcheck())
    caps = runner.capabilities
    typer.echo(f"  {'backend':<14} {report.backend}")
    typer.echo(f"  {'auth':<14} {report.credential}")
    typer.echo(f"  {'window':<14} {caps.min_context_tokens:,} tokens")
    typer.echo(f"  {'overhead':<14} {caps.harness_overhead:,} tokens/call")
    typer.echo(f"  {'cost':<14} {caps.cost_per_run}")
    if report.version:
        typer.echo(f"  {'version':<14} {report.version}")
    typer.secho(
        f"  {'status':<14} {'ok' if report.ok else 'unavailable'}"
        + (f" — {report.detail}" if report.detail else ""),
        fg=typer.colors.GREEN if report.ok else typer.colors.RED,
    )

    # The gate that refuses rather than chunks (spec-06 §4). Reported here so a
    # corpus that has outgrown the model surfaces before a run, not during one.
    try:
        caps.assert_corpus_fits(report.backend, tokens)
        typer.secho(f"  {'context':<14} corpus fits", fg=typer.colors.GREEN)
    except ContextExceeded as exc:
        typer.secho(f"  {'context':<14} {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from exc


@app.command("fit")
def fit_command(
    text: str | None = typer.Option(None, "--text", help="The job posting, pasted."),
    file: Path | None = typer.Option(None, "--file", help="Read the posting from a file."),
    root: Path | None = ROOT_OPTION,
) -> None:
    """Find an existing resume that already fits this posting. No model call."""
    from .pipeline.fit import fit as fit_posting

    base, _, _ = _resolve(root)
    posting = (file.read_text(encoding="utf-8") if file else text or "").strip()
    if not posting:
        typer.secho("give me the posting: --text or --file", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)
    ranked = fit_posting(posting, base / "runs", base / "applications")
    if not ranked:
        typer.echo("no completed resumes to reuse yet — run the pipeline once.")
        raise typer.Exit(0)
    best = ranked[0]
    kind = "use this resume" if best.recommend else "closest, but a new tailor is safer"
    typer.secho(f"  {best.card.title}", bold=True)
    typer.echo(f"  {best.card.kind} {best.card.id}  score {best.score:.2f}  ·  {kind}")
    if best.card.company:
        typer.echo(f"  company {best.card.company}")
    if best.absent:
        typer.secho("\n  gaps this resume does not cover", bold=True)
        for gap in best.absent[:8]:
            typer.echo(f"  - {gap.text}")
    if best.weak:
        typer.echo("\n  weak on")
        for gap in best.weak[:6]:
            typer.echo(f"  - {gap.text}")
    typer.echo("\n  rt tailor --file …    new resume from the knowledge base")
    if best.card.run_id:
        typer.echo(f"  open run {best.card.run_id} to reuse or fill gaps in the UI")


@app.command("tailor")
def tailor(
    text: str | None = typer.Option(None, "--text", help="The job posting, pasted."),
    file: Path | None = typer.Option(None, "--file", help="Read the posting from a file."),
    root: Path | None = ROOT_OPTION,
    company: str | None = typer.Option(None, "--company", help="Used in the run's folder name."),
    bullets: int = typer.Option(9, "--bullets", help="Bullet budget for the Writer."),
    sequential: bool = typer.Option(
        False, "--sequential", help="Run Recall after the Selector, so it can see its picks."
    ),
    pdf: bool = typer.Option(True, "--pdf/--no-pdf", help="Render and compile the result."),
    resume_run: str | None = typer.Option(
        None, "--resume", help="Continue an existing run from its last completed stage."
    ),
) -> None:
    """Tailor the resume to a job posting — the full five-agent pipeline."""
    base, kb_dir, _ = _resolve(root)
    config = Config.load(base)

    posting = (file.read_text(encoding="utf-8") if file else text or "").strip()
    if not posting and not resume_run:
        typer.secho("give me the posting: --text or --file", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)

    corpus = load_corpus(kb_dir)
    if corpus.parse_errors:
        typer.secho(
            "knowledge base has parse errors; run `rt kb validate`", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(1)

    runs_dir = base / "runs"
    if resume_run:
        run = Run(runs_dir / resume_run)
        if not run.directory.is_dir():
            typer.secho(f"no run named {resume_run!r} under runs/", fg=typer.colors.RED, err=True)
            raise typer.Exit(2)
        posting = posting or run.read("posting")
        typer.echo(f"resuming {run.id} — done: {', '.join(run.completed_stages()) or 'nothing'}")
    else:
        run = Run.create(runs_dir, run_slug(guess_role(posting), company))
        run.write("meta", {"company": company} if company else {})

    def progress(stage: str, status: str, detail: dict) -> None:
        if status == "running":
            typer.secho(f"  {stage:<10} running...", fg=typer.colors.CYAN, nl=False)
            typer.echo("\r", nl=False)
        elif status == "skipped":
            typer.secho(f"  {stage:<10} skipped ({detail.get('reason')})", fg=typer.colors.BLUE)
        else:
            repairs = f"  repairs={detail['repairs']}" if detail.get("repairs") else ""
            typer.secho(
                f"  {stage:<10} done   in={detail.get('input', 0):>7,} "
                f"out={detail.get('output', 0):>6,} cached={detail.get('cached', 0):>7,}{repairs}",
                fg=typer.colors.GREEN,
            )

    backend = build_backend(config)
    pipeline = Pipeline(backend, corpus, config, on_progress=progress)

    typer.secho(f"\nrun {run.id}  —  backend {backend.name}", bold=True)
    try:
        result = asyncio.run(pipeline.run(run, posting, bullets=bullets, concurrent=not sequential))
    except ContextExceeded as exc:
        typer.secho(f"\n{exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    except BackendError as exc:
        typer.secho(f"\n{exc}", fg=typer.colors.RED, err=True)
        typer.secho(f"resume with: rt tailor --resume {run.id}", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(1) from exc

    counts = result.selection.to_dict()["counts"]
    typer.secho("\nselection", bold=True)
    typer.echo(
        f"  {counts['total']} facts  "
        f"({counts['both']} both passes, {counts['selector_only']} selector only, "
        f"{counts['recall_only']} recall only)  —  {counts['rejected']} considered and rejected"
    )

    report = render_gap_report(
        result.requirements, result.selection, result.gaps, result.validation
    )
    (run.directory / "gap-report.md").write_text(report, encoding="utf-8")

    absent = [g for g in result.gaps if g["status"] == "absent"]
    weak = [g for g in result.gaps if g["status"] == "weak"]
    typer.secho("\ngaps", bold=True)
    typer.secho(
        f"  {len(absent)} absent, {len(weak)} weak",
        fg=typer.colors.YELLOW if result.gaps else typer.colors.GREEN,
    )
    for gap in absent[:5]:
        typer.echo(f"    absent: {gap['text']}")

    cuts = result.validation.get("cuts") or []
    warnings = result.validation.get("warnings") or []
    typer.secho("\nvalidator", bold=True)
    typer.secho(
        f"  {len(cuts)} cut, {len(warnings)} flagged",
        fg=typer.colors.GREEN if result.clean else typer.colors.YELLOW,
    )
    for cut in cuts[:3]:
        typer.echo(f"    cut: {cut.get('reason')}")

    draft, notes = apply_validation(result.draft, result.validation)
    for note in notes[:3]:
        typer.echo(f"    {note}")

    # Prompt tokens are input + cache reads. Reporting `input_tokens` alone
    # showed "in 66" on a run that sent 49,000 tokens, because the corpus was
    # served from cache and Anthropic counts that separately — a number that
    # looks like the cost and is not.
    usage = result.usage
    prompt_tokens = usage.input_tokens + usage.cache_read_tokens
    typer.secho("\ntokens", bold=True)
    typer.echo(
        f"  prompt {prompt_tokens:,}  ({usage.cache_read_tokens:,} from cache)  "
        f"output {usage.output_tokens:,}"
    )
    if prompt_tokens:
        saved = usage.cache_read_tokens / prompt_tokens
        typer.echo(f"  {saved:.0%} of the prompt was cached across the five agents")

    identity_path = kb_dir / "identity.yaml"
    if not identity_path.is_file():
        typer.secho("\nkb/identity.yaml missing — not rendering", fg=typer.colors.YELLOW)
        raise typer.Exit(0)

    identity = load_identity(identity_path)
    typer.secho("\noutput", bold=True)
    for contact_set in identity.set_names:
        document = document_from_draft(draft, corpus, identity, contact_set)
        tex_path = run.directory / f"resume-{contact_set}.tex"
        tex_path.write_text(render_document(document, geometry=Geometry()), encoding="utf-8")
        typer.echo(f"  {tex_path.relative_to(base)}")

        if not pdf:
            continue
        try:
            compiled = compile_pdf(tex_path, run.directory)
        except (TectonicMissing, CompileError) as exc:
            typer.secho(f"  {exc}", fg=typer.colors.RED, err=True)
            continue
        typer.echo(f"  {compiled.pdf.relative_to(base)}")
        overflow = check_overflow(compiled, document, budget=config.page_budget)
        typer.secho(
            f"      {overflow.summary()}",
            fg=typer.colors.YELLOW if overflow.over else typer.colors.GREEN,
        )

    typer.echo(f"  {(run.directory / 'gap-report.md').relative_to(base)}")


@app.command("serve")
def serve(
    root: Path | None = ROOT_OPTION,
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload", help="Restart on code changes."),
) -> None:
    """Run the local web interface.

    Binds 127.0.0.1 only, never 0.0.0.0 (AC-R1.2). This process has filesystem
    write access and an authenticated model session; putting it on the LAN
    would hand both to anyone on the network.
    """
    import uvicorn

    base, _, _ = _resolve(root)
    from .api.daemon import public_url

    typer.secho(f"  {public_url(port)}", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  serving {base}")
    if not (base / "web" / "dist").is_dir():
        typer.secho(
            "  no web/dist yet — API only (the UI is M6). Try /api/health.",
            fg=typer.colors.YELLOW,
        )

    # uvicorn builds the app from an import string, which cannot carry arguments.
    # Without this the app re-resolved the root from the working directory and
    # silently served a different project than the one printed above.
    os.environ["RESUME_TAILOR_ROOT"] = str(base)
    uvicorn.run(
        "resume_tailor.api.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=port,
        reload=reload,
        log_level="info",
    )


@app.command("start")
def start_command(
    root: Path | None = ROOT_OPTION,
    port: int = typer.Option(8000, "--port"),
) -> None:
    """Start the web interface in the background. `rt stop` closes it."""
    from .api.daemon import start as start_server

    base, _, _ = _resolve(root)
    state = start_server(base, port)
    if not state.running:
        typer.secho(state.detail or "failed to start", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    from .api.daemon import alias_resolves, public_url

    url = public_url(state.port)
    if state.detail == "started":
        typer.secho(f"  {url}", fg=typer.colors.GREEN, bold=True)
        typer.echo(f"  pid {state.pid}  ·  rt stop to close")
    else:
        typer.echo(f"  already running at {url} (pid {state.pid})")
    if not alias_resolves():
        typer.echo('  to type rs.local:  sudo sh -c \'echo "127.0.0.1 rs.local" >> /etc/hosts\'')


@app.command("stop")
def stop_command(root: Path | None = ROOT_OPTION) -> None:
    """Close the background web interface started by `rt start`."""
    from .api.daemon import stop as stop_server

    base, _, _ = _resolve(root)
    state = stop_server(base)
    typer.echo(state.detail)


@app.command("open")
def open_command(
    root: Path | None = ROOT_OPTION,
    port: int = typer.Option(8000, "--port"),
) -> None:
    """Start the UI if needed and open it in the browser (`rs.local` when set)."""
    from .api.daemon import open_browser, public_url, read_state
    from .api.daemon import start as start_server

    base, _, _ = _resolve(root)
    state = read_state(base)
    if not state.running:
        state = start_server(base, port)
    if not state.running:
        typer.secho(state.detail or "failed to start", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    url = public_url(state.port)
    open_browser(url)
    typer.secho(f"  {url}", fg=typer.colors.GREEN, bold=True)


apps_app = typer.Typer(no_args_is_help=True, help="The application archive and tracker.")
app.add_typer(apps_app, name="applications")


@app.command("apply")
def apply_command(
    run_id: str = typer.Argument(..., help="The run that produced what you sent."),
    company: str = typer.Option(..., "--company"),
    role: str = typer.Option(..., "--role"),
    root: Path | None = ROOT_OPTION,
    job_id: str | None = typer.Option(None, "--job-id"),
    job_url: str | None = typer.Option(None, "--job-url"),
    source: str | None = typer.Option(
        None, "--source", help="referral | board | direct | recruiter"
    ),
    sent: str | None = typer.Option(None, "--sent", help="Which contact set actually went out."),
    on: str | None = typer.Option(None, "--on", help="Application date; defaults to today."),
) -> None:
    """Record that you applied — freezing what was sent.

    Exporting a PDF does not create a record; you often export to look at
    something. This is the moment the system can know the content became
    permanent, so it is the moment it freezes.
    """
    from datetime import date as _date

    base, kb_dir, _ = _resolve(root)
    run = Run(base / "runs" / run_id)
    if not run.directory.is_dir():
        typer.secho(f"no run named {run_id!r}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)

    try:
        promotion = promote(
            base,
            run,
            company=company,
            role=role,
            applied_on=_date.fromisoformat(on) if on else None,
            job_id=job_id,
            job_url=job_url,
            source=source,
            contact_set_sent=sent,
        )
    except PromotionConflict as exc:
        typer.secho(f"  {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    appdb.reindex(base / "applications", base / ".cache")
    views.regenerate(base / "applications")

    typer.secho(f"\n  {promotion.application.id}", bold=True)
    typer.echo(f"  {promotion.directory.relative_to(base)}")
    for name in sorted(p.name for p in promotion.directory.iterdir() if p.is_file()):
        typer.echo(f"      {name}")
    typer.secho(
        "\n  Frozen. The resumes and the content snapshot are read-only and hashed;\n"
        "  status, stages and referral stay editable.",
        fg=typer.colors.GREEN,
    )


@apps_app.command("list")
def applications_list(
    root: Path | None = ROOT_OPTION,
    company: str | None = typer.Option(None, "--company"),
    status: str | None = typer.Option(None, "--status"),
    live: bool = typer.Option(False, "--live", help="Only applications still in play."),
) -> None:
    """The tracker."""
    base, _, cache = _resolve(root)
    applications_dir = base / "applications"
    if appdb.is_stale(applications_dir, cache):
        appdb.reindex(applications_dir, cache)

    rows = appdb.query(cache, company=company, status=status, live_only=live)
    if not rows:
        typer.echo("  no applications yet — record one with `rt apply <run-id> ...`")
        return

    counts = appdb.pipeline_counts(cache)
    live_total = sum(counts.get(s, 0) for s in apprecord.LIVE_STATUSES)
    typer.secho(
        f"  {len(rows)} shown · {live_total} live · "
        + " · ".join(f"{k} {v}" for k, v in sorted(counts.items())),
        fg=typer.colors.BLUE,
    )
    typer.echo()
    typer.secho(
        f"  {'applied':<12}{'company':<22}{'role':<30}{'status':<11}{'ref':<5}sent",
        bold=True,
    )
    for row in rows:
        typer.echo(
            f"  {row['applied_on']:<12}{row['company'][:20]:<22}{row['role'][:28]:<30}"
            f"{row['status']:<11}{'yes' if row['referral_received'] else '-':<5}"
            f"{row['contact_set_sent'] or '-'}"
        )


@apps_app.command("verify")
def applications_verify(root: Path | None = ROOT_OPTION) -> None:
    """Re-hash every archived artifact and report drift.

    Read-only permissions are a guardrail against accident — anyone can chmod —
    so the hash is what actually establishes that what is on disk is what was
    sent.
    """
    base, _, _ = _resolve(root)
    checked = drifted = 0
    for path in sorted((base / "applications").glob("*/*/application.yaml")):
        if "_views" in path.parts:
            continue
        checked += 1
        result = verify(path.parent)
        if not result["intact"]:
            drifted += 1
            typer.secho(f"  DRIFT  {result['id']}", fg=typer.colors.RED)
            for problem in result["problems"]:
                typer.echo(f"           {problem['file']}: {problem['issue']}")

    if not checked:
        typer.echo("  nothing archived yet")
        return
    colour = typer.colors.RED if drifted else typer.colors.GREEN
    typer.secho(f"  {checked} checked, {drifted} with drift", fg=colour)
    if drifted:
        raise typer.Exit(1)


@apps_app.command("reindex")
def applications_reindex(root: Path | None = ROOT_OPTION) -> None:
    """Rebuild the SQLite index and the month views. Always safe."""
    base, _, cache = _resolve(root)
    indexed = appdb.reindex(base / "applications", cache)
    linked = views.regenerate(base / "applications")
    typer.echo(f"  indexed {indexed} application(s), {linked} month link(s)")


if __name__ == "__main__":
    app()


# -- tracing and evals (OQ-10) --------------------------------------------------

eval_app = typer.Typer(no_args_is_help=True, help="Prompt and model evals.")
app.add_typer(eval_app, name="eval")
trace_app = typer.Typer(no_args_is_help=True, help="Agent-call tracing.")
app.add_typer(trace_app, name="trace")


@trace_app.command("summary")
def trace_summary(
    root: Path | None = ROOT_OPTION,
    days: int = typer.Option(7, "--days", help="Most recent N log files."),
) -> None:
    """Calls, errors, latency and tokens per agent and prompt version."""
    from .observability.summary import read_entries, summarise

    base, _, _ = _resolve(root)
    rows = summarise(read_entries(base, days))
    if not rows:
        typer.echo("no traces yet — they are written as agents run (traces/*.jsonl)")
        return
    typer.echo(
        f"{'agent':<10} {'prompt':<9} {'backend':<12} {'calls':>5} {'err':>3} "
        f"{'rep':>3} {'sec':>6} {'out tok':>8} {'prompt tok':>10}"
    )
    for r in rows:
        typer.echo(
            f"{r['agent']:<10} {r['prompt_version']:<9} {r['backend']:<12} {r['calls']:>5} "
            f"{r['errors']:>3} {r['repairs']:>3} {r['mean_seconds']:>6} "
            f"{r['mean_output_tokens']:>8} {r['mean_prompt_tokens']:>10}"
        )


@trace_app.command("status")
def trace_status(root: Path | None = ROOT_OPTION) -> None:
    """Where traces go, and whether the Langfuse connection works."""
    import os

    from .observability.tracing import NotSelfHosted, check_self_hosted

    base, _, _ = _resolve(root)
    obs = Config.load(base).observability
    typer.echo(f"local log   {'on' if obs.local_log else 'off'}  ({base / 'traces'})")
    typer.echo(
        f"content     {'prompts and outputs recorded' if obs.record_content else 'metadata only'}"
    )
    if not obs.langfuse:
        typer.echo(
            "langfuse    off  (enable in resume-tailor.toml: [observability] langfuse = true)"
        )
        return
    try:
        check_self_hosted(obs.host)
    except NotSelfHosted as exc:
        typer.secho(f"langfuse    refused — {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from exc
    keys = all(os.environ.get(k) for k in (obs.public_key_env, obs.secret_key_env))
    typer.echo(f"langfuse    {obs.host}  keys {'set' if keys else 'MISSING'}")
    if keys:
        from langfuse import Langfuse

        client = Langfuse(
            host=obs.host,
            public_key=os.environ[obs.public_key_env],
            secret_key=os.environ[obs.secret_key_env],
        )
        ok = client.auth_check()
        typer.secho(
            "            " + ("connected" if ok else "auth check failed"),
            fg=typer.colors.GREEN if ok else typer.colors.RED,
        )


@eval_app.command("build")
def eval_build(
    run_id: str = typer.Argument(..., help="A finished run to snapshot as a case."),
    name: str | None = typer.Option(None, "--name"),
    root: Path | None = ROOT_OPTION,
) -> None:
    """Make an eval case from a run. Review the file before trusting its scores."""
    from .evals import build_case, save_case

    base, _, _ = _resolve(root)
    run = Run(base / "runs" / run_id)
    if not run.directory.is_dir():
        typer.secho(f"no run {run_id}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    path = save_case(base, build_case(run, name))
    typer.echo(f"wrote {path.relative_to(base)}")
    typer.secho(
        "reviewed: false — scores against it measure consistency with that run. Edit\n"
        "must_include / must_exclude, then set reviewed: true, to measure quality.",
        fg=typer.colors.YELLOW,
    )


@eval_app.command("list")
def eval_list(root: Path | None = ROOT_OPTION) -> None:
    """Cases and past results."""
    from .evals import load_cases
    from .evals.runner import results_dir

    base, _, _ = _resolve(root)
    for case in load_cases(base):
        typer.echo(
            f"case    {case.id:<50} {len(case.must_include):>3} expected  "
            f"{'reviewed' if case.reviewed else 'unreviewed'}"
        )
    for path in sorted(results_dir(base).glob("*.json")):
        typer.echo(f"result  {path.stem}")


@eval_app.command("run")
def eval_run(
    label: str = typer.Option(
        "run", "--label", help="Names the result; use the change under test."
    ),
    case: list[str] = typer.Option(None, "--case", help="Only these case ids."),
    probe: bool = typer.Option(True, "--probe/--no-probe", help="Include the validator probe."),
    backend: str | None = typer.Option(None, "--backend"),
    root: Path | None = ROOT_OPTION,
) -> None:
    """Re-run the cases against the current prompts and model, and score them."""
    from .evals import load_cases, run_eval
    from .observability.tracing import build_sinks

    base, kb_dir, _ = _resolve(root)
    config = Config.load(base)
    cases = load_cases(base, case or None)
    if not cases:
        typer.secho(
            "no cases — make one with: rt eval build <run-id>", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(1)
    corpus = load_corpus(kb_dir)
    runner = build_backend(config, backend)
    sink = next((s for s in build_sinks(config) if hasattr(s, "score")), None)
    typer.secho(f"{len(cases)} case(s) on {runner.name}", bold=True)
    result = asyncio.run(
        run_eval(base, runner, corpus, config, cases, label=label, probe_validator=probe, sink=sink)
    )
    for cid, row in result["cases"].items():
        scores = "  ".join(f"{k}={v}" for k, v in row["scores"].items())
        typer.echo(f"  {cid[:48]:<48} {scores}")
        if row["missed"]:
            typer.echo(f"    missed: {', '.join(row['missed'])}")
    typer.secho(
        "mean  " + "  ".join(f"{k}={v}" for k, v in sorted(result["mean"].items())), bold=True
    )
    typer.echo(f"prompts {result['prompt_versions']}")
    typer.echo(f"saved evals/results/{result['file']}")
    if not result["reviewed_cases"]:
        typer.secho(
            "no case is reviewed: read these as consistency, not quality.", fg=typer.colors.YELLOW
        )


@eval_app.command("compare")
def eval_compare(
    a: str = typer.Argument(..., help="Result name or part of it."),
    b: str = typer.Argument(...),
    root: Path | None = ROOT_OPTION,
) -> None:
    """What changed between two results, and which prompt versions differ."""
    from .evals import compare, load_result

    base, _, _ = _resolve(root)
    diff = compare(load_result(base, a), load_result(base, b))
    typer.secho(f"{diff['a']}  →  {diff['b']}", bold=True)
    for agent, (old, new) in diff["prompt_changes"].items():
        typer.echo(f"  prompt {agent}: {old} → {new}")
    if diff["backend_changed"]:
        typer.echo(f"  backend: {diff['backend_changed'][0]} → {diff['backend_changed'][1]}")
    if diff["models_changed"]:
        typer.echo("  models changed")
    if not (diff["prompt_changes"] or diff["backend_changed"] or diff["models_changed"]):
        typer.secho(
            "  nothing differs between them: this is run-to-run noise.", fg=typer.colors.YELLOW
        )
    for key in sorted(diff["delta"]):
        typer.echo(
            f"  {key:<34} {diff['mean_a'].get(key, '-'):>6} → {diff['mean_b'].get(key, '-'):>6}"
            f"  ({diff['delta'][key]:+})"
        )
