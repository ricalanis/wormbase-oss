"""Notion connector — skeletal.

Notion-as-source is on-thesis for institutional AI: org wiki content
ingested as a first-class data source. Production impl: Notion API
via httpx. Discover lists databases via ``/v1/search?filter=database``.
Profile via per-database ``GET /v1/databases/<id>`` for property
schema. Sample via ``POST /v1/databases/<id>/query?page_size=n``.
"""

from __future__ import annotations

from ._skeletal import SkeletalConnector
from .registry import register_connector


@register_connector
class NotionConnector(SkeletalConnector):
    kind = "notion"
    capability = {"discover"}
    classification_hints = []
    status = "coming_soon"
    status_note = (
        "Connector skeleton — Notion API integration lands in v1.5 (on-thesis priority)."
    )
    required_secrets = ("integration_token",)
    optional_secrets = ("workspace_id",)
    not_implemented_reason = (
        "Notion API integration lands post-day-one (on-thesis priority)"
    )


__all__ = ["NotionConnector"]
