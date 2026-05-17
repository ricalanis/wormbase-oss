"""Shared MCP-tool helpers: auth, role-aware filtering, audit, rate-limit.

J5 of docs/superpowers/plans/2026-04-26-production-dashboard.md
hardens the Phase 0 bearer-token surface with three additions:

1. Token-encoded tenancy. The bearer can be a signed compact JWT-ish
   blob (HMAC-SHA256, payload base64-url) carrying ``person_id`` +
   ``tenant_slug`` + ``exp``. Backward-compatible: a flat token (the
   raw ``WORMBASE_LEDGER_API_TOKEN``) still works and is treated as
   ``(person_id=None, tenant resolved from arg/header)``.

2. Rate-limit via the ledger. Counts ``mcp_call_received`` execute
   entries per (caller, tenant) over the last 60 seconds. If the
   count exceeds ``WORMBASE_MCP_RATE_LIMIT_PER_MIN`` (default 100),
   writes a ``denied`` audit entry and raises ``RateLimitExceeded``.

3. Audit-log privacy. When a row carries PII / regulated
   classification, ``client_ua`` is clipped to 32 chars before being
   recorded, and the result-count bucket leak is bucketed (``small`` /
   ``medium`` / ``large``) instead of recording an exact number.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable, TypedDict
from uuid import UUID, uuid4

from mcp.server.fastmcp import Context

from wormbase_core import write_actions
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger, Ledger

logger = logging.getLogger("wormbase_core.mcp_tools.auth")

LedgerLike = Ledger | InMemoryLedger | Any

# Rate-limit window + default ceiling.
RATE_LIMIT_WINDOW_SECONDS = 60
DEFAULT_RATE_LIMIT_PER_MIN = 100

# Privacy: how many chars of client_ua we keep when an audit row touches
# pii / regulated data.
PII_UA_CLIP = 32

# Pre-classified buckets for ``rows_returned``-style observations on
# privacy-sensitive results (see audit_outcome_bucket).
_BUCKET_SMALL = "small"
_BUCKET_MEDIUM = "medium"
_BUCKET_LARGE = "large"


class RateLimitExceeded(PermissionError):
    """Raised when a caller exceeds the per-minute MCP-call ceiling."""


class TokenClaims(TypedDict, total=False):
    person_id: str | None
    tenant_slug: str | None
    exp: float | None


# ---------------------------------------------------------------------------
# Token decoding
# ---------------------------------------------------------------------------


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def encode_compact_token(
    *,
    secret: str,
    person_id: UUID | None,
    tenant_slug: str | None,
    expires_in_seconds: int = 3600,
    issued_at: datetime | None = None,
) -> str:
    """Encode a compact ``payload.sig`` token. Used by tests + tokens API.

    The format is intentionally simple: base64url-of-canonical-JSON
    payload, followed by a ``.``, followed by the base64url HMAC-SHA256
    of the payload bytes under ``secret``. Stable, replay-safe, and
    independent of any third-party JWT lib.
    """
    issued_at = issued_at or datetime.now(tz=UTC)
    body: dict[str, Any] = {
        "person_id": str(person_id) if person_id is not None else None,
        "tenant_slug": tenant_slug,
        "exp": (issued_at + timedelta(seconds=expires_in_seconds)).timestamp(),
    }
    body_bytes = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    sig = hmac.new(secret.encode(), body_bytes, hashlib.sha256).digest()
    return f"{_b64url_encode(body_bytes)}.{_b64url_encode(sig)}"


# Default Person-token lifetime. The dashboard's Connect Claude Desktop
# panel issues 30-day tokens — long enough for a desktop client to live
# without re-authentication, short enough that revocation is bounded.
DEFAULT_PERSON_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60


def issue_person_token(
    *,
    person_id: UUID,
    tenant_slug: str,
    secret: str | None = None,
    expires_in_seconds: int = DEFAULT_PERSON_TOKEN_TTL_SECONDS,
    issued_at: datetime | None = None,
) -> str:
    """Issue a Person-scoped MCP bearer token.

    Returns a compact ``payload.sig`` token signed with ``secret`` (the
    HMAC key shared with worm-core's ``WORMBASE_LEDGER_API_TOKEN``). The
    returned token is the same compact format ``authorize_caller`` already
    accepts, so a Claude Desktop client can use it as
    ``Authorization: Bearer <token>`` without any further wrapping.

    ``secret`` defaults to ``WORMBASE_LEDGER_API_TOKEN`` from the
    environment so call-sites in the HTTP API don't have to plumb the
    key explicitly. Raises ``ValueError`` if the secret is missing.
    """
    effective_secret = secret if secret is not None else os.environ.get(
        "WORMBASE_LEDGER_API_TOKEN", ""
    )
    if not effective_secret:
        raise ValueError(
            "issue_person_token requires a non-empty secret; set "
            "WORMBASE_LEDGER_API_TOKEN or pass secret= explicitly",
        )
    return encode_compact_token(
        secret=effective_secret,
        person_id=person_id,
        tenant_slug=tenant_slug,
        expires_in_seconds=expires_in_seconds,
        issued_at=issued_at,
    )


def decode_compact_token(token: str, *, secret: str) -> TokenClaims | None:
    """Verify + decode a compact token.

    Returns the claims dict on success. Returns None if the token is
    malformed, the signature does not verify, or it has expired.
    """
    if "." not in token:
        return None
    head, _, sig_b64 = token.rpartition(".")
    if not head or not sig_b64:
        return None
    try:
        body_bytes = _b64url_decode(head)
        sig_bytes = _b64url_decode(sig_b64)
    except (ValueError, TypeError):
        return None
    expected = hmac.new(secret.encode(), body_bytes, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, sig_bytes):
        return None
    try:
        body = json.loads(body_bytes.decode())
    except (ValueError, UnicodeDecodeError):
        return None
    exp = body.get("exp")
    if exp is not None:
        try:
            if datetime.now(tz=UTC).timestamp() > float(exp):
                return None
        except (TypeError, ValueError):
            return None
    out: TokenClaims = {
        "person_id": body.get("person_id"),
        "tenant_slug": body.get("tenant_slug"),
        "exp": exp,
    }
    return out


# ---------------------------------------------------------------------------
# Header / context resolution
# ---------------------------------------------------------------------------


def _resolve_header(ctx: Context, *names: str) -> str | None:
    try:
        rc = ctx.request_context
    except (LookupError, ValueError):
        return None
    request = getattr(rc, "request", None)
    if request is None:
        return None
    headers = getattr(request, "headers", None)
    if headers is None:
        return None
    for name in names:
        v = headers.get(name) or headers.get(name.lower()) or headers.get(name.title())
        if v:
            return v
    return None


def resolve_bearer_token(ctx: Context) -> str | None:
    """Extract the bearer token from the underlying Starlette Request."""
    auth = _resolve_header(ctx, "authorization", "Authorization") or ""
    if not auth.startswith("Bearer "):
        return None
    return auth[len("Bearer "):].strip() or None


def resolve_user_agent(ctx: Context) -> str | None:
    return _resolve_header(ctx, "user-agent", "User-Agent")


def resolve_tenant_slug_header(ctx: Context) -> str | None:
    return _resolve_header(ctx, "x-tenant-slug", "X-Tenant-Slug")


# ---------------------------------------------------------------------------
# Caller resolution: token + header → (person_id, company_id)
# ---------------------------------------------------------------------------


def resolve_caller(
    ctx: Context,
    *,
    api_token: str,
    fallback_company_id: str | None = None,
) -> tuple[UUID | None, UUID, str]:
    """Resolve (person_id, company_id, tenant_slug) from the request.

    Authentication ladder:

    1. Compact signed token (``payload.sig``). Decoded with ``api_token``
       as the HMAC secret. Carries ``person_id`` + ``tenant_slug``.
    2. Legacy flat token (``api_token``). Person is None; tenant resolves
       from ``X-Tenant-Slug`` header → ``fallback_company_id`` arg.
    3. Anything else → PermissionError.

    Returns ``(caller_person_id, company_id, tenant_slug)``. Raises
    ``PermissionError`` for missing/invalid auth.
    """
    presented = resolve_bearer_token(ctx)
    if presented is None:
        raise PermissionError("missing bearer token")

    person_id: UUID | None = None
    tenant_slug: str | None = None

    # Try compact token first; fall back to flat token check.
    claims = decode_compact_token(presented, secret=api_token)
    if claims is not None:
        pid_raw = claims.get("person_id")
        if pid_raw:
            try:
                person_id = UUID(pid_raw)
            except (TypeError, ValueError):
                person_id = None
        tenant_slug = claims.get("tenant_slug")
    elif presented != api_token:
        raise PermissionError("invalid bearer token")

    # Tenant resolution: header > arg > 'baseworm' env default.
    tenant_slug = (
        tenant_slug
        or resolve_tenant_slug_header(ctx)
        or fallback_company_id
        or os.environ.get("WORMBASE_TENANT_ID", "baseworm")
    )
    company_id = tenant_to_uuid(tenant_slug)
    return person_id, company_id, tenant_slug


# ---------------------------------------------------------------------------
# Role-aware filtering — mirrors apps/dashboard/lib/server/role-filter.ts
# ---------------------------------------------------------------------------


def fold_role_grants(
    rows: list[dict[str, Any]],
    *,
    person_id: UUID,
    company_id: UUID,
) -> list[dict[str, Any]]:
    """Walk the ledger entries and reconstruct active role grants.

    Returns a list of ``{facet, role, scope_id, scope_type}`` dicts
    (active = unrevoked) for the given person within the company. The
    caller can then ask "is this person admin?" or "what domains do
    they own?" without round-tripping to the SQL projection.
    """
    active: dict[str, dict[str, Any]] = {}
    revoked: set[tuple[str, str, str | None]] = set()

    for entry in rows:
        if entry.get("kind") != "execute":
            continue
        payload = entry.get("payload") or {}
        tool = payload.get("tool")
        args = payload.get("args") or {}
        if tool == "emit_role_assigned":
            if args.get("person_id") != str(person_id):
                continue
            key = f"tenancy:{args['role']}:"
            active[key] = {
                "facet": "tenancy",
                "role": args["role"],
                "scope_id": None,
                "scope_type": None,
            }
        elif tool == "emit_role_revoked":
            if args.get("person_id") != str(person_id):
                continue
            revoked.add(("tenancy", args["role"], None))
        elif tool == "emit_domain_role_assigned":
            if args.get("person_id") != str(person_id):
                continue
            domain_id = args.get("domain_id")
            key = f"domain:{args['role']}:{domain_id}"
            active[key] = {
                "facet": "domain",
                "role": args["role"],
                "scope_id": domain_id,
                "scope_type": "domain",
            }
        elif tool == "emit_resource_role_assigned":
            if args.get("person_id") != str(person_id):
                continue
            resource_id = args.get("resource_id")
            key = f"resource:{args['role']}:{resource_id}"
            active[key] = {
                "facet": "resource",
                "role": args["role"],
                "scope_id": resource_id,
                "scope_type": args.get("resource_type"),
            }

    # Apply tenancy revocations.
    out: list[dict[str, Any]] = []
    for key, grant in active.items():
        if grant["facet"] == "tenancy":
            if (grant["facet"], grant["role"], None) in revoked:
                continue
        out.append(grant)
    return out


def tenancy_role_for(grants: list[dict[str, Any]]) -> str | None:
    """Pick the highest-privilege tenancy role from a grant list.

    Order: installer > admin > observer > member.
    """
    levels = {"installer": 4, "admin": 3, "observer": 2, "member": 1}
    best: tuple[int, str] | None = None
    for g in grants:
        if g["facet"] != "tenancy":
            continue
        score = levels.get(g["role"], 0)
        if best is None or score > best[0]:
            best = (score, g["role"])
    return best[1] if best is not None else None


def domain_access_set(grants: list[dict[str, Any]]) -> set[str]:
    """Domain ids the person has owner-or-contributor access to."""
    out: set[str] = set()
    for g in grants:
        if g["facet"] != "domain":
            continue
        if g["role"] in ("owner", "contributor"):
            sid = g.get("scope_id")
            if sid:
                out.add(str(sid))
    return out


def filter_rows_by_domain_access(
    rows: Iterable[dict[str, Any]],
    *,
    tenancy_role: str | None,
    domains: set[str],
    fields: tuple[str, ...] = ("domain_id", "domainId", "domain"),
) -> list[dict[str, Any]]:
    """Mirror of role-filter.ts ``filterByDomainAccess``.

    Rules:
    - admin / installer → all rows
    - observer → all rows (chrome enforces read-only)
    - member → rows whose ``domain_id`` is in ``domains``
    - unknown role → no rows (defensive)
    """
    if tenancy_role in ("admin", "installer", "observer"):
        return list(rows)
    if tenancy_role != "member":
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        for f in fields:
            v = r.get(f)
            if v is None:
                continue
            if str(v) in domains:
                out.append(r)
                break
    return out


# ---------------------------------------------------------------------------
# Rate-limit check
# ---------------------------------------------------------------------------


def rate_limit_per_min() -> int:
    raw = os.environ.get("WORMBASE_MCP_RATE_LIMIT_PER_MIN", "").strip()
    if not raw:
        return DEFAULT_RATE_LIMIT_PER_MIN
    try:
        n = int(raw)
        return n if n > 0 else DEFAULT_RATE_LIMIT_PER_MIN
    except ValueError:
        return DEFAULT_RATE_LIMIT_PER_MIN


async def check_rate_limit(
    ledger: LedgerLike,
    *,
    company_id: UUID,
    caller_person_id: UUID | None,
    now: datetime | None = None,
) -> int:
    """Count ``mcp_call_received`` execute entries in the rolling window.

    Returns the count (so callers can include it in the audit / response).
    Raises ``RateLimitExceeded`` if the configured ceiling is breached.
    """
    now = now or datetime.now(tz=UTC)
    window_start = now - timedelta(seconds=RATE_LIMIT_WINDOW_SECONDS)
    rows = await ledger.fetch(company_id)
    caller_match = (
        str(caller_person_id) if caller_person_id is not None else None
    )
    count = 0
    for r in rows:
        if r.get("kind") != "execute":
            continue
        ts = r.get("ts")
        if ts is None or ts < window_start:
            continue
        payload = r.get("payload") or {}
        if payload.get("tool") != "emit_mcp_call_received":
            continue
        args = payload.get("args") or {}
        # Only count successful or denied calls toward the budget; ok and
        # denied both reflect a real client request landing on the wire.
        if args.get("outcome") in ("ok", "denied"):
            row_caller = args.get("caller_person_id")
            if caller_match is None and row_caller is None:
                count += 1
            elif caller_match is not None and row_caller == caller_match:
                count += 1

    ceiling = rate_limit_per_min()
    if count >= ceiling:
        raise RateLimitExceeded(
            f"rate limit exceeded: {count} mcp calls in last "
            f"{RATE_LIMIT_WINDOW_SECONDS}s for caller "
            f"{caller_person_id or 'anonymous'} (ceiling={ceiling})"
        )
    return count


# ---------------------------------------------------------------------------
# Audit-log privacy + write
# ---------------------------------------------------------------------------


def bucket_size(n: int) -> str:
    if n <= 10:
        return _BUCKET_SMALL
    if n <= 100:
        return _BUCKET_MEDIUM
    return _BUCKET_LARGE


def clip_ua_for_audit(ua: str | None, *, has_pii: bool) -> str | None:
    """Clip ``client_ua`` when the audit log would otherwise leak PII."""
    if ua is None:
        return None
    if has_pii:
        return ua[:PII_UA_CLIP]
    return ua


async def audit(
    ledger: LedgerLike,
    *,
    company_id: UUID,
    caller_person_id: UUID | None,
    tool_name: str,
    args_hash: str,
    client_ua: str | None,
    started_at: datetime,
    outcome: str,
    latency_ms: int,
) -> UUID:
    """Audit one MCP call through the canonical PEVR cycle.

    Errors are logged but not raised — we never want to mask the
    underlying tool result with an audit-write failure (parity with
    ``mcp_server._audit``).
    """
    call_id = uuid4()
    try:
        await write_actions.record_mcp_call(
            ledger,
            company_id,
            mcp_call_id=call_id,
            caller_person_id=caller_person_id,
            tool_name=tool_name,
            args_hash=args_hash,
            client_ua=client_ua,
            started_at=started_at,
            outcome=outcome,
            latency_ms=latency_ms,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "mcp audit write failed (call_id=%s outcome=%s): %s",
            call_id, outcome, exc,
        )
    return call_id


def canonical_args_hash(args: dict[str, Any]) -> str:
    blob = json.dumps(args, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# Tool wrapper helper — every tool follows the same outer shape, this lifts
# the boilerplate so each tool body is just "fold the ledger + project".
# ---------------------------------------------------------------------------


class CallerContext(TypedDict):
    caller_person_id: UUID | None
    company_id: UUID
    tenant_slug: str
    grants: list[dict[str, Any]]
    tenancy_role: str | None
    domain_access: set[str]


def _person_exists_in_tenant(
    rows: list[dict[str, Any]],
    *,
    person_id: UUID,
    company_id: UUID,
) -> bool:
    """Walk the ledger rows for emit_person_{proposed,confirmed,archived}.

    Returns True iff there is at least one ``emit_person_proposed`` entry
    for ``person_id`` AND the Person is not archived. ``tenant_id`` check
    is implicit via the ledger fetch already filtering by ``company_id``,
    but the proposer's ``tenant_id`` arg is also checked when present
    as a defensive belt-and-braces measure.

    Phase 1B.F gate. Closes the loophole where a forged compact token
    with arbitrary ``person_id + tenant_slug`` could resolve without
    the Person actually existing in that tenant.
    """
    proposed = False
    archived = False
    target = str(person_id)
    cid_str = str(company_id)
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        tool = payload.get("tool")
        args = payload.get("args") or {}
        if tool == "emit_person_proposed" and args.get("person_id") == target:
            tenant_arg = args.get("tenant_id")
            # Defensive: if tenant_id is recorded on the row, it MUST
            # match the company_id we're folding for. If not present
            # (older rows), the ledger fetch's company_id filter is the
            # primary tenant boundary.
            if tenant_arg is None or tenant_arg == cid_str:
                proposed = True
        elif tool == "emit_person_archived" and args.get("person_id") == target:
            archived = True
    return proposed and not archived


async def authorize_caller(
    ctx: Context,
    *,
    ledger: LedgerLike,
    api_token: str,
    fallback_company_id: str | None,
) -> CallerContext:
    """Resolve + authenticate + load role grants for the caller.

    Phase 1B.F adds the person-tenant binding gate: when a token claims
    ``person_id + tenant_slug``, the projection MUST contain an
    unrevoked Person row at ``(person_id, tenant_slug)``. If not,
    raises ``PermissionError`` immediately — even before role grants
    are folded, so a forged token can't pollute the ``mcp_call_received``
    audit projection with phantom callers.

    Raises PermissionError on auth failure; the calling tool is
    responsible for writing a ``denied`` audit entry before re-raising.
    """
    caller_person_id, company_id, tenant_slug = resolve_caller(
        ctx,
        api_token=api_token,
        fallback_company_id=fallback_company_id,
    )

    grants: list[dict[str, Any]] = []
    if caller_person_id is not None:
        rows = await ledger.fetch(company_id)
        # Phase 1B.F gate: token-claimed person MUST exist in tenant.
        if not _person_exists_in_tenant(
            rows, person_id=caller_person_id, company_id=company_id,
        ):
            raise PermissionError(
                f"token claims person {caller_person_id} for tenant "
                f"{tenant_slug} but no such Person row exists"
            )
        grants = fold_role_grants(
            rows, person_id=caller_person_id, company_id=company_id,
        )
    role = tenancy_role_for(grants)
    # If we have no person at all, treat the caller as a backstage admin
    # (legacy flat-token path) — keeps Phase 0 behaviour intact while the
    # Person-aware token rollout lands.
    if caller_person_id is None and role is None:
        role = "admin"
    domains = domain_access_set(grants)
    return {
        "caller_person_id": caller_person_id,
        "company_id": company_id,
        "tenant_slug": tenant_slug,
        "grants": grants,
        "tenancy_role": role,
        "domain_access": domains,
    }


__all__ = [
    "CallerContext",
    "DEFAULT_PERSON_TOKEN_TTL_SECONDS",
    "DEFAULT_RATE_LIMIT_PER_MIN",
    "PII_UA_CLIP",
    "RATE_LIMIT_WINDOW_SECONDS",
    "RateLimitExceeded",
    "audit",
    "authorize_caller",
    "bucket_size",
    "canonical_args_hash",
    "check_rate_limit",
    "clip_ua_for_audit",
    "decode_compact_token",
    "domain_access_set",
    "encode_compact_token",
    "filter_rows_by_domain_access",
    "fold_role_grants",
    "issue_person_token",
    "rate_limit_per_min",
    "resolve_bearer_token",
    "resolve_caller",
    "resolve_tenant_slug_header",
    "resolve_user_agent",
    "tenancy_role_for",
]
