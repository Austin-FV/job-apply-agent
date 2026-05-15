from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import typer

from src.config import RUNS_DIR, get_logger, load_profile, new_run_dir
from src.scrape_jd import scrape
from src.schemas import JobPosting

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command()
def apply(
    url: str = typer.Argument(None, help="Job posting URL (omit when using --use-run)"),
    skip_form: bool = typer.Option(False, help="Generate docs but skip the browser agent"),
    autonomous: bool = typer.Option(
        False,
        "--autonomous",
        help="Let the agent submit the application without human review. "
        "Default behavior: agent fills the form and stops at the review step.",
    ),
    reveal_agent: bool = typer.Option(
        False,
        "--reveal-agent",
        help="Cover letter leads with the agent reveal (architecture, repo link). "
        "Use for submissions where the agent itself is the lead signal.",
    ),
    use_run: str = typer.Option(
        None,
        "--use-run",
        help="Skip scrape + doc generation. Reuse jd.json, resume.pdf, and "
        "cover_letter.pdf from the named run dir under runs/. Pass 'latest' "
        "for the most recent run.",
    ),
) -> None:
    """End-to-end: scrape JD, generate tailored resume + cover letter, fill form."""
    if use_run is None and url is None:
        raise typer.BadParameter("Either URL or --use-run must be provided.")
    asyncio.run(_apply_async(url, skip_form, autonomous, reveal_agent, use_run))


async def _apply_async(
    url: str | None,
    skip_form: bool,
    autonomous: bool,
    reveal_agent: bool,
    use_run: str | None,
) -> None:
    from src.fill_form import fill_application
    from src.generate_docs import generate

    profile = load_profile()

    if use_run:
        source_dir = _resolve_run_dir(use_run)
        posting, src_resume, src_cover = _load_existing_artifacts(source_dir)

        # Fresh run dir for this form-fill attempt; source dir stays untouched.
        run_dir = new_run_dir(posting.company, posting.title)
        log = get_logger(run_dir)
        log.info("reusing_run", source=source_dir.name, target=run_dir.name)

        shutil.copy2(src_resume, run_dir / "resume.pdf")
        shutil.copy2(src_cover, run_dir / "cover_letter.pdf")
        shutil.copy2(source_dir / "jd.json", run_dir / "jd.json")
        resume_pdf = run_dir / "resume.pdf"
        cover_pdf = run_dir / "cover_letter.pdf"
    else:
        run_dir = new_run_dir("pending", "pending")
        log = get_logger(run_dir)
        log.info("scraping", url=url)

        posting = await scrape(url, run_dir)
        log.info(
            "scraped",
            company=posting.company,
            title=posting.title,
            keywords=posting.keywords,
        )

        # Rename run dir now that we know the company/role.
        from src.config import _slug

        new_name = (
            f"{run_dir.name.split('-pending')[0]}-"
            f"{_slug(posting.company)}-{_slug(posting.title)}"
        )
        new_path = RUNS_DIR / new_name
        run_dir.rename(new_path)
        run_dir = new_path

        (run_dir / "jd.json").write_text(
            posting.model_dump_json(indent=2), encoding="utf-8"
        )

        log.info("generating_docs", reveal_agent=reveal_agent)
        resume_pdf, cover_pdf = await generate(
            profile, posting, run_dir, reveal_agent=reveal_agent
        )
        log.info("docs_generated", resume=str(resume_pdf), cover=str(cover_pdf))

    if skip_form:
        log.info("skipping_form")
        return

    log.info("filling_form", autonomous=autonomous)
    result = await fill_application(
        profile, posting, resume_pdf, cover_pdf, run_dir, autonomous=autonomous
    )
    log.info("form_filled", **{k: v for k, v in result.items() if k != "errors"})
    print(json.dumps(result, indent=2))


def _resolve_run_dir(use_run: str) -> Path:
    """Resolve --use-run argument to an actual run directory."""
    if use_run == "latest":
        candidates = [d for d in RUNS_DIR.iterdir() if d.is_dir()]
        if not candidates:
            raise typer.BadParameter(f"No runs found under {RUNS_DIR}.")
        return max(candidates, key=lambda d: d.stat().st_mtime)

    direct = RUNS_DIR / use_run
    if direct.is_dir():
        return direct

    raise typer.BadParameter(
        f"Run directory not found: {direct}. "
        f"Pass a name from `ls runs/` or use 'latest'."
    )


def _load_existing_artifacts(run_dir: Path) -> tuple[JobPosting, Path, Path]:
    """Load JobPosting + resume.pdf + cover_letter.pdf from a prior run dir."""
    jd_json = run_dir / "jd.json"
    resume_pdf = run_dir / "resume.pdf"
    cover_pdf = run_dir / "cover_letter.pdf"
    missing = [p.name for p in (jd_json, resume_pdf, cover_pdf) if not p.exists()]
    if missing:
        raise typer.BadParameter(
            f"Run dir {run_dir.name} is missing required artifacts: {missing}. "
            f"Cannot reuse — run a full pipeline first."
        )
    posting = JobPosting.model_validate_json(jd_json.read_text(encoding="utf-8"))
    return posting, resume_pdf, cover_pdf


@app.command()
def scrape_only(url: str) -> None:
    """Debug helper — just scrape and dump the JobPosting JSON."""

    async def _go() -> None:
        run_dir = new_run_dir("scrape-only", "debug")
        posting = await scrape(url, run_dir)
        print(posting.model_dump_json(indent=2))

    asyncio.run(_go())


if __name__ == "__main__":
    app()
