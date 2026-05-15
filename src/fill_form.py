from __future__ import annotations

import json
from pathlib import Path

from browser_use import Agent, Browser
from browser_use.llm import ChatAnthropic

from src.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, BROWSER_USE_HEADLESS, load_prompt
from src.schemas import JobPosting, Profile


def _build_task(
    profile: Profile,
    posting: JobPosting,
    resume_pdf: Path,
    cover_pdf: Path,
    autonomous: bool,
) -> str:
    field_map = load_prompt("form_field_map.md")
    p = profile.personal
    auth = profile.work_authorization
    screen = profile.screening_answers

    submit_clause = (
        "5. After every applicable field has a value AND both PDFs are uploaded, click\n"
        "   the final Submit/Apply button to complete the application. Take a screenshot\n"
        "   of the confirmation page shown AFTER submission."
        if autonomous
        else "5. STOP at the final submit/review step. DO NOT click submit. Take a full-page\n"
        "   screenshot of the completed form for human review, then exit."
    )

    return f"""You are filling out a job application form for {posting.company} — {posting.title}.

APPLY URL: {posting.apply_url}

YOUR GOAL:
1. Navigate to the apply URL.
2. **Scroll all the way through the form first**, top to bottom, to learn what fields exist BEFORE filling anything. Forms often have collapsed or below-the-fold sections (work authorization, screening questions, custom Qs) that aren't visible on initial load. Build a mental map of every section.
3. Fill every applicable field using the applicant data below — go SECTION BY SECTION, top to bottom. Do not skip fields just because they look optional unless the data explicitly says so (e.g., demographics are optional, screening questions are not).
4. Upload the resume and cover letter PDFs at the indicated paths.
{submit_clause}

FIELD REFERENCE — the form MAY contain any subset of the fields below. It is normal and expected that a given ATS only asks for some of these. Fill every field that is PRESENT on the form using the data above. Do NOT treat an absent field as a problem, do NOT hunt for fields that aren't there, and do NOT report missing fields as a failure — many ATS forms are intentionally short.

Possible fields (fill the ones that exist):
  - Personal: first name, last name, preferred name, email, phone, location, LinkedIn, GitHub, portfolio, current company
  - Work authorization: authorized to work, requires sponsorship, US status, willing to relocate, remote preference
  - Screening: years of experience, desired salary, notice period, start date, how did you hear, assessment willingness, background check consent, any custom questions
  - Files: resume PDF, cover letter PDF (verify the filename appears on the form, not "No file chosen")
  - Demographics/EEO (optional): fill from the data, or select "prefer not to say"; never invent

COMPLETION SIGNAL — the form is complete when the Apply/Submit button is ENABLED (not greyed out). A disabled button means a required field on the form is still empty: scroll the whole form and find it. An enabled button means every required field this form actually has is filled — you are done, regardless of which optional fields exist. Trust the button state over any expectation of what fields "should" be there.

Before finishing: scroll the full form once to confirm no field shows a red/required error indicator. The GIF of your run is captured automatically — a manual screenshot is a nice-to-have, not required; if your screenshot tool produces a PDF that is acceptable.

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
    autonomous: bool = False,
) -> dict:
    """Drive the browser-use agent to fill the application form.

    Default: stops at the review step before submission so the human can verify
    and click submit. Pass autonomous=True to let the agent click submit itself.

    Full trace lives in run_dir/form_log.jsonl. A screen recording of the run
    is saved to run_dir/video/.
    """
    task = _build_task(profile, posting, resume_pdf, cover_pdf, autonomous)
    (run_dir / "form_task.md").write_text(task, encoding="utf-8")

    gif_path = run_dir / "form_run.gif"

    llm = ChatAnthropic(model=ANTHROPIC_MODEL, api_key=ANTHROPIC_API_KEY, temperature=0)
    browser = Browser(headless=BROWSER_USE_HEADLESS)

    agent = Agent(
        task=task,
        llm=llm,
        browser=browser,
        available_file_paths=[str(resume_pdf), str(cover_pdf)],
        generate_gif=str(gif_path),
        save_conversation_path=str(run_dir / "form_log.jsonl"),
    )

    history = await agent.run(max_steps=60 if autonomous else 50)
    await browser.stop()

    summary = {
        "autonomous": autonomous,
        "final_url": history.urls()[-1] if history.urls() else None,
        "n_steps": len(history.history),
        "errors": history.errors() if hasattr(history, "errors") else [],
        "gif": str(gif_path) if gif_path.exists() else None,
    }
    (run_dir / "form_result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
