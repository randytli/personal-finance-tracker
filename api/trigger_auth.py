"""Signed scheduler-trigger authentication for a one-shot jobs endpoint (M5 design).

Not mounted in ``api.main``; nothing in the Windows runtime uses it. The
scheduler (Supabase Cron + pg_net) signs each request with HMAC-SHA256 over an
audience, key ID, timestamp, single-use nonce, method, pinned path and body
hash. The endpoint verifies all of it before any database or Plaid work, then
claims the nonce, then runs one scheduler pass. A replayed or forged request
never reaches ``run_once``. The existing jobs advisory lock still serialises
overlapping valid deliveries; this module does not replace it.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re

HEADER = "x-pft-trigger-signature"
VERSION = "pft-trigger-v1"
WINDOW = timedelta(seconds=300)
MAX_BODY = 4096
MIN_KEY_BYTES = 32
KINDS = {"tick"}
_FIELD = re.compile(r"kid=([a-z0-9_-]{1,32}),ts=(\d{1,12}),nonce=([0-9a-f]{32}),sig=([0-9a-f]{64})")

# Additive operational table for the SQL nonce store; applied only by a
# reviewed M6 migration, never by startup.
NONCE_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS {table} (
    nonce text PRIMARY KEY,
    expires_at timestamptz NOT NULL
)
"""


class TriggerAuthError(Exception):
    def __init__(self, status, reason):
        super().__init__(reason)
        self.status = status
        self.reason = reason


@dataclass(frozen=True)
class TriggerClaim:
    key_id: str
    timestamp: datetime
    nonce: str
    kind: str


def canonical_body(payload):
    """pg_net serialises a jsonb body itself (exact bytes 未核实), so the MAC
    covers a canonical JSON rendering of the parsed object, not raw bytes."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def canonical(audience, key_id, timestamp, nonce, method, path, body_canonical):
    return "\n".join((VERSION, audience, key_id, str(timestamp), nonce, method.upper(), path,
                      hashlib.sha256(body_canonical).hexdigest())).encode()


def sign(secret, *, audience, key_id, timestamp, nonce, method, path, payload):
    """Reference signer (tests and the SQL signer must agree with it)."""
    mac = hmac.new(secret, canonical(audience, key_id, timestamp, nonce, method, path,
                                     canonical_body(payload)), hashlib.sha256).hexdigest()
    return f"kid={key_id},ts={timestamp},nonce={nonce},sig={mac}"


def verify(headers, *, method, path, body, keys, audience, expected_path, now=None):
    """Return a TriggerClaim or raise TriggerAuthError. Performs no I/O.

    ``keys`` maps key ID to secret bytes; two entries allow rotation.
    Header names are matched case-insensitively.
    """
    now = now or datetime.now(timezone.utc)
    if not keys or any(len(secret) < MIN_KEY_BYTES for secret in keys.values()):
        raise TriggerAuthError(503, "trigger keys not configured")
    if not audience:
        raise TriggerAuthError(503, "trigger audience not configured")
    if method.upper() != "POST" or path != expected_path:
        raise TriggerAuthError(404, "not found")
    if len(body) > MAX_BODY:
        raise TriggerAuthError(413, "body too large")
    values = [value for name, value in headers.items() if name.lower() == HEADER]
    if len(values) != 1:
        raise TriggerAuthError(401, "signature required")
    match = _FIELD.fullmatch(values[0].strip())
    if not match:
        raise TriggerAuthError(401, "malformed signature")
    key_id, ts, nonce, supplied = match.groups()
    secret = keys.get(key_id)
    if secret is None:
        raise TriggerAuthError(401, "unknown key")
    try:
        payload = json.loads(body)  # bounded by MAX_BODY above
    except ValueError:
        raise TriggerAuthError(401, "bad signature") from None
    if not isinstance(payload, dict):
        raise TriggerAuthError(401, "bad signature")
    expected = hmac.new(secret, canonical(audience, key_id, int(ts), nonce, method, path,
                                          canonical_body(payload)), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise TriggerAuthError(401, "bad signature")
    # Freshness is checked after the MAC so unauthenticated clocks reveal nothing.
    timestamp = datetime.fromtimestamp(int(ts), timezone.utc)
    if abs(now - timestamp) > WINDOW:
        raise TriggerAuthError(401, "stale or future timestamp")
    if set(payload) != {"kind"} or payload["kind"] not in KINDS:
        raise TriggerAuthError(400, "unsupported trigger")
    return TriggerClaim(key_id=key_id, timestamp=timestamp, nonce=nonce, kind=payload["kind"])


class MemoryNonceStore:
    """Test double with the same contract as SqlNonceStore."""

    def __init__(self):
        self.seen = {}

    async def claim(self, nonce, expires_at, now):
        self.seen = {key: value for key, value in self.seen.items() if value > now}
        if nonce in self.seen:
            return False
        self.seen[nonce] = expires_at
        return True


class SqlNonceStore:
    """Single-use nonce claim in its own committed transaction.

    The claim commits before the scheduler pass starts, so a concurrent replay
    of the same signed request loses the primary-key race even if the first
    delivery is still running.
    """

    def __init__(self, engine, table="pft_ops.trigger_nonces"):
        if not re.fullmatch(r"[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)?", table):
            raise ValueError("invalid nonce table name")
        self.engine = engine
        self.table = table

    async def claim(self, nonce, expires_at, now):
        from sqlalchemy import text
        async with self.engine.begin() as connection:
            # Bounded cleanup: rows are useless after their signature window.
            await connection.execute(text(f"DELETE FROM {self.table} WHERE expires_at < :now"),
                                     {"now": now})
            inserted = await connection.scalar(text(
                f"INSERT INTO {self.table} (nonce, expires_at) VALUES (:nonce, :expires) "
                "ON CONFLICT (nonce) DO NOTHING RETURNING nonce"),
                {"nonce": nonce, "expires": expires_at})
        return inserted is not None


async def handle_trigger(*, method, path, headers, body, keys, audience, expected_path,
                         nonce_store, run_once, now=None):
    """Authenticate, claim the nonce, then run exactly one scheduler pass.

    Returns ``(status, payload)``. ``run_once`` is e.g. a closure over
    ``run_scheduler_once``; its own advisory lock returns ``busy`` for
    overlapping valid deliveries. Payloads never echo request material.
    """
    now = now or datetime.now(timezone.utc)
    try:
        claim = verify(headers, method=method, path=path, body=body, keys=keys,
                       audience=audience, expected_path=expected_path, now=now)
    except TriggerAuthError as exc:
        return exc.status, {"error": exc.reason}
    if not await nonce_store.claim(claim.nonce, claim.timestamp + WINDOW, now):
        return 409, {"error": "replayed request"}
    result = await run_once()
    # Completion of this request is the scheduler pass's own durable outcome;
    # the HTTP status only reports what this delivery did.
    return 200, {"status": result.get("status", "unknown")}
