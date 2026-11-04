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
- `ffprobe/hdr10-source.json`: **real** `ffprobe -v error -select_streams v:0 -read_intervals
  %+#1 -show_streams -show_frames -of json` (AMA's ffprobe 9.0.2) of a 3 s 3840x2160 HDR10
  clip made with libx265 (`hdr10=1`, master-display G(13250,34500)B(7500,3000)R(34000,16000)
  WP(15635,16450)L(10000000,50), max-cll 1000,400), 2026-11-04. Frame side data = SEI.
- `ffprobe/hdr10-encode.json`: the same command on that clip after AMA's hevc_nvenc Encode
  (`-hwaccel cuda`, temporal AQ, b_ref_mode middle, explicit colour tags) on the archive PC's
  RTX 3060 Ti, driver 621.01. Stream side data comes back with reduced fractions (17/25).
- The LibreDrive lines in `FakeMakemkv` are not captured: no UHD Disc has been scanned yet.
