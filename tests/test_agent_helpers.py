"""Tests for agent comment-formatting helpers (_md_inline, _fenced_diff, _format_comment)."""
from __future__ import annotations

import pytest

from pipelineguard.agent import _fenced_diff, _md_inline, _format_comment
from pipelineguard.models import (
    Confidence,
    DiagnosisReport,
    FailureCategory,
    FixProposal,
)


class TestMdInline:
    def test_plain_text_unchanged(self) -> None:
        assert _md_inline("hello world") == "hello world"

    def test_escapes_backtick(self) -> None:
        assert "\\`" in _md_inline("`code`")

    def test_escapes_brackets(self) -> None:
        out = _md_inline("[label](url)")
        assert "\\[" in out and "\\]" in out

    def test_escapes_angle_brackets(self) -> None:
        out = _md_inline("<script>alert(1)</script>")
        assert "\\<" in out and "\\>" in out

    def test_escapes_backslash(self) -> None:
        assert "\\\\" in _md_inline("C:\\path")

    def test_phishing_link_not_active(self) -> None:
        injected = "OK [click here](https://evil.example)"
        out = _md_inline(injected)
        assert "\\[" in out and "\\]" in out
        assert "[click here](https://evil.example)" not in out

    def test_coerces_non_string(self) -> None:
        assert _md_inline(42) == "42"


class TestFencedDiff:
    def test_basic_diff_uses_triple_backticks(self) -> None:
        out = _fenced_diff("- old\n+ new")
        assert out.startswith("```diff\n")
        assert out.endswith("\n```")

    def test_fence_longer_than_internal_run(self) -> None:
        diff = "context\n```\ninjected heading\n```\nmore"
        out = _fenced_diff(diff)
        fence = out.split("diff\n", 1)[0]
        assert len(fence) >= 4
        body = out[len(fence) + len("diff\n") : -len(fence)]
        assert fence not in body

    def test_empty_diff(self) -> None:
        out = _fenced_diff("")
        assert out.startswith("```diff")
        assert out.endswith("```")

    def test_five_backtick_run_needs_six_fence(self) -> None:
        diff = "`````"
        out = _fenced_diff(diff)
        fence = out.split("diff\n", 1)[0]
        assert len(fence) == 6


class TestFormatComment:
    def _minimal_report(self, **kwargs) -> DiagnosisReport:
        defaults = dict(
            project="org/repo",
            pipeline_id=1,
            root_cause="missing REDIS_URL",
            failure_category=FailureCategory.ENV_VAR_MISSING,
            affected_jobs=["deploy"],
            is_flaky=False,
            fix_proposals=[],
            full_analysis="full text",
        )
        defaults.update(kwargs)
        return DiagnosisReport(**defaults)

    def test_injected_link_not_active(self) -> None:
        r = self._minimal_report(root_cause="[click](https://evil.example)")
        comment = _format_comment(r)
        assert "[click](https://evil.example)" not in comment
        assert "\\[click\\]" in comment

    def test_diff_fence_breakout_prevented(self) -> None:
        proposal = FixProposal(
            file_path=".gitlab-ci.yml",
            description="add var",
            diff="- old\n```\n## INJECTED\n```\n+ new",
            confidence=Confidence.HIGH,
        )
        r = self._minimal_report(fix_proposals=[proposal])
        comment = _format_comment(r)
        assert "````diff" in comment or "`````diff" in comment

    def test_enum_values_unescaped(self) -> None:
        r = self._minimal_report(failure_category=FailureCategory.ENV_VAR_MISSING)
        assert "`env_var_missing`" in _format_comment(r)

    def test_flaky_note_present(self) -> None:
        r = self._minimal_report(is_flaky=True)
        assert "flaky" in _format_comment(r)

    def test_affected_jobs_escaped(self) -> None:
        # A job name containing backticks must not produce a runaway code-span
        r = self._minimal_report(affected_jobs=["deploy`rm -rf /`"])
        comment = _format_comment(r)
        assert "deploy`rm -rf /`" not in comment
        assert "deploy\\`rm" in comment
