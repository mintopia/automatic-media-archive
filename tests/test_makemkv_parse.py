"""makemkvcon robot-output parsing.

`makemkv-licence-too-old.txt` is real output captured on the archive PC
(MakeMKV 1.18.2, unregistered). The `info`/`mkv` fixtures are format-accurate
but synthetic (no licensed run was possible yet); see tests/data/README.md.
"""

from pathlib import Path

from ama.drive import DiscType
from ama.makemkv import (
    Msg,
    licence_problem,
    parse_line,
    parse_scan,
    rip_summary,
    select_titles,
)

DATA = Path(__file__).parent / "data"


def lines(name: str) -> list[str]:
    return (DATA / name).read_text(encoding="utf-8").splitlines()


def test_real_licence_failure_is_detected():
    msgs = [m for m in map(parse_line, lines("makemkv-licence-too-old.txt")) if isinstance(m, Msg)]
    assert [m.code for m in msgs] == [1005, 5075, 5021]
    assert msgs[2].params == ("http://www.makemkv.com/",)
    assert "too old" in msgs[2].text
    assert [licence_problem(m, DiscType.BD) for m in msgs] == [False, False, True]


def test_new_version_banner_is_not_a_licence_problem():
    banner = parse_line('MSG:5075,131072,2,"The new version 1.18.3 is available","x","1.18.3","u"')
    assert not licence_problem(banner, DiscType.DVD)


def test_expired_evaluation_still_allows_dvds():
    expired = Msg(code=5052, flags=0, text="Evaluation period has expired.", params=())
    assert licence_problem(expired, DiscType.BD)
    assert not licence_problem(expired, DiscType.DVD)


def test_quoted_fields_with_commas_and_escapes():
    m = parse_line(r'MSG:3307,0,2,"File a, \"b\".mpls was added as title #0","File %1 was added as title #%2","a, \"b\".mpls","0"')
    assert m == Msg(3307, 0, 'File a, "b".mpls was added as title #0', ('a, "b".mpls', "0"))


def test_scan_lists_titles_with_durations_sizes_and_tracks():
    scan = parse_scan(lines("makemkv-info-bd.txt"))
    assert [d.index for d in scan.drives if d.has_disc] == [0]
    assert scan.drives[0].device == "D:"
    t0 = scan.titles[0]
    assert (t0.id, t0.duration_s, t0.size_bytes) == (0, 2 * 3600 + 1 * 60 + 33, 33501239296)
    assert (t0.audio, t0.subtitles) == (2, 3)
    assert t0.segments_map == "1"
    assert t0.output_file == "Example_Movie_t00.mkv"
    assert [t.id for t in scan.titles] == [0, 1, 2, 3]
    assert scan.skipped_short == 11
    assert scan.skipped_duplicates == 1


def test_select_drops_exact_duplicates_and_short_titles():
    scan = parse_scan(lines("makemkv-info-bd.txt"))
    sel = select_titles(scan.titles, min_seconds=30)
    assert [t.id for t in sel.keep] == [0, 1]
    # title 2 has the same segments as title 0; title 3 is 12 s long
    assert [(d.id, of.id) for d, of in sel.duplicates] == [(2, 0)]
    assert [t.id for t in sel.short] == [3]


def test_rip_summary_reads_saved_and_failed_counts():
    out = lines("makemkv-mkv-title.txt")
    assert rip_summary(map(parse_line, out)) == (1, 0)
    assert rip_summary(map(parse_line, ["MSG:5011,0,0,\"x\",\"x\""])) is None
