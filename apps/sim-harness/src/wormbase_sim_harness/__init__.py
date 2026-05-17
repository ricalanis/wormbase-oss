"""WormBase sim harness — scenario-driven persona poster.

Drives an authentic-feeling Slack conversation against a real workspace,
exercising every Path 3 capture path (silent message, @mention, file drop).
The harness writes nothing to the WormBase ledger directly; it drives Slack
and lets the existing Path 3 stack capture deterministically. It DOES read
the ledger (via wormbase-ledger) to verify post-run acceptance.
"""

from wormbase_sim_harness.personas import Persona, PersonaRegistry
from wormbase_sim_harness.scenario import Beat, Scenario, FileDrop

__all__ = [
    "Persona",
    "PersonaRegistry",
    "Beat",
    "Scenario",
    "FileDrop",
]
