# job-apply-agent

An AI agent that applies to a job from a URL. It scrapes the posting, generates a tailored resume and cover letter from a structured profile, and drives a browser to fill the ATS form — end-to-end, in one command.

```
$ uv run job-apply apply <posting-url> --reveal-agent
```

> This repo was built to apply to Opendoor's [Operations AI Engineer role in Toronto](https://ats.rippling.com/en-CA/opendoor/jobs/f572e889-0644-4590-8a5a-64f73d7db17d) in response to [Kaz Nejatian's challenge](https://x.com/nejatian/status/2054547638997966976): apply using only AI, explain how you did it, extra points for creativity. The artifacts of that exact run are committed under [`runs/`](runs/) so you can inspect what the agent actually produced.

<!-- TODO: embed the agent-run GIF here. Generated automatically at runs/<latest>/form_run.gif — an annotated step-by-step of the agent filling the ATS form. -->

## What it does

```
   ┌──────────────┐    ┌──────────────────┐    ┌────────────────┐
   │ scrape_jd.py │ ─► │ generate_docs.py │ ─► │  fill_form.py  │
   └──────────────┘    └──────────────────┘    └────────────────┘
   Playwright +        Claude Sonnet 4.6        browser-use agent
   BeautifulSoup       resume JSON + cover      driving Chromium,
   ATS detection       prose, rendered to       Claude Sonnet 4.6
   keyword extract     PDF via Playwright       as the brain
```

Three stages, each with a typed contract between them. From `JobPosting` → `ResumeContent` → rendered PDFs → filled form, every boundary is a Pydantic schema. That's what makes the output trustworthy enough to actually submit.

## Capabilities

**JD scraping** ([`scrape_jd.py`](src/scrape_jd.py))
- Renders JS-heavy ATS pages with Playwright (no empty-shell HTML problem)
- Detects the ATS source (Rippling / Greenhouse / Lever / Workday / generic)
- Extracts company + title from `og:` meta tags with `<title>` and logo-alt fallbacks
- Auto-derives the apply-form URL: scrapes the apply anchor, falls back to per-ATS URL patterns when the button is JS-driven (Rippling)
- Pulls requirements/responsibilities bullets and an AI-tooling-aware keyword set (Claude Code, Cursor, MCP, Gumloop, Replit, Snowflake, …) for cheap relevance matching before any LLM call
- Saves raw HTML for replay; scrapes are reproducible

**Resume tailoring** ([`generate_docs.py`](src/generate_docs.py), [`resume_tailor.md`](src/prompts/resume_tailor.md))
- Claude Sonnet 4.6 returns a structured `ResumeContent` JSON, not freeform text
- **Anti-hallucination**: every bullet carries a `source_tag` validated by Pydantic — the model cannot invent experience (see design decision #1)
- Selects and lightly edits from real profile achievements; never fabricates metrics
- One-page Jake's-style layout with a page budget the prompt enforces (≤4 bullets/role, 3–4 projects), tuned to ~90% fill
- `keywords_covered` audit field reports which JD keywords actually landed in the resume

**Cover letter** ([`cover_letter.md`](src/prompts/cover_letter.md))
- Two modes: **default** (standard letter in the candidate's voice) and **agent-reveal** (`--reveal-agent`: leads with the agent disclosure, technical architecture, repo link — for submissions where the agent itself is the signal)
- Grounded in `profile.narrative`; no invented experiences

**PDF rendering**
- Jinja2 → HTML → PDF via Playwright's `page.pdf()`. Zero native dependencies (replaced WeasyPrint after Windows GTK pain — see git history)
- Shared print stylesheet inlined into the HTML so rendering is self-contained

**ATS form filling** ([`fill_form.py`](src/fill_form.py))
- A `browser-use` agent driven by Claude Sonnet 4.6 (browser-use's native client) fills any ATS form — one code path, no per-site scripts
- Checklist-driven, **form-agnostic**: fills whatever fields a given form actually has; treats absent fields as normal; uses the Apply-button-enabled state as the completion signal
- Uploads resume + cover letter via an explicit file-path allowlist (browser-use security requirement)
- Generates an annotated **GIF of the entire run** (`form_run.gif`) — each step with the agent's goal overlaid
- Two submission modes: **review-stop** (default — fills the form, stops before submit for human verification) and **`--autonomous`** (clicks submit, captures the confirmation page)

**Run management** ([`run.py`](src/run.py))
- Every run is a self-contained, timestamped dir under `runs/` — JD, JSON outputs, PDFs, agent trace, GIF
- `--use-run <id>|latest` reuses prior docs and only re-runs the form fill, in a fresh isolated dir (the source dir stays read-only) — cheap iteration on form-fill without re-spending on doc generation
- `scrape-only <url>` subcommand for debugging the scraper in isolation
- Structured JSON logging throughout (`structlog`)

## Three design decisions worth calling out

### 1. Anti-hallucination via `source_tag`

LLMs invent experience. That's a hard blocker for a job-application agent — fabricated bullets get you fired in the interview. The fix in this codebase: every `ResumeBullet` must carry a `source_tag` like `experience:Express Scripts Canada:2` or `project:gimmit:0`, where the integer indexes into the candidate's actual `profile.yaml` achievements.

```python
class ResumeBullet(BaseModel):
    text: str
    source_tag: str  # "experience:<company>:<idx>" or "project:<name>:<idx>"

    @field_validator("source_tag")
    @classmethod
    def _source_tag_shape(cls, v: str) -> str:
        if not re.match(r"^(experience|project):[^:]+:\d+$", v):
            raise ValueError(...)
```

The prompt requires every bullet to have one. Pydantic rejects anything else at parse time. The LLM cannot output a bullet that doesn't trace back to a real entry in the profile. (Validating that the index *exists* in the source profile is a defense-in-depth follow-up — covered in the prompt for now, code-validated next iteration.)

### 2. Typed pipeline, not chat-driven glue

Each stage is a pure function with a typed contract. Scraper returns `JobPosting`. Resume tailor returns `ResumeContent`. Templates consume `ResumeContent`. No "string passes through six prompts" anti-pattern.

This matters because it makes failures debuggable. When the first end-to-end run failed on `projects[].one_liner missing`, the error pointed at a single Pydantic field on a single LLM call — not "the model returned garbage somewhere." Fixed in one prompt edit and one schema tweak.

The full schema lives in [`src/schemas.py`](src/schemas.py).

### 3. `browser-use` over deterministic per-ATS scripts

The naive path is to write per-ATS Playwright scripts (one for Rippling, one for Greenhouse, one for Lever, one for Workday). Each one bit-rots the moment the ATS redesigns. Hundreds of LOC of maintenance.

`browser-use` flips it: hand the LLM a vision-aware browser, a task description, and the applicant data; it figures out the fields itself. One code path covers every ATS. Tradeoff: slower per-application (~$0.30 of LLM calls), occasionally needs guidance prompts. Worth it.

The form-fill task lives in [`src/fill_form.py`](src/fill_form.py); the field-mapping hints the agent uses live in [`src/prompts/form_field_map.md`](src/prompts/form_field_map.md).

## Stack

- **Python 3.11+**, `uv` for deps
- **Claude Sonnet 4.6** via the `anthropic` SDK for resume and cover letter generation
- **`browser-use`** for the ATS form-filling agent, using its native Claude client (the LangChain integration was dropped after an API-contract break — `browser-use` walked away from the LangChain ecosystem mid-development; the git history has the debugging trail)
- **Playwright** for JD scraping and HTML → PDF rendering
- **Pydantic v2** for every typed contract in the pipeline
- **Jinja2** templates rendering a Jake's-style resume layout
- **Typer** CLI, **structlog** for run logs

## Quickstart

```bash
git clone https://github.com/Austin-FV/job-apply-agent
cd job-apply-agent
uv sync
uv run playwright install chromium
cp .env.example .env
# paste your ANTHROPIC_API_KEY into .env

# customize profile.yaml for your background
# then:
uv run job-apply apply <posting-url> --skip-form      # generate docs only
uv run job-apply apply <posting-url>                  # + fill form, stop before submit
uv run job-apply apply <posting-url> --autonomous     # + click submit
uv run job-apply apply <posting-url> --reveal-agent   # cover letter leads with agent disclosure

# iterate on the form fill without re-spending on doc generation:
uv run job-apply apply --use-run latest               # reuse latest run's docs, fresh form-fill dir
uv run job-apply apply --use-run <run-id> --autonomous

# debug the scraper in isolation:
uv run job-apply scrape-only <posting-url>
```

Flags compose: `--reveal-agent --autonomous` is the full closed-loop submission (agent-disclosing cover letter + the agent submitting itself).

Each run lands in `runs/<timestamp>-<company>-<role>/`:

```
runs/20260515-165420-opendoor-operations-ai-engineer/   ← the committed submission run
├── jd.html, jd.json          scraped JD + parsed JobPosting
├── resume.json               LLM-tailored ResumeContent (audit trail with source_tags)
├── resume.html, resume.pdf   final resume
├── cover_letter.md, .pdf     cover letter
├── form_task.md              task prompt handed to browser-use
├── form_log.jsonl            agent step-by-step trace
├── form_result.json          final URL, step count, errors
└── form_run.gif              annotated GIF of the agent filling the form
```

Each dir is self-contained — hand someone a run dir and they have the full picture of that application. `--use-run` copies `jd.json` + both PDFs into the new dir so form-fill retries are independently inspectable.

## Layout

```
src/
├── config.py          env, paths, profile + prompt loaders
├── schemas.py         Pydantic: Profile, JobPosting, ResumeContent
├── scrape_jd.py       Playwright scraper → JobPosting
├── generate_docs.py   Claude → ResumeContent → Jinja → PDF
├── fill_form.py       browser-use agent driver
├── run.py             Typer CLI
└── prompts/
    ├── resume_tailor.md    bullet selection policy + JSON schema example
    ├── cover_letter.md     default + agent-reveal modes
    └── form_field_map.md   ATS field-mapping hints for browser-use
templates/
├── resume.html.j2          Jake's-style single-column layout
├── cover_letter.html.j2
└── styles.css              inlined into HTML before PDF render
```

## What I'd build next

- **Source-tag existence validation** — Pydantic checks the *shape* but not that the index references a real profile entry. A post-parse pass that cross-references `source_tag` against the loaded `Profile` would close the last hallucination gap.
- **Per-application company research** — before generating the cover letter, do a quick web search + summarize for `company_specific` so the letter can reference something concrete the company is doing.
- **ATS adapter registry** — even with `browser-use`, some forms (Workday, especially) need an authenticated session flow. A small per-ATS preflight that handles login/redirects before handing off to the agent.
- **Multi-application batch mode** — a queue of postings, parallel runs, summary report. The architecture supports it (each run is isolated under `runs/<id>/`); just a thin orchestration layer.

## Background

I'm [Austin Varghese](https://austinfv.dev) — currently an Automation Engineer at Express Scripts Canada, looking to move from test automation into product engineering on a team building AI-powered tooling.

This repo is itself my application to Opendoor's Operations AI Engineer role. The cover letter, the resume, and the filled ATS form fields you're reading were all generated by the code here. The full submission run is in [`runs/`](runs/) — every JSON output, every browser-use trace, every PDF.
