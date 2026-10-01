"""Draft capability ordering and invocation-owned lifecycle, no DB or SDK."""
import unittest
from unittest.mock import AsyncMock, Mock, patch

from scripts.pft_m5_scheduler_draft import run_scheduler_once


class SchedulerDraftTests(unittest.IsolatedAsyncioTestCase):
    async def test_capability_denied_before_engine_creation(self):
        factory = Mock()
        with self.assertRaises(PermissionError):
            await run_scheduler_once("synthetic", verify_capability=AsyncMock(side_effect=PermissionError),
                engine_factory=factory, verify_identity=AsyncMock(), sync=AsyncMock(), backup_fn=None)
        factory.assert_not_called()

    async def test_identity_denied_disposes_without_tick(self):
        engine = Mock(dispose=AsyncMock())
        with patch("scripts.pft_m5_scheduler_draft.tick", new_callable=AsyncMock) as poll:
            with self.assertRaises(RuntimeError):
                await run_scheduler_once("synthetic", verify_capability=AsyncMock(),
                    engine_factory=Mock(return_value=engine), verify_identity=AsyncMock(side_effect=RuntimeError),
                    sync=AsyncMock(), backup_fn=None)
            poll.assert_not_called()
        engine.dispose.assert_awaited_once()

    async def test_cancellation_disposes_invocation_engine(self):
        import asyncio
        engine = Mock(dispose=AsyncMock())
        with patch("scripts.pft_m5_scheduler_draft.tick", new_callable=AsyncMock,
                   side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await run_scheduler_once("synthetic", verify_capability=AsyncMock(),
                    engine_factory=Mock(return_value=engine), verify_identity=AsyncMock(),
                    sync=AsyncMock(), backup_fn=None)
        engine.dispose.assert_awaited_once()
