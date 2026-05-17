"""``wormbase`` CLI — sim harness entry point.

Subcommands:

* ``wormbase demo run [--script PATH] [--pace wall|virtual] [--channel CHAN]
                      [--no-improv] [--skip-acceptance]``
  Drives the configured Slack workspace end-to-end.
* ``wormbase demo personas`` — prints loaded personas.
* ``wormbase demo scenarios`` — lists scenarios under ``scenarios/``.
* ``wormbase demo seed`` — real tenant seed: warmup (domains, policies,
  ramp gauges) + optional simulated past-week chat history. Idempotent;
  re-runs dedupe on deterministic message ids.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid5

import click

from wormbase_sim_harness.acceptance import assert_demo_invariants
from wormbase_sim_harness.clock import Clock, VirtualClock, WallClock
from wormbase_sim_harness.engine import ScenarioEngine
from wormbase_sim_harness.improv import ImprovEngine
from wormbase_sim_harness.personas import PersonaRegistry
from wormbase_sim_harness.rehearsal import RehearsalReport, run_rehearsal
from wormbase_sim_harness.scenario import Scenario, list_scenarios
from wormbase_sim_harness.slack_poster import SlackPoster

log = logging.getLogger("wormbase.sim")

# Resolve project paths relative to this file. The package is installed as
# editable in dev (uv workspace) and the personas/scenarios/fixtures dirs
# live one level above ``src/``. In the container these are bind-mounted
# at /workspace/apps/sim-harness/.
_HARNESS_ROOT_ENV = "WORMBASE_SIM_HARNESS_ROOT"


def _harness_root() -> Path:
    env = os.environ.get(_HARNESS_ROOT_ENV)
    if env:
        return Path(env)
    # __file__ = .../apps/sim-harness/src/wormbase_sim_harness/cli.py
    return Path(__file__).resolve().parents[2]


def _personas_path() -> Path:
    return _harness_root() / "personas.yml"


def _scenarios_dir() -> Path:
    return _harness_root() / "scenarios"


def _fixtures_dir() -> Path:
    return _harness_root() / "fixtures"


def _company_id_from_tenant(tenant: str) -> UUID:
    """Stable UUID5 from tenant slug — matches the ledger's tenant convention."""
    return uuid5(NAMESPACE_DNS, f"wormbase.tenant.{tenant}")


@click.group(help="WormBase CLI (sim harness).")
def main() -> None:
    logging.basicConfig(
        level=os.environ.get("WORMBASE_SIM_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@main.group(help="Demo-run subcommands.")
def demo() -> None:
    pass


@demo.command("personas", help="List loaded personas.")
def cmd_personas() -> None:
    reg = PersonaRegistry.from_yaml(_personas_path())
    rows = []
    for p in reg.personas.values():
        rows.append(
            {
                "id": p.id,
                "display_name": p.display_name,
                "icon_emoji": p.icon_emoji,
                "role": p.role,
            }
        )
    click.echo(json.dumps(rows, indent=2))


@demo.command("scenarios", help="List available scenarios.")
def cmd_scenarios() -> None:
    names = list_scenarios(_scenarios_dir())
    click.echo(json.dumps({"scenarios": names, "dir": str(_scenarios_dir())}, indent=2))


_DEFAULT_LEDGER_DSN = (
    "postgresql+asyncpg://wormbase:wormbase@postgres:5432/wormbase"
)


@demo.command(
    "seed-tenants",
    help=(
        "Phase 1B.G — seed the 3-5 demo tenants used by the email "
        "magic-link evaluator carousel. Each demo tenant gets a "
        "tenant_signup_initiated + tenant_signup_completed pair "
        "(signup_source=demo_seed). Idempotent."
    ),
)
@click.option(
    "--ledger-dsn",
    envvar="WORMBASE_LEDGER_DSN",
    default=_DEFAULT_LEDGER_DSN,
    show_default=True,
    help="Postgres DSN for the wormbase ledger (asyncpg URL).",
)
def cmd_seed_tenants(ledger_dsn: str) -> None:
    """Seed the canonical demo-tenant carousel via the ledger.

    Writes the canonical signup chain
    (``tenant_signup_initiated`` → ``tenant_signup_completed``) for
    each demo tenant in ``DEMO_TENANT_DEFAULTS``. Idempotent: re-running
    produces the same UUIDv5-derived tenant_ids and the projection
    upserts on tenant_id.
    """
    # Lazy imports keep the unrelated ``wormbase demo personas`` /
    # ``scenarios`` commands cheap.
    from wormbase_core import write_actions
    from wormbase_core.service import tenant_to_uuid
    from wormbase_ledger import Ledger
    from wormbase_sim_harness.seed_demo_tenants import (
        DEMO_TENANT_DEFAULTS,
        build_seed_plan,
    )

    async def _run() -> dict[str, object]:
        ledger = Ledger(ledger_dsn)
        try:
            plan = build_seed_plan(DEMO_TENANT_DEFAULTS)
            written: list[str] = []
            for entry in plan:
                cid = tenant_to_uuid(entry["slug"])
                if entry["kind"] == "tenant_signup_initiated":
                    await write_actions.initiate_tenant_signup(
                        ledger,
                        cid,
                        tenant_id=cid,
                        slug=entry["slug"],
                        display_name=entry["display_name"],
                        signup_source=entry["signup_source"],
                        signup_email=entry["signup_email"],
                        pending_token_hash=entry["pending_token_hash"],
                    )
                    written.append(f"initiated:{entry['slug']}")
                else:
                    await write_actions.complete_tenant_signup(
                        ledger,
                        cid,
                        tenant_id=cid,
                        signup_source=entry["signup_source"],
                        assigned_tenant_slug=entry["assigned_tenant_slug"],
                        signup_email=entry["signup_email"],
                    )
                    written.append(f"completed:{entry['slug']}")
            return {
                "tenants_seeded": len(DEMO_TENANT_DEFAULTS),
                "ledger_entries_written": len(written) * 4,  # 4 PEVR entries each
                "writes": written,
            }
        finally:
            await ledger.dispose()

    result = asyncio.run(_run())
    click.echo(json.dumps(result, indent=2))


@demo.command(
    "seed",
    help=(
        "Seed a tenant: run warmup (domains, policies, ramp gauges, ontology). "
        "Use --replay-history <jsonl> to feed recorded wire events through the "
        "production channel-adapter PEVR primitive. Idempotent."
    ),
)
@click.option(
    "--ledger-dsn",
    envvar="WORMBASE_LEDGER_DSN",
    default=_DEFAULT_LEDGER_DSN,
    show_default=True,
    help="Postgres DSN for the wormbase ledger (asyncpg URL).",
)
@click.option(
    "--tenant",
    default="baseworm",
    show_default=True,
    help="Tenant slug — drives company_id derivation.",
)
@click.option(
    "--domain-pack",
    default="saas",
    show_default=True,
    help="Domain pack to apply during warmup (saas|fintech|marketplace).",
)
@click.option(
    "--reset-only",
    is_flag=True,
    help="Clear the tenant's ledger rows; skip warmup and history.",
)
@click.option(
    "--reset-first",
    is_flag=True,
    help="Clear the tenant's ledger rows before warmup + history.",
)
@click.option(
    "--replay-history",
    "replay_history_path",
    type=click.Path(dir_okay=False, exists=False, path_type=Path),
    default=None,
    help=(
        "Replay a recorded JSONL of channel-adapter wire events through "
        "the production wire-replay tool. Use this instead of the legacy "
        "direct-ledger-write history seed — wire-replay drives the same "
        "PEVR primitive the live channel-adapter uses, so the dashboard "
        "cannot distinguish replayed entries from real ones. Capture the "
        "JSONL with `wormbase demo wire-record`."
    ),
)
@click.option(
    "--no-personas",
    is_flag=True,
    help=(
        "Skip seeding the four canonical personas as Person rows via "
        "the worm-core HTTP API. Personas are bot-roster only when this "
        "flag is set."
    ),
)
@click.option(
    "--worm-core-api-base",
    default=None,
    envvar="WORMBASE_LEDGER_API_BASE",
    help=(
        "Worm-core HTTP write API base URL "
        "(default: http://worm-core:8910 in compose; "
        "http://localhost:8910 outside)."
    ),
)
@click.option(
    "--worm-core-api-token",
    default=None,
    envvar="WORMBASE_LEDGER_API_TOKEN",
    help="Bearer token for the worm-core HTTP write API (E5 personas seed).",
)
@click.option(
    "--install-from-env/--no-install-from-env",
    "install_from_env",
    default=None,
    help=(
        "Drive a real Install via worm-core /api/v1/installs using a "
        "pre-issued bot token. Auto-enabled when SLACK_BOT_TOKEN_"
        "${TENANT_UPPER} is set in env (e.g. SLACK_BOT_TOKEN_BASEWORM); "
        "skipped when absent. Pass --install-from-env to require it "
        "(exits non-zero if env unset). Pass --no-install-from-env to "
        "always skip even if env is set. No synthesized fallback under "
        "any flag combination — install requires real Slack creds."
    ),
)
@click.option(
    "--provision-local-lake/--no-provision-local-lake",
    "provision_local_lake_flag",
    default=None,
    help=(
        "Block I7. Provision the default local lake via worm-core "
        "/api/v1/installs/provision-local-lake. Defaults to True when "
        "--install-from-env is also passed (the install path itself "
        "auto-provisions; this flag is for tenants where install ran "
        "previously and the lake row is missing). Defaults to False "
        "otherwise."
    ),
)
@click.option(
    "--rich/--no-rich",
    "rich",
    default=True,
    help=(
        "W7.A1. After personas are confirmed, drive a Beat-9-ready "
        "enrichment via the worm-core HTTP write API: register the "
        "retention domain, propose churn_rate KPI, grant Carol "
        "domain.owner + resource.maintainer, record 2 decisions, "
        "1 process map, and generate the q3_churn_cohort data "
        "product. Default-on so `make seed` produces a tenant ready "
        "for `wormbase demo run --script scenarios/_beat9-focused.yml` "
        "without any post-seed setup. Pass --no-rich to skip "
        "(matches the legacy lean baseline)."
    ),
)
def cmd_seed(
    ledger_dsn: str,
    tenant: str,
    domain_pack: str,
    reset_only: bool,
    reset_first: bool,
    replay_history_path: Path | None,
    no_personas: bool,
    worm_core_api_base: str | None,
    worm_core_api_token: str | None,
    install_from_env: bool | None,
    provision_local_lake_flag: bool | None,
    rich: bool,
) -> None:
    """Real tenant seeding via wormbase_sim_harness.seed.seed_tenant."""
    # Local import keeps `wormbase demo personas` cheap and avoids
    # importing worm-core / governance / sqlalchemy when only listing
    # personas or scenarios.
    from wormbase_sim_harness.seed import seed_tenant

    if reset_only:
        # --reset-only implies a destructive clear with no rebuild.
        # We model this as reset_first=True + skip warmup/history by
        # delegating to the helper directly.
        async def _go_reset() -> dict[str, object]:
            from wormbase_ledger import Ledger as _Ledger

            from wormbase_sim_harness.seed import _reset_tenant

            ledger = _Ledger(ledger_dsn)
            try:
                from wormbase_core.service import tenant_to_uuid as _t2u

                cid = _t2u(tenant)
                deleted = await _reset_tenant(ledger, cid)
                return {
                    "tenant": tenant,
                    "company_id": str(cid),
                    "reset": True,
                    "rows_deleted": deleted,
                    "warmup_ran": False,
                    "history_entries_written": 0,
                }
            finally:
                await ledger.dispose()

        result = asyncio.run(_go_reset())
        _print_seed_table(result)
        return

    async def _go() -> dict[str, object]:
        nonlocal install_from_env
        # Default flow: warmup only — fresh tenants have no prior chat.
        # ``--replay-history`` opts into wire-replay, which feeds a recorded
        # JSONL through the production channel-adapter PEVR primitive so
        # the resulting ``channel_adapter.emit_chat_received`` entries are
        # indistinguishable from live ones at the ledger level.
        report = await seed_tenant(
            ledger_dsn=ledger_dsn,
            tenant=tenant,
            domain_pack=domain_pack,
            reset_first=reset_first,
            write_history=False,
            rich=rich,
        )
        payload = report.model_dump(mode="json")

        if replay_history_path is not None:
            from uuid import UUID as _UUID

            from wormbase_channel_adapter.wire_replay import WireReplayer
            from wormbase_ledger import Ledger as _Ledger

            from wormbase_core.service import tenant_to_uuid as _t2u

            cid: _UUID = _t2u(tenant)
            replay_ledger = _Ledger(ledger_dsn)
            try:
                replayer = WireReplayer(
                    ledger=replay_ledger,
                    company_id=cid,
                    jsonl_path=replay_history_path,
                )
                replayed = await replayer.run()
                payload["history_replayed_events"] = replayed
                payload["history_replayed_path"] = str(replay_history_path)
            except FileNotFoundError as exc:
                raise click.ClickException(
                    f"--replay-history file not found: {exc}"
                ) from exc
            finally:
                await replay_ledger.dispose()

        api_base = worm_core_api_base or _default_worm_core_api_base()
        api_token = worm_core_api_token or os.environ.get(
            "WORMBASE_LEDGER_API_TOKEN", "",
        )

        # `--install-from-env` drives a real Install via the production
        # worm-core orchestrator using a pre-issued bot token. There is
        # NO synthesized fallback: if the env is unset the CLI exits
        # non-zero with a clear pointer. Same code path as the OAuth
        # callback — the only difference is who supplies the token.
        #
        # Tristate default (None): auto-enable when SLACK_BOT_TOKEN_${TENANT}
        # is set in env. Operators with creds get a fully-populated dev
        # tenant by default; operators without creds get a clean empty
        # state (correct production behavior).
        if install_from_env is None:
            bot_token_env = f"SLACK_BOT_TOKEN_{tenant.upper()}"
            install_from_env = bool(
                os.environ.get(bot_token_env, "").strip()
            )
            if install_from_env:
                click.echo(
                    f"auto-enabled --install-from-env "
                    f"({bot_token_env} detected in env)",
                    err=True,
                )
            else:
                click.echo(
                    f"--install-from-env skipped "
                    f"(SLACK_BOT_TOKEN_{tenant.upper()} not in env). "
                    f"Pass --install-from-env to require it; pass "
                    f"--no-install-from-env to silence this notice.",
                    err=True,
                )
        if install_from_env:
            from wormbase_sim_harness.seed_install import seed_install_from_env

            if not api_token:
                raise click.ClickException(
                    "--install-from-env requires WORMBASE_LEDGER_API_TOKEN "
                    "(bearer for worm-core write API)"
                )
            try:
                install_report = await seed_install_from_env(
                    tenant=tenant,
                    dashboard_api_base=api_base,
                    api_token=api_token,
                )
            except Exception as exc:  # noqa: BLE001
                raise click.ClickException(
                    f"--install-from-env failed: {exc}"
                ) from exc
            if install_report is None:
                env_name = f"SLACK_BOT_TOKEN_{tenant.upper()}"
                raise click.ClickException(
                    f"set {env_name} env to use --install-from-env"
                )
            payload["install_id"] = str(install_report.install_id)
            payload["installer_person_id"] = str(install_report.installer_person_id)
            payload["installer_email"] = install_report.installer_email
            payload["installer_name"] = install_report.installer_name
            payload["bot_user_id"] = install_report.bot_user_id

        # Block I7: optional default-local-lake provisioning. Default-on
        # when --install-from-env is set (the install path itself
        # auto-provisions; this branch is the resync helper for tenants
        # where install ran previously without the lake), default-off
        # otherwise. The explicit --no-provision-local-lake flag
        # short-circuits in either case.
        should_provision_lake: bool
        if provision_local_lake_flag is not None:
            should_provision_lake = provision_local_lake_flag
        else:
            should_provision_lake = install_from_env

        if should_provision_lake:
            from uuid import UUID as _UUID2

            from wormbase_core.service import tenant_to_uuid as _t2u_lake

            from wormbase_sim_harness.seed_local_lake import seed_local_lake

            installer_person_id_str = str(payload.get("installer_person_id") or "")
            if not installer_person_id_str:
                click.echo(
                    "--provision-local-lake skipped: no installer_person_id "
                    "available (run with --install-from-env first or pass "
                    "--no-provision-local-lake to silence).",
                    err=True,
                )
                payload["local_lake_provisioned"] = False
            elif not api_token:
                click.echo(
                    "WORMBASE_LEDGER_API_TOKEN unset; skipping local-lake provision.",
                    err=True,
                )
                payload["local_lake_provisioned"] = False
            else:
                try:
                    lake_report = await seed_local_lake(
                        tenant=tenant,
                        tenant_id=_t2u_lake(tenant),
                        installer_person_id=_UUID2(installer_person_id_str),
                        dashboard_api_base=api_base,
                        api_token=api_token,
                    )
                    payload["local_lake_source_id"] = str(lake_report.source_id)
                    payload["local_lake_entry_count"] = lake_report.entry_count
                    payload["local_lake_provisioned"] = True
                except Exception as exc:  # noqa: BLE001
                    click.echo(f"local-lake provision failed: {exc}", err=True)
                    payload["local_lake_provisioned"] = False
                    payload["local_lake_error"] = str(exc)

        # E5: seed the four canonical personas as Person rows via the
        # worm-core HTTP API. The CLI defaults expect the API to be
        # reachable at the same host as the rest of the demo stack;
        # pass --no-personas to skip when running tests or against a
        # tenant that's already populated.
        if no_personas:
            payload["personas_seeded"] = 0
            return payload

        from wormbase_sim_harness.seed_personas import seed_personas

        if not api_token:
            click.echo(
                "WORMBASE_LEDGER_API_TOKEN unset; skipping persona seed.",
                err=True,
            )
            payload["personas_seeded"] = 0
            return payload

        try:
            personas_report = await seed_personas(
                tenant=tenant,
                dashboard_api_base=api_base,
                api_token=api_token,
            )
            payload["personas_seeded"] = personas_report.proposed
            payload["personas_confirmed"] = personas_report.confirmed
            payload["persona_ids"] = personas_report.to_dict()["person_ids"]
        except Exception as exc:  # noqa: BLE001
            click.echo(f"persona seed failed: {exc}", err=True)
            payload["personas_seeded"] = 0
            payload["personas_error"] = str(exc)
            return payload

        # W7.A1 — rich Beat-9 enrichment: KPI + role grants + decisions
        # + process map + data product. Gated on `--rich` (default-on)
        # AND on the personas seed having succeeded (otherwise Carol's
        # Person id isn't available). Fully opt-out via `--no-rich`.
        if rich and personas_report.person_ids:
            from wormbase_core.service import tenant_to_uuid as _t2u_rich

            from wormbase_sim_harness.seed_personas import CANONICAL_PERSONAS
            from wormbase_sim_harness.seed_rich import seed_rich

            # Resolve Carol's Person id by matching CANONICAL_PERSONAS
            # rather than a fixed list index — robust to roster
            # reordering. The ledger handle is opened only for the one
            # direct write the rich phase needs (the synthetic
            # emit_domain_registered for "retention" — no HTTP endpoint
            # exists for it).
            carol_person_id: UUID | None = None
            for cp, pid in zip(
                CANONICAL_PERSONAS, personas_report.person_ids, strict=True,
            ):
                if cp.pid == "carol":
                    carol_person_id = pid
                    break

            if carol_person_id is None:
                click.echo(
                    "rich seed skipped: Carol's Person id not found in "
                    "personas roster.",
                    err=True,
                )
                payload["rich_seed_completed"] = False
            else:
                from wormbase_ledger import Ledger as _Ledger

                rich_ledger = _Ledger(ledger_dsn)
                try:
                    rich_report = await seed_rich(
                        tenant=tenant,
                        carol_person_id=carol_person_id,
                        dashboard_api_base=api_base,
                        api_token=api_token,
                        ledger=rich_ledger,
                        company_id=_t2u_rich(tenant),
                    )
                    payload["rich_seed_completed"] = True
                    payload["rich_kpi_id"] = (
                        str(rich_report.kpi_id) if rich_report.kpi_id else None
                    )
                    payload["rich_decision_count"] = len(
                        rich_report.decision_ids,
                    )
                    payload["rich_process_id"] = (
                        str(rich_report.process_id)
                        if rich_report.process_id
                        else None
                    )
                    payload["rich_data_product_id"] = (
                        str(rich_report.data_product_id)
                        if rich_report.data_product_id
                        else None
                    )
                    payload["rich_retention_domain_id"] = str(
                        rich_report.retention_domain_id,
                    )
                except Exception as exc:  # noqa: BLE001
                    click.echo(f"rich seed failed: {exc}", err=True)
                    payload["rich_seed_completed"] = False
                    payload["rich_seed_error"] = str(exc)
                finally:
                    try:
                        await rich_ledger.dispose()
                    except Exception as exc:  # noqa: BLE001
                        log.warning("rich ledger dispose failed: %s", exc)

            # Wave-B Seeds: replay the four install-arc seed JSONLs
            # (S1..S4) through the channel-adapter wire-replay primitive
            # so the install arc trips its targeted reactivities at the
            # expected beats. Per CLAUDE.md invariant 1 (no flow-bypass)
            # this runs through ``WireReplayer`` — the same code path
            # the live channel-adapter uses. Failure here is logged but
            # does not unfire the rich seed; the seeds are an additive
            # demo-arc enrichment.
            try:
                from wormbase_channel_adapter.wire_replay import (
                    WireReplayer as _WireReplayer,
                )
                from wormbase_core.service import (
                    tenant_to_uuid as _t2u_seed,
                )
                from wormbase_ledger import Ledger as _Ledger_seed
                from wormbase_sim_harness.seed_loader import (
                    default_fixture_dir,
                    load_install_arc_seeds,
                    write_unioned_jsonl,
                )

                fixture_dir = default_fixture_dir()
                events, seed_report = load_install_arc_seeds(
                    fixture_dir=fixture_dir,
                )
                # Stage the unioned JSONL beside the fixtures so the
                # wire-replay run is auditable post-hoc; pinned name
                # keeps re-runs deterministic.
                unioned_path = (
                    fixture_dir / "_unioned_install_arc_seeds.jsonl"
                )
                write_unioned_jsonl(events, unioned_path)

                seed_ledger = _Ledger_seed(ledger_dsn)
                try:
                    replayer = _WireReplayer(
                        ledger=seed_ledger,
                        company_id=_t2u_seed(tenant),
                        jsonl_path=unioned_path,
                    )
                    replayed = await replayer.run()
                finally:
                    try:
                        await seed_ledger.dispose()
                    except Exception as exc:  # noqa: BLE001
                        log.warning("seed ledger dispose failed: %s", exc)
                payload["install_arc_seeds_replayed"] = replayed
                payload["install_arc_seeds_total"] = (
                    seed_report.total_events
                )
                payload["install_arc_seeds_per_seed"] = (
                    seed_report.events_per_seed
                )
            except Exception as exc:  # noqa: BLE001
                click.echo(
                    f"install-arc seeds replay failed: {exc}", err=True,
                )
                payload["install_arc_seeds_replayed"] = 0
                payload["install_arc_seeds_error"] = str(exc)
        elif not rich:
            payload["rich_seed_completed"] = False

        return payload

    payload = asyncio.run(_go())
    _print_seed_table(payload)


def _default_worm_core_api_base() -> str:
    """Pick a sensible default for the worm-core write API URL.

    Inside the compose network, the worm-core service is reachable at
    ``http://worm-core:8910``. Outside (running CLI on the host), it's
    ``http://localhost:8910``. We default to the compose hostname since
    that's where ``wormbase demo seed`` runs in CI / production; the
    host case can override via ``--worm-core-api-base`` or the
    ``WORMBASE_LEDGER_API_BASE`` env var.
    """
    return os.environ.get(
        "WORMBASE_LEDGER_API_BASE", "http://worm-core:8910",
    )


def _print_seed_table(payload: dict[str, object]) -> None:
    """Pretty-print a SeedReport-shaped dict as a compact two-column table."""
    keys = [
        "tenant",
        "company_id",
        "domain_pack",
        "reset",
        "rows_deleted",
        "warmup_ran",
        "warmup_already_warm",
        "warmup_entries_written",
        "history_replayed_events",
        "history_replayed_path",
        "install_id",
        "installer_person_id",
        "installer_email",
        "installer_name",
        "bot_user_id",
        "personas_seeded",
        "personas_confirmed",
        "local_lake_provisioned",
        "local_lake_source_id",
        "local_lake_entry_count",
        "rich",
        "rich_seed_completed",
        "rich_kpi_id",
        "rich_decision_count",
        "rich_process_id",
        "rich_data_product_id",
        "rich_retention_domain_id",
        "install_arc_seeds_replayed",
        "install_arc_seeds_total",
    ]
    rows = [(k, str(payload.get(k))) for k in keys if k in payload]
    if not rows:
        click.echo(json.dumps(payload, indent=2))
        return
    width = max(len(k) for k, _ in rows)
    click.echo("seed report")
    click.echo("-" * (width + 2 + 24))
    for k, v in rows:
        click.echo(f"{k.ljust(width)}  {v}")


def _probe(host: str, port: int, timeout: float = 1.5) -> dict[str, object]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {"host": host, "port": port, "reachable": True}
    except OSError as exc:
        return {"host": host, "port": port, "reachable": False, "error": str(exc)}


@demo.command("run", help="Run a scenario end-to-end against Slack.")
@click.option(
    "--script",
    "script_path",
    default=None,
    help="Scenario YAML (default: scenarios/install-arc-7beat.yml).",
)
@click.option(
    "--pace",
    type=click.Choice(["wall", "virtual"], case_sensitive=False),
    default="wall",
)
@click.option("--channel", default=None, help="Override default_channel from scenario.")
@click.option("--no-improv", is_flag=True, help="Disable LLM improvisation.")
@click.option("--skip-acceptance", is_flag=True, help="Skip ledger acceptance check.")
@click.option(
    "--tenant",
    default=os.environ.get("WORMBASE_TENANT_ID", "baseworm"),
    help="Tenant slug (drives company_id derivation).",
)
@click.option(
    "--bot-token-env",
    default="SLACK_BOT_TOKEN_SIM_BASEWORM",
    help="Environment variable holding the WormBase Sim bot token.",
)
def cmd_run(
    script_path: str | None,
    pace: str,
    channel: str | None,
    no_improv: bool,
    skip_acceptance: bool,
    tenant: str,
    bot_token_env: str,
) -> None:
    pace = pace.lower()
    script = (
        Path(script_path) if script_path else _scenarios_dir() / "install-arc-7beat.yml"
    )
    if not script.is_file():
        raise click.ClickException(f"scenario not found: {script}")

    registry = PersonaRegistry.from_yaml(_personas_path())
    scenario = Scenario.from_yaml(script)
    if channel:
        scenario = scenario.model_copy(update={"default_channel": channel})
    scenario.validate_against(registry)

    bot_token = os.environ.get(bot_token_env, "")
    if not bot_token:
        raise click.ClickException(
            f"missing {bot_token_env}; provision the WormBase Sim Slack app and "
            "set the bot token in .env"
        )

    # Translate `@WormBase` (the readable handle in scenario YAMLs) into
    # `<@USER_ID>` so Slack treats it as a real mention. The agent user
    # id is sourced from WORMBASE_AGENT_USER_ID; without it, mentions
    # render as literal text and the agent won't engage.
    mention_subs: dict[str, str] = {}
    agent_user_id = os.environ.get("WORMBASE_AGENT_USER_ID", "").strip()
    agent_handle = os.environ.get(
        "WORMBASE_AGENT_HANDLE", "@WormBase"
    ).strip()
    if agent_user_id:
        mention_subs[agent_handle] = f"<@{agent_user_id}>"
    poster = SlackPoster(bot_token, mention_substitutions=mention_subs)
    improv: ImprovEngine | None = None
    if not no_improv:
        improv = ImprovEngine()

    # The 7-beat install arc uses ``wait_for`` beats that poll the
    # ledger; wire one Ledger + company_id into the engine so those
    # directives resolve. We dispose the engine-side ledger in the
    # outer ``finally`` so the connection pool is freed even when the
    # scenario exits via timeout / exception.
    company_id = _company_id_from_tenant(tenant)
    engine_ledger = None
    dsn = os.environ.get("WORMBASE_LEDGER_DSN") or _DEFAULT_LEDGER_DSN
    needs_ledger = any(b.wait_for is not None for b in scenario.beats)
    if needs_ledger:
        from wormbase_ledger import Ledger as _Ledger

        engine_ledger = _Ledger(dsn)

    engine = ScenarioEngine(
        registry,
        improv=improv,
        fixtures_root=_fixtures_dir(),
        ledger=engine_ledger,
        company_id=company_id,
        agent_user_id=agent_user_id or None,
    )

    clock: Clock = WallClock() if pace == "wall" else VirtualClock()

    async def _go() -> int:
        started = datetime.now(UTC)
        try:
            report = await engine.run(scenario, clock, poster)
        finally:
            if engine_ledger is not None:
                try:
                    await engine_ledger.dispose()
                except Exception as exc:  # noqa: BLE001
                    log.warning("engine ledger dispose failed: %s", exc)
        click.echo(
            json.dumps(
                {
                    "scenario": report.scenario,
                    "started_at": report.started_at_iso,
                    "beats_run": len(report.beats),
                    "pace": pace,
                    "channel": scenario.default_channel,
                },
                indent=2,
            )
        )
        if skip_acceptance:
            return 0
        acceptance_dsn = os.environ.get("WORMBASE_LEDGER_DSN")
        if not acceptance_dsn:
            click.echo(
                "WORMBASE_LEDGER_DSN unset; skipping acceptance check.",
                err=True,
            )
            return 0
        # Local import keeps `wormbase demo personas` cheap even when the
        # ledger package isn't installed (e.g. CI without the workspace).
        from wormbase_ledger import Ledger

        ledger = Ledger(acceptance_dsn)
        try:
            acceptance = await assert_demo_invariants(ledger, company_id, started)
        finally:
            await ledger.dispose()
        click.echo(json.dumps(acceptance.to_dict(), indent=2))
        return 0 if acceptance.passed else 2

    rc = asyncio.run(_go())
    sys.exit(rc)


# ---------------------------------------------------------------------------
# `wormbase demo rehearse` — dry-run a scenario without touching real Slack.
# ---------------------------------------------------------------------------


@demo.command(
    "rehearse",
    help=(
        "Dry-run a scenario through a MockSlackPoster. Verifies pre-flight, "
        "seed (best-effort), engine dispatch, and beat ordering without "
        "posting to Slack. Exit 0 on all-pass, 1 on any fail."
    ),
)
@click.option(
    "--script",
    "script_path",
    default=None,
    help="Scenario YAML (default: scenarios/install-arc-7beat.yml).",
)
@click.option(
    "--ledger-dsn",
    envvar="WORMBASE_LEDGER_DSN",
    default=None,
    help="Postgres DSN. When set, the seed phase will run; otherwise skipped.",
)
@click.option(
    "--tenant",
    default=os.environ.get("WORMBASE_TENANT_ID", "baseworm"),
    show_default=True,
    help="Tenant slug (drives company_id derivation).",
)
@click.option(
    "--reset",
    "reset",
    is_flag=True,
    default=False,
    help=(
        "Destructively wipe the tenant's ledger rows before seeding. "
        "Off by default — rehearse builds on top of existing state so "
        "dry-runs do not silently destroy 36k+ ledger rows. Pass "
        "explicitly when you want a clean rebuild between rehearsals."
    ),
)
@click.option(
    "--keep-state",
    "keep_state",
    is_flag=True,
    default=False,
    hidden=True,
    help=(
        "Deprecated alias retained for backwards compatibility. The "
        "default is now keep-state; this flag is a no-op. Use --reset "
        "to opt into the destructive path."
    ),
)
@click.option(
    "--no-history",
    is_flag=True,
    default=False,
    hidden=True,
    help=(
        "Deprecated no-op kept for backwards compatibility. History "
        "writes are now off by default — pass --include-history to "
        "opt back into the legacy direct-ledger seed path."
    ),
)
@click.option(
    "--include-history",
    "include_history",
    is_flag=True,
    default=False,
    help=(
        "Opt-in to the legacy past-week history write during seed. "
        "Off by default — the production demo path replays history via "
        "the channel-adapter wire-replay primitive (CLAUDE.md §1)."
    ),
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit the full RehearsalReport as JSON instead of a table.",
)
def cmd_rehearse(
    script_path: str | None,
    ledger_dsn: str | None,
    tenant: str,
    reset: bool,
    keep_state: bool,
    no_history: bool,
    include_history: bool,
    as_json: bool,
) -> None:
    script = (
        Path(script_path) if script_path else _scenarios_dir() / "install-arc-7beat.yml"
    )
    if not script.is_file():
        raise click.ClickException(f"scenario not found: {script}")

    # P0.4 fix: rehearse no longer resets by default. The legacy
    # --keep-state flag is kept hidden as a no-op so existing CI invocations
    # don't break; --reset is the new opt-in for the destructive path.
    _ = keep_state  # silence unused-arg lint; flag is intentionally a no-op
    _ = no_history  # deprecated no-op; --include-history is the new opt-in

    async def _go() -> RehearsalReport:
        return await run_rehearsal(
            script,
            ledger_dsn=ledger_dsn,
            tenant=tenant,
            personas_path=_personas_path(),
            fixtures_root=_fixtures_dir(),
            reset_first=reset,
            write_history=include_history,
        )

    report = asyncio.run(_go())
    if as_json:
        click.echo(json.dumps(report.to_dict(), indent=2))
    else:
        _print_rehearsal_table(report)
    sys.exit(0 if report.passed else 1)


def _print_rehearsal_table(report: RehearsalReport) -> None:
    """Compact pass/fail table for ``wormbase demo rehearse``."""
    overall = "PASS" if report.passed else "FAIL"
    click.echo(f"rehearsal: scenario={report.scenario} tenant={report.tenant}  →  {overall}")
    click.echo("-" * 72)
    width = max((len(p.name) for p in report.phases), default=10)
    for p in report.phases:
        click.echo(f"  {p.name.ljust(width)}  {p.status:<4}  {p.detail}")
    click.echo("-" * 72)
    click.echo(
        f"calls={report.total_calls}  drops={report.drops_observed}  "
        f"posts/persona={report.posts_per_persona}  "
        f"uploads/persona={report.uploads_per_persona}"
    )
    if report.ordering_violations:
        click.echo("ordering violations:")
        for v in report.ordering_violations:
            click.echo(f"  - {v}")
    if report.errors:
        click.echo("errors:")
        for e in report.errors:
            click.echo(f"  - {e}")


@demo.command(
    "wire-record",
    help=(
        "Capture wire events (channel_adapter.emit_chat_received / "
        "emit_chat_sent / emit_file_received) into a JSONL for wire-replay. "
        "Pair with `wire-replay` (channel-adapter) to reproduce a demo run."
    ),
)
@click.option(
    "--ledger-dsn",
    envvar="WORMBASE_LEDGER_DSN",
    default=_DEFAULT_LEDGER_DSN,
    show_default=True,
)
@click.option(
    "--tenant",
    envvar="WORMBASE_TENANT_ID",
    default="baseworm",
    show_default=True,
)
@click.option(
    "--out",
    "out_path",
    required=True,
    type=click.Path(dir_okay=False, writable=True),
    help="Output JSONL path.",
)
@click.option(
    "--follow",
    is_flag=True,
    default=False,
    help="Keep tailing the ledger; otherwise drain once and exit.",
)
@click.option(
    "--interval-s",
    default=1.0,
    show_default=True,
    type=float,
    help="Polling interval when --follow is set.",
)
def cmd_wire_record(
    ledger_dsn: str,
    tenant: str,
    out_path: str,
    follow: bool,
    interval_s: float,
) -> None:
    """Drain a tenant's wire events into JSONL (PRD §8.3)."""
    from wormbase_ledger import Ledger

    from wormbase_sim_harness.wire_record import WireRecorder

    out = Path(out_path)
    company_id = _company_id_from_tenant(tenant)

    async def _go() -> int:
        ledger = Ledger(ledger_dsn)
        try:
            recorder = WireRecorder(
                ledger=ledger,
                company_id=company_id,
                out_path=out,
                follow=follow,
            )
            if follow:
                await recorder.run_forever(interval_s=interval_s)
                return 0
            n = await recorder.run_once()
            click.echo(
                json.dumps(
                    {"recorded": n, "out": str(out), "tenant": tenant},
                    indent=2,
                )
            )
            return n
        finally:
            await ledger.dispose()

    asyncio.run(_go())


@demo.command(
    "acme-demo",
    help=(
        "DEMO.1 — seed the canonical Acme SaaS demo tenant by replaying "
        "tests/fixtures/acme_demo_seed/events.jsonl through the production "
        "wire-replay primitive. Per CLAUDE.md §1, this is the only "
        "deterministic backstop for demo state — no flow-bypass shortcuts."
    ),
)
@click.option(
    "--ledger-dsn",
    envvar="WORMBASE_LEDGER_DSN",
    default=_DEFAULT_LEDGER_DSN,
    show_default=True,
    help="Postgres DSN for the wormbase ledger (asyncpg URL).",
)
@click.option(
    "--tenant-slug",
    "tenant_slug",
    default=None,
    show_default=False,
    help=(
        "Override the demo tenant slug. Defaults to the canonical "
        "'acme-saas' from seed_acme.ACME_TENANT_SLUG."
    ),
)
@click.option(
    "--fixture-path",
    "fixture_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help=(
        "Override the JSONL fixture path. Defaults to "
        "tests/fixtures/acme_demo_seed/events.jsonl."
    ),
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help=(
        "Print the fixture summary (event count, tools, channels, "
        "senders) without replaying. Useful for evaluator pre-flight."
    ),
)
def cmd_acme_demo(
    ledger_dsn: str,
    tenant_slug: str | None,
    fixture_path: Path | None,
    dry_run: bool,
) -> None:
    """Seed the Acme SaaS demo tenant via wire-replay."""
    # Lazy imports keep the unrelated subcommands fast.
    from wormbase_sim_harness.seed_acme import (
        ACME_TENANT_SLUG,
        acme_seed_summary,
        default_acme_fixture_path,
    )

    slug = tenant_slug or ACME_TENANT_SLUG
    path = fixture_path or default_acme_fixture_path()

    summary = acme_seed_summary(path)
    if dry_run:
        click.echo(json.dumps(summary, indent=2, sort_keys=True))
        return

    async def _go() -> dict[str, Any]:
        from uuid import UUID as _UUID

        from wormbase_channel_adapter.wire_replay import WireReplayer
        from wormbase_ledger import Ledger as _Ledger

        from wormbase_core.service import tenant_to_uuid as _t2u

        cid: _UUID = _t2u(slug)
        ledger = _Ledger(ledger_dsn)
        try:
            replayer = WireReplayer(
                ledger=ledger, company_id=cid, jsonl_path=path,
            )
            n = await replayer.run()
        finally:
            try:
                await ledger.dispose()
            except Exception as exc:  # noqa: BLE001
                log.warning("acme-demo ledger dispose failed: %s", exc)
        return {
            "tenant_slug": slug,
            "company_id": str(cid),
            "fixture_path": str(path),
            "events_total": summary["events_total"],
            "events_replayed": n,
            "tools_count": summary["tools_count"],
            "distinct_beats": summary["distinct_beats"],
            "distinct_channels": summary["distinct_channels"],
            "distinct_senders": summary["distinct_senders"],
        }

    result = asyncio.run(_go())
    click.echo(json.dumps(result, indent=2, sort_keys=True))


@demo.command(
    "populate-cache",
    help=(
        "DEMO.1.C — pre-populate the inference-router sqlite cache with "
        "every prompt the Acme demo will issue (decision detection, "
        "topic labeling, recurring-question summarization, position "
        "inference, autoresearch experiment proposals, lesson "
        "extraction). Pair with WORMBASE_INFERENCE_CACHE_ONLY=1 to run "
        "the demo offline."
    ),
)
@click.option(
    "--cache-path",
    "cache_path",
    type=click.Path(dir_okay=False, path_type=Path),
    envvar="WORMBASE_INFERENCE_CACHE_PATH",
    default="/tmp/wormbase-inference-cache.sqlite",
    show_default=True,
    help=(
        "Path to the sqlite cache file. Matches the router's default "
        "(WORMBASE_INFERENCE_CACHE_PATH). Created if missing."
    ),
)
@click.option(
    "--no-overwrite",
    is_flag=True,
    default=False,
    help=(
        "Skip prompts that already have a cached entry. Default is "
        "overwrite-on so reseeds are deterministic."
    ),
)
def cmd_populate_cache(cache_path: Path, no_overwrite: bool) -> None:
    """Pre-populate the inference-router sqlite cache for the Acme demo."""
    # Lazy-import keeps the unrelated subcommands free of httpx /
    # inference deps when they're not needed.
    from wormbase_inference.demo_prompts import populate_acme_cache_at_path

    report = populate_acme_cache_at_path(
        cache_path, overwrite=not no_overwrite,
    )
    click.echo(
        json.dumps(
            {
                "cache_path": str(report.cache_path),
                "written": report.written,
                "skipped_existing": report.skipped_existing,
                "total_prompts": report.written + report.skipped_existing,
                "first_keys": report.keys[:3],
            },
            indent=2,
            sort_keys=True,
        )
    )


__all__ = ["main"]
