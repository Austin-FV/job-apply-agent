from __future__ import annotations

import json
from pathlib import Path

from anthropic import Anthropic
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import CSS, HTML

from src.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, TEMPLATES_DIR, load_prompt
from src.schemas import JobPosting, Profile, ResumeContent

_client = Anthropic(api_key=ANTHROPIC_API_KEY)

_jinja = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


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


def render_resume_pdf(resume: ResumeContent, profile: Profile, run_dir: Path) -> Path:
    template = _jinja.get_template("resume.html.j2")
    html_str = template.render(resume=resume, personal=profile.personal)
    html_path = run_dir / "resume.html"
    pdf_path = run_dir / "resume.pdf"
    html_path.write_text(html_str, encoding="utf-8")

    HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf(
        pdf_path,
        stylesheets=[CSS(filename=str(TEMPLATES_DIR / "styles.css"))],
    )
    return pdf_path


def write_cover_letter(profile: Profile, posting: JobPosting, run_dir: Path) -> str:
    system_prompt = load_prompt("cover_letter.md")
    user_msg = (
        f"<job_posting>\n"
        f"company: {posting.company}\n"
        f"title: {posting.title}\n\n"
        f"{posting.description_md}\n"
        f"</job_posting>\n\n"
        f"<profile_narrative>\n"
        f"elevator_pitch: {profile.narrative.elevator_pitch}\n"
        f"career_themes:\n  - " + "\n  - ".join(profile.narrative.career_themes) + "\n"
        f"why_im_looking: {profile.narrative.why_im_looking}\n"
        f"</profile_narrative>\n\n"
        f"Return the cover letter body only — no header, no signoff line. "
        f"3-4 paragraphs of prose."
    )

    resp = _client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=2000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )
    body = resp.content[0].text.strip()
    (run_dir / "cover_letter.md").write_text(body, encoding="utf-8")
    return body


def render_cover_letter_pdf(
    body: str, profile: Profile, posting: JobPosting, run_dir: Path
) -> Path:
    template = _jinja.get_template("cover_letter.html.j2")
    html_str = template.render(
        body_paragraphs=[p.strip() for p in body.split("\n\n") if p.strip()],
        personal=profile.personal,
        company=posting.company,
        title=posting.title,
    )
    html_path = run_dir / "cover_letter.html"
    pdf_path = run_dir / "cover_letter.pdf"
    html_path.write_text(html_str, encoding="utf-8")

    HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf(
        pdf_path,
        stylesheets=[CSS(filename=str(TEMPLATES_DIR / "styles.css"))],
    )
    return pdf_path


def generate(profile: Profile, posting: JobPosting, run_dir: Path) -> tuple[Path, Path]:
    """Generate both PDFs. Returns (resume_pdf, cover_letter_pdf)."""
    resume = tailor_resume(profile, posting, run_dir)
    resume_pdf = render_resume_pdf(resume, profile, run_dir)
    cover_body = write_cover_letter(profile, posting, run_dir)
    cover_pdf = render_cover_letter_pdf(cover_body, profile, posting, run_dir)
    return resume_pdf, cover_pdf
