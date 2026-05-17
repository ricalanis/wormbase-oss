"""Notion connector — skeletal.

Notion-as-source is on-thesis for institutional AI: org wiki content
ingested as a first-class data source. Production impl: Notion API
via httpx. Discover lists databases via ``/v1/search?filter=database``.
Profile via per-database ``GET /v1/databases/<id>`` for property
schema. Sample via ``POST /v1/databases/<id>/query?page_size=n``.
"""

from __future__ import annotations

from ._skeletal import SkeletalSurfaceDriver
from .registry import register_surface_driver


@register_surface_driver
class NotionSurfaceDriver(SkeletalSurfaceDriver):
    kind = "notion"
    capability = {"discover"}
    classification_hints = []
    status = "coming_soon"
    status_note = (
        "SurfaceDriver skeleton — Notion API integration lands in v1.5 (on-thesis priority)."
    )
    required_secrets = ("integration_token",)
    optional_secrets = ("workspace_id",)
    not_implemented_reason = (
        "Notion API integration lands post-day-one (on-thesis priority)"
    )


__all__ = ["NotionSurfaceDriver"]
