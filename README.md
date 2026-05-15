# job-apply-agent

An AI agent that applies to a job from a URL. It scrapes the posting, generates a tailored resume and cover letter from a structured profile, and drives a browser to fill the ATS form — end-to-end, in one command.

```
$ uv run job-apply apply <posting-url> --reveal-agent
```

> This repo was built to apply to Opendoor's [Operations AI Engineer role in Toronto](https://ats.rippling.com/en-CA/opendoor/jobs/f572e889-0644-4590-8a5a-64f73d7db17d) in response to [Kaz Nejatian's challenge](https://x.com/nejatian/status/2054547638997966976): apply using only AI, explain how you did it, extra points for creativity. The artifacts of that exact run are committed under [`runs/`](runs/) so you can inspect what the agent actually produced.

<!-- TODO: embed a 60-90 second screen recording of the agent filling the form here. The video file is at runs/<latest>/video/. -->

## What it does

```
   ┌──────────────┐    ┌──────────────────┐    ┌────────────────┐
   │ scrape_jd.py │ ─► │ generate_docs.py │ ─► │  fill_form.py  │
   └──────────────┘    └──────────────────┘    └────────────────┘
   Playwright +        Claude Sonnet 4.6        browser-use agent
   BeautifulSoup       resume JSON + cover      driving Chromium
                       prose, rendered to       via LangChain
                       PDF via Playwright       ChatAnthropic
```

Three stages, each with a typed contract between them. From `JobPosting` → `ResumeContent` → rendered PDFs → filled form, every boundary is a Pydantic schema. That's what makes the output trustworthy enough to actually submit.

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
- **`browser-use`** + **`langchain-anthropic`** for the ATS form-filling agent
- **Playwright** for JD scraping and HTML → PDF rendering
- **Pydantic v2** for every typed contract in the pipeline
- **Jinja2** templates rendering a Jake's-style resume layout

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
uv run job-apply apply <posting-url> --skip-form     # generate docs only
uv run job-apply apply <posting-url>                  # + fill form, stop before submit
uv run job-apply apply <posting-url> --autonomous     # + click submit
uv run job-apply apply <posting-url> --reveal-agent   # cover letter leads with agent disclosure
```

Each run lands in `runs/<timestamp>-<company>-<role>/`:

```
runs/20260515-013040-opendoor-operations-ai-engineer/
├── jd.html, jd.json          scraped JD + parsed JobPosting
├── resume.json               LLM-tailored ResumeContent (audit trail)
├── resume.html, resume.pdf   final resume
├── cover_letter.md, .pdf     cover letter
├── form_task.md              task prompt handed to browser-use
├── form_log.jsonl            agent step-by-step trace
├── form_result.json          final URL, step count, errors
└── video/                    Playwright screen recording of the run
```

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
