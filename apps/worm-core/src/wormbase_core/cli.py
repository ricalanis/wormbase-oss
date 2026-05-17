"""CLI entrypoint for the worm-core service."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any

import click

from wormbase_core.http_api import (
    build_app as build_http_app,
    read_api_port,
    read_api_token,
)
from wormbase_core.mcp_server import (
    build_mcp_server,
    is_mcp_enabled,
    read_mcp_port,
)
from wormbase_chat_presence import wire_chat_for_install
from wormbase_identity_tracker import wire_identity_for_install
from wormbase_process_extractor import wire_process_for_install
from wormbase_reactivities import ReactivityRegistry, ReactivityRunner
from wormbase_research_loop import wire_research_for_install
from wormbase_agent_gateway import wire_agent_gateway_for_install
from wormbase_core.agent_gateway_construction import (
    is_build_smoke_enabled as _is_agent_gateway_build_smoke_enabled,
    is_listener_enabled as _is_agent_gateway_listener_enabled,
    is_subscriptions_enabled as _is_subscriptions_enabled,
    make_clock_tick_emitter_if_configured,
    resolve_listener_transport as _resolve_agent_gateway_listener_transport,
    resolve_subscription_webhook_max_retries as _resolve_sub_webhook_max_retries,
    resolve_subscription_webhook_timeout_s as _resolve_sub_webhook_timeout_s,
    run_agent_gateway_build_smoke,
    run_agent_gateway_mcp_listener,
)
from wormbase_core.projection_runner import ProjectionRunner
from wormbase_core.setup_conversation import (
    DmAdapter as SetupDmAdapter,
    SetupConversationLoop,
)
from wormbase_core.service import (
    build_worm_core,
    chat_received_reactivity_poller,
    is_mentioned_in_conversation_enabled as _is_mention_stub_enabled,
    kpi_gap_default_channel_id as _kpi_gap_default_channel_id,
    kpi_gap_triggered_poller,
    tenant_to_uuid,
)
from wormbase_ledger import Ledger


def _disable_lurker_socket() -> bool:
    """Return True if the lurker SocketMode connection should be skipped.

    Path 3 routes inbound capture through the channel-adapter's
    OpenClaw-log tail; worm-core then polls Postgres for new
    chat_received entries. The lurker module stays in the codebase
    (other code constructs it for tests), but its SocketMode connection
    is gated off when ``WORMBASE_DISABLE_LURKER_SOCKET`` is "1" or
    "true" (case-insensitive).
    """
    return os.environ.get("WORMBASE_DISABLE_LURKER_SOCKET", "").strip().lower() in (
        "1",
        "true",
    )

logger = logging.getLogger("wormbase_core.cli")


from wormbase_core.webhook_secret_resolver import (
    get_lazy_webhook_resolver,
    get_or_create_lazy_webhook_resolver as _get_or_create_lazy_webhook_resolver,
)


def _compose_subscription_dispatcher_deps_if_enabled(
    *,
    ledger: object,
    company_id: object,
) -> object | None:
    """v2.A Batch B Task 5 — compose SubscriptionDispatcherDeps when enabled.

    Returns the deps bundle when ``WORMBASE_SUBSCRIPTIONS_ENABLED=true``,
    otherwise ``None``. The returned value is threaded into
    ``wire_agent_gateway_for_install`` and surfaces in the boot log
    enumeration ("6th agent-gateway Reactivity").

    v1.4 #3: the webhook secret resolver is now the
    :class:`LazyWebhookSecretResolver` singleton. The dispatcher is
    composed at boot (before the broker exists); the agent-gateway
    build smoke binds the resolved broker into this resolver later.
    Webhook deliveries that fire before the broker is bound and that
    use ``vault://`` refs fail with a clear error; ``env://`` refs
    work immediately because they don't need a broker.
    """
    if not _is_subscriptions_enabled():
        return None
    # Lazy import to keep the import surface light when subscriptions
    # are disabled (the common case for pre-v2.A deploys).
    from wormbase_agent_gateway.subscriptions import (
        StreamRegistry,
        SubscriptionDispatcherDeps,
        WebhookTransport,
    )
    from wormbase_core.agent_gateway_readers import (
        LedgerSubscriptionReader,
    )

    resolver = _get_or_create_lazy_webhook_resolver()
    return SubscriptionDispatcherDeps(
        subscription_reader=LedgerSubscriptionReader(ledger=ledger),
        webhook_transport=WebhookTransport(
            secret_resolver=resolver,
            max_retries=_resolve_sub_webhook_max_retries(),
            request_timeout_s=float(_resolve_sub_webhook_timeout_s()),
        ),
        stream_registry=StreamRegistry(),
        ledger=ledger,
    )


@click.group()
def main() -> None:
    """WormBase worm-core CLI."""
    logging.basicConfig(
        level=os.environ.get("WORM_CORE_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


@main.command()
@click.option("--dsn", envvar="WORMBASE_LEDGER_DSN",
              default="postgresql+asyncpg://wormbase:wormbase@postgres:5432/wormbase")
@click.option("--tenant", envvar="WORMBASE_TENANT_ID", default="baseworm")
@click.option("--domain-pack", default="saas",
              type=click.Choice(["saas", "marketplace", "fintech"]))
@click.option("--no-lurker", is_flag=True, default=False,
              help="Skip starting the Slack lurker.")
def run(dsn: str, tenant: str, domain_pack: str, no_lurker: bool) -> None:
    """Run the worm-core service: lurker + heartbeat."""
    asyncio.run(_run_async(dsn, tenant, domain_pack, not no_lurker))


async def _run_async(dsn: str, tenant: str, pack: str, with_lurker: bool) -> None:
    company_id = tenant_to_uuid(tenant)
    logger.info("worm-core starting tenant=%s company_id=%s", tenant, company_id)
    ledger = Ledger(dsn)

    # Item #8 (2026-05-13 final wave) — pgvector >=0.6 boot-time pre-flight.
    # Runs BEFORE projection migrations because v019 (HNSW index) requires
    # pgvector's ``vector_cosine_ops`` operator class. Without this check,
    # operators see an opaque asyncpg ``UndefinedObject`` at migration
    # apply-time; with it, they see a clear "install pgvector / upgrade
    # to >=0.6 / bypass via env knob" message. Skipped on SQLite (the
    # InMemoryLedger path uses JSON column fallback) and on Postgres when
    # both ``WORMBASE_GATHER_VIA_PROJECTION`` and ``WORMBASE_EMBEDDING_ENABLED``
    # are unset (no pgvector code path is engaged).
    from wormbase_core.preflight import (
        PgVectorPreflightError,
        check_pgvector,
    )

    try:
        await check_pgvector(ledger)
    except PgVectorPreflightError as exc:
        logger.error("%s", exc)
        await ledger.dispose()
        sys.exit(exc.exit_code)

    # Boot-time schema migrations (W1.A1). Tenant-agnostic — the
    # projection schema is shared across tenants, so this runs once
    # per worm-core boot, before any read or write touches the
    # projection_* tables. Closes the schema-drift gap that
    # previously required ``docker volume rm wormbase-postgres-data``
    # to recover from a missing column.
    #
    # ``migrate`` is the source of truth for the projection surface;
    # the ``metadata.create_all`` fallback below is retained only as
    # a belt-and-braces guard against a future migration list that
    # forgot to register a newly-added table. Both paths are
    # idempotent so they coexist safely.
    try:
        from wormbase_ledger.projections.migrate import migrate as run_migrations
        from wormbase_ledger.projections.migrations import (
            MIGRATIONS as LEDGER_MIGRATIONS,
        )
        # W5.A1 — merge in the reactivities migrations so the
        # reactivity_state / reactivity_budget / reactivity_fires tables
        # exist before the runner first writes. The reactivities migrations
        # are numbered 1001+ to live above the ledger's projection
        # migrations (v001/v002 today) without colliding.
        from wormbase_reactivities.migrations import (
            MIGRATIONS as REACTIVITIES_MIGRATIONS,
        )
        merged_migrations = list(LEDGER_MIGRATIONS) + list(REACTIVITIES_MIGRATIONS)
        applied = await run_migrations(ledger, migrations=merged_migrations)
        if applied:
            logger.info(
                "projection schema migrations applied: versions=%s", applied,
            )
        else:
            logger.info("projection schema up-to-date")
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "projection schema migrations FAILED: %s — refusing to start",
            exc,
        )
        await ledger.dispose()
        raise

    try:
        from wormbase_ledger.schema import metadata as ledger_metadata
        async with ledger.engine.begin() as conn:
            await conn.run_sync(ledger_metadata.create_all)
        logger.info("ledger schema ready")
    except Exception as exc:  # noqa: BLE001
        logger.warning("ledger schema create skipped: %s", exc)

    worm = await build_worm_core(
        ledger, company_id,
        domain_pack=pack, enable_lurker=with_lurker,
    )
    logger.info(
        "worm-core warmed: domain_pack=%s lurker=%s",
        worm.domain_pack, with_lurker,
    )

    tasks: list[asyncio.Task] = []
    disable_socket = _disable_lurker_socket()
    if with_lurker and worm.lurker is not None and not disable_socket:
        tasks.append(asyncio.create_task(worm.lurker.start()))
    elif with_lurker and worm.lurker is not None and disable_socket:
        logger.info(
            "lurker socket disabled via WORMBASE_DISABLE_LURKER_SOCKET; "
            "relying on channel-adapter log-tail capture path"
        )
    # Always run the chat_received reactivity poller — it's how the
    # triad sees inbound chat regardless of capture path. We pass a
    # flow_dispatcher so file_drop events route to DropAndProfileFlow
    # (and other source-building flows) the same way the lurker did.
    #
    # Wave B (chat-worm extraction) — 2026-05-03: dispatcher construction
    # moved to ``wire_chat_for_install`` (chat-presence package). The poller
    # task is appended AFTER the registry + slack adapter are wired so the
    # bundle's dispatcher can be threaded into ``flow_dispatcher`` kwarg.
    # The MedallionCascade is left out of the chat dispatcher in spike
    # posture per chat-worm extraction plan §G2 (cascade-on-drop will be
    # restored in Wave-D follow-up via lake-maintainer + reactivity wiring).
    if isinstance(ledger, Ledger):
        # P1.1 — projection-builder runner. Polls the ledger for new
        # entries and materialises the in-memory ``Projections`` fold
        # into the SQL ``projection_*`` tables. Without this loop the
        # projection_* tables stay empty and the dashboard compensates
        # with a TS-side fold-at-request — slow + not architecture-correct.
        projection_runner = ProjectionRunner(ledger, worm.company_id)
        tasks.append(asyncio.create_task(projection_runner.run_forever()))

        # A4 — auto-discovery worker. Watches the ledger for unknown
        # (platform, platform_user_id) tuples in chat / file events
        # and proposes a Person via the same write_actions.propose_person
        # path the dashboard's Person API uses.
        #
        # Lookup strategy (B6 update):
        #   1. Try SlackChannelAdapter.users_info — production path,
        #      works whether or not the lurker socket is connected.
        #      This is the FIX for the lookup-degrades-without-lurker
        #      issue noted in A4.
        #   2. Fall back to worm.lurker._app.client.users_info — the
        #      pre-B6 path, used when no bot token is configured for
        #      the channel-adapter side (e.g. local dev without
        #      OpenClaw).
        #
        # When neither path is reachable, the lookup returns None and
        # the discovery loop simply retries on the next cycle.
        slack_adapter_handle = None
        _slack_adapter: Any = None
        try:
            from wormbase_channel_adapters import (
                SecretBundle as _SecretBundle,
                default_registry as _ca_default_registry,
            )
            slack_bot_token = (
                os.environ.get("SLACK_BOT_TOKEN_OBSERVER_BASEWORM")
                or os.environ.get("SLACK_BOT_TOKEN_BASEWORM")
            )
            adapter_cls = _ca_default_registry().get("slack")
            if slack_bot_token and adapter_cls is not None:
                _slack_adapter = adapter_cls()
                slack_adapter_handle = await _slack_adapter.authenticate(
                    _SecretBundle(payload={"bot_token": slack_bot_token}),
                )
                logger.info(
                    "SlackChannelAdapter wired for identity-discovery "
                    "(works without lurker socket)",
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "SlackChannelAdapter init for identity-discovery failed: %s",
                exc,
            )
            _slack_adapter = None
            slack_adapter_handle = None

        async def _slack_member_lookup(
            platform: str, platform_user_id: str,
        ) -> dict | None:
            """Fetch Slack workspace member metadata.

            B6 update: prefer ``SlackChannelAdapter.users_info`` so the
            lookup works even when ``WORMBASE_DISABLE_LURKER_SOCKET=1``
            (Path 3 / log-tail mode). Falls back to the lurker's
            ``AsyncApp.client.users_info`` when no adapter handle is
            available (no bot token at startup).
            """
            if platform != "slack":
                return None

            # Path 1: SlackChannelAdapter — preferred.
            if slack_adapter_handle is not None:
                try:
                    member = await _slack_adapter.users_info(
                        slack_adapter_handle, platform_user_id,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "SlackChannelAdapter users.info failed for %s: %s",
                        platform_user_id, exc,
                    )
                    member = None
                if member is not None:
                    return {
                        "name": member.display_name,
                        "email": member.email,
                        "avatar_url": member.avatar_url,
                    }

            # Path 2: lurker fallback — for environments without a
            # bot token configured at the channel-adapter side.
            if worm.lurker is None:
                return None
            app = getattr(worm.lurker, "_app", None)
            if app is None:
                return None
            client = getattr(app, "client", None)
            if client is None:
                return None
            try:
                resp = await client.users_info(user=platform_user_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "slack member lookup (lurker path) failed for %s: %s",
                    platform_user_id, exc,
                )
                return None
            if not resp.get("ok"):
                return None
            info = resp.get("user", {}) or {}
            profile = info.get("profile", {}) or {}
            return {
                "name": (
                    info.get("real_name")
                    or info.get("name")
                    or "Unknown"
                ),
                "email": profile.get("email"),
                "avatar_url": profile.get("image_192"),
            }

        # W5.A1 — identity reactivities are wired by the
        # wormbase-identity-tracker package's lifecycle factory.
        # ``wire_identity_for_install`` registers the (one, in v1)
        # identity Reactivity into the registry and returns the
        # ``IdentityResolver`` Protocol implementation that downstream
        # consumers (StatementToOwnerReactivity here, then chat-worm /
        # process-worm / research-worm in subsequent waves) take via DI.
        # The legacy IdentityDiscoveryLoop is no longer wired here — its
        # class is preserved in ``identity_discovery.py`` (Block H shim)
        # for the existing test suite, but only the Reactivity facade
        # runs in production.
        #
        # CRITICAL: do NOT also start IdentityDiscoveryLoop here — both
        # paths write the same emit_person_proposed entries and would
        # duplicate proposals on every chat event.
        reactivity_registry = ReactivityRegistry(
            ledger=ledger,
            company_id=worm.company_id,
        )
        # > AUTHORED 2026-05-03 (Wave A — identity-worm extraction):
        # > wire_identity_for_install replaces the direct-register pattern.
        # > The returned identity_resolver is threaded into downstream
        # > StatementToOwnerReactivity below via DI (kwarg ``identity=``).
        # >
        # > UPDATED 2026-05-04 (O-A2): the `Install` dataclass owned by
        # > chat-presence (the canonical install-consumer) replaces the
        # > former SimpleNamespace duck-typing. Same `.id` / `.platform`
        # > fields lifecycle factories read; just typed.
        from wormbase_chat_presence import Install
        _identity_install = Install(
            id=worm.company_id, platform="slack",
        )
        identity_resolver = await wire_identity_for_install(
            install=_identity_install,
            member_lookup=_slack_member_lookup,
            reactivity_registry=reactivity_registry,
            ledger=ledger,
            company_id=worm.company_id,
        )

        # > AUTHORED 2026-05-03 (Wave B — chat-worm extraction, Block G2):
        # > wire_chat_for_install registers the four chat Reactivities
        # > (chat_received, mention_response, interjection_budget,
        # > source_mentioned) and returns the ChatBundle whose dispatcher
        # > is threaded into chat_received_reactivity_poller below.
        # > ChatReply.speak uses the same Slack adapter handle the
        # > identity-discovery wiring authenticates above.
        # >
        # > UPDATED 2026-05-04 (O-B1, deferred-backlog Block D): the
        # > MedallionCascade is now wired into the chat dispatcher via the
        # > ``cascade`` kwarg — cascade_after_propose runs immediately after
        # > a successful drop_and_profile.on_file_drop, restoring the
        # > bronze/silver/gold chain that regressed when chat-worm was
        # > extracted from make_flow_dispatcher_with_proactivity.
        from wormbase_core.flows import cascade_after_propose
        from wormbase_core.medallion import MedallionCascade

        _medallion_cascade = MedallionCascade(ledger)

        async def _chat_cascade_adapter(infra, correlation_id):
            payload = infra.payload or {}
            uri = (
                payload.get("bytes_url")
                or payload.get("url")
                or f"file://{payload.get('filename', 'unknown')}"
            )
            mime = payload.get("mimetype") or None
            await cascade_after_propose(
                worm.drop_and_profile.builder,
                _medallion_cascade,
                correlation_id=str(correlation_id),
                company_id=worm.company_id,
                uri=uri,
                mime=mime,
            )

        _chat_install = Install(
            id=worm.company_id, platform="slack",
        )
        chat_bundle = await wire_chat_for_install(
            install=_chat_install,
            ledger=ledger,
            reactivity_registry=reactivity_registry,
            drop_and_profile=worm.drop_and_profile,
            credential_in_dm=worm.credential_in_dm,
            mentioned_in_conversation=worm.mentioned_in_conversation,
            channel_adapter=_slack_adapter,
            channel_adapter_handle=slack_adapter_handle,
            cascade=_chat_cascade_adapter,
        )
        tasks.append(
            asyncio.create_task(
                chat_received_reactivity_poller(
                    ledger, worm.pipeline, worm.company_id,
                    flow_dispatcher=chat_bundle.dispatcher,
                )
            )
        )

        # > AUTHORED 2026-05-30 (Sub-wave A F3 — kpi_gap_triggered
        # > dispatcher hook). KpiGapTriggeredFlow was factory-only until
        # > this wave; the poller below watches for
        # > emit_semantic_gap_proposed ledger entries (canonical
        # > agent-reported "no metric for this question" signal) and
        # > dispatches each one through propose_for_gap. Producers are
        # > the agent-gateway MCP tools, so a worm-core boot without
        # > agent-gateway never sees rows and the poller is a no-op.
        # > Idempotent + tenant-reset aware. Mirrors the chat_received
        # > poller's operational shape.
        _kpi_gap_default = _kpi_gap_default_channel_id()
        if _kpi_gap_default is not None:
            logger.info(
                "Onboarding Sub-wave C: kpi_gap_triggered_poller seeded with "
                "default_channel_id=%r from WORMBASE_KPI_GAP_DEFAULT_CHANNEL",
                _kpi_gap_default,
            )
        tasks.append(
            asyncio.create_task(
                kpi_gap_triggered_poller(
                    ledger, worm.kpi_gap_triggered, worm.company_id,
                    default_channel_id=_kpi_gap_default,
                )
            )
        )
        # F3 stub-predicate operator log: lets a deploy verify the
        # WORMBASE_MENTIONED_IN_CONVERSATION_ENABLED knob is read at
        # boot. Default off — no log when unset.
        if _is_mention_stub_enabled():
            logger.info(
                "F3 mentioned_in_conversation stub-predicate enabled "
                "(WORMBASE_MENTIONED_IN_CONVERSATION_ENABLED=true) — "
                "legacy make_flow_dispatcher routes `data:`-prefixed "
                "events to MentionedInConversationFlow.on_proactive_mention.",
            )

        # W5.A3 — phenomenon-gap detectors. Four reactivities that close
        # the conversation-to-substrate loop: when a chat statement
        # references a KPI / Domain / Process / Reactivity that does not
        # yet exist, the matching detector proposes it for admin
        # confirmation. Load-bearing for "the worm builds the rules it
        # runs on". Each detector is independent — enabling/disabling one
        # does not affect the others.
        from wormbase_reactivities.phenomenon_gaps import (
            DomainReferenceWithoutDomainReactivity,
            KpiReferenceWithoutKpiReactivity,
            ProcessReferenceWithoutProcessReactivity,
            RecurringActionWithoutReactivityReactivity,
        )
        reactivity_registry.register(KpiReferenceWithoutKpiReactivity())
        reactivity_registry.register(DomainReferenceWithoutDomainReactivity())
        reactivity_registry.register(ProcessReferenceWithoutProcessReactivity())
        reactivity_registry.register(RecurringActionWithoutReactivityReactivity())

        # > AUTHORED 2026-05-03 (Wave C₂ — process-worm extraction, Block G2):
        # > wire_process_for_install replaces the legacy polling task that
        # > previously drove process retrieval on a 5s/60s timer. The four
        # > process Reactivities (topic_synthesis,
        # > recurring_question_process_mapper, decision_record,
        # > system_map_node) take over the chat → decision_recorded /
        # > process_map_proposed / system_map_node / recurring_question
        # > sequence on a ledger-driven trigger. Called once per process
        # > boot; idempotent on re-registration.
        process_ids = wire_process_for_install(
            registry=reactivity_registry,
        )
        logger.info(
            "wire_process_for_install wired: %d process Reactivities "
            "registered (%s)",
            len(process_ids),
            ", ".join(process_ids),
        )

        # W5.A2 — StatementToOwnerReactivity. When a chat statement
        # references a resource (KPI / source / domain / process) with a
        # known owner, DM the owner with the statement plus pinned
        # resources. The resource_aggregator + topic_extractor +
        # owner_lookup helpers are dependency-injected so the same code
        # works in production (real ledger, real Slack DMs) and tests
        # (in-memory ledger, no wire). The DM sender is wired below
        # only when a Slack adapter is authenticated; otherwise the
        # reactivity still records the ledger entry but skips the wire
        # (the dashboard surfaces the entry with an "unsent" badge).
        from wormbase_reactivities.statement_to_owner import (
            StatementToOwnerReactivity,
        )
        from wormbase_identity_tracker.owner_lookup import lookup_owner
        from wormbase_core.resource_aggregator import (
            gather_related_resources,
        )
        from wormbase_core.topic_extractor import extract_topic
        statement_to_owner_dm_sender = None
        if slack_adapter_handle is not None and _slack_adapter is not None:
            # Thin DMSender shim around SlackChannelAdapter. Open DMs
            # via conversations.open; send via SlackChannelAdapter.send.
            statement_to_owner_dm_sender = _SlackDMSender(
                _slack_adapter, slack_adapter_handle,
            )
        reactivity_registry.register(StatementToOwnerReactivity(
            topic_extractor=extract_topic,
            owner_lookup=lookup_owner,
            resource_aggregator=gather_related_resources,
            dm_sender=statement_to_owner_dm_sender,
            # Wave A wiring (2026-05-03): identity resolver threaded in
            # for forward-compat. Wave B (chat-worm) switches consumer
            # body to call self.identity.lookup_owner(topic) instead of
            # the existing owner_lookup DI callable; for v1 the resolver
            # is accepted but unused.
            identity=identity_resolver,
        ))

        # > AUTHORED 2026-05-03 (Wave C₁ — research-worm extraction, Block G2):
        # > wire_research_for_install replaces the three timer-driven runners
        # > (autoresearch_loop_runner per-Person, team_loop_runner per
        # > Team-Domain, company_loop_runner per company) with a single
        # > registration call against the W5a registry. The four research
        # > Reactivities (ExperimentTrigger / ExperimentResolve /
        # > LessonExtraction / KeepRatePublish) take over the propose →
        # > run → resolve → publish_keep_notebook sequence on a ledger-driven
        # > trigger. The ReactivityRunner (started below) is now the sole
        # > orchestrator; conflict arbitration (Company > Team > Person)
        # > moved inside ExperimentTriggerReactivity._resolve_scope.
        _research_install = Install(
            id=worm.company_id, platform="slack",
        )
        await wire_research_for_install(
            install=_research_install,
            ledger=ledger,
            reactivity_registry=reactivity_registry,
        )
        logger.info(
            "wire_research_for_install wired: company_id=%s "
            "(4 research Reactivities registered)",
            worm.company_id,
        )

        # > REFACTORED 2026-05-11 (Wave 1 cleanup 1a — catalog-mirror per-source):
        # > catalog-mirror no longer wires at boot. Per-source registration
        # > happens via ``wire_catalog_for_source`` inside
        # > ``source_builder.SourceBuilder.on_source_connected`` when a
        # > source carries a ``catalog_source`` attribute (i.e. an
        # > upstream_mirror Source). This matches lake-maintainer's
        # > canonical ``wire_maintenance_for_source`` pattern and catches
        # > mid-session source connections that a boot-scope wire would
        # > miss.
        #
        # > AUTHORED 2026-05-11 (Wave 2 Task 8 — agent-gateway 5th wire):
        # > ``wire_agent_gateway_for_install`` registers the
        # > OutcomeToTemplatePromotion W5a Reactivity. It watches
        # > ``query_outcome_recorded`` propose entries written by the
        # > §4.5 compounding-loop MCP tools (lake.query.record_outcome)
        # > and promotes high-quality clusters to
        # > ``query_template_promoted`` durable templates. After this
        # > wire lands the install-scope boot path has 5 wires:
        # > identity, chat, process, research, agent-gateway.
        _agent_gateway_install = Install(
            id=worm.company_id, platform="slack",
        )
        # > AUTHORED 2026-05-12 (v2.A Batch B Task 5 — opt-in subscription
        # > dispatcher). When ``WORMBASE_SUBSCRIPTIONS_ENABLED=true`` is
        # > set, construct the SubscriptionDispatcherDeps here and pass it
        # > into ``wire_agent_gateway_for_install`` so the dispatcher
        # > becomes the 6th agent-gateway Reactivity. The dispatcher's
        # > webhook secret resolver routes through the same broker used
        # > for the broker_executor — no raw secrets on the ledger.
        # > Default off → wire registers 5 reactivities (byte-identical).
        _subscription_dispatcher_deps = (
            _compose_subscription_dispatcher_deps_if_enabled(
                ledger=ledger, company_id=worm.company_id,
            )
        )
        # > AUTHORED 2026-05-12 (v2.B Phase 3c — projection-promoted
        # > gather for axes 1+3). When
        # > ``WORMBASE_GATHER_VIA_PROJECTION=true`` is set AND the
        # > ledger has a SQL engine, construct a dialect-appropriate
        # > QueryOutcomeProjectionReader and thread it through so
        # > axes 1 (template promotion) + 3 (bad-pattern) swap their
        # > 30d / 14d ledger-scan gather for a TopK projection-table
        # > SELECT. InMemoryLedger / no-engine paths keep the
        # > ledger-scan gather (reader is None).
        from wormbase_core.agent_gateway_construction import (
            build_projection_reader_from_ledger as _build_projection_reader,
        )
        from wormbase_core.agent_gateway_construction import (
            is_gather_via_projection_enabled as _is_proj_gather_enabled,
        )
        _projection_reader: Any | None = None
        if _is_proj_gather_enabled():
            _projection_reader = _build_projection_reader(ledger)
        agent_gateway_reactivities = await wire_agent_gateway_for_install(
            install=_agent_gateway_install,
            ledger=ledger,
            reactivity_registry=reactivity_registry,
            subscription_dispatcher_deps=_subscription_dispatcher_deps,
            projection_reader=_projection_reader,
        )
        logger.info(
            "wire_agent_gateway_for_install wired: %d agent-gateway "
            "Reactivities registered (%s)",
            len(agent_gateway_reactivities),
            ", ".join(r.id for r in agent_gateway_reactivities),
        )
        if _subscription_dispatcher_deps is not None:
            logger.info(
                "v2.A subscription dispatcher enabled "
                "(WORMBASE_SUBSCRIPTIONS_ENABLED=true) — 6th agent-gateway "
                "Reactivity registered",
            )
        if _projection_reader is not None:
            logger.info(
                "v2.B Phase 3c projection-promoted gather enabled "
                "(WORMBASE_GATHER_VIA_PROJECTION=true) — axes 1+3 read "
                "from projection_query_outcomes (%s)",
                type(_projection_reader).__name__,
            )

        # > AUTHORED 2026-05-29 (L3 Sub-wave C — lake-side lineage-discovery).
        # > Compose + register the L3 lineage-discovery Compounding
        # > Reactivity AFTER ``wire_agent_gateway_for_install`` so the
        # > reactivity count is byte-identical when L3 is disabled
        # > (default off). When ``WORMBASE_LINEAGE_DISCOVERY_ENABLED=true``,
        # > this adds one more Reactivity to the registry — yielding
        # > 6 default or 7 if subscriptions are also enabled.
        from wormbase_core.agent_gateway_construction import (
            compose_lineage_reactivity_if_enabled as _compose_lineage,
        )
        _lineage_reactivity = _compose_lineage(
            ledger=ledger, company_id=worm.company_id,
        )
        if _lineage_reactivity is not None:
            reactivity_registry.register(_lineage_reactivity)
            logger.info(
                "L3 lineage-discovery enabled "
                "(WORMBASE_LINEAGE_DISCOVERY_ENABLED=true) — +1 "
                "agent-gateway Reactivity registered (%s)",
                _lineage_reactivity.id,
            )

        # > AUTHORED 2026-05-30 (L7 Sub-wave C — lake-side quality-discovery).
        # > Compose + register the L7 quality-discovery Compounding
        # > Reactivity AFTER ``wire_agent_gateway_for_install`` AND
        # > AFTER L3 so the reactivity count is byte-identical when L7
        # > is disabled (default off) and telemetry counters indexing
        # > by Reactivity position stay stable across L3+L7 enable
        # > permutations. When ``WORMBASE_QUALITY_DISCOVERY_ENABLED=true``,
        # > this adds one more Reactivity to the registry — yielding
        # > 7 default + L3 = 8 when both axes are enabled, or 9 if
        # > subscriptions are also enabled.
        from wormbase_core.agent_gateway_construction import (
            compose_quality_reactivity_if_enabled as _compose_quality,
        )
        _quality_reactivity = _compose_quality(
            ledger=ledger, company_id=worm.company_id,
        )
        if _quality_reactivity is not None:
            reactivity_registry.register(_quality_reactivity)
            logger.info(
                "L7 quality-discovery enabled "
                "(WORMBASE_QUALITY_DISCOVERY_ENABLED=true) — +1 "
                "agent-gateway Reactivity registered (%s)",
                _quality_reactivity.id,
            )

        # > AUTHORED 2026-06-02 (L4 Sub-wave C — lake-side schema-impact-discovery).
        # > Compose + register the L4 schema-impact-discovery Compounding
        # > Reactivity AFTER ``wire_agent_gateway_for_install`` AND
        # > AFTER L3 AND AFTER L7 (per Sub-wave B handoff concern) so the
        # > reactivity count is byte-identical when L4 is disabled
        # > (default off) and telemetry counters indexing by Reactivity
        # > position stay stable across L3+L7+L4 enable permutations.
        # >
        # > L4 is the **first lake-side axis to consume another axis's
        # > output** — its strategies cross-axis-read L3's confirmed
        # > lineage edges via the new
        # > :class:`LedgerLineageEdgeReader` (shared single instance
        # > across LineageEdgeImpactStrategy + TypeCoercionImpactStrategy
        # > per concern #5).
        # >
        # > When ``WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED=true``, this
        # > adds one more Reactivity to the registry — yielding 5
        # > default + L3 + L7 + L4 = 8 when all axes are enabled, or 9
        # > if subscriptions are also enabled.
        from wormbase_core.agent_gateway_construction import (
            compose_schema_impact_reactivity_if_enabled as _compose_schema_impact,
        )
        _schema_impact_reactivity = _compose_schema_impact(
            ledger=ledger, company_id=worm.company_id,
        )
        if _schema_impact_reactivity is not None:
            reactivity_registry.register(_schema_impact_reactivity)
            logger.info(
                "L4 schema-impact discovery enabled "
                "(WORMBASE_SCHEMA_IMPACT_DISCOVERY_ENABLED=true) — +1 "
                "agent-gateway Reactivity registered (%s)",
                _schema_impact_reactivity.id,
            )

        # > AUTHORED 2026-06-05 (L5 Sub-wave C — lake-side fingerprint-discovery).
        # > Compose + register the L5 fingerprint-discovery Compounding
        # > Reactivity AFTER ``wire_agent_gateway_for_install`` AND
        # > AFTER L3 + L7 + L4 (per Sub-wave B handoff concern #5) so the
        # > reactivity count is byte-identical when L5 is disabled
        # > (default off) and telemetry counters indexing by Reactivity
        # > position stay stable across L3+L7+L4+L5 enable permutations.
        # >
        # > L5 is the **first lake-side axis to use
        # > :class:`LakeLoopComposite` from day one** — the composite
        # > is built via :func:`make_composite_semantic_type_service`
        # > (~15 LOC factory instead of a ~250 LOC custom composite
        # > class). No new reader Protocols; reuses L3's
        # > :class:`NoopSampler` and L7's
        # > :class:`NoopHistoricalStatsReader` for the two empty-
        # > upstream strategies.
        # >
        # > When ``WORMBASE_FINGERPRINT_DISCOVERY_ENABLED=true``, this
        # > adds one more Reactivity to the registry — yielding 5
        # > default + L3 + L7 + L4 + L5 = 9 when all axes are enabled,
        # > or 10 if subscriptions are also enabled.
        from wormbase_core.agent_gateway_construction import (
            compose_fingerprint_reactivity_if_enabled as _compose_fingerprint,
        )
        _fingerprint_reactivity = _compose_fingerprint(
            ledger=ledger, company_id=worm.company_id,
        )
        if _fingerprint_reactivity is not None:
            reactivity_registry.register(_fingerprint_reactivity)
            logger.info(
                "L5 fingerprint discovery enabled "
                "(WORMBASE_FINGERPRINT_DISCOVERY_ENABLED=true) — +1 "
                "agent-gateway Reactivity registered (%s)",
                _fingerprint_reactivity.id,
            )

        # > AUTHORED 2026-06-06 (L6 Sub-wave C — lake-side column-classification
        # > discovery).
        # > Compose + register the L6 column-classification-discovery
        # > Compounding Reactivity AFTER ``wire_agent_gateway_for_install``
        # > AND AFTER L3 + L7 + L4 + L5 so the reactivity count is
        # > byte-identical when L6 is disabled (default off) and
        # > telemetry counters indexing by Reactivity position stay
        # > stable across L3+L7+L4+L5+L6 enable permutations.
        # >
        # > L6 is the **second cross-axis chain** in the lake stack
        # > (after L4→L3). Its
        # > :class:`SemanticTypeClassificationStrategy` reads L5's
        # > confirmed semantic types via the new
        # > :class:`LedgerConfirmedSemanticTypeReader` (2nd cross-axis
        # > impl — mirrors L4's :class:`LedgerLineageEdgeReader`).
        # > L6 is also the **second lake-side axis built on
        # > :class:`LakeLoopComposite[T]` from day one** (after L5's
        # > case 12).
        # >
        # > When ``WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED=true``,
        # > this adds one more Reactivity to the registry — yielding
        # > 5 default + L3 + L7 + L4 + L5 + L6 = 10 when all axes are
        # > enabled, or 11 if subscriptions are also enabled.
        from wormbase_core.agent_gateway_construction import (
            compose_column_classification_reactivity_if_enabled
            as _compose_column_classification,
        )
        _column_classification_reactivity = _compose_column_classification(
            ledger=ledger,
        )
        if _column_classification_reactivity is not None:
            reactivity_registry.register(
                _column_classification_reactivity,
            )
            logger.info(
                "L6 column-classification discovery enabled "
                "(WORMBASE_COLUMN_CLASSIFICATION_DISCOVERY_ENABLED=true) — +1 "
                "agent-gateway Reactivity registered (%s)",
                _column_classification_reactivity.id,
            )

        # > AUTHORED 2026-06-07 (L8 Sub-wave C — lake-side cross-source
        # > entity stitching).
        # > Compose + register the L8 entity-stitch-discovery
        # > Compounding Reactivity AFTER ``wire_agent_gateway_for_install``
        # > AND AFTER L3 + L7 + L4 + L5 + L6 so the reactivity count is
        # > byte-identical when L8 is disabled (default off) and
        # > telemetry counters indexing by Reactivity position stay
        # > stable across L3+L7+L4+L5+L6+L8 enable permutations.
        # >
        # > L8 is the **third cross-axis chain** in the lake stack
        # > (after L4→L3 and L6→L5). Its
        # > :class:`NameMatchEntityStrategy` reuses L6's
        # > :class:`LedgerConfirmedSemanticTypeReader` **verbatim** —
        # > no new cross-axis adapter; second consumer of L6's
        # > Protocol after L6's own SemanticType strategy.
        # > L8 is also the **third lake-side axis built on
        # > :class:`LakeLoopComposite[T]` from day one** (after L5's
        # > case 12 and L6's case 13).
        # >
        # > When ``WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED=true``,
        # > this adds one more Reactivity to the registry — yielding
        # > 5 default + L3 + L7 + L4 + L5 + L6 + L8 = 11 when all axes
        # > are enabled, or 12 if subscriptions are also enabled.
        from wormbase_core.agent_gateway_construction import (
            compose_entity_stitch_reactivity_if_enabled
            as _compose_entity_stitch,
        )
        _entity_stitch_reactivity = _compose_entity_stitch(
            ledger=ledger, company_id=worm.company_id,
        )
        if _entity_stitch_reactivity is not None:
            reactivity_registry.register(_entity_stitch_reactivity)
            logger.info(
                "L8 entity-stitch discovery enabled "
                "(WORMBASE_ENTITY_STITCH_DISCOVERY_ENABLED=true) — +1 "
                "agent-gateway Reactivity registered (%s)",
                _entity_stitch_reactivity.id,
            )

        # > AUTHORED 2026-06-08 (L1 Sub-wave C — lake-side source-candidate
        # > triage).
        # > Compose + register the L1 source-candidate-discovery
        # > Compounding Reactivity AFTER ``wire_agent_gateway_for_install``
        # > AND AFTER L3 + L7 + L4 + L5 + L6 + L8 so the reactivity
        # > count is byte-identical when L1 is disabled (default off)
        # > and telemetry counters indexing by Reactivity position stay
        # > stable across L3+L7+L4+L5+L6+L8+L1 enable permutations.
        # >
        # > L1 introduces ZERO new cross-axis chains (cross-axis chain
        # > count stays at 3 — L4→L3, L6→L5, L8→L5). Its three
        # > lightweight Reader impls
        # > (:class:`LedgerConnectedSourceReader`,
        # > :class:`LedgerKpiNodeReader`,
        # > :class:`LedgerSilverConversationReader`) read first-class
        # > platform projections (sources, KPI tree, silver
        # > conversations), not peer L-axis projections — per spec §4.6
        # > doctrine clarification.
        # >
        # > L1 is the **fourth lake-side axis built on
        # > :class:`LakeLoopComposite[T]` from day one** (after L5
        # > case 12, L6 case 13, L8 case 14).
        # >
        # > L1 uses a **Periodic source predicate** (diverges from
        # > L3/L7/L4/L5/L6/L8 which key on external_catalog_imported /
        # > source_connected). The strategies all scan platform
        # > projections rather than react to a specific entry kind, so
        # > a periodic cadence decouples discovery from upstream
        # > traffic.
        # >
        # > When ``WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED=true``,
        # > this adds one more Reactivity to the registry — yielding
        # > 5 default + L3 + L7 + L4 + L5 + L6 + L8 + L1 = 12 when all
        # > axes are enabled, or 13 if subscriptions are also enabled.
        from wormbase_core.agent_gateway_construction import (
            compose_source_candidate_reactivity_if_enabled
            as _compose_source_candidate,
        )
        _source_candidate_reactivity = _compose_source_candidate(
            ledger=ledger,
        )
        if _source_candidate_reactivity is not None:
            reactivity_registry.register(_source_candidate_reactivity)
            logger.info(
                "L1 source-candidate discovery enabled "
                "(WORMBASE_SOURCE_CANDIDATE_DISCOVERY_ENABLED=true) — +1 "
                "agent-gateway Reactivity registered (%s)",
                _source_candidate_reactivity.id,
            )

        # > AUTHORED 2026-06-09 (L2 Sub-wave C — lake-side catalog-drift
        # > detection).
        # > Compose + register the L2 catalog-drift-discovery
        # > Compounding Reactivity AFTER ``wire_agent_gateway_for_install``
        # > AND AFTER L3 + L7 + L4 + L5 + L6 + L8 + L1 so the reactivity
        # > count is byte-identical when L2 is disabled (default off)
        # > and telemetry counters indexing by Reactivity position stay
        # > stable across L3+L7+L4+L5+L6+L8+L1+L2 enable permutations.
        # >
        # > L2 introduces ZERO new cross-axis chains (cross-axis chain
        # > count stays at 3 — L4→L3, L6→L5, L8→L5). Its lightweight
        # > Reader impl
        # > (:class:`LedgerCatalogSnapshotReader`) reads catalog-mirror
        # > substrate (``external_catalog_imported`` entries) — NOT a
        # > peer L-axis projection. Per spec §4.6 doctrine
        # > clarification this is the **platform-reader** category.
        # >
        # > L2 is the **fifth lake-side axis built on
        # > :class:`LakeLoopComposite[T]` from day one** (after L5
        # > case 12, L6 case 13, L8 case 14, L1 case 15) — and the
        # > **eighth lake-side axis overall** (the FINAL planned axis
        # > in this generation; L-axis family completes at 24 of 30).
        # >
        # > L2 uses an **event-driven source predicate**
        # > (``EntryKind("external_catalog_imported")``) — mirrors
        # > L3/L7/L4/L5/L6/L8 event-driven posture; diverges from L1's
        # > Periodic. Drift detection is naturally event-driven (no
        # > point running on a stale snapshot pair).
        # >
        # > When ``WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED=true``,
        # > this adds one more Reactivity to the registry — yielding
        # > 5 default + L3 + L7 + L4 + L5 + L6 + L8 + L1 + L2 = 13
        # > when all axes are enabled, or 14 if subscriptions are also
        # > enabled.
        from wormbase_core.agent_gateway_construction import (
            compose_catalog_drift_reactivity_if_enabled
            as _compose_catalog_drift,
        )
        _catalog_drift_reactivity = _compose_catalog_drift(ledger=ledger)
        if _catalog_drift_reactivity is not None:
            reactivity_registry.register(_catalog_drift_reactivity)
            logger.info(
                "L2 catalog-drift discovery enabled "
                "(WORMBASE_CATALOG_DRIFT_DISCOVERY_ENABLED=true) — +1 "
                "agent-gateway Reactivity registered (%s)",
                _catalog_drift_reactivity.id,
            )

        # > AUTHORED 2026-05-13 (v1.1 Task 6 — Part A gateway-construction
        # > smoke). The agent-gateway MCP server has its own FastMCP
        # > construction site (``build_agent_gateway_mcp_server``) that
        # > previously was called only from tests. v1.1 wires it into
        # > the install path so a worm-core boot validates the server
        # > BUILDS with v1.1's production readers
        # > (``LedgerDecisionReader`` + ``LedgerProcessMapReader``).
        # >
        # > The remaining 9 deps (catalog_client, catalog_reader,
        # > broker_executor, federate_issuer, grant_lookup,
        # > agent_id_resolver, governance_resolver, data_product_reader,
        # > stateful gate bundle) ship as named no-op stubs — see
        # > ``agent_gateway_construction.py`` for the v1.2 follow-up list.
        # > Because those stubs are pending, this smoke does NOT start
        # > the gateway as an HTTP listener; it confirms construction
        # > succeeds and logs the dep gap. Listener startup gates behind
        # > v1.2's catalog/broker/grant work.
        if _is_agent_gateway_build_smoke_enabled():
            try:
                # v1.2 Task 2 Item #2: pass the four governance gates
                # already constructed inside ``build_worm_core``
                # (service.py lines 129-143) so the agent-gateway MCP
                # path composes with the same gate instances
                # chat-presence uses. No chat-presence refactor needed
                # — the gates live on ``WormCore`` directly.
                smoke = run_agent_gateway_build_smoke(
                    ledger=ledger,
                    company_id=worm.company_id,
                    install_id=str(worm.company_id),
                    pii_gate=worm.pii_gate,
                    warmup_gate=worm.warmup_gate,
                    interjection_gate=worm.interjection_gate,
                    knowledge_gate=worm.knowledge_gate,
                )
                logger.info(
                    "agent-gateway MCP server built: %d tools registered, "
                    "production readers wired=%s, broker wired=%s, "
                    "stateful gates wired=%s, grant_lookup wired=%s, "
                    "subscriptions wired=%s, embedding wired=%s, "
                    "multi_tenant wired=%s, pending deps=[%s]",
                    len(smoke.server.tool_names),
                    smoke.production_readers_wired,
                    smoke.broker_wired,
                    smoke.stateful_gates_wired,
                    smoke.grant_lookup_wired,
                    smoke.subscriptions_wired,
                    smoke.embedding_wired,
                    smoke.multi_tenant_wired,
                    ", ".join(smoke.pending_deps),
                )

                # > AUTHORED 2026-05-12 (v1.4 #3 — bind broker into the
                # > LazyWebhookSecretResolver). The subscription
                # > dispatcher was composed earlier (before the smoke)
                # > with the lazy resolver as its secret_resolver. Now
                # > that the smoke has resolved a CredentialBroker,
                # > bind it so vault:// webhook secrets resolve at
                # > delivery time. env:// refs work without this binding.
                _lazy_resolver = get_lazy_webhook_resolver()
                if _lazy_resolver is not None and smoke.broker is not None:
                    _lazy_resolver.bind_broker(smoke.broker)
                elif _lazy_resolver is not None and smoke.broker is None:
                    logger.info(
                        "lazy webhook resolver remains unbound — no "
                        "broker resolved by the build smoke; vault:// "
                        "webhook secrets will fail at delivery time "
                        "(env:// secrets still work)",
                    )

                # > AUTHORED 2026-05-15 (v1.3 Task 1 Item #2 — MCP
                # > listener binding). Bind a runtime listener after
                # > the build smoke succeeds. Listener startup is
                # > failure-isolated: any crash logs loudly and the
                # > rest of boot continues. Opt-in via
                # > WORMBASE_AGENT_GATEWAY_MCP_LISTENER_ENABLED=1.
                # > Default transport is stdio (Claude Desktop +
                # > local-MCP-client integrations); HTTP is the
                # > opt-in single-tenant production path. Multi-tenant
                # > routing is v2 per spec §11.
                if _is_agent_gateway_listener_enabled():
                    listener_transport = (
                        _resolve_agent_gateway_listener_transport()
                    )
                    logger.info(
                        "agent-gateway MCP listener enabled "
                        "(transport=%s) — starting as background task",
                        listener_transport,
                    )
                    tasks.append(
                        asyncio.create_task(
                            run_agent_gateway_mcp_listener(smoke.server),
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                # A failed smoke means agent-gateway and worm-core have
                # drifted at the GatewayDeps contract. Surface loudly
                # but don't abort the rest of boot — worm-core's other
                # surfaces (HTTP write API, MCP query_ledger, lurker)
                # remain useful even if the agent-gateway MCP path is
                # broken.
                logger.error(
                    "agent-gateway MCP build smoke FAILED: %s — "
                    "worm-core HTTP write API + MCP query_ledger remain "
                    "available; investigate listener wire-up gap",
                    exc,
                )

        reactivity_runner = ReactivityRunner(
            ledger=ledger,
            company_id=worm.company_id,
            registry=reactivity_registry,
        )
        tasks.append(asyncio.create_task(reactivity_runner.run_forever()))
        logger.info(
            "ReactivityRunner started: registered=%d "
            "(identity_discovery + 4 phenomenon-gap detectors + "
            "statement_to_owner + 4 research reactivities)",
            len(reactivity_registry.list()),
        )

        # v2.B Phase 3 (2026-05-12) — opt-in ClockTickEmitter for the
        # agent-gateway gap-escalation axis. The emitter writes
        # ``clock_tick`` ledger entries at the configured cadence; the
        # ReactivityRunner picks them up via the Periodic predicate.
        # Default OFF (env knob unset) preserves byte-identical boot
        # behavior.
        clock_tick_emitter = make_clock_tick_emitter_if_configured(
            ledger=ledger, company_id=worm.company_id,
        )
        if clock_tick_emitter is not None:
            tasks.append(
                asyncio.create_task(clock_tick_emitter.run_forever()),
            )
            logger.info(
                "ClockTickEmitter started: tick_interval_s=%d "
                "(drives agent_gateway.gap_to_escalation axis)",
                clock_tick_emitter.tick_interval_s,
            )

        # G5 — SetupConversationLoop. Drives bot-path setup conversations
        # for every tenant whose setup_mode == 'bot'. The loop wires a
        # SlackDmAdapter that delegates to the same SlackChannelAdapter
        # already authenticated above. Discord/Teams remain 'preview' for
        # the bot path until v1.5; the loop is Slack-only by design.
        if slack_adapter_handle is not None and _slack_adapter is not None:
            setup_adapter: SetupDmAdapter = _SlackSetupDmAdapter(
                _slack_adapter, slack_adapter_handle,
            )
            setup_loop = SetupConversationLoop(
                ledger,
                dm_adapter=setup_adapter,
            )
            tasks.append(asyncio.create_task(setup_loop.run_forever()))
            logger.info(
                "SetupConversationLoop wired (Slack DM driver)",
            )
    tasks.append(asyncio.create_task(_heartbeat_loop(worm)))

    # A3.5 — HTTP write API (aiohttp). Bearer-token-authed; refuses to
    # start if WORMBASE_LEDGER_API_TOKEN is unset (we don't quietly run
    # an unauthenticated endpoint that writes hash-chained ledger
    # entries on behalf of the dashboard).
    api_token = read_api_token()
    if api_token is None:
        logger.warning(
            "WORMBASE_LEDGER_API_TOKEN unset; skipping HTTP write API. "
            "Dashboard writes will fail with 502 until this is set."
        )
    else:
        api_port = read_api_port()
        # Forward the registry so /api/v1/reactivities/* can proxy through
        # it (W5.A5). When `start` ran the early-exit path
        # (no_chat_received_poller branch) the variable was never set;
        # ``locals()`` lookup keeps that path working.
        _registry_for_http = locals().get("reactivity_registry")
        tasks.append(
            asyncio.create_task(
                _http_server_task(
                    ledger, api_token, api_port,
                    reactivity_registry=_registry_for_http,
                )
            )
        )
        logger.info(
            "worm-core HTTP write API listening on :%d (bearer-token authed)",
            api_port,
        )

    # MCP server (Phase 0 spike — env-gated, additive).
    # Per docs/superpowers/specs/2026-04-27-mcp-integration.md §10.1.
    # Only starts when WORMBASE_MCP_ENABLED=1 so non-spike CI / production
    # contexts don't burn cycles starting an experimental server. Bound to
    # WORMBASE_MCP_PORT (default 9911) — DIFFERENT from the HTTP write API
    # port so the two coexist.
    if is_mcp_enabled():
        if api_token is None:
            logger.warning(
                "WORMBASE_MCP_ENABLED=1 but WORMBASE_LEDGER_API_TOKEN unset; "
                "skipping MCP server (it shares the same bearer token).",
            )
        else:
            mcp_port = read_mcp_port()
            tasks.append(
                asyncio.create_task(
                    _mcp_server_task(ledger, api_token, mcp_port)
                )
            )
            logger.info(
                "worm-core MCP server listening on :%d "
                "(Streamable HTTP at /mcp, bearer-token authed)",
                mcp_port,
            )

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        logger.info("worm-core shutting down")
        if worm.lurker is not None and not disable_socket:
            await worm.lurker.stop()
        await ledger.dispose()


class _SlackSetupDmAdapter:
    """SlackChannelAdapter → DmAdapter shim for SetupConversationLoop.

    The SetupConversationLoop expects a tiny ``open_dm / post_message /
    fetch_replies`` surface; SlackChannelAdapter exposes the richer
    ChannelAdapter Protocol. This shim translates between them.

    fetch_replies is best-effort: we read the DM's recent history and
    return messages the loop hasn't processed yet. The loop's own
    ``last_advance_seq`` cursor handles dedup. Production wiring of a
    real Slack ``conversations.history`` polling cycle is a v1.5 detail;
    in the meantime we rely on the chat_received_poller having already
    folded the DM messages into the ledger and pull from there.
    """

    def __init__(self, adapter: Any, handle: Any) -> None:
        self._adapter = adapter
        self._handle = handle

    async def open_dm(self, platform_user_id: str) -> str:
        # SlackChannelAdapter exposes a ``conversations_open`` (or
        # ``open_dm``) method depending on the build. We try the
        # canonical name first.
        if hasattr(self._adapter, "open_dm"):
            return await self._adapter.open_dm(self._handle, platform_user_id)
        if hasattr(self._adapter, "conversations_open"):
            return await self._adapter.conversations_open(
                self._handle, platform_user_id,
            )
        raise NotImplementedError(
            "SlackChannelAdapter has no open_dm / conversations_open method",
        )

    async def post_message(self, channel_id: str, text: str) -> str:
        # SlackChannelAdapter.send is the canonical Protocol method.
        ref = await self._adapter.send(self._handle, channel_id, text)
        return getattr(ref, "message_id", str(ref))

    async def fetch_replies(
        self, channel_id: str, *, since_seq: int,
    ) -> list[dict[str, Any]]:
        # Until SlackChannelAdapter exposes a ``conversations_history``
        # poll surface, the loop falls back to the ledger's chat_received
        # rows for this channel. Returning [] is safe — the loop will
        # re-poll on the next cycle.
        return []


class _SlackDMSender:
    """SlackChannelAdapter → wormbase_channel_adapter.dm.DMSender shim.

    Mirrors the ``open_dm`` + ``send_dm`` minimum surface that the
    StatementToOwnerReactivity expects. Delegates to the same
    SlackChannelAdapter the SetupConversationLoop uses; we only need a
    different shape because the dm helper takes (channel_id, text)
    while SetupConversationLoop takes a slightly richer call.
    """

    platform = "slack"

    def __init__(self, adapter: Any, handle: Any) -> None:
        self._adapter = adapter
        self._handle = handle

    async def open_dm(self, platform_user_id: str) -> str:
        if hasattr(self._adapter, "open_dm"):
            return await self._adapter.open_dm(
                self._handle, platform_user_id,
            )
        if hasattr(self._adapter, "conversations_open"):
            return await self._adapter.conversations_open(
                self._handle, platform_user_id,
            )
        raise NotImplementedError(
            "SlackChannelAdapter has no open_dm / conversations_open",
        )

    async def send_dm(
        self, platform_channel_id: str, text: str,
        *, blocks: list[Any] | None = None,
    ) -> str:
        # Build the SlackChannelAdapter ChannelRef + OutMessage shapes.
        from wormbase_channel_adapters.types import ChannelRef, OutMessage
        ref = await self._adapter.send(
            self._handle,
            ChannelRef(
                platform="slack",
                platform_channel_id=platform_channel_id,
                is_dm=True,
            ),
            OutMessage(text=text, blocks=list(blocks or [])),
        )
        return getattr(ref, "platform_message_id", "")


async def _heartbeat_loop(worm) -> None:  # type: ignore[no-untyped-def]
    interval = float(os.environ.get("WORM_CORE_LOOP_INTERVAL_S", "5"))
    while True:
        try:
            state = await worm.ramp.compute(worm.company_id)
            logger.info(
                "ramp ontology=%.1f schema=%.1f bd=%.1f kpi=%.1f conv=%.1f op=%.1f",
                state.ontology, state.schema_axis, state.business_definitions,
                state.kpi_relational, state.conversational, state.operational,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("heartbeat ramp compute failed: %s", exc)
        await asyncio.sleep(interval)


async def _mcp_server_task(
    ledger: Ledger, api_token: str, port: int,
) -> None:
    """Run the FastMCP Streamable HTTP server as a long-lived asyncio task.

    Lives alongside the reactivity loops so the MCP server shares the
    same Ledger instance + connection pool as the HTTP write API. Gated
    behind ``WORMBASE_MCP_ENABLED=1`` (Phase 0 spike posture).
    """
    mcp = build_mcp_server(
        ledger=ledger,
        api_token=api_token,
        host="0.0.0.0",
        port=port,
    )
    # FastMCP.run_streamable_http_async is the canonical entrypoint;
    # it wraps a uvicorn.Server.serve() call internally.
    await mcp.run_streamable_http_async()


async def _http_server_task(
    ledger: Ledger, api_token: str, port: int,
    *, reactivity_registry: Any = None,
) -> None:
    """Run the aiohttp HTTP write API as a long-lived asyncio task.

    Lives alongside the reactivity loops so worm-core stays one process /
    one Ledger instance / one connection pool. The runner is started
    here and the task only exits if the surrounding asyncio.gather is
    cancelled (e.g. KeyboardInterrupt).

    ``reactivity_registry`` is forwarded to ``build_http_app`` so the
    W5.A5 /reactivities endpoints can proxy through it. None is fine —
    the endpoints return honest-empty payloads in that case.
    """
    from aiohttp import web

    app = build_http_app(
        ledger=ledger,
        api_token=api_token,
        reactivity_registry=reactivity_registry,
    )
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    try:
        # Run forever — the task is cancelled when worm-core shuts down.
        while True:
            await asyncio.sleep(3600)
    finally:
        await runner.cleanup()


@main.command()
@click.option("--dsn", envvar="WORMBASE_LEDGER_DSN", required=True)
@click.option("--tenant", envvar="WORMBASE_TENANT_ID", default="baseworm")
@click.option("--limit", default=20)
def inspect(dsn: str, tenant: str, limit: int) -> None:
    """Print the most recent worm-core ledger entries."""
    asyncio.run(_inspect_async(dsn, tenant, limit))


async def _inspect_async(dsn: str, tenant: str, limit: int) -> None:
    company_id = tenant_to_uuid(tenant)
    ledger = Ledger(dsn)
    rows = await ledger.fetch(company_id)
    rows.sort(key=lambda r: r["seq"], reverse=True)
    for r in rows[:limit]:
        click.echo(
            f"seq={r['seq']:>4} kind={r['kind']:<22} "
            f"quad={r['quadrant']:<22} "
            f"ts={r['ts'].isoformat()}"
        )
    await ledger.dispose()


@main.command("discover-lake")
@click.option("--dsn", envvar="WORMBASE_LEDGER_DSN",
              default="postgresql+asyncpg://wormbase:wormbase@postgres:5432/wormbase")
@click.option("--tenant", envvar="WORMBASE_TENANT_ID", default="baseworm")
@click.option("--uri", required=True,
              help="Lake root URI: snowflake://account/wh/db, "
                   "postgres://host/db, or s3://bucket/prefix")
@click.option("--domain-pack", default="saas",
              type=click.Choice(["saas", "marketplace", "fintech"]))
def discover_lake(dsn: str, tenant: str, uri: str, domain_pack: str) -> None:
    """Walk an existing data lake and propose every table as a source.

    Step 2 (GROW THE LAKE) of the canonical product arc — see
    ``docs/superpowers/specs/2026-04-26-wormbase-product-arc.md``.

    Mocks the catalog walk for snowflake, postgres, and s3 URIs so the
    flow is deterministic and offline. Writes one ``source_proposed``
    entry per discovered table plus a ``lake_discovered`` summary.
    """
    asyncio.run(_discover_lake_async(dsn, tenant, uri, domain_pack))


async def _discover_lake_async(
    dsn: str, tenant: str, uri: str, pack: str
) -> None:
    from wormbase_core.flows import LakeDiscoveryFlow
    from wormbase_core.medallion import MedallionCascade

    company_id = tenant_to_uuid(tenant)
    logger.info(
        "discover-lake tenant=%s company_id=%s uri=%s",
        tenant, company_id, uri,
    )
    ledger = Ledger(dsn)
    # Apply boot-time projection migrations (W1.A1). Same path as the
    # ``run`` command so discover-lake against an existing DB lands a
    # current schema before any write.
    try:
        from wormbase_ledger.projections.migrate import migrate as run_migrations
        await run_migrations(ledger)
    except Exception as exc:  # noqa: BLE001
        logger.error("projection schema migrations failed: %s", exc)
        await ledger.dispose()
        raise
    try:
        from wormbase_ledger.schema import metadata as ledger_metadata
        async with ledger.engine.begin() as conn:
            await conn.run_sync(ledger_metadata.create_all)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ledger schema create skipped: %s", exc)

    worm = await build_worm_core(
        ledger, company_id, domain_pack=pack, enable_lurker=False,
    )
    flow = LakeDiscoveryFlow(worm.source_builder, ledger)
    cascade = MedallionCascade(ledger)

    summary = await flow.discover(company_id, uri)
    click.echo(
        f"discovered lake_kind={summary['lake_kind']} "
        f"tables_seen={summary['tables_seen']} "
        f"sources_proposed={summary['sources_proposed']}"
    )

    # Run cascade for each discovered source. Remote URIs read 0 bytes
    # but still produce deterministic bronze/silver/gold entries.
    for cid in summary["source_correlation_ids"]:
        source_id = worm.source_builder.get_source_id(cid)
        if source_id is None:
            continue
        # Reconstruct URI from the proposal stash for cascade.
        prop = worm.source_builder.get_proposal(cid)
        if prop is None:
            continue
        try:
            await cascade.cascade(
                company_id=company_id,
                source_id=source_id,
                uri=prop.proposed_uri,
                mime=None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("cascade failed for %s: %s", prop.proposed_uri, exc)

    await ledger.dispose()


if __name__ == "__main__":
    main()
