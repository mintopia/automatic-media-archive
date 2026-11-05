import asyncio

from ama.config import NasConfig
from ama.events import EventBus
from ama.nas import NasConnected, NasMonitor, NasUnreachable
from ama.proc import ProcResult
from tests.fakes import FakeRunner

UNC = r"\\nas\media"
NET_USE_53 = "System error 53 has occurred.\n\nThe network path was not found.\n\n"


class Share:
    def __init__(self, reachable=False):
        self.reachable = reachable

    def exists(self, path: str) -> bool:
        assert path == UNC
        return self.reachable


def _monitor(share, runner, **nas):
    cfg = NasConfig(unc=UNC, **nas)
    return NasMonitor(cfg, runner=runner, bus=EventBus(), exists=share.exists)


def test_maps_the_share_with_net_use_and_the_configured_credentials():
    share = Share()

    def net_use(args):
        share.reachable = True
        return ProcResult(0, "The command completed successfully.")

    runner = FakeRunner(net_use)
    mon = _monitor(share, runner, username="ama", password="s3cret")
    asyncio.run(mon.check())
    assert runner.calls == [["net", "use", UNC, "s3cret", "/user:ama", "/persistent:no"]]
    assert mon.status == NasConnected()


def test_without_a_username_connects_as_the_logged_on_user():
    runner = FakeRunner(lambda a: ProcResult(2, NET_USE_53))
    mon = _monitor(Share(), runner)
    asyncio.run(mon.check())
    assert runner.calls == [["net", "use", UNC, "/persistent:no"]]


def test_an_already_reachable_share_is_not_remapped():
    runner = FakeRunner()
    mon = _monitor(Share(reachable=True), runner)
    asyncio.run(mon.check())
    assert runner.calls == [] and mon.status == NasConnected()


def test_failure_is_reported_with_the_reason_and_recovery_is_published():
    share = Share()
    runner = FakeRunner(lambda a: ProcResult(2, NET_USE_53))
    mon = _monitor(share, runner, username="ama", password="pw")

    async def scenario():
        with mon.bus.subscribe() as q:
            await mon.check()
            assert mon.status == NasUnreachable(UNC, "The network path was not found.")
            assert q.get_nowait() == "nas"
            await mon.check()
            assert q.empty()  # unchanged: no event
            share.reachable = True
            await mon.check()
            assert mon.status == NasConnected() and q.get_nowait() == "nas"

    asyncio.run(scenario())


def test_the_password_never_appears_in_the_reported_reason():
    runner = FakeRunner(lambda a: ProcResult(2, "net use \\\\nas\\media hunter2 failed"))
    mon = _monitor(Share(), runner, username="ama", password="hunter2")
    asyncio.run(mon.check())
    assert isinstance(mon.status, NasUnreachable)
    assert "hunter2" not in mon.status.detail
