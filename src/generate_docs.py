from __future__ import annotations

import asyncio
import json
from pathlib import Path

from anthropic import AsyncAnthropic
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.async_api import async_playwright

from src.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, TEMPLATES_DIR, load_prompt
from src.schemas import JobPosting, Profile, ResumeContent

_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

# Marks a content block as cacheable. The system prompts are fully static and
# the profile block is static per-person, so caching that prefix cuts latency
# and cost on every run — and pays off hugely across multiple applications.
_CACHE = {"type": "ephemeral"}

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


async def tailor_resume(
    profile: Profile, posting: JobPosting, run_dir: Path
) -> ResumeContent:
    system_prompt = load_prompt("resume_tailor.md")
    # Cached prefix: static system prompt + per-person profile. Variable suffix:
    # the JD + final instruction (changes every application).
    profile_block = f"<profile>\n{_profile_for_prompt(profile)}\n</profile>"
    jd_block = (
        f"<job_posting>\n"
        f"company: {posting.company}\n"
        f"title: {posting.title}\n"
        f"keywords: {', '.join(posting.keywords)}\n\n"
        f"{posting.description_md}\n"
        f"</job_posting>\n\n"
        f"Return ONLY a JSON object matching the ResumeContent schema. "
        f"No prose, no markdown fences."
    )

    resp = await _client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=8000,
        system=[{"type": "text", "text": system_prompt, "cache_control": _CACHE}],
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": profile_block, "cache_control": _CACHE},
                    {"type": "text", "text": jd_block},
                ],
            }
        ],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").split("\n", 1)[1].rsplit("```", 1)[0]

    (run_dir / "resume.json").write_text(raw, encoding="utf-8")
    resume = ResumeContent.model_validate_json(raw)
    return resume


_AGENT_REVEAL_CONTEXT = """\
This block is source material for a first-person cover letter. Everything below is written in my own voice — use "I" and "my" throughout. Do not narrate about me in third person; mirror the voice of the source.

---

I built an open-source agent — github.com/Austin-FV/job-apply-agent — that wrote this letter, generated the attached resume, and (depending on the run mode) filled out this application form on its own. Python, Claude Sonnet 4.6, browser-use, Playwright.

Two design choices in it that map to what the Operations AI Engineer role is asking for:

1. **Anti-hallucination as a typed contract.** Every resume bullet the agent produces carries a Pydantic-validated `source_tag` that points back to a specific achievement in my profile.yaml. The LLM physically cannot output a bullet that doesn't trace to a real entry — fabricated content fails schema validation at parse time, before it ever hits a PDF. Schemas as data quality enforcement, not paperwork.

2. **One agent code path over per-ATS scripts.** The naive build would have been a Rippling adapter, a Greenhouse adapter, a Lever adapter — each one rotting on the next ATS redesign. Instead I hand a vision-aware browser to Claude with a checklist and applicant data, and one code path covers any ATS. The maintenance cost stays flat as I add target sites.

Prior work that shows the same instincts: at Express Scripts Canada I built a Selenium automation framework with 25 reusable components rather than one-off scripts (which is why the cover-letter agent's "one code path" bet felt natural). gimmit, a VS Code extension I shipped, uses Anthropic and OpenAI APIs to ground commit messages in actual diffs — the same anti-hallucination instinct as the source_tag system, applied to a different surface.

The full run artifacts for this exact application — scraped JD, resume JSON with source_tags, the browser-use trace, the GIF and MP4 of the agent at work — are committed in the repo so you can inspect what the agent actually produced."""


async def write_cover_letter(
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

    resp = await _client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=2000,
        system=[{"type": "text", "text": system_prompt, "cache_control": _CACHE}],
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
    # The two LLM calls are independent — run them concurrently.
    resume, cover_body = await asyncio.gather(
        tailor_resume(profile, posting, run_dir),
        write_cover_letter(profile, posting, run_dir, reveal_agent=reveal_agent),
    )
    resume_html = _render_resume_html(resume, profile, run_dir)
    cover_html = _render_cover_html(cover_body, profile, posting, run_dir)

    resume_pdf = run_dir / "resume.pdf"
    cover_pdf = run_dir / "cover_letter.pdf"
    await _html_files_to_pdfs([(resume_html, resume_pdf), (cover_html, cover_pdf)])
    return resume_pdf, cover_pdf
