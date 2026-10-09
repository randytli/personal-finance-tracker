import os
from threading import Lock

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, async_sessionmaker

from api.models import Base
from api.migrations import (migrate_multi_institution, migrate_manual_categories,
                            migrate_consumer_scope, migrate_statement_imports,
                            migrate_transaction_labels, migrate_benefit_categories,
                            migrate_sync_runs, migrate_institution_lifecycle,
                            require_lifecycle_preflight)

class _LazyEngine:
    """Keep imported engine references stable without reading configuration yet."""

    def __init__(self):
        self._engine = None
        self._lock = Lock()

    def _get(self):
        with self._lock:
            if self._engine is None:
                url = os.environ.get("DATABASE_URL")
                if not url or not url.strip():
                    raise RuntimeError("DATABASE_URL is required before using the database")
                self._engine = create_async_engine(url, echo=False, pool_pre_ping=True)
            return self._engine

    def __getattr__(self, name):
        return getattr(self._get(), name)

    # __getattr__ does not cover special methods. AsyncEngine defines only
    # __eq__/__hash__ beyond object, so forward those and report the engine type
    # (without constructing it) for isinstance checks.
    @property
    def __class__(self):
        return AsyncEngine

    def __eq__(self, other):
        if isinstance(other, _LazyEngine) and type(other) is _LazyEngine:
            other = other._get()
        return self._get() == other

    def __hash__(self):
        return hash(self._get())

    def __repr__(self):
        return repr(self._engine) if self._engine is not None else "<lazy AsyncEngine (not created)>"


class _LazySessionFactory:
    """Defer the sessionmaker while retaining SessionLocal() and .begin().

    Like the former eager module, the factory binds the engine that exists at
    first use; patching api.db.engine afterwards does not rebind it."""

    def __init__(self):
        self._factory = None
        self._lock = Lock()

    def _get(self):
        with self._lock:
            if self._factory is None:
                bind = engine._get() if isinstance(engine, _LazyEngine) else engine
                self._factory = async_sessionmaker(bind, expire_on_commit=False)
            return self._factory

    def __call__(self, **kwargs):
        return self._get()(**kwargs)

    def __getattr__(self, name):
        return getattr(self._get(), name)


# Stable objects preserve `from api.db import ...` callers. Helpers below still
# look up the public engine, so patch.object(database, "engine", ...) works.
engine = _LazyEngine()
SessionLocal = _LazySessionFactory()

async def init_db():
    async with engine.begin() as connection:
        # Mandatory read-only gate: Production stops here, before any DDL, unless
        # every Item is in a state the lifecycle migration supports.
        await require_lifecycle_preflight(
            connection, production=os.environ.get("PLAID_ENV", "").lower() == "production")
        await connection.run_sync(Base.metadata.create_all)
        await migrate_multi_institution(connection)
        await migrate_manual_categories(connection)
        await migrate_consumer_scope(connection)
        await migrate_statement_imports(connection)
        await migrate_transaction_labels(connection)
        await migrate_benefit_categories(connection)
        await migrate_sync_runs(connection)
        await migrate_institution_lifecycle(connection)


async def verify_database_name():
    """Fail before startup/migration when a configured database identity differs."""
    expected = os.environ.get("EXPECTED_DATABASE_NAME")
    if not expected and os.environ.get("PLAID_ENV", "").lower() != "production":
        return
    if not expected:
        raise RuntimeError("EXPECTED_DATABASE_NAME is required in Production")
    async with engine.connect() as connection:
        actual = await connection.scalar(text("select current_database()"))
    if actual != expected:
        raise RuntimeError(
            "Database safety check failed: connected database does not "
            "match EXPECTED_DATABASE_NAME"
        )


async def verify_runtime_schema():
    """Runtime startup is read only; migrations require an explicit command."""
    missing = []
    async with engine.connect() as connection:
        # Resolve each relation through the same search_path the ORM uses. A
        # similarly named table in another schema must not satisfy this check.
        for table in Base.metadata.sorted_tables:
            columns = set((await connection.execute(text(
                "SELECT attname FROM pg_catalog.pg_attribute "
                "WHERE attrelid=to_regclass(:name) AND attnum>0 AND NOT attisdropped"
            ), {"name": table.name})).scalars())
            missing.extend(f"{table.name}.{column.name}" for column in table.columns
                           if column.name not in columns)
        for table, trigger in (
            ("transaction_label_definitions", "pft_label_definition_guard"),
            ("manual_transaction_label_overrides", "pft_label_association_guard"),
            ("items", "pft_label_item_owner_guard"),
            ("raw_transactions", "pft_label_raw_owner_guard"),
        ):
            present = await connection.scalar(text(
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_trigger "
                "WHERE tgrelid=to_regclass(:table) AND tgname=:trigger "
                "AND NOT tgisinternal AND tgenabled IN ('O','A'))"),
                {"table": table, "trigger": trigger})
            if not present:
                missing.append(f"{table}.{trigger}")
        label_fk = await connection.scalar(text(
            "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_constraint "
            "WHERE conrelid=to_regclass('manual_transaction_label_overrides') "
            "AND conname='fk_manual_transaction_label' AND contype='f' AND convalidated)"))
        if not label_fk:
            missing.append("manual_transaction_label_overrides.fk_manual_transaction_label")
    if missing:
        raise RuntimeError("Runtime schema is incomplete; run explicit migration: " + ", ".join(missing))
