"""Fresh-process checks: imports elsewhere in the suite cannot hide eager setup."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LazyDatabaseTests(unittest.TestCase):
    def run_fresh(self, source):
        env = {key: value for key, value in os.environ.items()
               if key not in {"DATABASE_URL", "EXPECTED_DATABASE_NAME"}}
        result = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(source)], cwd=ROOT, env=env,
            text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_import_without_database_url_does_not_construct_resources(self):
        self.run_fresh('''
            from unittest.mock import patch
            with patch('sqlalchemy.ext.asyncio.create_async_engine') as create, \\
                 patch('sqlalchemy.ext.asyncio.async_sessionmaker') as sessions:
                import api.db
                from api.db import engine, SessionLocal
                create.assert_not_called()
                sessions.assert_not_called()
        ''')

    def test_each_first_use_without_url_has_clear_error(self):
        for expression in ('engine.connect()', 'engine.begin()', 'engine.url',
                           'SessionLocal()', 'SessionLocal.begin()'):
            with self.subTest(expression=expression):
                self.run_fresh(f'''
                    from api.db import engine, SessionLocal
                    try:
                        {expression}
                    except RuntimeError as error:
                        assert str(error) == 'DATABASE_URL is required before using the database'
                    else:
                        raise AssertionError('missing configuration accepted')
                ''')

    def test_configuration_can_be_set_after_import_and_failed_first_use(self):
        self.run_fresh('''
            import os
            from api.db import engine, SessionLocal
            try:
                SessionLocal()
            except RuntimeError:
                pass
            os.environ['DATABASE_URL'] = 'postgresql+asyncpg://test@127.0.0.1:55440/lazy'
            session = SessionLocal()
            assert session.bind.sync_engine is engine.sync_engine
            assert session.sync_session.expire_on_commit is False
            assert engine.url.database == 'lazy'
            original = engine.sync_engine
            os.environ['DATABASE_URL'] = 'invalid-after-initialization'
            assert engine.sync_engine is original
            assert SessionLocal().bind is session.bind
        ''')

    def test_blank_url_is_rejected(self):
        self.run_fresh('''
            import os
            from api.db import SessionLocal
            os.environ['DATABASE_URL'] = '   '
            try:
                SessionLocal.begin()
            except RuntimeError as error:
                assert 'DATABASE_URL is required' in str(error)
            else:
                raise AssertionError('blank configuration accepted')
        ''')

    def test_session_begin_and_keyword_arguments_remain_usable(self):
        self.run_fresh('''
            import asyncio
            import os
            from api.db import engine, SessionLocal
            os.environ['DATABASE_URL'] = 'postgresql+asyncpg://test@127.0.0.1:55440/lazy'
            async def check():
                async with SessionLocal(info={'test': True}) as session:
                    assert session.info == {'test': True}
                async with SessionLocal.begin() as session:
                    assert session.in_transaction()
                    assert session.bind.sync_engine is engine.sync_engine
                await engine.dispose()
            asyncio.run(check())
        ''')

    def test_parallel_first_use_constructs_one_engine_and_factory(self):
        self.run_fresh('''
            from concurrent.futures import ThreadPoolExecutor
            import os
            import time
            from unittest.mock import patch
            from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
            from api.db import SessionLocal
            os.environ['DATABASE_URL'] = 'postgresql+asyncpg://test@127.0.0.1:55440/lazy'
            def slow_engine(*args, **kwargs):
                time.sleep(0.02)
                return create_async_engine(*args, **kwargs)
            with patch('api.db.create_async_engine', side_effect=slow_engine) as create, \\
                 patch('api.db.async_sessionmaker', wraps=async_sessionmaker) as factory:
                with ThreadPoolExecutor(max_workers=8) as workers:
                    sessions = list(workers.map(lambda _: SessionLocal(), range(16)))
                create.assert_called_once()
                factory.assert_called_once()
                assert all(session.bind is sessions[0].bind for session in sessions)
        ''')

    def test_public_engine_patch_is_used_without_database_url(self):
        self.run_fresh('''
            import asyncio
            import os
            from unittest.mock import AsyncMock, MagicMock, patch
            import api.db as database
            fake = MagicMock()
            connection = AsyncMock()
            connection.scalar.return_value = 'synthetic'
            fake.connect.return_value.__aenter__.return_value = connection
            os.environ['EXPECTED_DATABASE_NAME'] = 'synthetic'
            with patch.object(database, 'engine', fake):
                asyncio.run(database.verify_database_name())
            fake.connect.assert_called_once()
            connection.scalar.assert_awaited_once()
        ''')

    def test_engine_proxy_behaves_like_an_async_engine(self):
        self.run_fresh('''
            import os
            from sqlalchemy.ext.asyncio import AsyncEngine
            from unittest.mock import patch
            with patch('api.db.create_async_engine') as create:
                from api.db import engine
                # Type checks and repr must not construct the engine or need configuration.
                assert isinstance(engine, AsyncEngine)
                assert 'not created' in repr(engine)
                create.assert_not_called()
            os.environ['DATABASE_URL'] = 'postgresql+asyncpg://test@127.0.0.1:55440/lazy'
            real = engine._get()
            assert engine == real and real == engine
            assert hash(engine) == hash(real)
            assert {engine: 1}[real] == 1
            assert repr(engine) == repr(real)
        ''')

    def test_session_factory_keeps_the_engine_bound_at_first_use(self):
        # Same as the eager module: patching api.db.engine later does not rebind
        # SessionLocal. Tests that need another database build their own factory.
        self.run_fresh('''
            import os
            from unittest.mock import MagicMock, patch
            import api.db as database
            os.environ['DATABASE_URL'] = 'postgresql+asyncpg://test@127.0.0.1:55440/lazy'
            first = database.SessionLocal().bind
            with patch.object(database, 'engine', MagicMock()):
                assert database.SessionLocal().bind is first
        ''')
