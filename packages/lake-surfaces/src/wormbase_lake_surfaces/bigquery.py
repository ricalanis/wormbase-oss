"""BigQuery connector — skeletal.

Production impl will use ``google-cloud-bigquery`` (sync) bridged via
``asyncio.to_thread``. Discovery via ``INFORMATION_SCHEMA.TABLES`` of
the configured project. Profile via ``Client.get_table()``. Sample via
``SELECT … LIMIT n``.
"""

from __future__ import annotations

from ._skeletal import SkeletalSurfaceDriver
from .registry import register_surface_driver


@register_surface_driver
class BigQuerySurfaceDriver(SkeletalSurfaceDriver):
    kind = "bigquery"
    capability = {"discover"}
    classification_hints = []
    status = "coming_soon"
    status_note = (
        "SurfaceDriver skeleton — google-cloud-bigquery integration lands in v1.5."
    )
    required_secrets = ("project", "service_account_json")
    optional_secrets = ("dataset",)
    not_implemented_reason = (
        "google-cloud-bigquery integration lands post-day-one"
    )


__all__ = ["BigQuerySurfaceDriver"]
