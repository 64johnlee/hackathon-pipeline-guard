"""Ingesters that pump pipeline events into Splunk for agent investigation."""
from .gitlab_to_splunk import GitLabToSplunkIngester

__all__ = ["GitLabToSplunkIngester"]
