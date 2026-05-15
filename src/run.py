from __future__ import annotations

import asyncio
import json

import typer

from src.config import get_logger, load_profile, new_run_dir
from src.fill_form import fill_application
from src.generate_docs import generate
from src.scrape_jd import scrape

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command()
def apply(
    url: str = typer.Argument(..., help="Job posting URL"),
    skip_form: bool = typer.Option(False, help="Generate docs but skip the browser agent"),
) -> None:
    """End-to-end: scrape JD, generate tailored resume + cover letter, fill form."""
    asyncio.run(_apply_async(url, skip_form))


async def _apply_async(url: str, skip_form: bool) -> None:
    profile = load_profile()
    # We need company+role for the run dir name, but those come from the scrape.
    # Use a placeholder run dir, then rename. (Cheap; happens once per run.)
    run_dir = new_run_dir("pending", "pending")
    log = get_logger(run_dir)
    log.info("scraping", url=url)

    posting = await scrape(url, run_dir)
    log.info("scraped", company=posting.company, title=posting.title, keywords=posting.keywords)

    # Rename run dir now that we know the company/role.
    from src.config import RUNS_DIR, _slug
    new_name = f"{run_dir.name.split('-pending')[0]}-{_slug(posting.company)}-{_slug(posting.title)}"
    new_path = RUNS_DIR / new_name
    run_dir.rename(new_path)
    run_dir = new_path

    (run_dir / "jd.json").write_text(posting.model_dump_json(indent=2), encoding="utf-8")

    log.info("generating_docs")
    resume_pdf, cover_pdf = generate(profile, posting, run_dir)
    log.info("docs_generated", resume=str(resume_pdf), cover=str(cover_pdf))

    if skip_form:
        log.info("skipping_form")
        return

    log.info("filling_form")
    result = await fill_application(profile, posting, resume_pdf, cover_pdf, run_dir)
    log.info("form_filled", **{k: v for k, v in result.items() if k != "errors"})
    print(json.dumps(result, indent=2))


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
