"""Bounded disposable benchmark of unchanged shared sync; synthetic SDK only.

Private schemas are provisioned separately. No DDL, real SDK, arbitrary SQL,
cron, backup, or public financial routes are exposed by this adapter.
"""
import asyncio
import hashlib
from collections import defaultdict
from contextlib import ExitStack
import json
import math
import os
import resource
import statistics
import time
import uuid
from unittest.mock import patch

from fastapi import Depends, HTTPException, Request
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSessionTransaction, async_sessionmaker, create_async_engine
from starlette.responses import JSONResponse

SCALES = {2610: "pft_m5_bench_2610", 35600: "pft_m5_bench_35600"}
NEGATIVE_ACTIONS = {"timeout_publication", "cancel_publication", "cancel_fetch"}
ACTIONS = {"noop", "append_one"} | NEGATIVE_ACTIONS
APPEND_ROWS = 5  # append_one publishes one synthetic transaction per Item
APPLICATION_DEADLINE = 210
PROCESS_GATE = asyncio.Lock()
PROCESS_CALLS = 0


def distribution(values):
    values = sorted(values)
    if not values:
        return {"n": 0}
    return {"n": len(values), "min_s": values[0], "median_s": statistics.median(values),
        "mean_s": statistics.mean(values), "max_s": values[-1],
        "observed_query_p90_s": values[math.ceil(.90 * len(values))-1],
        "observed_query_p95_s": values[math.ceil(.95 * len(values))-1]}


class SyntheticClient:
    def __init__(self, scale, action):
        self.scale, self.action = scale, action
        self.calls, self.response_bytes, self.request_bytes = 0, 0, 0
        self.started = False
        self.finished = False
        self.cancel_id = "m5-cancel-" + uuid.uuid4().hex
        self.append_id = uuid.uuid4().hex

    def transactions_sync(self, request, *, _request_timeout):
        data = request.to_dict()
        token = data["access_token"]
        if token not in {f"synthetic-token-{i}" for i in range(5)}:
            raise RuntimeError("Non-synthetic token rejected")
        self.started = True
        if self.action == "cancel_fetch":
            time.sleep(.8)
        self.calls += 1
        self.request_bytes += len(json.dumps(data, default=str).encode())
        value = {"added": [], "modified": [], "removed": [],
            "next_cursor": data.get("cursor"), "has_more": False,
            "transactions_update_status": "HISTORICAL_UPDATE_COMPLETE"}
        if self.action == "append_one":
            from datetime import date
            item = token.removeprefix("synthetic-token-")
            identity = f"m5-append-{self.append_id}-{item}"
            value["next_cursor"] = f"m5-append-cursor-{self.append_id}-{item}"
            value["added"] = [{"transaction_id": identity, "account_id": f"account-{item}-0",
                "date": date(2026, 8, 2), "amount": 23, "name": "Synthetic append",
                "merchant_name": "Synthetic", "personal_finance_category": {"primary": "GENERAL_MERCHANDISE"}}]
        elif self.action != "noop":
            value["next_cursor"] = self.cancel_id
            if token == "synthetic-token-0":
                from datetime import date
                value["added"] = [{"transaction_id": self.cancel_id, "account_id": "account-0-0",
                    "date": date(2026, 8, 1), "amount": 19, "name": "Synthetic cancellation",
                    "merchant_name": "Synthetic", "personal_finance_category": {"primary": "GENERAL_MERCHANDISE"}}]
        self.response_bytes += len(json.dumps(value, default=str).encode())
        self.finished = True
        return value

    def accounts_get(self, *args, **kwargs):
        raise RuntimeError("Unexpected metadata request in retained no-op fixture")


def parse_options(raw):
    """Bound the request to a known scale/action; negative tests stay on the small fixture."""
    options = json.loads(raw)
    scale, action = options["scale"], options.get("action", "noop")
    if (set(options) - {"scale", "action"} or type(scale) is not int
            or scale not in SCALES or action not in ACTIONS
            or (action in NEGATIVE_ACTIONS and scale != 2610)):
        raise ValueError()
    return scale, action


def fixture_rows_accepted(scale, action, rows, appends):
    """No-ops time the exact retained fixture, so they must all run before any append.
    Later runs accept only rows published by the appends already recorded as successful."""
    if action == "noop":
        return rows == scale
    return scale <= rows <= scale + appends * APPEND_ROWS


# Successful runs that published rows; only append_one publishes additions on these fixtures.
APPENDS_SQL = ("select count(*) from (select r.run_id from sync_runs r join sync_item_runs i using (run_id) "
               "where r.status = 'success' group by r.run_id having sum(i.added_count) > 0) appended")


TYPE_CODES = {"expense": "e", "refund": "r", "reimbursement": "m", "income": "i", "card_benefit": "c",
              "payment": "p", "transfer": "t", "adjustment": "a"}
FLAG_CODES = {True: "t", False: "f"}


def decode_classification(code):
    types = {value: key for key, value in TYPE_CODES.items()}
    flags = {value: key for key, value in FLAG_CODES.items()}
    return types.get(code[0]), flags.get(code[1]), flags.get(code[2])


# One fixed-width code per pre-existing row, ordered by id: three bytes per row
# lets a changed classification be located without fetching every row twice.
CLASSIFICATION_CODE_SQL = ("case when t.transaction_type is null then '-' "
    + " ".join(f"when t.transaction_type = '{name}' then '{code}'" for name, code in TYPE_CODES.items())
    + " else '?' end || case t.is_spending when true then 't' when false then 'f' else '-' end"
    " || case t.is_internal_transfer when true then 't' when false then 'f' else '-' end")


async def append_state(engine, append_id):
    """Pre-existing rows only (new rows carry this run's append id), timestamps excluded.
    Normalized hashes also exclude classification, which is compared row by row instead."""
    async with engine.connect() as connection:
        row = (await connection.execute(text(
            "select (select count(*) from raw_transactions), (select count(*) from transactions), "
            "(select md5(coalesce(string_agg((to_jsonb(r) - 'created_at' - 'updated_at')::text, E'\\n' "
            "order by r.transaction_id), '')) from raw_transactions r where r.transaction_id not like :new), "
            "(select md5(coalesce(string_agg((to_jsonb(t) - 'created_at' - 'updated_at' - 'transaction_type' "
            "- 'is_spending' - 'is_internal_transfer')::text, E'\\n' order by t.transaction_id), '')) "
            "from transactions t where t.transaction_id not like :new), "
            f"(select coalesce(string_agg({CLASSIFICATION_CODE_SQL}, '' order by t.transaction_id), '') "
            "from transactions t where t.transaction_id not like :new)"),
            {"new": f"m5-append-{append_id}-%"})).one()
    return dict(zip(("raw_rows", "normalized_rows", "raw_hash", "normalized_hash", "classification_codes"), row))


async def classification_changes(engine, append_id, before, after, positions, limit=200):
    async with engine.connect() as connection:
        ids = (await connection.execute(text(
            "select n, transaction_id from (select transaction_id, row_number() over "
            "(order by transaction_id) as n from transactions where transaction_id not like :new) s "
            "where n = any(CAST(:positions AS BIGINT[])) order by n"),
            {"new": f"m5-append-{append_id}-%", "positions": [p + 1 for p in positions[:limit]]})).all()
    return [{"transaction_id": transaction_id,
             "before": decode_classification(before[3 * (n - 1):3 * n]),
             "after": decode_classification(after[3 * (n - 1):3 * n])} for n, transaction_id in ids]


def verify_append(before, after, snapshot_before, snapshot_after, run_id):
    """Positive checks for a successful append_one; classification changes are listed, not failed."""
    cursors_before = {row[0]: row[1] for row in snapshot_before["cursors_and_success"]}
    cursors_after = {row[0]: row[1] for row in snapshot_after["cursors_and_success"]}
    marker_before = snapshot_before["publication_marker"][0] if snapshot_before["publication_marker"] else {}
    marker_after = snapshot_after["publication_marker"][0] if snapshot_after["publication_marker"] else {}
    codes_before, codes_after = before["classification_codes"], after["classification_codes"]
    checks = {
        "rows_increased_by_append": (after["raw_rows"] == before["raw_rows"] + APPEND_ROWS
                                     and after["normalized_rows"] == before["normalized_rows"] + APPEND_ROWS),
        "every_cursor_advanced": (cursors_before.keys() == cursors_after.keys() and all(
            cursors_after[item] != cursors_before[item] for item in cursors_before)),
        "publication_marker_advanced": (marker_after.get("last_published_run_id") == run_id
                                        != marker_before.get("last_published_run_id")
                                        and marker_after.get("published_at") != marker_before.get("published_at")),
        "existing_raw_rows_unchanged": before["raw_hash"] == after["raw_hash"],
        "existing_normalized_rows_unchanged": before["normalized_hash"] == after["normalized_hash"],
        "existing_row_set_unchanged": len(codes_before) == len(codes_after),
    }
    return {"passed": all(checks.values()), "checks": checks,
            "classification_digest_before": hashlib.md5(codes_before.encode()).hexdigest(),
            "classification_digest_after": hashlib.md5(codes_after.encode()).hexdigest(),
            "classification_changed_positions": [
                index // 3 for index in range(0, min(len(codes_before), len(codes_after)), 3)
                if codes_before[index:index + 3] != codes_after[index:index + 3]]}


class WireCounter:
    """TLS ciphertext bytes received on this engine's own database sockets.

    pg_stat_statements has no network-byte columns, so this counts at the driver
    transport: each tracked connection's asyncio SSLProtocol.buffer_updated is
    wrapped on that instance only. The observer engine is never tracked. The TLS
    handshake precedes the connect event and is not included.
    """

    def __init__(self, metrics):
        self.metrics = metrics
        self.bytes = defaultdict(int)
        self.tracked = self.untracked = 0

    def track(self, dbapi_connection):
        try:
            protocol = dbapi_connection._connection._transport._ssl_protocol
            original = protocol.buffer_updated
        except AttributeError:
            self.untracked += 1
            return

        def counted(nbytes):
            self.bytes[self.metrics.phase] += nbytes
            return original(nbytes)

        protocol.buffer_updated = counted
        self.tracked += 1


class Metrics:
    def __init__(self):
        self.phase = "setup"
        self.wire = WireCounter(self)
        self.queries = defaultdict(list)
        self.attempts = defaultdict(int)
        self.stages = defaultdict(float)
        self.connections = []
        self.exits = []
        self.checked_out = self.peak = 0

    def attach(self, engine):
        @event.listens_for(engine.sync_engine, "do_connect")
        def start_connect(dialect, record, args, params):
            record.info["m5_connection_start"] = time.perf_counter()

        @event.listens_for(engine.sync_engine, "connect")
        def connected(connection, record):
            self.connections.append(time.perf_counter()-record.info.pop("m5_connection_start"))
            self.wire.track(connection)

        @event.listens_for(engine.sync_engine, "checkout")
        def checkout(*args):
            self.checked_out += 1
            self.peak = max(self.peak, self.checked_out)

        @event.listens_for(engine.sync_engine, "checkin")
        def checkin(*args):
            self.checked_out -= 1

        @event.listens_for(engine.sync_engine, "before_cursor_execute")
        def before(connection, cursor, statement, params, context, many):
            context._m5_started, context._m5_phase = time.perf_counter(), self.phase
            self.attempts[self.phase] += 1

        @event.listens_for(engine.sync_engine, "after_cursor_execute")
        def after(connection, cursor, statement, params, context, many):
            self.queries[context._m5_phase].append(time.perf_counter()-context._m5_started)

        @event.listens_for(engine.sync_engine, "handle_error")
        def error(context):
            c = context.execution_context
            if c is not None and hasattr(c, "_m5_started"):
                self.queries[c._m5_phase].append(time.perf_counter()-c._m5_started)

    def timed(self, name, original, hook=None):
        async def wrapped(*args, **kwargs):
            prior, start = self.phase, time.perf_counter()
            self.phase = name
            try:
                result = await original(*args, **kwargs)
                if hook:
                    await hook()
                return result
            finally:
                self.stages[name] += time.perf_counter()-start
                self.phase = prior
        return wrapped


def engine_for(config, schema, tls_context, *, observer=False):
    return create_async_engine(config.url, pool_size=1 if observer else 4, max_overflow=0,
        pool_timeout=5, pool_pre_ping=True, connect_args={"ssl": tls_context(), "timeout": 10,
            "command_timeout": 15, "server_settings": {"search_path": schema}})


async def snapshot(engine):
    """Full raw/normalized rows, all other financial tables, cursor and marker."""
    from api.models import Base
    result = {}
    excluded = {"items", "sync_runs", "sync_item_runs", "sync_runtime_state"}
    async with engine.connect() as connection:
        for table in Base.metadata.sorted_tables:
            name = table.name
            if name in excluded:
                continue
            order = ",".join('t."'+column.name+'"' for column in table.primary_key.columns)
            row = (await connection.execute(text(f'SELECT count(*), md5(coalesce(string_agg('
                f'md5(row_to_json(t)::text), \'\' ORDER BY {order}),\'\')) FROM "{name}" t'))).one()
            result[name] = {"rows": row[0], "full_row_hash": row[1]}
        result["cursors_and_success"] = (await connection.execute(text("select coalesce(jsonb_agg("
            "jsonb_build_array(item_id,transactions_cursor,last_sync_success_at,last_sync_change_at) "
            "order by item_id),'[]'::jsonb) from items"))).scalar_one()
        result["publication_marker"] = (await connection.execute(text(
            "select coalesce(jsonb_agg(to_jsonb(s) order by user_id),'[]'::jsonb) from sync_runtime_state s"))).scalar_one()
    return result


def current_rss_mib():
    try:
        with open("/proc/self/status") as source:
            for line in source:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])/1024
    except OSError:
        pass
    return None


async def observe(engine, stopped, output):
    try:
        async with engine.connect() as connection:
            while not stopped.is_set():
                row = (await connection.execute(text("select count(*) as db_total, "
                    "count(*) filter(where usename='pft_m5_jobs') as jobs, "
                    "count(*) filter(where usename='pft_m5_jobs' and state='active') as active_jobs "
                    "from pg_stat_activity where datname=current_database()"))).one()
                await connection.commit()
                output["samples"] += 1
                for key, value in zip(("database_backends", "jobs_backends", "active_jobs_backends"), row):
                    output[key] = max(output[key], value)
                rss = current_rss_mib()
                if rss is not None:
                    output["rss_sampled_peak_mib"] = max(output["rss_sampled_peak_mib"], rss)
                try:
                    await asyncio.wait_for(stopped.wait(), timeout=.5)
                except TimeoutError:
                    pass
    except Exception as exc:
        output["error_type"] = type(exc).__name__


def register(app, capability, identity, tls_context, instance_id):
    @app.post("/probe/sync-benchmark")
    async def benchmark(request: Request, config=Depends(capability)):
        global PROCESS_CALLS
        if (config.role != "jobs" or config.project_ref != "acyghoemtdrilsdszolq"
                or os.environ.get("M5_BENCHMARK_ENABLED") != "synthetic-20261001"):
            raise HTTPException(403, "Synthetic jobs benchmark required")
        raw = await request.body()
        if len(raw) > 1024:
            raise HTTPException(422, "Request bounds rejected")
        try:
            scale, action = parse_options(raw)
        except (ValueError, KeyError, TypeError):
            raise HTTPException(422, "Request bounds rejected") from None
        if PROCESS_GATE.locked():
            raise HTTPException(409, "Benchmark process busy")
        async with PROCESS_GATE:
            start, cpu = time.perf_counter(), time.process_time()
            first = PROCESS_CALLS == 0
            PROCESS_CALLS += 1
            import_start = time.perf_counter()
            from api.services import sync_all as service
            import_s = time.perf_counter()-import_start
            schema = SCALES[scale]
            engine = engine_for(config, schema, tls_context)
            observer = engine_for(config, schema, tls_context, observer=True)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            metrics = Metrics(); metrics.attach(engine)
            stopped = asyncio.Event()
            peaks = {"samples": 0, "database_backends": 0, "jobs_backends": 0,
                     "active_jobs_backends": 0, "rss_sampled_peak_mib": 0}
            observation = None
            client = SyntheticClient(scale, action)
            initial_rss_hwm = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
            try:
                guard_start = time.perf_counter()
                async with engine.begin() as connection:
                    await identity(connection, config)
                    if await connection.scalar(text("select current_schema()")) != schema:
                        raise RuntimeError("Private schema pin rejected")
                    row = (await connection.execute(text("select dataset_id, project_ref, retained_rows "
                        "from bench_manifest where singleton=true"))).one()
                    if tuple(row) != (config.dataset_id, config.project_ref, scale):
                        raise RuntimeError("Benchmark fixture identity rejected")
                    if await connection.scalar(text("select pg_database_size(current_database())")) > 200_000_000:
                        raise RuntimeError("Synthetic database size budget reached")
                    rows = await connection.scalar(text("select count(*) from raw_transactions"))
                    appends = await connection.scalar(text(APPENDS_SQL))
                    if not fixture_rows_accepted(scale, action, rows, appends):
                        raise RuntimeError("Retained fixture row count rejected")
                    if not await connection.scalar(text("select pg_try_advisory_xact_lock(hashtextextended("
                            "'pft-m5-benchmark-control',0))")):
                        raise HTTPException(409, "Benchmark invocation already active")
                    allowance = await connection.scalar(text("update bench_manifest set invocations=invocations+1 "
                        "where singleton=true and invocations<16 returning invocations"))
                    if allowance is None:
                        raise RuntimeError("Synthetic invocation budget exhausted")
                    # A dedicated guard transaction retains the control lock; rollback/commit releases it.
                    guard_s = time.perf_counter()-guard_start
                    before = await snapshot(engine) if action != "noop" or scale == 35600 else None
                    append_before = await append_state(engine, client.append_id) if action == "append_one" else None
                    append_verification = None
                    observation = asyncio.create_task(observe(observer, stopped, peaks))
                    metrics.phase = "sync"
                    published_first_item = asyncio.Event()
                    published_calls = 0
                    async def publication_hook():
                        nonlocal published_calls
                        published_calls += 1
                        if published_calls == 1:
                            published_first_item.set()
                            if action == "timeout_publication":
                                await asyncio.sleep(30)
                    old_exit = AsyncSessionTransaction.__aexit__
                    async def exit_transaction(transaction, *args):
                        timestamp = time.perf_counter()
                        try:
                            return await old_exit(transaction, *args)
                        finally:
                            if transaction.session.bind is engine:
                                metrics.exits.append({"wall_s": time.perf_counter()-timestamp,
                                    "nested": transaction.nested, "exception": args[0] is not None})
                    sync_start = time.perf_counter()
                    status, result = None, None
                    with ExitStack() as patches:
                        patches.enter_context(patch.object(service, "MAX_RUN_SECONDS",
                            20 if action == "timeout_publication" else APPLICATION_DEADLINE))
                        patches.enter_context(patch.object(AsyncSessionTransaction, "__aexit__", exit_transaction))
                        for name in ("_fetch_item", "_publish_item", "normalize_item_transactions",
                            "classify_active_transactions", "acquire_session_lock", "_finalize_failure", "_assert_lock_owner"):
                            patches.enter_context(patch.object(service, name, metrics.timed(name,
                                getattr(service, name), publication_hook if name == "_publish_item" else None)))
                        task = asyncio.create_task(service.sync_all(f"synthetic-cloud-{scale}", client=client,
                            engine=engine, session_factory=sessions))
                        async def cancel_at_boundary():
                            if action == "cancel_publication":
                                await published_first_item.wait()
                            else:
                                while not client.started:
                                    await asyncio.sleep(.01)
                            task.cancel()
                        canceller = asyncio.create_task(cancel_at_boundary()) if action.startswith("cancel_") else None
                        try:
                            async with asyncio.timeout(240):
                                result = await task
                            status = result["status"]
                        except asyncio.CancelledError:
                            status = "cancelled"
                        except Exception as exc:
                            status = "timeout" if isinstance(exc, TimeoutError) else "error"
                            result = {"error_type": type(exc).__name__}
                        finally:
                            if canceller is not None:
                                canceller.cancel()
                                await asyncio.gather(canceller, return_exceptions=True)
                    sync_s = time.perf_counter()-sync_start
                    metrics.phase = "verification"
                    if action == "cancel_fetch":
                        # The synthetic SDK thread can finish after cancellation; it cannot publish.
                        await asyncio.sleep(1)
                    after = await snapshot(engine) if before is not None else None
                    async def latest_run():
                        async with sessions() as db:
                            row = (await db.execute(text("select run_id,status,published_at,classification_status,"
                                "error_category from sync_runs order by started_at desc limit 1"))).mappings().one()
                            return {k: str(v) if v is not None else None for k,v in row.items()}
                    immediate_run = await latest_run()
                    reconciled_run = None
                    if action.startswith("cancel_"):
                        # Observe the unmodified service's next-owner reconciliation separately.
                        await service.sync_all(f"synthetic-cloud-{scale}", client=SyntheticClient(scale,"noop"),
                            engine=engine, session_factory=sessions, item_ids=[])
                        reconciled_run = await latest_run()
                    async with engine.connect() as verify:
                        test_lock = await verify.scalar(text("select pg_try_advisory_lock(hashtextextended(:key,0))"),
                            {"key": f"pft-sync:synthetic-cloud-{scale}"})
                        if test_lock:
                            await verify.scalar(text("select pg_advisory_unlock(hashtextextended(:key,0))"),
                                {"key": f"pft-sync:synthetic-cloud-{scale}"})
                        await verify.commit()
                    preservation = None if before is None else {"state_unchanged": before == after,
                        "before": before, "after": after, "immediate_run": immediate_run,
                        "after_next_owner_reconciliation": reconciled_run,
                        "locks_released": bool(test_lock), "sdk_thread_finished": client.finished}
                    # A successful append_one publishes by design; every other path must preserve state.
                    if (before is not None and (action in NEGATIVE_ACTIONS or status != "success")
                            and (before != after or not test_lock or immediate_run["published_at"])):
                        raise RuntimeError("Cancellation preservation verification failed")
                    if append_before is not None and status == "success":
                        append_after = await append_state(engine, client.append_id)
                        append_verification = verify_append(append_before, append_after, before, after,
                                                            result["run_id"])
                        positions = append_verification.pop("classification_changed_positions")
                        append_verification["classification_changed_count"] = len(positions)
                        append_verification["classification_changes"] = await classification_changes(
                            engine, client.append_id, append_before["classification_codes"],
                            append_after["classification_codes"], positions) if positions else []
            finally:
                cleanup_start = time.perf_counter()
                stopped.set()
                if observation is not None:
                    await observation
                await engine.dispose()
                await observer.dispose()
                cleanup_s = time.perf_counter()-cleanup_start
            measured_queries = {key: value for key,value in metrics.queries.items()
                                if key not in {"setup", "verification"}}
            all_queries = [v for values in measured_queries.values() for v in values]
            outer_exits = [v for v in metrics.exits if not v["nested"]]
            body = {"kind": "real_cloud_shared_sync_benchmark", "scale": scale, "action": action,
                "instance_id": instance_id, "first_benchmark_in_process": first,
                "process_benchmark_ordinal": PROCESS_CALLS, "status": status,
                "published": bool(result and result.get("published")), "shared_sync_result": result,
                "handler_wall_s": time.perf_counter()-start, "shared_sync_wall_s": sync_s,
                "process_cpu_s": time.process_time()-cpu, "import_s": import_s,
                "initial_rss_high_water_mib": initial_rss_hwm,
                "rss_high_water_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                "connection_identity_guard_s": guard_s, "connection_samples_s": metrics.connections,
                "stage_s": dict(metrics.stages), "transaction_exits": metrics.exits,
                "last_outer_transaction_exit_s": outer_exits[-1]["wall_s"] if outer_exits else None,
                "cleanup_s": cleanup_s, "sql_attempts": sum(v for k,v in metrics.attempts.items()
                    if k not in {"setup", "verification"}), "sql_observed": distribution(all_queries),
                "sql_by_phase": {k:distribution(v) for k,v in measured_queries.items()},
                "sql_total_s": sum(all_queries), "engine_checkout_peak": metrics.peak,
                "engine_checked_out_after": metrics.checked_out, "observer_checkout_bound": 1,
                "observed_peaks": peaks, "sdk_calls": client.calls,
                "synthetic_sdk_request_bytes": client.request_bytes,
                "synthetic_sdk_response_bytes": client.response_bytes,
                "http_request_body_bytes": len(raw), "application_deadline_s":
                    20 if action == "timeout_publication" else APPLICATION_DEADLINE,
                "cancellation": preservation if action in NEGATIVE_ACTIONS else None,
                "failed_noop_preservation": preservation if action not in NEGATIVE_ACTIONS
                    and status != "success" else None,
                "fixture_rows_before": rows, "successful_appends_before": appends,
                "append_verification": append_verification,
                "verification_failed": bool(append_verification and not append_verification["passed"]),
                "db_tls_bytes_received_by_phase": dict(metrics.wire.bytes),
                "db_tls_bytes_received_measured": sum(v for k, v in metrics.wire.bytes.items()
                    if k not in {"setup", "verification"}) if metrics.wire.tracked else None,
                "db_tls_tracked_connections": metrics.wire.tracked,
                "db_tls_untracked_connections": metrics.wire.untracked,
                "event_loop": type(asyncio.get_running_loop()).__module__,
                "locks_released": bool(test_lock)}
            return JSONResponse(body, headers={"Cache-Control": "private, no-store"})
