"""Linear connector — skeletal.

Linear-as-source captures issue-tracker signal as a first-class data
source: tickets, cycles, projects, comments, audit history. Production
impl: Linear GraphQL API via httpx. Discover lists teams + projects.
Profile via Linear's introspection schema. Sample via paginated
``issues(first: n)`` queries.
"""

from __future__ import annotations

from ._skeletal import SkeletalConnector
from .registry import register_connector


@register_connector
class LinearConnector(SkeletalConnector):
    kind = "linear"
    capability = {"discover"}
    classification_hints = []
    status = "coming_soon"
    status_note = (
        "Connector skeleton — Linear GraphQL API integration lands in v1.5 (on-thesis priority)."
    )
    required_secrets = ("api_key",)
    optional_secrets = ("workspace_id",)
    not_implemented_reason = (
        "Linear GraphQL API integration lands post-day-one (on-thesis priority)"
    )


__all__ = ["LinearConnector"]
