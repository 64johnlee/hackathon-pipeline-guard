"""Tests for the multi-tenant data layer (store.py), via the in-memory backend.

No GCP credentials required — exercises account/connection/diagnosis CRUD,
per-account isolation, monthly quota accounting, and the backend factory.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from pipelineguard.store import (
    PLAN_PRO,
    Account,
    Connection,
    DiagnosisRecord,
    FirestoreStore,
    InMemoryStore,
    get_store,
    make_account_id,
    make_connection_id,
    month_start,
    remaining_quota,
    reset_store,
    within_quota,
)


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch):
    for var in ("GCP_PROJECT", "PG_TENANCY_BACKEND"):
        monkeypatch.delenv(var, raising=False)
    reset_store()
    yield
    reset_store()


class TestIdHelpers:
    def test_account_and_connection_ids(self) -> None:
        assert make_account_id("gitlab", 12345) == "gitlab:12345"
        assert make_connection_id("gitlab", "grp/repo") == "gitlab:grp/repo"


class TestAccounts:
    def test_upsert_and_get(self, store: InMemoryStore) -> None:
        acct = Account(id="gitlab:1", provider="gitlab", username="ada")
        store.upsert_account(acct)
        got = store.get_account("gitlab:1")
        assert got is not None and got.username == "ada"

    def test_default_plan_is_free(self, store: InMemoryStore) -> None:
        acct = store.upsert_account(Account(id="gitlab:1", provider="gitlab"))
        assert acct.plan == "free"

    def test_missing_account_is_none(self, store: InMemoryStore) -> None:
        assert store.get_account("nope") is None

    def test_upsert_overwrites(self, store: InMemoryStore) -> None:
        store.upsert_account(Account(id="gitlab:1", provider="gitlab", plan="free"))
        store.upsert_account(Account(id="gitlab:1", provider="gitlab", plan=PLAN_PRO))
        assert store.get_account("gitlab:1").plan == PLAN_PRO


class TestConnections:
    def _conn(self, acct="gitlab:1", repo="grp/repo") -> Connection:
        return Connection(
            id=make_connection_id("gitlab", repo),
            account_id=acct,
            provider="gitlab",
            repo_full_path=repo,
        )

    def test_crud_and_find_by_repo(self, store: InMemoryStore) -> None:
        c = store.upsert_connection(self._conn())
        assert store.get_connection(c.id).repo_full_path == "grp/repo"
        assert store.find_connection_by_repo("gitlab", "grp/repo").id == c.id
        store.delete_connection(c.id)
        assert store.get_connection(c.id) is None

    def test_find_by_repo_missing(self, store: InMemoryStore) -> None:
        assert store.find_connection_by_repo("gitlab", "absent/repo") is None

    def test_list_is_isolated_per_account(self, store: InMemoryStore) -> None:
        store.upsert_connection(self._conn(acct="gitlab:1", repo="a/one"))
        store.upsert_connection(self._conn(acct="gitlab:1", repo="a/two"))
        store.upsert_connection(self._conn(acct="gitlab:2", repo="b/three"))
        mine = store.list_connections("gitlab:1")
        assert {c.repo_full_path for c in mine} == {"a/one", "a/two"}


class TestDiagnoses:
    def _rec(self, acct="gitlab:1", pid=1, created=None) -> DiagnosisRecord:
        kw = {}
        if created is not None:
            kw["created_at"] = created
        return DiagnosisRecord(
            id="",
            account_id=acct,
            connection_id="gitlab:grp/repo",
            provider="gitlab",
            repo_full_path="grp/repo",
            pipeline_id=pid,
            **kw,
        )

    def test_add_autogenerates_id(self, store: InMemoryStore) -> None:
        rec = store.add_diagnosis(self._rec())
        assert rec.id  # non-empty uuid
        assert store.list_diagnoses("gitlab:1")[0].id == rec.id

    def test_list_is_newest_first_and_limited(self, store: InMemoryStore) -> None:
        base = month_start()
        for i in range(5):
            store.add_diagnosis(self._rec(pid=i, created=base + timedelta(minutes=i)))
        rows = store.list_diagnoses("gitlab:1", limit=3)
        assert [r.pipeline_id for r in rows] == [4, 3, 2]  # newest first, capped at 3

    def test_count_since_excludes_prior_month(self, store: InMemoryStore) -> None:
        this_month = month_start() + timedelta(days=1)
        last_month = month_start() - timedelta(days=1)
        store.add_diagnosis(self._rec(pid=1, created=this_month))
        store.add_diagnosis(self._rec(pid=2, created=this_month))
        store.add_diagnosis(self._rec(pid=3, created=last_month))
        assert store.count_diagnoses_since("gitlab:1", month_start()) == 2


class TestQuota:
    def _fill(self, store: InMemoryStore, acct: str, n: int) -> None:
        when = month_start() + timedelta(hours=1)
        for i in range(n):
            store.add_diagnosis(
                DiagnosisRecord(
                    id="",
                    account_id=acct,
                    connection_id="c",
                    provider="gitlab",
                    repo_full_path="grp/repo",
                    pipeline_id=i,
                    created_at=when,
                )
            )

    def test_free_plan_blocks_after_limit(self, store: InMemoryStore) -> None:
        acct = store.upsert_account(Account(id="gitlab:1", provider="gitlab"))
        assert within_quota(store, acct) is True
        self._fill(store, acct.id, 19)
        assert remaining_quota(store, acct) == 1
        assert within_quota(store, acct) is True
        self._fill(store, acct.id, 1)  # now 20
        assert remaining_quota(store, acct) == 0
        assert within_quota(store, acct) is False

    def test_pro_plan_is_unlimited(self, store: InMemoryStore) -> None:
        acct = store.upsert_account(Account(id="gitlab:1", provider="gitlab", plan=PLAN_PRO))
        self._fill(store, acct.id, 50)
        assert remaining_quota(store, acct) is None
        assert within_quota(store, acct) is True

    def test_unknown_plan_defaults_to_free_limit(self, store: InMemoryStore) -> None:
        acct = store.upsert_account(Account(id="gitlab:1", provider="gitlab", plan="enterprise"))
        self._fill(store, acct.id, 20)
        assert within_quota(store, acct) is False


class TestFactory:
    def test_memory_when_forced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PG_TENANCY_BACKEND", "memory")
        reset_store()
        assert isinstance(get_store(), InMemoryStore)

    def test_memory_when_no_project(self) -> None:
        reset_store()
        assert isinstance(get_store(), InMemoryStore)

    def test_firestore_when_project_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GCP_PROJECT", "demo-proj")
        reset_store()
        # Constructed lazily — no client/network until a method is called.
        assert isinstance(get_store(), FirestoreStore)

    def test_singleton_is_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PG_TENANCY_BACKEND", "memory")
        reset_store()
        assert get_store() is get_store()


class TestFirestoreDocId:
    def test_slash_in_connection_id_is_encoded(self) -> None:
        # Firestore doc ids cannot contain "/"; connection ids embed repo paths.
        from pipelineguard.store import FirestoreStore

        doc_id = FirestoreStore._doc_id(make_connection_id("gitlab", "grp/repo"))
        assert "/" not in doc_id
        assert doc_id == "gitlab:grp__repo"

    def test_idless_records_unchanged(self) -> None:
        from pipelineguard.store import FirestoreStore

        assert FirestoreStore._doc_id("gitlab:12345") == "gitlab:12345"
