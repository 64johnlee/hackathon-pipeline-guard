#!/usr/bin/env python3
"""Generate the starter CI/CD knowledge corpus for PipelineGuard's Vertex AI Search store.

Writes one .txt per known failure pattern to knowledge_base/. These get uploaded
to GCS and imported into a Discovery Engine data store (dataSchema=content), so
the agent can ground diagnoses in real error->fix patterns. Add more docs over time.
"""
from pathlib import Path

OUT = Path(__file__).resolve().parent / "knowledge_base"

DOCS: dict[str, str] = {
    "flaky_tests.txt": """TITLE: Flaky / intermittent test failures in CI
SYMPTOMS: A job passes on retry with no code change; errors like "Timeout exceeded",
"element not found", "connection reset", race conditions, order-dependent failures.
ROOT CAUSE: Non-deterministic tests — timing/race conditions, shared state, real
network calls, or unmocked time/randomness.
FIX: Retry the job to confirm flakiness, then fix the root test: add explicit waits
instead of sleeps, mock network/time/randomness, isolate shared state, and seed RNG.
In GitLab CI add `retry: 2` on the job as a stop-gap; quarantine the test if needed.
REFERENCE: https://docs.gitlab.com/ee/ci/yaml/#retry
""",
    "dependency_conflict.txt": """TITLE: Dependency resolution / version conflict
SYMPTOMS: "ERESOLVE could not resolve", "Cannot find module", pip "ResolutionImpossible",
"incompatible peer dependency", build fails on install step.
ROOT CAUSE: Unpinned or conflicting transitive dependencies; lockfile out of sync with
the manifest; a new release of a dependency broke compatibility.
FIX: Commit and use a lockfile (package-lock.json / poetry.lock / requirements.txt with
pins). Install with `npm ci` / `pip install -r requirements.txt` (not loose installs).
Pin the offending package to a known-good version; regenerate the lockfile locally.
REFERENCE: https://docs.npmjs.com/cli/v10/commands/npm-ci
""",
    "docker_build_oom.txt": """TITLE: Docker build fails with out-of-memory or no space left
SYMPTOMS: "no space left on device", "Killed", build hangs then dies, OOMKilled, exit 137.
ROOT CAUSE: Build runner out of memory/disk — large layers, no cleanup, single-stage build
copying build tooling into the final image.
FIX: Use multi-stage builds to drop build deps from the final image; add .dockerignore;
clean caches in the same RUN layer; increase runner memory; enable BuildKit layer caching.
Exit 137 = OOM -> raise the container/runner memory limit.
REFERENCE: https://docs.docker.com/build/building/multi-stage/
""",
    "expired_token.txt": """TITLE: Authentication failure — expired or missing token/secret
SYMPTOMS: 401/403 on registry push, deploy, or git operation; "authentication required",
"invalid credentials", "permission denied" only in CI (works locally).
ROOT CAUSE: A CI secret/token expired, was rotated, or isn't exposed to the job (protected
variable on an unprotected branch, wrong scope).
FIX: Rotate the token and update the CI/CD variable/secret. Verify scope (e.g. api +
read/write_registry). For protected variables, ensure the branch/tag is protected.
In GitLab: Settings > CI/CD > Variables. Re-run after updating.
REFERENCE: https://docs.gitlab.com/ee/ci/variables/
""",
    "lint_format_failure.txt": """TITLE: Lint / formatting check failed
SYMPTOMS: ruff/eslint/flake8/black/prettier exit non-zero; "would reformat", "lint error",
style violations; job named lint/format/style fails.
ROOT CAUSE: Code not run through the formatter/linter before commit; config drift between
local and CI.
FIX: Run the formatter locally (`ruff format` / `black .` / `npm run lint -- --fix`) and
commit. Add a pre-commit hook so it can't happen again. Ensure the same config/version is
pinned in CI as locally.
REFERENCE: https://pre-commit.com/
""",
    "missing_env_var.txt": """TITLE: Missing environment variable / configuration in CI
SYMPTOMS: "KeyError", "undefined", "$VAR: unbound variable", works locally but the job
crashes reading config; tests fail only in CI.
ROOT CAUSE: A required env var/secret exists locally (.env) but isn't defined as a CI/CD
variable, or isn't passed into the job's environment.
FIX: Add the variable under the project's CI/CD variables; reference it in the job. Don't
commit secrets — use masked/protected CI variables. Provide safe defaults for non-secret
config.
REFERENCE: https://docs.gitlab.com/ee/ci/variables/
""",
    "cache_restore_failure.txt": """TITLE: Cache restore/save failure or stale cache
SYMPTOMS: "Failed to extract cache", slow jobs re-downloading deps, stale artifacts causing
mismatched builds, cache key warnings.
ROOT CAUSE: Cache key not tied to the lockfile, cache corrupted, or paths misconfigured.
FIX: Key the cache on the lockfile hash (e.g. `key: files: [package-lock.json]`); cache the
right paths (node_modules, .venv, ~/.cache/pip); add a fallback key. Clear the cache if
corrupted.
REFERENCE: https://docs.gitlab.com/ee/ci/caching/
""",
    "test_runner_oom.txt": """TITLE: Test runner out of memory (JS/Node heap, JVM, etc.)
SYMPTOMS: "JavaScript heap out of memory", "FATAL ERROR: Reached heap limit", exit 137 in
the test job, runner killed mid-suite.
ROOT CAUSE: Test process exceeds available memory — large suites, memory leaks between tests,
default heap too small for CI.
FIX: Raise the heap (`NODE_OPTIONS=--max-old-space-size=4096`), run tests in shards/parallel,
fix leaks (close handles, clear globals between tests), and increase runner memory.
REFERENCE: https://nodejs.org/api/cli.html#--max-old-space-sizesize-in-mib
""",
    "network_dns_flake.txt": """TITLE: Network / DNS flake pulling dependencies or images
SYMPTOMS: "Temporary failure in name resolution", "connection timed out", "ETIMEDOUT",
intermittent failures fetching packages or pulling images.
ROOT CAUSE: Transient registry/network issue or rate limiting (e.g. Docker Hub anonymous
pull limits).
FIX: Add retries with backoff to network steps; use a dependency proxy/mirror or cache;
authenticate to the registry to lift anonymous rate limits. Confirm it's transient by
re-running.
REFERENCE: https://docs.gitlab.com/ee/user/packages/dependency_proxy/
""",
    "yaml_config_error.txt": """TITLE: CI YAML / config syntax or schema error
SYMPTOMS: "Invalid configuration", "jobs config should contain...", pipeline doesn't start,
"mapping values are not allowed here", lint errors on .gitlab-ci.yml.
ROOT CAUSE: Invalid YAML (indentation/tabs), unknown keyword, or invalid job structure.
FIX: Validate with the CI Lint tool (GitLab: CI/CD > Editor > Lint). Use spaces not tabs;
check job keywords; split large configs with `include`. Validate locally before pushing.
REFERENCE: https://docs.gitlab.com/ee/ci/lint.html
""",
    "image_version_mismatch.txt": """TITLE: Wrong language/runtime version in CI image
SYMPTOMS: "SyntaxError" on valid new syntax, "unsupported", features missing, passes locally
on a newer Node/Python/Java than CI.
ROOT CAUSE: CI uses a different (often older) runtime than local — image tag pinned to an old
version or `latest` drifting.
FIX: Pin the image to the exact runtime you target (e.g. `image: node:20` / `python:3.12`).
Match local with .nvmrc/.tool-versions. Avoid `latest`.
REFERENCE: https://docs.gitlab.com/ee/ci/yaml/#image
""",
    "protected_branch_deploy.txt": """TITLE: Deploy/job fails only on protected branch or MR from fork
SYMPTOMS: Deploy job has no credentials, protected variables empty, "masked variable not
available", works on main but not in MR pipelines.
ROOT CAUSE: Protected CI/CD variables are only exposed on protected branches/tags; fork MR
pipelines don't receive secrets by design.
FIX: Protect the branch/tag that needs the secret; for deploys, restrict to protected refs.
For fork contributions, run deploys only on the canonical repo's protected branches.
REFERENCE: https://docs.gitlab.com/ee/ci/variables/#protect-a-cicd-variable
""",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, body in DOCS.items():
        (OUT / name).write_text(body, encoding="utf-8")
    print(f"wrote {len(DOCS)} knowledge docs to {OUT}")


if __name__ == "__main__":
    main()
