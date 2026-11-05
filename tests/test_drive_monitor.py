import asyncio

from ama.drive import DiscPresent, DiscType, DriveEmpty, DriveMissing, DriveMonitor
from ama.events import EventBus
from tests.fakes import FakeDrive


def _drain(q: asyncio.Queue[str]) -> list[str]:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def test_monitor_publishes_only_when_the_drive_changes():
    async def scenario():
        drive, bus = FakeDrive(), EventBus()
        mon = DriveMonitor(drive, bus, interval=0)
        with bus.subscribe() as q:
            await mon.poll_once()
            assert _drain(q) == [] and mon.state == DriveEmpty()

            drive.insert(DiscType.DVD, "HEAT_DISC1")
            await mon.poll_once()
            await mon.poll_once()
            assert _drain(q) == ["drive"]
            assert mon.state == DiscPresent(DiscType.DVD, "HEAT_DISC1")

            drive.eject()
            await mon.poll_once()
            assert _drain(q) == ["drive"] and mon.state == DriveEmpty()

    asyncio.run(scenario())


def test_a_probe_error_becomes_a_visible_state_not_a_crash():
    async def scenario():
        drive = FakeDrive()
        drive.fail_with(OSError("device gone"))
        mon = DriveMonitor(drive, EventBus(), interval=0)
        await mon.poll_once()
        assert isinstance(mon.state, DriveMissing)
        assert "device gone" in mon.state.reason

    asyncio.run(scenario())
