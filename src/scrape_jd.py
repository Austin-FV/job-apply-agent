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
    # Languages
    "python", "java", "javascript", "typescript", "go", "rust", "c++", "c#", "sql",
    # Web frameworks
    "react", "next.js", "node.js", "express", "flask", "django", "fastapi",
    # Test / automation
    "selenium", "playwright", "cypress", "junit", "pytest",
    # Cloud / infra
    "aws", "gcp", "azure", "docker", "kubernetes", "terraform",
    # Databases / data
    "postgresql", "mysql", "mongodb", "redis", "snowflake", "bigquery",
    "databricks", "dbt", "airflow",
    # AI / LLM platforms
    "anthropic", "openai", "llm", "llms", "claude", "gpt", "rag", "langchain",
    "langgraph", "mcp", "agentic", "vector database", "embeddings",
    # AI coding assistants
    "claude code", "cursor", "copilot", "windsurf",
    # AI rapid prototyping / no-code
    "lovable", "replit", "v0", "bolt", "figma",
    # Workflow automation platforms
    "gumloop", "zapier", "n8n", "make.com", "retool",
    # DevOps
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

    soup = BeautifulSoup(html, "html.parser")
    description_raw = _html_to_text(html)
    description_md = _html_to_markdown(html)

    title, company = _parse_title_company(title_tag, soup)
    requirements = _split_bullets_under(
        description_md, ["requirement", "qualification", "what you", "you have", "you'll need"]
    )
    responsibilities = _split_bullets_under(
        description_md, ["responsibilit", "what you'll do", "the role", "your day"]
    )
    location, remote_policy = _parse_location(html)
    keywords = _extract_keywords(description_raw)
    apply_url = _find_apply_url(url, source, soup)

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
        apply_url=apply_url,
        scraped_at=datetime.now(),
        raw_html_path=raw_html_path,
    )


def _meta(soup: BeautifulSoup, *keys: str) -> str | None:
    """Look up <meta property=... content=...> or <meta name=... content=...>."""
    for key in keys:
        tag = soup.find("meta", attrs={"property": key}) or soup.find(
            "meta", attrs={"name": key}
        )
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None


def _split_role_company(text: str) -> tuple[str, str] | None:
    """Pull (role, company) from a string with a common separator. Returns None on miss."""
    for sep in (" | ", " - ", " — ", " at "):
        if sep in text:
            a, b = text.split(sep, 1)
            return a.strip(), b.strip()
    return None


def _parse_title_company(page_title: str, soup: BeautifulSoup) -> tuple[str, str]:
    """Resolve (title, company) from meta tags first, then <title>, then logo alt."""
    og_title = _meta(soup, "og:title", "twitter:title")
    if og_title:
        parts = _split_role_company(og_title)
        if parts:
            return parts

    site_name = _meta(soup, "og:site_name", "application-name")

    parts = _split_role_company(page_title)
    if parts:
        return parts

    # Final fallback: logo alt text often holds the company name.
    company = site_name or "Unknown"
    if company == "Unknown":
        for img in soup.find_all("img"):
            alt = (img.get("alt") or "").strip()
            if alt and len(alt) < 40 and "logo" not in alt.lower():
                company = alt
                break

    return page_title.strip() or "Unknown", company


def _find_apply_url(posting_url: str, source: str, soup: BeautifulSoup) -> str:
    """Find the apply form URL.

    Strategy:
    1. Scan anchors for an 'Apply'-text link with a real href (Greenhouse, Lever, generic).
    2. If none, fall back to per-ATS URL construction (Rippling uses a JS button).
    3. Last resort: the posting URL itself (handles inline forms like Greenhouse).
    """
    from urllib.parse import urljoin

    for a in soup.find_all("a", href=True):
        text = (a.get_text(strip=True) or "").lower()
        if "apply" in text and len(text) < 30:
            href = a["href"]
            if href and not href.startswith("#"):
                return urljoin(posting_url, href)

    if source == "rippling":
        sep = "&" if "?" in posting_url else "?"
        if "/apply" not in posting_url:
            return f"{posting_url}/apply?step=application"
        if "step=" not in posting_url:
            return f"{posting_url}{sep}step=application"
    elif source == "lever" and "/apply" not in posting_url:
        return posting_url.rstrip("/") + "/apply"

    return posting_url


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
