"""HubSpot connector — skeletal.

Production impl: HubSpot CRM API via httpx. Discover lists CRM object
types via ``/crm/v3/schemas``. Profile via per-object ``/properties``.
Sample via ``/crm/v3/objects/<type>?limit=n``.
"""

from __future__ import annotations

from ._skeletal import SkeletalConnector
from .registry import register_connector


@register_connector
class HubspotConnector(SkeletalConnector):
    kind = "hubspot"
    capability = {"discover"}
    classification_hints = ["pii"]
    status = "coming_soon"
    status_note = (
        "Connector skeleton — HubSpot CRM API integration lands in v1.5."
    )
    required_secrets = ("access_token",)
    optional_secrets = ("portal_id",)
    not_implemented_reason = (
        "HubSpot CRM API integration lands post-day-one"
    )


__all__ = ["HubspotConnector"]
