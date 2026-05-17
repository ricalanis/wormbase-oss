"""Onboarding helpers for the install-arc default state.

Submodules:

* :mod:`default_local_source` — resolves the canonical cursed-CSV
  fixture path and provides the silver-layer normalization the
  install-arc Beat 2 cascade runs against it.
* :mod:`pack_loader` — reads + validates the 4 bundled domain pack
  YAMLs (Onboarding Sub-wave C, 2026-05-30).
* :mod:`pack_seeder` — fans a loaded pack into a ``domain_pack_selected``
  parent PEVR cycle plus per-domain / per-policy fan-out.
"""

from .default_local_source import (
    CURSED_CSV_FIXTURE_FILENAME,
    CURSED_CSV_PATH,
    cursed_csv_path,
    cursed_csv_silver_bytes,
    run_default_local_cascade,
)
from .pack_loader import (
    Pack,
    PackClassificationDefault,
    PackDomain,
    PackLoadError,
    PackPolicy,
    available_pack_ids,
    list_packs,
    load_pack,
)
from .pack_seeder import PackSeedReport, seed_pack

__all__ = [
    "CURSED_CSV_FIXTURE_FILENAME",
    "CURSED_CSV_PATH",
    "Pack",
    "PackClassificationDefault",
    "PackDomain",
    "PackLoadError",
    "PackPolicy",
    "PackSeedReport",
    "available_pack_ids",
    "cursed_csv_path",
    "cursed_csv_silver_bytes",
    "list_packs",
    "load_pack",
    "run_default_local_cascade",
    "seed_pack",
]
