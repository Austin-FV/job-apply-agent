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

COMPLETENESS CHECKLIST — before you claim done, verify EVERY item below has been addressed. If any required field is unfilled, the Apply/Submit button will be disabled — that is your signal you missed something. Scroll back and find it.

Personal:
  [ ] First name, last name, preferred name, email, phone
  [ ] Location (city + province/state + country, may be a single autocomplete field)
  [ ] LinkedIn, GitHub, Portfolio (all three URLs)
  [ ] Current company (if asked)

Work authorization (these are usually radio buttons or dropdowns):
  [ ] Authorized to work in Canada
  [ ] Requires sponsorship in Canada
  [ ] US work status (separate question on many forms)
  [ ] Willing to relocate
  [ ] Remote work preference

Screening questions (often scattered through the form):
  [ ] Years of experience
  [ ] Desired salary
  [ ] Notice period
  [ ] Earliest start date
  [ ] How did you hear about us
  [ ] Willing to complete assessment / take-home
  [ ] Comfortable with background check
  [ ] Any custom screening questions the company added

Files:
  [ ] Resume PDF uploaded (verify the filename shows on the form, not "No file chosen")
  [ ] Cover letter PDF uploaded (same verification)

Demographics / EEO (optional — use the data; never invent):
  [ ] Each field either filled or set to "prefer not to say"

After filling: scroll the entire form one more time to confirm no field shows an error/required indicator. The Apply button being ENABLED is the strongest signal completeness has been reached.

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

    video_dir = run_dir / "video"
    video_dir.mkdir(exist_ok=True)

    llm = ChatAnthropic(model=ANTHROPIC_MODEL, api_key=ANTHROPIC_API_KEY, temperature=0)
    browser = Browser(
        headless=BROWSER_USE_HEADLESS,
        record_video_dir=video_dir,
    )

    agent = Agent(
        task=task,
        llm=llm,
        browser=browser,
        available_file_paths=[str(resume_pdf), str(cover_pdf)],
        save_conversation_path=str(run_dir / "form_log.jsonl"),
    )

    history = await agent.run(max_steps=60 if autonomous else 50)
    await browser.stop()

    summary = {
        "autonomous": autonomous,
        "final_url": history.urls()[-1] if history.urls() else None,
        "n_steps": len(history.history),
        "errors": history.errors() if hasattr(history, "errors") else [],
        "video_dir": str(video_dir),
    }
    (run_dir / "form_result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
