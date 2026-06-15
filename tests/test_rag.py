"""Tests for the Vertex AI Search RAG layer (rag.py) and the agent KB helpers.

These cover the parts that must hold regardless of whether a live data store or
ADC credentials are available: config gating, fail-safe behaviour, dedupe,
grounding rendering, error-signature query extraction, and the KB tool schema.
"""

from __future__ import annotations

import pytest

from pipelineguard.rag import KBHit, KnowledgeBase, format_grounding


@pytest.fixture(autouse=True)
def _clear_kb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate from any GCP_PROJECT / PG_KB_* set in the ambient environment."""
    for var in ("GCP_PROJECT", "PG_KB_DATASTORE", "PG_KB_LOCATION"):
        monkeypatch.delenv(var, raising=False)


# --- fakes for the Discovery Engine client (plain dicts mimic derived_struct_data) ---


class _FakeDoc:
    def __init__(self, doc_id: str, data: dict) -> None:
        self.id = doc_id
        self.derived_struct_data = data


class _FakeResult:
    def __init__(self, doc: _FakeDoc) -> None:
        self.document = doc


class TestEnabled:
    def test_requires_both_project_and_datastore(self) -> None:
        assert not KnowledgeBase(project="", data_store_id="d").enabled
        assert not KnowledgeBase(project="p", data_store_id="").enabled
        assert KnowledgeBase(project="p", data_store_id="d").enabled

    def test_disabled_search_returns_empty(self) -> None:
        assert KnowledgeBase(project="", data_store_id="").search("docker oom") == []

    def test_blank_query_returns_empty(self) -> None:
        assert KnowledgeBase(project="p", data_store_id="d").search("   ") == []

    def test_location_defaults_to_global(self) -> None:
        assert KnowledgeBase(project="p", data_store_id="d").location == "global"


class TestSearch:
    def test_fails_safe_when_client_raises(self) -> None:
        kb = KnowledgeBase(project="p", data_store_id="d")

        class Boom:
            def search(self, req):  # noqa: ANN001
                raise RuntimeError("backend down")

        kb._client = Boom()
        # A KB error must degrade to empty, never propagate into a diagnosis.
        assert kb.search("docker build killed exit 137") == []

    def test_dedupes_by_title_case_insensitive(self) -> None:
        kb = KnowledgeBase(project="p", data_store_id="d")
        results = [
            _FakeResult(_FakeDoc("a", {"title": "Docker OOM", "snippets": [{"snippet": "multi-stage"}]})),
            _FakeResult(_FakeDoc("b", {"title": "docker oom", "snippets": [{"snippet": "dupe"}]})),
            _FakeResult(_FakeDoc("c", {"title": "DNS flake", "snippets": [{"snippet": "retry"}]})),
        ]

        class Client:
            def search(self, req):  # noqa: ANN001
                return iter(results)

        kb._client = Client()
        hits = kb.search("docker oom")
        assert [h.title for h in hits] == ["Docker OOM", "DNS flake"]
        assert hits[0].snippet == "multi-stage"

    def test_falls_back_to_doc_id_when_no_title(self) -> None:
        kb = KnowledgeBase(project="p", data_store_id="d")

        class Client:
            def search(self, req):  # noqa: ANN001
                return iter([_FakeResult(_FakeDoc("doc-42", {}))])

        kb._client = Client()
        hits = kb.search("something")
        assert hits[0].title == "doc-42"
        assert hits[0].snippet == ""

    def test_picks_first_non_empty_snippet(self) -> None:
        # Discovery Engine may return leading NO_SNIPPET_AVAILABLE (empty) entries.
        kb = KnowledgeBase(project="p", data_store_id="d")
        doc = _FakeDoc(
            "a",
            {"title": "Docker OOM", "snippets": [{"snippet": ""}, {"snippet": "raise memory"}]},
        )

        class Client:
            def search(self, req):  # noqa: ANN001
                return iter([_FakeResult(doc)])

        kb._client = Client()
        assert kb.search("q")[0].snippet == "raise memory"


class TestFormatGrounding:
    def test_empty_hits_render_nothing(self) -> None:
        assert format_grounding([]) == ""

    def test_renders_titles_snippets_citations_and_source(self) -> None:
        hits = [
            KBHit(title="Docker OOM", snippet="use multi-stage builds", uri="https://x/doc"),
            KBHit(title="DNS flake", snippet="add retries", uri=""),
        ]
        out = format_grounding(hits)
        assert "[1]" in out and "[2]" in out
        assert "Docker OOM" in out and "use multi-stage builds" in out
        assert "DNS flake" in out and "add retries" in out
        assert "https://x/doc" in out
        # a hit with no uri must not emit a stray "(source:)" line
        assert out.count("(source:") == 1


class TestKbQueryFromData:
    def _q(self, data: dict) -> str:
        from pipelineguard.agent import _kb_query_from_data

        return _kb_query_from_data(data)

    def test_prefers_error_lines_over_noise(self) -> None:
        data = {
            "failed_jobs": [
                {
                    "failure_reason": "script_failure",
                    "log_tail": "installing deps\nall good\nKilled\nexit code 137\ntrailing noise",
                }
            ]
        }
        q = self._q(data)
        assert "script_failure" in q
        assert "Killed" in q and "exit code 137" in q
        assert "installing deps" not in q  # non-error noise dropped

    def test_falls_back_to_tail_when_no_error_lines(self) -> None:
        data = {"failed_jobs": [{"log_tail": "all good\nnothing notable here"}]}
        assert "nothing notable here" in self._q(data)

    def test_capped_at_1000_chars(self) -> None:
        data = {"failed_jobs": [{"log_tail": "error " * 500}]}
        assert len(self._q(data)) <= 1000

    def test_empty_when_no_failed_jobs(self) -> None:
        assert self._q({"failed_jobs": []}) == ""

    def test_dedupes_repeated_error_lines(self) -> None:
        # A log that spams the same error 50x must not flood the query budget.
        data = {"failed_jobs": [{"log_tail": "\n".join(["error: boom"] * 50)}]}
        q = self._q(data)
        assert q.count("error: boom") == 1


class TestKbToolDeclaration:
    def test_declares_named_tool_with_required_query(self) -> None:
        from pipelineguard.agent import _KB_TOOL_NAME, _kb_tool_declaration

        decl = _kb_tool_declaration()
        assert decl.name == _KB_TOOL_NAME
        assert "query" in (decl.parameters.required or [])
        assert "query" in (decl.parameters.properties or {})
