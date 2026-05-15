from __future__ import annotations

import json
from pathlib import Path

from browser_use import Agent, Browser, BrowserConfig
from langchain_anthropic import ChatAnthropic

from src.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, BROWSER_USE_HEADLESS, load_prompt
from src.schemas import JobPosting, Profile


def _build_task(
    profile: Profile,
    posting: JobPosting,
    resume_pdf: Path,
    cover_pdf: Path,
) -> str:
    field_map = load_prompt("form_field_map.md")
    p = profile.personal
    auth = profile.work_authorization
    screen = profile.screening_answers

    return f"""You are filling out a job application form for {posting.company} — {posting.title}.

APPLY URL: {posting.apply_url}

YOUR GOAL:
1. Navigate to the apply URL.
2. Fill every required field using the applicant data below.
3. Upload the resume and cover letter PDFs at the indicated paths.
4. STOP at the final submit/review step. DO NOT click submit. Take a screenshot
   of the completed form for human review, then exit.

APPLICANT DATA:
- Full name: {p.full_name}
- Preferred name: {p.preferred_name}
- Email: {p.email}
- Phone: {p.phone}
- Location: {p.location.city}, {p.location.province}, {p.location.country}
- LinkedIn: {p.links.get('linkedin', '')}
- GitHub: {p.links.get('github', '')}
- Portfolio: {p.links.get('portfolio', '')}

WORK AUTHORIZATION:
- Authorized to work in Canada: {screen.authorized_to_work_canada}
- Requires Canada sponsorship: {screen.requires_sponsorship_canada}
- US status: {auth.us}
- Willing to relocate: {auth.willing_to_relocate}
- Remote preference: {auth.remote_preference}

SCREENING ANSWERS:
- Years of experience: {screen.years_of_experience}
- Willing to complete assessment: {screen.willing_to_complete_assessment}
- Comfortable with background check: {screen.comfortable_with_background_check}
- How did you hear: {screen.how_did_you_hear}
- Desired salary (CAD): {profile.preferences.desired_salary_cad}
- Notice period (weeks): {profile.preferences.notice_period_weeks}
- Start date: {profile.preferences.start_date}

DEMOGRAPHICS (optional, only fill if asked):
{json.dumps(profile.demographics, indent=2)}

FILES TO UPLOAD:
- Resume PDF: {resume_pdf}
- Cover letter PDF: {cover_pdf}

FIELD MAPPING NOTES:
{field_map}

RULES:
- Never invent information not present above. If a required field has no
  matching data, pause and report the field name back rather than guessing.
- For optional demographic/EEO fields, use the values above. If a value is
  "prefer_not_to_say", select that option if available, otherwise leave blank.
- Treat dropdowns as fuzzy: pick the closest matching option to the data above.
- Save a screenshot when you reach the review step.
"""


async def fill_application(
    profile: Profile,
    posting: JobPosting,
    resume_pdf: Path,
    cover_pdf: Path,
    run_dir: Path,
) -> dict:
    """Drive the browser-use agent to fill the application form.

    Stops before final submission. Returns a dict with the agent's history
    summary; full trace lives in run_dir/form_log.jsonl.
    """
    task = _build_task(profile, posting, resume_pdf, cover_pdf)
    (run_dir / "form_task.md").write_text(task, encoding="utf-8")

    llm = ChatAnthropic(model=ANTHROPIC_MODEL, api_key=ANTHROPIC_API_KEY, temperature=0)
    browser = Browser(config=BrowserConfig(headless=BROWSER_USE_HEADLESS))

    agent = Agent(
        task=task,
        llm=llm,
        browser=browser,
        save_conversation_path=str(run_dir / "form_log.jsonl"),
    )

    history = await agent.run(max_steps=50)
    await browser.close()

    summary = {
        "final_url": history.urls()[-1] if history.urls() else None,
        "n_steps": len(history.history),
        "errors": history.errors() if hasattr(history, "errors") else [],
        "screenshot": str(run_dir / "final_form.png"),
    }
    (run_dir / "form_result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
