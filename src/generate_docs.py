from __future__ import annotations

import json
from pathlib import Path

from anthropic import Anthropic
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.async_api import async_playwright

from src.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, TEMPLATES_DIR, load_prompt
from src.schemas import JobPosting, Profile, ResumeContent

_client = Anthropic(api_key=ANTHROPIC_API_KEY)

_jinja = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

# Inline styles.css into rendered HTML so Playwright doesn't need a base URL.
_STYLES = (TEMPLATES_DIR / "styles.css").read_text(encoding="utf-8")


def _profile_for_prompt(profile: Profile) -> str:
    """Render profile as JSON for the LLM with explicit source indices.

    The resume_tailor prompt requires every bullet to carry a source_tag like
    'experience:Express Scripts Canada:2', so we expose indices clearly.
    """
    data = profile.model_dump(mode="json")
    for exp in data["experience"]:
        exp["achievements"] = [
            {"idx": i, "text": a} for i, a in enumerate(exp["achievements"])
        ]
    for proj in data["projects"]:
        proj["achievements"] = [
            {"idx": i, "text": a} for i, a in enumerate(proj["achievements"])
        ]
    return json.dumps(data, indent=2, default=str)


def _inline_styles(html: str) -> str:
    """Replace <link rel='stylesheet' href='styles.css'> with an inline <style>."""
    return html.replace(
        '<link rel="stylesheet" href="styles.css">',
        f"<style>{_STYLES}</style>",
    )


def tailor_resume(profile: Profile, posting: JobPosting, run_dir: Path) -> ResumeContent:
    system_prompt = load_prompt("resume_tailor.md")
    user_msg = (
        f"<job_posting>\n"
        f"company: {posting.company}\n"
        f"title: {posting.title}\n"
        f"keywords: {', '.join(posting.keywords)}\n\n"
        f"{posting.description_md}\n"
        f"</job_posting>\n\n"
        f"<profile>\n{_profile_for_prompt(profile)}\n</profile>\n\n"
        f"Return ONLY a JSON object matching the ResumeContent schema. "
        f"No prose, no markdown fences."
    )

    resp = _client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=8000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").split("\n", 1)[1].rsplit("```", 1)[0]

    (run_dir / "resume.json").write_text(raw, encoding="utf-8")
    resume = ResumeContent.model_validate_json(raw)
    return resume


_AGENT_REVEAL_CONTEXT = """\
The candidate's project at github.com/Austin-FV/job-apply-agent is the agent that wrote this letter, generated the attached resume, and (depending on the run mode) filled out this very application form.

Key technical points the candidate wants the reader to understand:
- Python + Claude Sonnet 4.6 + browser-use + Playwright. The browser-use agent is what drives the ATS form.
- Anti-hallucination: every resume bullet carries a Pydantic `source_tag` that points back to a real profile achievement. The LLM cannot invent experience — fabricated bullets fail schema validation.
- Typed pipeline: JD HTML → Pydantic `JobPosting` → LLM-tailored `ResumeContent` JSON → Jinja2 HTML → Playwright PDF. Each step has a typed contract, which is why the output is reliable enough to submit.
- Pragmatic build choices: dropped WeasyPrint after hitting Windows GTK install pain, switched to Playwright's `page.pdf()` since Playwright was already in the stack. The git history shows the actual debugging path.

The agent is open source and the run artifacts for this exact application (scraped JD, generated resume JSON with source_tags, cover letter, browser-use trace) are committed in the repo."""


def write_cover_letter(
    profile: Profile,
    posting: JobPosting,
    run_dir: Path,
    reveal_agent: bool = False,
) -> str:
    system_prompt = load_prompt("cover_letter.md")
    parts = [
        f"<job_posting>\ncompany: {posting.company}\ntitle: {posting.title}\n\n"
        f"{posting.description_md}\n</job_posting>",
        f"<profile_narrative>\nelevator_pitch: {profile.narrative.elevator_pitch}\n"
        f"career_themes:\n  - " + "\n  - ".join(profile.narrative.career_themes) + "\n"
        f"why_im_looking: {profile.narrative.why_im_looking}\n</profile_narrative>",
    ]
    if reveal_agent:
        parts.append(f"<agent_reveal_mode>\n{_AGENT_REVEAL_CONTEXT}\n</agent_reveal_mode>")
    parts.append(
        "Return the cover letter body only — no header, no signoff line. "
        "3-4 paragraphs of prose."
    )
    user_msg = "\n\n".join(parts)

    resp = _client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=2000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )
    body = resp.content[0].text.strip()
    (run_dir / "cover_letter.md").write_text(body, encoding="utf-8")
    return body


def _render_resume_html(resume: ResumeContent, profile: Profile, run_dir: Path) -> Path:
    template = _jinja.get_template("resume.html.j2")
    html_str = _inline_styles(template.render(resume=resume, personal=profile.personal))
    html_path = run_dir / "resume.html"
    html_path.write_text(html_str, encoding="utf-8")
    return html_path


def _render_cover_html(
    body: str, profile: Profile, posting: JobPosting, run_dir: Path
) -> Path:
    template = _jinja.get_template("cover_letter.html.j2")
    html_str = _inline_styles(template.render(
        body_paragraphs=[p.strip() for p in body.split("\n\n") if p.strip()],
        personal=profile.personal,
        company=posting.company,
        title=posting.title,
    ))
    html_path = run_dir / "cover_letter.html"
    html_path.write_text(html_str, encoding="utf-8")
    return html_path


async def _html_files_to_pdfs(jobs: list[tuple[Path, Path]]) -> None:
    """Render each (html_path, pdf_path) pair via a shared Chromium instance."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context()
        page = await ctx.new_page()
        for html_path, pdf_path in jobs:
            await page.goto(html_path.as_uri(), wait_until="load")
            await page.pdf(
                path=str(pdf_path),
                format="Letter",
                margin={"top": "0.6in", "bottom": "0.6in", "left": "0.7in", "right": "0.7in"},
                print_background=True,
            )
        await browser.close()


async def generate(
    profile: Profile,
    posting: JobPosting,
    run_dir: Path,
    reveal_agent: bool = False,
) -> tuple[Path, Path]:
    """Generate both PDFs. Returns (resume_pdf, cover_letter_pdf)."""
    resume = tailor_resume(profile, posting, run_dir)
    resume_html = _render_resume_html(resume, profile, run_dir)

    cover_body = write_cover_letter(profile, posting, run_dir, reveal_agent=reveal_agent)
    cover_html = _render_cover_html(cover_body, profile, posting, run_dir)

    resume_pdf = run_dir / "resume.pdf"
    cover_pdf = run_dir / "cover_letter.pdf"
    await _html_files_to_pdfs([(resume_html, resume_pdf), (cover_html, cover_pdf)])
    return resume_pdf, cover_pdf
