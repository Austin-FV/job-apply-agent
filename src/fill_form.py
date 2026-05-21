from __future__ import annotations

import json
import subprocess
from pathlib import Path

from browser_use import Agent, Browser
from browser_use.agent.gif import _add_overlay_to_image, create_history_gif
from browser_use.llm import ChatAnthropic
from imageio_ffmpeg import get_ffmpeg_exe

# browser-use's GIF overlay defaults to a fully-opaque black box behind the
# step number and goal text. That hides whatever browser content sits behind
# it. Patch the function's default text_box_color from alpha=255 to alpha=180
# (≈70% opaque) so the screenshot bleeds through and no step is fully hidden.
_defaults = list(_add_overlay_to_image.__defaults__ or ())
_defaults[-1] = (0, 0, 0, 180)  # text_box_color = semi-transparent black
_add_overlay_to_image.__defaults__ = tuple(_defaults)


def _trim_video_intro(video_path: Path, skip_seconds: float) -> None:
    """Trim the first `skip_seconds` off the recorded form-fill video.

    The recording starts when Chromium connects to CDP, which is several seconds
    before the agent actually navigates to the apply URL — the front of the
    video is browser launch / new-tab animations. Skip past it.

    Uses the ffmpeg binary bundled with imageio-ffmpeg. No re-encode (-c copy)
    so the trim is fast and lossless.
    """
    ffmpeg = get_ffmpeg_exe()
    trimmed = video_path.with_name(video_path.stem + ".trimmed" + video_path.suffix)
    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-ss", str(skip_seconds),
            "-i", str(video_path),
            "-c", "copy",
            str(trimmed),
        ],
        capture_output=True,
    )
    if result.returncode == 0 and trimmed.exists() and trimmed.stat().st_size > 0:
        trimmed.replace(video_path)
    else:
        # Trim failed (very short video, weird codec, etc.) — leave the original.
        if trimmed.exists():
            trimmed.unlink()

from src.config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_FILL_MODEL,
    BROWSER_USE_HEADLESS,
    VIDEO_INTRO_TRIM_SECONDS,
    load_prompt,
)
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
"""


async def fill_application(
    profile: Profile,
    posting: JobPosting,
    resume_pdf: Path,
    cover_pdf: Path,
    run_dir: Path,
    autonomous: bool = False,
    record: bool = False,
) -> dict:
    """Drive the browser-use agent to fill the application form.

    Default: stops at the review step before submission so the human can verify
    and click submit. Pass autonomous=True to let the agent click submit itself.

    An annotated GIF of the agent's steps is always written to
    run_dir/form_run.gif. When record=True, a continuous MP4 of the whole
    session is also written to run_dir/form_run.mp4. The full agent trace
    lives in run_dir/form_log.jsonl regardless.
    """
    task = _build_task(profile, posting, resume_pdf, cover_pdf, autonomous)
    (run_dir / "form_task.md").write_text(task, encoding="utf-8")

    gif_path = run_dir / "form_run.gif"
    # Recording is opt-in: the annotated GIF is essentially free (stitched from
    # screenshots the agent already captured), but the continuous MP4 adds
    # CDP screencast + imageio encoding + trim overhead. Only useful for demos.
    video_dir: Path | None = None
    if record:
        video_dir = run_dir / "video"
        video_dir.mkdir(exist_ok=True)

    llm = ChatAnthropic(
        model=ANTHROPIC_FILL_MODEL, api_key=ANTHROPIC_API_KEY, temperature=0
    )
    # Smaller window → smaller screenshots → faster vision call on every step.
    browser_kwargs: dict = {
        "headless": BROWSER_USE_HEADLESS,
        "window_size": {"width": 1280, "height": 800},
    }
    if record:
        browser_kwargs["record_video_dir"] = video_dir
    browser = Browser(**browser_kwargs)

    agent = Agent(
        task=task,
        llm=llm,
        browser=browser,
        available_file_paths=[str(resume_pdf), str(cover_pdf)],
        # We render the GIF ourselves after run() so we can drop the unreadable
        # task-text frame and tighten per-step duration.
        save_conversation_path=str(run_dir / "form_log.jsonl"),
    )

    history = await agent.run(max_steps=60 if autonomous else 50)
    await browser.stop()

    # Render the run-through GIF. Pass a SHORT task summary instead of the full
    # checklist (the full task would be an unreadable wall of text on frame 1).
    # browser-use also drops about:blank screenshots, which can make labels look
    # like they start at "Step 2" — an intro slate sets context cleanly.
    # Default per-step duration is 3s; 1.2s makes the run watchable as an embed.
    gif_task = f"Apply to {posting.title} at {posting.company}"
    create_history_gif(
        task=gif_task,
        history=history,
        output_path=str(gif_path),
        show_task=True,
        duration=1200,
    )

    # browser-use writes the recording via CDP screencast + imageio. Default
    # format is MP4 but configurable; accept either. Rename to a stable filename
    # at the run-dir root so README links and other tooling can rely on the path.
    video_path: Path | None = None
    if record and video_dir is not None:
        candidates = list(video_dir.glob("*.mp4")) + list(video_dir.glob("*.webm"))
        if candidates:
            suffix = candidates[0].suffix
            video_path = run_dir / f"form_run{suffix}"
            candidates[0].replace(video_path)
            try:
                video_dir.rmdir()  # empty now; keep the run dir flat
            except OSError:
                pass  # leave it if other files snuck in

            # Trim the browser-launch lead-in so the video starts at real work.
            if VIDEO_INTRO_TRIM_SECONDS > 0:
                _trim_video_intro(video_path, VIDEO_INTRO_TRIM_SECONDS)

    summary = {
        "autonomous": autonomous,
        "final_url": history.urls()[-1] if history.urls() else None,
        "n_steps": len(history.history),
        "errors": history.errors() if hasattr(history, "errors") else [],
        "gif": str(gif_path) if gif_path.exists() else None,
        "video": str(video_path) if video_path else None,
    }
    (run_dir / "form_result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
