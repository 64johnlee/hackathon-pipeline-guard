"""Vertex AI Search (Discovery Engine) retrieval for grounded diagnoses.

PipelineGuard 2.0 — Phase 0. Instead of relying on the model's training alone,
ground root-cause + fix proposals in a curated CI/CD knowledge base (known
error->fix patterns, CI docs). Runs on the Vertex AI Search / Agent Builder
stack, funded by the GenAI App Builder credit.

Config via env: GCP_PROJECT, PG_KB_DATASTORE (data store id), PG_KB_LOCATION
(default "global"). If the KB isn't configured or a query fails, retrieval
degrades to an empty result — a diagnosis must never break because of the KB.

Requires: google-cloud-discoveryengine (add to [web]/[vertex] extras).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class KBHit:
    title: str
    snippet: str
    uri: str


class KnowledgeBase:
    """Queries a Vertex AI Search data store for relevant CI/CD fix knowledge."""

    def __init__(
        self,
        project: str = "",
        location: str = "",
        data_store_id: str = "",
    ) -> None:
        self.project = project or os.environ.get("GCP_PROJECT", "")
        self.location = location or os.environ.get("PG_KB_LOCATION", "global")
        self.data_store_id = data_store_id or os.environ.get("PG_KB_DATASTORE", "")
        self._client = None

    @property
    def enabled(self) -> bool:
        return bool(self.project and self.data_store_id)

    def _serving_config(self) -> str:
        return (
            f"projects/{self.project}/locations/{self.location}"
            f"/collections/default_collection/dataStores/{self.data_store_id}"
            f"/servingConfigs/default_search"
        )

    def search(self, query: str, top_k: int = 4) -> list[KBHit]:
        """Top-k knowledge snippets for an error/query. Empty list if KB off or on error."""
        if not self.enabled or not query.strip():
            return []
        try:
            from google.cloud import discoveryengine_v1 as de

            if self._client is None:
                self._client = de.SearchServiceClient()
            spec = de.SearchRequest.ContentSearchSpec(
                snippet_spec=de.SearchRequest.ContentSearchSpec.SnippetSpec(
                    return_snippet=True
                ),
            )
            req = de.SearchRequest(
                serving_config=self._serving_config(),
                query=query[:1000],
                page_size=top_k,
                content_search_spec=spec,
                spell_correction_spec=de.SearchRequest.SpellCorrectionSpec(
                    mode=de.SearchRequest.SpellCorrectionSpec.Mode.AUTO
                ),
            )
            hits: list[KBHit] = []
            for result in self._client.search(req):
                data = (
                    dict(result.document.derived_struct_data)
                    if result.document.derived_struct_data
                    else {}
                )
                # Pick the first non-empty snippet — Discovery Engine can return
                # leading entries with status NO_SNIPPET_AVAILABLE (empty text).
                snippet = ""
                for s in data.get("snippets") or []:
                    cand = (s.get("snippet", "") if hasattr(s, "get") else "") or ""
                    if cand.strip():
                        snippet = cand[:600]  # bound prompt size
                        break
                hits.append(
                    KBHit(
                        title=str(data.get("title") or result.document.id),
                        snippet=str(snippet),
                        uri=str(data.get("link") or data.get("uri") or ""),
                    )
                )
            # dedupe by title, preserve rank order
            seen: set[str] = set()
            unique: list[KBHit] = []
            for h in hits:
                key = h.title.lower()
                if key not in seen:
                    seen.add(key)
                    unique.append(h)
            return unique
        except Exception as exc:  # the KB must never break a diagnosis
            logger.warning("KB search failed (%s) — continuing ungrounded", exc)
            return []


def format_grounding(hits: list[KBHit]) -> str:
    """Render KB hits as a prompt-injectable 'known issues & fixes' block."""
    if not hits:
        return ""
    lines = ["", "## Relevant known CI/CD issues & fixes (cite [n] if you use them):"]
    for i, h in enumerate(hits, 1):
        block = f"\n[{i}] {h.title}\n{h.snippet}"
        if h.uri:
            block += f"\n(source: {h.uri})"
        lines.append(block)
    return "\n".join(lines)
