from ama.proc import split_lines


def test_progress_redraws_and_lines_split_across_chunks():
    chunks = [b"Disc tracks:    2\r\nRipping track 1, progress - 1",
              b"0.00%\rRipping track 1, progress - 20.00%\r", b"\nTrack 1 ripped", b" ok\n",
              "Album:          ’70s".encode()[:-3], "’70s".encode()[-3:] + b" Gold"]
    assert list(split_lines(chunks)) == [
        "Disc tracks:    2", "Ripping track 1, progress - 10.00%",
        "Ripping track 1, progress - 20.00%", "Track 1 ripped ok", "Album:          ’70s Gold"]
