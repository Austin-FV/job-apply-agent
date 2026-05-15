# job-apply-agent

Takes a job posting URL, generates a tailored resume + cover letter PDF from your `profile.yaml`, and drives a `browser-use` agent to fill the ATS form end-to-end. Stops before final submit so you can review.

## Stack

- Python 3.11+
- [`anthropic`](https://pypi.org/project/anthropic/) — Claude Sonnet 4.6 for generation
- [`browser-use`](https://github.com/browser-use/browser-use) — LLM-driven browser agent for ATS forms
- [`playwright`](https://playwright.dev/python/) — JD scraping and the browser layer browser-use rides on
- [`jinja2`](https://jinja.palletsprojects.com/) + [`weasyprint`](https://weasyprint.org/) — HTML templates rendered to PDF
- [`pydantic`](https://docs.pydantic.dev/) v2 — profile and JD schema validation
- `uv` for dependency management

## Setup

```bash
uv sync
uv run playwright install chromium
cp .env.example .env
# edit .env: paste ANTHROPIC_API_KEY
```

Replace `profile.yaml` with your real profile (validated against `src/schemas.py::Profile`).

### WeasyPrint on Windows

WeasyPrint needs GTK runtime libraries installed system-wide for PDF rendering. Install the [GTK3 runtime](https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases) once, then PDF rendering works. Without it, you'll see a `cannot load library 'libgobject-2.0-0'` error.

## Usage

```bash
# end-to-end: scrape -> generate -> fill form (stops before submit)
uv run job-apply apply "https://ats.rippling.com/opendoor/jobs/<id>"

# generate docs only, skip the browser agent
uv run job-apply apply <url> --skip-form

# scrape only — useful when debugging selector issues
uv run job-apply scrape-only <url>
```

Each run lands in `runs/<timestamp>-<company>-<role>/`:

```
runs/20260514-093015-opendoor-ai-ops-engineer/
├── jd.html               raw scraped HTML
├── jd.json               structured JobPosting
├── resume.json           LLM output (audit trail with source_tag per bullet)
├── resume.html           rendered template
├── resume.pdf            final resume
├── cover_letter.md       LLM output
├── cover_letter.html
├── cover_letter.pdf
├── form_task.md          the task prompt handed to browser-use
├── form_log.jsonl        browser-use trace
└── form_result.json      final URL + step count + errors
```

## How it works

1. **`scrape_jd.py`** — Playwright fetches the page, BeautifulSoup cleans HTML to text + markdown, regex pulls out requirements/responsibilities bullets, a keyword list flags tech overlap.
2. **`generate_docs.py`** — two Claude calls:
   - Resume: returns structured `ResumeContent` JSON. Every bullet carries a `source_tag` pointing back to the original `profile.yaml` achievement — no hallucinated experience.
   - Cover letter: returns prose in the candidate's voice, grounded in `profile.narrative`.
   - Both rendered via Jinja templates and WeasyPrint to PDF.
3. **`fill_form.py`** — builds a task prompt with the applicant data + file paths, hands it to `browser-use` (`ChatAnthropic` driver). Agent fills fields, uploads PDFs, stops at review.

## Anti-hallucination

The resume tailor prompt enforces a strict policy:

- Bullets must be selected (with light editing) from existing `profile.experience[].achievements` or `profile.projects[].achievements`.
- Every `ResumeBullet` carries a `source_tag` like `experience:Express Scripts Canada:2` — Pydantic rejects anything else.
- `keywords_covered` is an audit field listing which JD keywords actually made it into the resume.

If the LLM tries to invent bullets, Pydantic validation fails and you see the bad output in `runs/<id>/resume.json`.

## Tests

```bash
uv run pytest
```

## Layout

```
src/
├── config.py          env, paths, profile + prompt loaders, run dir, logger
├── schemas.py         Pydantic: Profile, JobPosting, ResumeContent
├── scrape_jd.py       Playwright scraper -> JobPosting
├── generate_docs.py   Claude -> ResumeContent + cover prose -> PDFs
├── fill_form.py       browser-use agent driver
├── run.py             Typer CLI
└── prompts/
    ├── resume_tailor.md
    ├── cover_letter.md
    └── form_field_map.md
templates/
├── resume.html.j2
├── cover_letter.html.j2
└── styles.css
runs/                  per-application artifacts (gitignored)
```
