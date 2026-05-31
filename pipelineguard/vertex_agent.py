"""
Vertex AI Agent Engine (Reasoning Engine) wrapper for PipelineGuard.

Deploy to Google Cloud Agent Builder:

    import vertexai
    from vertexai.preview import reasoning_engines
    from pipelineguard.vertex_agent import PipelineGuardVertexApp

    vertexai.init(project="my-gcp-project", location="us-central1")

    remote_app = reasoning_engines.ReasoningEngine.create(
        PipelineGuardVertexApp(gitlab_token="glpat-...", gitlab_url="https://gitlab.com"),
        requirements=["pipelineguard[web]>=0.1.0", "google-cloud-aiplatform[reasoningengine]"],
        display_name="PipelineGuard",
        description="AI-powered GitLab CI pipeline diagnostics using Gemini 2.5 Flash",
    )
    print(remote_app.resource_name)  # projects/.../reasoningEngines/...

    # Query the deployed engine:
    remote_app.query(project="myorg/myrepo")
"""
from __future__ import annotations

import asyncio
import os
from typing import Any


class PipelineGuardVertexApp:
    """
    Agent Engine-compatible app class.  The Reasoning Engine framework calls
    set_up() once on container start and query() for every inference request.
    """

    def __init__(
        self,
        gitlab_token: str = "",
        gitlab_url: str = "https://gitlab.com",
        gcp_project: str = "",
        gcp_location: str = "us-central1",
    ) -> None:
        self._gitlab_token = gitlab_token or os.environ.get("GITLAB_TOKEN", "")
        self._gitlab_url = gitlab_url
        self._gcp_project = gcp_project or os.environ.get("GCP_PROJECT", "")
        self._gcp_location = gcp_location or os.environ.get("GCP_LOCATION", "us-central1")
        self._agent: Any = None

    # ------------------------------------------------------------------
    # Agent Engine lifecycle
    # ------------------------------------------------------------------

    def set_up(self) -> None:
        """Initialise the agent (called once when the container starts)."""
        from .agent import PipelineGuardAgent

        self._agent = PipelineGuardAgent(
            gitlab_token=self._gitlab_token,
            gitlab_url=self._gitlab_url,
            use_vertex=True,
            gcp_project=self._gcp_project,
            gcp_location=self._gcp_location,
        )

    # ------------------------------------------------------------------
    # Public query interface
    # ------------------------------------------------------------------

    def query(
        self,
        project: str,
        pipeline_id: int | None = None,
        post_comment: bool = False,
    ) -> dict[str, Any]:
        """
        Diagnose a failed GitLab CI pipeline.

        Args:
            project: GitLab namespace/project path, e.g. ``"myorg/myrepo"``.
            pipeline_id: Specific pipeline ID.  ``None`` -> latest failed pipeline.
            post_comment: If True, post the diagnosis as an MR comment.

        Returns:
            Serialisable dict with keys: project, pipeline_id, root_cause,
            failure_category, affected_jobs, is_flaky, fix_proposals,
            mr_comment_url, pipeline_url.
        """
        if self._agent is None:
            self.set_up()

        report = asyncio.run(
            self._agent.diagnose(
                project=project,
                pipeline_id=pipeline_id,
                post_comment=post_comment,
            )
        )

        return {
            "project": report.project,
            "pipeline_id": report.pipeline_id,
            "root_cause": report.root_cause,
            "failure_category": report.failure_category.value,
            "affected_jobs": report.affected_jobs,
            "is_flaky": report.is_flaky,
            "fix_proposals": [
                {
                    "file_path": fp.file_path,
                    "description": fp.description,
                    "diff": fp.diff,
                    "confidence": fp.confidence.value,
                }
                for fp in report.fix_proposals
            ],
            "mr_comment_url": report.mr_comment_url,
            "pipeline_url": report.pipeline_url,
        }
