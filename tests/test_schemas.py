from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.schemas import ResumeBullet, ResumeContent, YearMonth  # noqa: F401


def test_source_tag_required_shape():
    ResumeBullet(text="x", source_tag="experience:Acme Corp:0")
    ResumeBullet(text="x", source_tag="project:gimmit:2")


def test_source_tag_rejects_freeform():
    with pytest.raises(ValidationError):
        ResumeBullet(text="x", source_tag="made-it-up")


def test_source_tag_rejects_missing_index():
    with pytest.raises(ValidationError):
        ResumeBullet(text="x", source_tag="experience:Acme")
