# Test fixtures

- `makemkv-licence-too-old.txt`: **real** output of `makemkvcon64 -r --cache=1 info disc:9999`
  on the archive PC (MakeMKV 1.18.2, unregistered), 2026-11-04.
- `makemkv-drives-no-disc.txt`: **real** output of the same command with MakeMKV 2.0.0
  (registered), drive empty, 2026-11-04. Exit code 0.
- `makemkv-info-bd.txt`, `makemkv-mkv-title.txt`: **synthetic** but format-accurate
  robot output (line grammar, attribute ids and MSG codes per MakeMKV's usage.txt,
  apdefs.h and other projects' captures). The PRGT codes, 3309 and the 6202/6203
  stream-type codes are unverified. Replace them with real captures once MakeMKV
  is registered and a Disc can be scanned.
- `makemkv-info-bd-decoys.txt`: **synthetic** robot output in the same format, modelled on
  forum reports of decoy-playlist BDs (notes/research/makemkvcon.md §7): 14 Titles
  `00800-00813.mpls` within 4 s of 2:50:12, same 12 clips; only `00805.mpls` (Title 6) plays
  them in order (`1-12`), the rest are shuffled; plus 2 extras. No real decoy Disc has been
  scanned yet: replace with a real capture when one turns up.
- `musicbrainz/discid-ffvii-rebirth-disc1.json`: **real** MusicBrainz response,
  `GET /ws/2/discid/kIBdaUqY_5kMBgOXehaFmL5TSbA-?inc=recordings+artist-credits&fmt=json`,
  2026-11-04, for disc 1 of the FINAL FANTASY VII REBIRTH OST (the CD in the archive PC's
  drive). It matches 3 releases (two 8-CD "Special edit version" entries, one 7-CD
  regular edition), all on medium 1. The Disc's MCN 4988601470865 is release
  139f3172's barcode. No `release-group`/`label-info` (not in that `inc`).
- `cyanrip/info-ffvii-rebirth-disc1.txt`: **real** `cyanrip -d D: -I -N -U` stdout for the
  same Disc (cyanrip 0.9.3).
- `makemkv-unregistered-v2.0.0.txt`: **real** output of `makemkvcon64 -r --cache=1 info disc:9999`
  with MakeMKV 2.0.0 and no `app_Key` in `HKCU\Software\MakeMKV`, drive empty, 2026-11-04.
  It runs normally; the registration check reads the registry, not this output.
- `ffmpeg/sample-*.txt`: **real** ffmpeg 9.0.2 output (stdout+stderr) of one picture-analysis
  sample, `ffmpeg -hide_banner -nostdin -nostats [-hwaccel cuda] -ss T -i src.mkv -map 0:v:0
  -frames:v 240 -vf "idet,cropdetect=limit=0.1:round=2:reset_count=0" -an -sn -f null -`,
  2026-11-04, on **synthetic** MPEG-2 720x480 sources (lavfi, letterboxed to 720x360 at y=60
  unless noted): `progressive` (mandelbrot, 23.976p; idet undecided), `progressive-busy`
  (testsrc2, 23.976p; idet misreads it as combed with mixed field order), `telecined` /
  `telecined-busy` (those through `telecine=pattern=23`, 29.97 TFF; ~38% repeated fields),
  `interlaced` (testsrc2 59.94p woven to 29.97 TFF, full frame, no bars), `dark-scene`
  (near-black picture with one small bright box), `black` (all black: cropdetect prints a
  negative box). Not real Discs: idet thresholds still need calibrating on real DVDs.
- `ffprobe/hdr10-source.json`: **real** `ffprobe -v error -select_streams v:0 -read_intervals
  %+#1 -show_streams -show_frames -of json` (AMA's ffprobe 9.0.2) of a 3 s 3840x2160 HDR10
  clip made with libx265 (`hdr10=1`, master-display G(13250,34500)B(7500,3000)R(34000,16000)
  WP(15635,16450)L(10000000,50), max-cll 1000,400), 2026-11-04. Frame side data = SEI.
- `ffprobe/hdr10-encode.json`: the same command on that clip after AMA's hevc_nvenc Encode
  (`-hwaccel cuda`, temporal AQ, b_ref_mode middle, explicit colour tags) on the archive PC's
  RTX 3060 Ti, driver 621.01. Stream side data comes back with reduced fractions (17/25).
- The LibreDrive lines in `FakeMakemkv` are not captured: no UHD Disc has been scanned yet.
- `flac/ffmpeg-tagged-sine.flac`: **real** FLAC from AMA's pinned ffmpeg 9.0.2, `ffmpeg -f lavfi -i
  sine=frequency=440:sample_rate=44100:duration=1 -ac 2 -sample_fmt s16 -metadata TITLE="Track 01"
  -metadata ARTIST=Unknown -metadata TRACKNUMBER=1 -metadata CYANRIP=0.9.3.1 out.flac`, 2026-11-06.
  cyanrip writes its rips through the same libavformat FLAC muxer, so the layout matches a rip:
  STREAMINFO, VORBIS_COMMENT (vendor `Lavf…`), 8192 bytes of PADDING, then the audio frames.
  Not an actual cyanrip rip (no CD was in the drive): replace with one when there is.
