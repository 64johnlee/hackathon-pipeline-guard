"""Multi-tenant data layer for PipelineGuard 2.0 (Phase 1).

Stores **accounts**, repo **connections**, and **diagnosis history** so the
product can support self-serve signup with per-account isolation. Backed by
Cloud Firestore in production (serverless, scale-to-zero, free-tier friendly)
with an in-memory implementation for local dev and tests — no GCP credentials
needed to run or test the tenancy logic.

Config via env:
  GCP_PROJECT          — Firestore project (required for the Firestore backend)
  PG_TENANCY_BACKEND   — "firestore" | "memory" (default: firestore if
                         GCP_PROJECT is set, else memory)

Provider-agnostic by design: `provider` is "gitlab" today, "github" next, so
adding GitHub is an additive backend rather than a schema change.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

# --- Plans & quotas -----------------------------------------------------------

PLAN_FREE = "free"
PLAN_PRO = "pro"
FREE_MONTHLY_DIAGNOSES = 20
# None == unlimited.
_PLAN_MONTHLY_QUOTA: dict[str, int | None] = {
    PLAN_FREE: FREE_MONTHLY_DIAGNOSES,
    PLAN_PRO: None,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def month_start(now: datetime | None = None) -> datetime:
    """First instant (UTC) of the current calendar month."""
    now = now or _utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def make_account_id(provider: str, provider_user_id: str | int) -> str:
    return f"{provider}:{provider_user_id}"


def make_connection_id(provider: str, repo_full_path: str) -> str:
    return f"{provider}:{repo_full_path}"


# --- Records ------------------------------------------------------------------


@dataclass
class Account:
    """A tenant — one signed-in user/org."""

    id: str  # make_account_id(provider, provider_user_id)
    provider: str  # "gitlab" | "github"
    username: str = ""
    email: str = ""
    plan: str = PLAN_FREE
    stripe_customer_id: str = ""
    token_ref: str = ""  # vault ref for the provider OAuth token (never the raw token)
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class Connection:
    """A repo a tenant has connected for monitoring."""

    id: str  # make_connection_id(provider, repo_full_path) — unique per repo
    account_id: str
    provider: str
    repo_full_path: str  # "group/repo"
    webhook_secret: str = ""  # per-connection HMAC token for inbound webhooks
    token_secret_ref: str = ""  # Secret Manager resource name (never the raw token)
    active: bool = True
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class DiagnosisRecord:
    """One diagnosis run, for history + quota accounting."""

    id: str
    account_id: str
    connection_id: str
    provider: str
    repo_full_path: str
    pipeline_id: int
    root_cause: str = ""
    failure_category: str = "unknown"
    is_flaky: bool = False
    affected_jobs: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utcnow)


# --- Store interface ----------------------------------------------------------


@runtime_checkable
class Store(Protocol):
    def upsert_account(self, account: Account) -> Account: ...
    def get_account(self, account_id: str) -> Account | None: ...
    def upsert_connection(self, conn: Connection) -> Connection: ...
    def get_connection(self, conn_id: str) -> Connection | None: ...
    def list_connections(self, account_id: str) -> list[Connection]: ...
    def delete_connection(self, conn_id: str) -> None: ...
    def find_connection_by_repo(
        self, provider: str, repo_full_path: str
    ) -> Connection | None: ...
    def add_diagnosis(self, rec: DiagnosisRecord) -> DiagnosisRecord: ...
    def list_diagnoses(self, account_id: str, limit: int = 50) -> list[DiagnosisRecord]: ...
    def count_diagnoses_since(self, account_id: str, since: datetime) -> int: ...


def _filter_to_fields(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    """Keep only keys that are fields of `cls` (tolerates schema drift)."""
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in names}


# --- In-memory backend (local dev + tests) ------------------------------------


class InMemoryStore:
    """Dict-backed Store. Not persistent — for local dev and unit tests."""

    def __init__(self) -> None:
        self._accounts: dict[str, Account] = {}
        self._connections: dict[str, Connection] = {}
        self._diagnoses: dict[str, DiagnosisRecord] = {}

    def upsert_account(self, account: Account) -> Account:
        self._accounts[account.id] = account
        return account

    def get_account(self, account_id: str) -> Account | None:
        return self._accounts.get(account_id)

    def upsert_connection(self, conn: Connection) -> Connection:
        self._connections[conn.id] = conn
        return conn

    def get_connection(self, conn_id: str) -> Connection | None:
        return self._connections.get(conn_id)

    def list_connections(self, account_id: str) -> list[Connection]:
        return [c for c in self._connections.values() if c.account_id == account_id]

    def delete_connection(self, conn_id: str) -> None:
        self._connections.pop(conn_id, None)

    def find_connection_by_repo(
        self, provider: str, repo_full_path: str
    ) -> Connection | None:
        return self._connections.get(make_connection_id(provider, repo_full_path))

    def add_diagnosis(self, rec: DiagnosisRecord) -> DiagnosisRecord:
        if not rec.id:
            rec.id = uuid.uuid4().hex
        self._diagnoses[rec.id] = rec
        return rec

    def list_diagnoses(self, account_id: str, limit: int = 50) -> list[DiagnosisRecord]:
        rows = [d for d in self._diagnoses.values() if d.account_id == account_id]
        rows.sort(key=lambda d: d.created_at, reverse=True)
        return rows[:limit]

    def count_diagnoses_since(self, account_id: str, since: datetime) -> int:
        return sum(
            1
            for d in self._diagnoses.values()
            if d.account_id == account_id and d.created_at >= since
        )


# --- Firestore backend (production) -------------------------------------------


class FirestoreStore:
    """Cloud Firestore-backed Store.

    Collections: ``accounts``, ``connections``, ``diagnoses`` (doc id == record
    id). Queries filter by a single field and sort/slice in-app, so no composite
    indexes are required.
    """

    _ACCOUNTS = "accounts"
    _CONNECTIONS = "connections"
    _DIAGNOSES = "diagnoses"

    def __init__(self, project: str = "") -> None:
        self.project = project or os.environ.get("GCP_PROJECT", "")
        self._client = None

    def _db(self):  # lazy import keeps firestore optional
        if self._client is None:
            from google.cloud import firestore

            self._client = firestore.Client(project=self.project or None)
        return self._client

    @staticmethod
    def _doc_id(record_id: str) -> str:
        # Firestore document ids cannot contain "/"; connection ids embed repo
        # paths like "gitlab:group/repo", so encode the slash to a safe token.
        return record_id.replace("/", "__")

    def upsert_account(self, account: Account) -> Account:
        self._db().collection(self._ACCOUNTS).document(account.id).set(vars(account))
        return account

    def get_account(self, account_id: str) -> Account | None:
        snap = self._db().collection(self._ACCOUNTS).document(account_id).get()
        return Account(**_filter_to_fields(Account, snap.to_dict())) if snap.exists else None

    def upsert_connection(self, conn: Connection) -> Connection:
        self._db().collection(self._CONNECTIONS).document(self._doc_id(conn.id)).set(vars(conn))
        return conn

    def get_connection(self, conn_id: str) -> Connection | None:
        snap = self._db().collection(self._CONNECTIONS).document(self._doc_id(conn_id)).get()
        return (
            Connection(**_filter_to_fields(Connection, snap.to_dict()))
            if snap.exists
            else None
        )

    def list_connections(self, account_id: str) -> list[Connection]:
        docs = (
            self._db()
            .collection(self._CONNECTIONS)
            .where("account_id", "==", account_id)
            .stream()
        )
        return [Connection(**_filter_to_fields(Connection, d.to_dict())) for d in docs]

    def delete_connection(self, conn_id: str) -> None:
        self._db().collection(self._CONNECTIONS).document(self._doc_id(conn_id)).delete()

    def find_connection_by_repo(
        self, provider: str, repo_full_path: str
    ) -> Connection | None:
        return self.get_connection(make_connection_id(provider, repo_full_path))

    def add_diagnosis(self, rec: DiagnosisRecord) -> DiagnosisRecord:
        if not rec.id:
            rec.id = uuid.uuid4().hex
        self._db().collection(self._DIAGNOSES).document(rec.id).set(vars(rec))
        return rec

    def list_diagnoses(self, account_id: str, limit: int = 50) -> list[DiagnosisRecord]:
        docs = (
            self._db()
            .collection(self._DIAGNOSES)
            .where("account_id", "==", account_id)
            .stream()
        )
        rows = [DiagnosisRecord(**_filter_to_fields(DiagnosisRecord, d.to_dict())) for d in docs]
        rows.sort(key=lambda d: d.created_at, reverse=True)
        return rows[:limit]

    def count_diagnoses_since(self, account_id: str, since: datetime) -> int:
        docs = (
            self._db()
            .collection(self._DIAGNOSES)
            .where("account_id", "==", account_id)
            .stream()
        )
        count = 0
        for d in docs:
            created = d.to_dict().get("created_at")
            if created is not None and created >= since:
                count += 1
        return count


# --- Factory + quota helpers --------------------------------------------------

_default_store: Store | None = None


def get_store() -> Store:
    """Return the configured Store (singleton).

    Firestore when PG_TENANCY_BACKEND=firestore, or when GCP_PROJECT is set and
    the backend isn't forced to "memory"; otherwise the in-memory store.
    """
    global _default_store
    if _default_store is not None:
        return _default_store
    backend = os.environ.get("PG_TENANCY_BACKEND", "").lower()
    project = os.environ.get("GCP_PROJECT", "")
    if backend == "memory" or (not backend and not project):
        _default_store = InMemoryStore()
    else:
        _default_store = FirestoreStore(project=project)
    return _default_store


def reset_store() -> None:
    """Drop the cached store (used by tests)."""
    global _default_store
    _default_store = None


def remaining_quota(store: Store, account: Account) -> int | None:
    """Diagnoses left this month, or None if the plan is unlimited."""
    quota = _PLAN_MONTHLY_QUOTA.get(account.plan, FREE_MONTHLY_DIAGNOSES)
    if quota is None:
        return None
    used = store.count_diagnoses_since(account.id, month_start())
    return max(0, quota - used)


def within_quota(store: Store, account: Account) -> bool:
    """True if the account may run another diagnosis this month."""
    rem = remaining_quota(store, account)
    return rem is None or rem > 0
