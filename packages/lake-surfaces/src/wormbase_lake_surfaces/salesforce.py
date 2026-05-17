"""Salesforce connector — skeletal.

Production impl: OAuth via the Connected App flow, then list sobjects
via ``/services/data/vXX.X/sobjects/`` (describe). Profile via
``describeSObject(name)``; sample via SOQL ``SELECT … FROM X LIMIT n``.
"""

from __future__ import annotations

from ._skeletal import SkeletalSurfaceDriver
from .registry import register_surface_driver


@register_surface_driver
class SalesforceSurfaceDriver(SkeletalSurfaceDriver):
    kind = "salesforce"
    capability = {"discover"}
    classification_hints = ["pii", "regulated"]
    status = "coming_soon"
    status_note = (
        "SurfaceDriver skeleton — Connected App OAuth + describeSObject lands in v1.5."
    )
    required_secrets = ("instance_url", "access_token")
    optional_secrets = ("refresh_token", "api_version")
    not_implemented_reason = (
        "Salesforce Connected App OAuth + describeSObject lands post-day-one"
    )


__all__ = ["SalesforceSurfaceDriver"]
