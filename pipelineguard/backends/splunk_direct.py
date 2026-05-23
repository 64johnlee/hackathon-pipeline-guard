"""Splunk direct backend — queries Splunk REST API without the MCP server."""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 0.5   # seconds between job status polls
_MAX_WAIT = 30.0       # max seconds to wait for a search job to complete
_DEFAULT_MAX_RESULTS = 100


class SplunkDirectBackend:
    """
    Fallback backend that talks to Splunk's REST API directly via httpx.
    Used when the Splunk MCP Server app is unavailable.

    Supports Splunk Enterprise and Splunk Cloud (token auth or user/pass).
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8089,
        token: str = "",
        username: str = "",
        password: str = "",
        scheme: str = "https",
        verify_ssl: bool = True,
    ) -> None:
        self._base = f"{scheme}://{host}:{port}"
        self._verify_ssl = verify_ssl

        if token:
            self._auth_headers = {"Authorization": f"Bearer {token}"}
            self._basic_auth: tuple[str, str] | None = None
        elif username and password:
            self._auth_headers = {}
            self._basic_auth = (username, password)
        else:
            raise ValueError("Provide either token or username+password")

    def _client(self) -> httpx.Client:
        kwargs: dict[str, Any] = {"verify": self._verify_ssl, "timeout": 30.0}
        if self._basic_auth:
            kwargs["auth"] = self._basic_auth
        return httpx.Client(**kwargs)

    def run_search(
        self,
        spl: str,
        earliest: str = "-24h",
        latest: str = "now",
        max_results: int = _DEFAULT_MAX_RESULTS,
    ) -> list[dict[str, Any]]:
        """
        Execute a blocking SPL search and return results as a list of dicts.

        Uses Splunk's job-based search (POST /services/search/jobs, then poll
        until done, then GET results) rather than the oneshot endpoint, which
        has a 50k-event cap and no streaming.
        """
        with self._client() as client:
            # 1. Create search job
            resp = client.post(
                f"{self._base}/services/search/jobs",
                headers={**self._auth_headers, "Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "search": f"search {spl}" if not spl.strip().startswith("search") else spl,
                    "earliest_time": earliest,
                    "latest_time": latest,
                    "output_mode": "json",
                },
            )
            resp.raise_for_status()
            sid = resp.json()["sid"]
            logger.debug("Created Splunk search job sid=%s", sid)

            # 2. Poll until done
            deadline = time.monotonic() + _MAX_WAIT
            while time.monotonic() < deadline:
                status_resp = client.get(
                    f"{self._base}/services/search/jobs/{sid}",
                    headers={**self._auth_headers},
                    params={"output_mode": "json"},
                )
                status_resp.raise_for_status()
                entry = status_resp.json()["entry"][0]["content"]
                if entry.get("isDone"):
                    break
                time.sleep(_POLL_INTERVAL)
            else:
                logger.warning("Splunk search job %s timed out after %.0fs", sid, _MAX_WAIT)

            # 3. Fetch results
            results_resp = client.get(
                f"{self._base}/services/search/jobs/{sid}/results",
                headers={**self._auth_headers},
                params={"output_mode": "json", "count": max_results},
            )
            results_resp.raise_for_status()
            return results_resp.json().get("results", [])

    def list_indexes(self) -> list[str]:
        """Return names of all accessible indexes."""
        with self._client() as client:
            resp = client.get(
                f"{self._base}/services/data/indexes",
                headers=self._auth_headers,
                params={"output_mode": "json", "count": 0},
            )
            resp.raise_for_status()
            return [e["name"] for e in resp.json().get("entry", [])]

    def get_server_info(self) -> dict[str, str]:
        """Return basic Splunk instance metadata."""
        with self._client() as client:
            resp = client.get(
                f"{self._base}/services/server/info",
                headers=self._auth_headers,
                params={"output_mode": "json"},
            )
            resp.raise_for_status()
            content = resp.json()["entry"][0]["content"]
            return {
                "version": content.get("version", ""),
                "server_name": content.get("serverName", ""),
                "product": content.get("product_type", "splunk"),
            }
