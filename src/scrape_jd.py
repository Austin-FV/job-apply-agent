from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from src.schemas import JobPosting


def _detect_source(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "rippling" in host:
        return "rippling"
    if "greenhouse" in host:
        return "greenhouse"
    if "lever" in host:
        return "lever"
    if "workday" in host:
        return "workday"
    return "generic"


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)


def _html_to_markdown(html: str) -> str:
    """Quick-and-dirty markdownification — preserve headings and bullets."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    lines: list[str] = []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
        text = el.get_text(" ", strip=True)
        if not text:
            continue
        if el.name in ("h1", "h2"):
            lines.append(f"\n## {text}\n")
        elif el.name in ("h3", "h4"):
            lines.append(f"\n### {text}\n")
        elif el.name == "li":
            lines.append(f"- {text}")
        else:
            lines.append(text)
    return "\n".join(lines)


def _split_bullets_under(md: str, headings: list[str]) -> list[str]:
    """Find bullets that follow any heading matching one of the keywords."""
    out: list[str] = []
    lines = md.splitlines()
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("##"):
            heading = stripped.lstrip("#").strip().lower()
            in_section = any(h in heading for h in headings)
            continue
        if in_section and stripped.startswith("- "):
            out.append(stripped[2:].strip())
    return out


_TECH_KEYWORDS = {
    "python", "java", "javascript", "typescript", "go", "rust", "c++", "c#",
    "react", "next.js", "node.js", "express", "flask", "django", "fastapi",
    "selenium", "playwright", "cypress", "junit", "pytest",
    "aws", "gcp", "azure", "docker", "kubernetes", "terraform",
    "postgresql", "mysql", "mongodb", "redis", "snowflake", "bigquery",
    "anthropic", "openai", "llm", "claude", "gpt", "rag", "langchain",
    "ci/cd", "github actions", "jenkins",
}


def _extract_keywords(text: str) -> list[str]:
    found = set()
    lower = text.lower()
    for kw in _TECH_KEYWORDS:
        if re.search(r"\b" + re.escape(kw) + r"\b", lower):
            found.add(kw)
    return sorted(found)


async def scrape(url: str, run_dir: Path) -> JobPosting:
    """Fetch and parse a job posting. Saves raw HTML to run_dir/jd.html."""
    source = _detect_source(url)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(url, wait_until="networkidle", timeout=30_000)
        html = await page.content()
        title_tag = await page.title()
        await browser.close()

    raw_html_path = run_dir / "jd.html"
    raw_html_path.write_text(html, encoding="utf-8")

    description_raw = _html_to_text(html)
    description_md = _html_to_markdown(html)

    # Best-effort field extraction — refine per-source as you encounter them.
    title, company = _parse_title_company(title_tag, html, source)
    requirements = _split_bullets_under(
        description_md, ["requirement", "qualification", "what you", "you have", "you'll need"]
    )
    responsibilities = _split_bullets_under(
        description_md, ["responsibilit", "what you'll do", "the role", "your day"]
    )
    location, remote_policy = _parse_location(html)
    keywords = _extract_keywords(description_raw)

    return JobPosting(
        url=url,
        source=source,
        company=company,
        title=title,
        location=location,
        employment_type=None,
        remote_policy=remote_policy,
        salary_range=None,
        description_raw=description_raw,
        description_md=description_md,
        requirements=requirements,
        responsibilities=responsibilities,
        keywords=keywords,
        apply_url=url,  # refine if the posting links out to a separate form
        scraped_at=datetime.now(),
        raw_html_path=raw_html_path,
    )


def _parse_title_company(page_title: str, html: str, source: str) -> tuple[str, str]:
    """Heuristic. Page titles tend to be 'Role - Company' or 'Company | Role'."""
    if " - " in page_title:
        a, b = page_title.split(" - ", 1)
        return a.strip(), b.strip()
    if " | " in page_title:
        a, b = page_title.split(" | ", 1)
        return a.strip(), b.strip()
    if " at " in page_title:
        a, b = page_title.split(" at ", 1)
        return a.strip(), b.strip()
    return page_title.strip(), "Unknown"


def _parse_location(html: str) -> tuple[str | None, str | None]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True).lower()
    remote = None
    if "remote" in text:
        remote = "Remote"
    if "hybrid" in text:
        remote = "Hybrid"
    if "on-site" in text or "onsite" in text:
        remote = "Onsite"
    return None, remote
