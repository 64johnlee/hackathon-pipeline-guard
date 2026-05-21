"""Data models for PipelineGuard diagnosis results."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Confidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FailureCategory(str, Enum):
    MISSING_DEPENDENCY = "missing_dependency"
    ENV_VAR_MISSING = "env_var_missing"
    CONFIG_ERROR = "config_error"
    FLAKY_TEST = "flaky_test"
    LOGIC_BUG = "logic_bug"
    INFRASTRUCTURE = "infrastructure"
    PERMISSIONS = "permissions"
    UNKNOWN = "unknown"


@dataclass
class FixProposal:
    file_path: str
    description: str
    diff: str = ""
    confidence: Confidence = Confidence.MEDIUM


@dataclass
class DiagnosisReport:
    project: str
    root_cause: str
    failure_category: FailureCategory = FailureCategory.UNKNOWN
    affected_jobs: list[str] = field(default_factory=list)
    fix_proposals: list[FixProposal] = field(default_factory=list)
    full_analysis: str = ""
    pipeline_id: int | None = None
    pipeline_url: str | None = None
    mr_comment_url: str | None = None
    fix_mr_url: str | None = None
    is_flaky: bool = False
