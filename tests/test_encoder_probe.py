"""The encoder probe (ADR 0010): a short test encode per encoder, at startup and on
save, so Settings offers only encoders that work and the tools banner can warn."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from ama.config import CqConfig, EncodeConfig
from ama.encoder_probe import EncoderProbe, ProbeFailed, ProbeUntested, ProbeWorks
from ama.events import EventBus, Topic
from ama.tools import ToolPending, ToolUnavailable


class FakeStreamer:
    def __init__(self, broken: set[str]) -> None:
        self.broken = broken
        self.calls: list[list[str]] = []

    def __call__(self, args, on_line, cwd=None) -> int:
        args = list(args)
        self.calls.append(args)
        encoder = args[args.index("-c:v") + 1]
        if encoder in self.broken:
            on_line(f"[{encoder} @ 0000] No capable devices found")
            on_line("Error while opening encoder")
            return 1
        return 0


def _probe(broken: set[str], cfg: EncodeConfig | None = None, ffmpeg_ready=lambda: True):
    cfg = cfg or EncodeConfig(cq=CqConfig(dvd=20, bd=22, uhd=22))
    streamer = FakeStreamer(broken)
    bus = EventBus()

    def tool(name: str) -> Path:
        if not ffmpeg_ready():
            raise ToolUnavailable(name, ToolPending())
        return Path("ffmpeg.exe")

    clock = iter(datetime(2026, 11, 5, 20, m) for m in range(14, 60))
    probe = EncoderProbe(bus, tool, streamer, lambda: cfg, clock=lambda: next(clock),
                         retry_seconds=0.01)
    return probe, streamer, bus


def test_every_encoder_is_test_encoded_and_only_the_working_ones_are_offered():
    probe, streamer, _ = _probe({"av1_nvenc", "hevc_qsv"})
    assert all(isinstance(s, ProbeUntested) for s in probe.states.values())
    asyncio.run(probe.probe_all())
    assert sorted(probe.working()) == ["hevc_nvenc", "libx265"]
    failed = probe.states["av1_nvenc"]
    assert isinstance(failed, ProbeFailed) and "No capable devices" in failed.detail
    assert isinstance(probe.states["hevc_nvenc"], ProbeWorks)
    test = streamer.calls[0]
    assert test[test.index("-i") + 1].startswith("testsrc2=size=1920x1080")
    assert test[-3:] == ["-f", "null", "-"]


def test_the_test_encode_uses_the_configured_speed():
    cfg = EncodeConfig(cq=CqConfig(dvd=20, bd=22, uhd=22), speed="slowest")
    probe, streamer, _ = _probe(set(), cfg)
    asyncio.run(probe.probe_all())
    nvenc = next(c for c in streamer.calls if "hevc_nvenc" in c)
    assert nvenc[nvenc.index("-multipass") + 1] == "fullres"


def test_a_configured_encoder_that_stops_working_is_reported_with_the_test_time():
    probe, streamer, _ = _probe(set())
    asyncio.run(probe.probe_all())
    assert probe.problem() is None
    streamer.broken.add("hevc_nvenc")
    asyncio.run(probe.probe_all())
    problem = probe.problem()
    assert problem is not None
    assert problem.label == "HEVC (NVIDIA)" and problem.stopped
    assert problem.at.strftime("%H:%M") == "20:15"
    assert "hevc_nvenc" not in probe.working()


def test_a_configured_encoder_that_never_worked_is_reported_too():
    probe, _, _ = _probe({"hevc_nvenc"})
    asyncio.run(probe.probe_all())
    problem = probe.problem()
    assert problem is not None and not problem.stopped


def test_run_waits_for_ffmpeg_tests_at_startup_and_again_on_request():
    ready = {"ffmpeg": False}
    probe, streamer, bus = _probe(set(), ffmpeg_ready=lambda: ready["ffmpeg"])

    async def scenario() -> list[str]:
        with bus.subscribe() as q:
            task = asyncio.create_task(probe.run())
            await asyncio.sleep(0.05)
            assert streamer.calls == []  # ffmpeg is still downloading
            ready["ffmpeg"] = True
            while len(streamer.calls) < 4:
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.05)
            assert len(streamer.calls) == 4  # once, until asked again
            probe.request()  # Settings saved
            while len(streamer.calls) < 8:
                await asyncio.sleep(0.01)
            task.cancel()
            topics = []
            while not q.empty():
                topics.append(q.get_nowait())
            return topics

    topics = asyncio.run(scenario())
    assert len(streamer.calls) == 8
    assert Topic.TOOLS in topics  # the tools banner re-renders
