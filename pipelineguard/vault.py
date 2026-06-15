"""Token vault — keeps per-account provider OAuth tokens out of the database.

Secret Manager in production; in-memory for local dev and tests. Firestore only
ever stores a Secret Manager resource *ref* (`Account.token_ref` /
`Connection.token_secret_ref`), never the raw access token.

Config via env (shared with store.py):
  GCP_PROJECT, PG_TENANCY_BACKEND ("firestore"/"memory").
"""
from __future__ import annotations

import contextlib
import logging
import os
import re
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class TokenVault(Protocol):
    def put(self, key: str, token: str) -> str: ...  # returns a ref
    def get(self, ref: str) -> str: ...  # "" if missing
    def delete(self, ref: str) -> None: ...


def _safe_secret_id(key: str) -> str:
    # Secret Manager ids: [A-Za-z0-9_-], <=255 chars.
    return ("pg-token-" + re.sub(r"[^A-Za-z0-9_-]", "-", key))[:255]


class InMemoryVault:
    """Dict-backed vault for local dev and tests. Not persistent."""

    def __init__(self) -> None:
        self._d: dict[str, str] = {}

    def put(self, key: str, token: str) -> str:
        ref = f"mem:{_safe_secret_id(key)}"
        self._d[ref] = token
        return ref

    def get(self, ref: str) -> str:
        return self._d.get(ref, "")

    def delete(self, ref: str) -> None:
        self._d.pop(ref, None)


class SecretManagerVault:
    """Google Secret Manager-backed vault (one secret per account token)."""

    def __init__(self, project: str = "") -> None:
        self.project = project or os.environ.get("GCP_PROJECT", "")
        self._client = None

    def _c(self):  # lazy import keeps secretmanager optional
        if self._client is None:
            from google.cloud import secretmanager

            self._client = secretmanager.SecretManagerServiceClient()
        return self._client

    def put(self, key: str, token: str) -> str:
        client = self._c()
        parent = f"projects/{self.project}"
        sid = _safe_secret_id(key)
        secret_name = f"{parent}/secrets/{sid}"
        with contextlib.suppress(Exception):  # secret may already exist — fine
            client.create_secret(
                request={
                    "parent": parent,
                    "secret_id": sid,
                    "secret": {"replication": {"automatic": {}}},
                }
            )
        client.add_secret_version(
            request={"parent": secret_name, "payload": {"data": token.encode()}}
        )
        return f"{secret_name}/versions/latest"

    def get(self, ref: str) -> str:
        try:
            resp = self._c().access_secret_version(request={"name": ref})
            return resp.payload.data.decode()
        except Exception as exc:
            logger.warning("vault get failed (%s)", exc)
            return ""

    def delete(self, ref: str) -> None:
        try:
            secret_path = ref.split("/versions/")[0]
            self._c().delete_secret(request={"name": secret_path})
        except Exception as exc:
            logger.warning("vault delete failed (%s)", exc)


_default_vault: TokenVault | None = None


def get_vault() -> TokenVault:
    """Return the configured vault (singleton), mirroring store.get_store()."""
    global _default_vault
    if _default_vault is not None:
        return _default_vault
    backend = os.environ.get("PG_TENANCY_BACKEND", "").lower()
    project = os.environ.get("GCP_PROJECT", "")
    if backend == "memory" or (not backend and not project):
        _default_vault = InMemoryVault()
    else:
        _default_vault = SecretManagerVault(project=project)
    return _default_vault


def reset_vault() -> None:
    """Drop the cached vault (used by tests)."""
    global _default_vault
    _default_vault = None
