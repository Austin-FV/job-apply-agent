from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field, HttpUrl, field_validator

YearMonth = Annotated[str, Field(pattern=r"^\d{4}-\d{2}$|^present$")]


class Location(BaseModel):
    city: str
    province: str
    country: str


class Personal(BaseModel):
    full_name: str
    preferred_name: str
    email: EmailStr
    phone: str
    location: Location
    links: dict[str, HttpUrl]


class WorkAuth(BaseModel):
    canada: Literal["citizen", "pr", "work_permit", "need_sponsorship"]
    us: Literal["citizen", "pr", "work_permit", "need_sponsorship"]
    willing_to_relocate: bool
    remote_preference: Literal["remote", "hybrid", "onsite", "flexible"]


class Experience(BaseModel):
    company: str
    title: str
    location: str
    start: YearMonth
    end: YearMonth
    summary: str
    achievements: list[str]
    tech: list[str] = []
    tags: list[str] = []


class Project(BaseModel):
    name: str
    url: HttpUrl | None = None
    start: YearMonth | None = None
    end: YearMonth | None = None
    summary: str
    achievements: list[str] = []
    tech: list[str] = []
    tags: list[str] = []


class Education(BaseModel):
    school: str
    degree: str
    location: str
    start: YearMonth
    end: YearMonth
    honors: list[str] = []
    relevant_courses: list[str] = []


class Skills(BaseModel):
    languages: list[str]
    frameworks: list[str]
    databases: list[str]
    cloud_infra: list[str]
    tools: list[str]
    practices: list[str]
    ai: list[str] = []


class Narrative(BaseModel):
    elevator_pitch: str
    career_themes: list[str]
    why_im_looking: str
    personal_color: str | None = None


class Preferences(BaseModel):
    desired_salary_cad: str | int
    notice_period_weeks: int
    start_date: str
    references: str


class ScreeningAnswers(BaseModel):
    years_of_experience: int
    authorized_to_work_canada: bool
    requires_sponsorship_canada: bool
    willing_to_complete_assessment: bool
    comfortable_with_background_check: bool
    how_did_you_hear: str


class Profile(BaseModel):
    personal: Personal
    work_authorization: WorkAuth
    demographics: dict[str, str] = {}
    experience: list[Experience]
    education: list[Education]
    skills: Skills
    projects: list[Project] = []
    certifications: list[str] = []
    narrative: Narrative
    company_specific: dict = {}
    preferences: Preferences
    screening_answers: ScreeningAnswers


# ---------------- JobPosting (scrape_jd -> generate_docs) ----------------


class JobPosting(BaseModel):
    url: HttpUrl
    source: str  # "rippling" | "greenhouse" | "lever" | "generic"
    company: str
    title: str
    location: str | None = None
    employment_type: str | None = None
    remote_policy: str | None = None
    salary_range: str | None = None
    description_raw: str
    description_md: str
    requirements: list[str] = []
    responsibilities: list[str] = []
    keywords: list[str] = []
    apply_url: HttpUrl
    scraped_at: datetime
    raw_html_path: Path | None = None


# ---------------- ResumeContent (LLM -> Jinja) ----------------


class ResumeBullet(BaseModel):
    """A bullet point for the tailored resume.

    Policy: every bullet must trace back to an existing profile achievement.
    source_tag identifies the origin so we can verify no hallucination.
    """

    text: str
    source_tag: str  # e.g. "experience:Express Scripts Canada:2" or "project:gimmit:0"

    @field_validator("source_tag")
    @classmethod
    def _source_tag_shape(cls, v: str) -> str:
        if not re.match(r"^(experience|project):[^:]+:\d+$", v):
            raise ValueError(
                "source_tag must be 'experience:<company>:<idx>' or 'project:<name>:<idx>'"
            )
        return v


class ResumeExperience(BaseModel):
    company: str
    title: str
    location: str
    start: YearMonth
    end: YearMonth
    bullets: list[ResumeBullet]


class ResumeProject(BaseModel):
    name: str
    url: HttpUrl | None = None
    one_liner: str
    bullets: list[ResumeBullet]


class ResumeContent(BaseModel):
    headline: str
    summary: str
    experience: list[ResumeExperience]
    projects: list[ResumeProject]
    skills_grouped: dict[str, list[str]]
    education: list[Education]
    keywords_covered: list[str]
