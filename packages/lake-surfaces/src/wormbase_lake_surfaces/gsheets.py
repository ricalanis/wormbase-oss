"""Google Sheets connector — skeletal.

Production impl: Google Sheets API v4 via google-auth + httpx. Discover
lists the spreadsheet's sheets. Profile via
``sheets.values.get(range='1:1')`` for the header row. Sample via
``sheets.values.get(range='1:n')``.
"""

from __future__ import annotations

from ._skeletal import SkeletalSurfaceDriver
from .registry import register_surface_driver


@register_surface_driver
class GsheetsSurfaceDriver(SkeletalSurfaceDriver):
    kind = "gsheets"
    capability = {"discover"}
    classification_hints = []
    status = "coming_soon"
    status_note = (
        "SurfaceDriver skeleton — Google Sheets API v4 integration lands in v1.5."
    )
    required_secrets = ("service_account_json",)
    optional_secrets = ("spreadsheet_id",)
    not_implemented_reason = (
        "Google Sheets API v4 integration lands post-day-one"
    )


__all__ = ["GsheetsSurfaceDriver"]
