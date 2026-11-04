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
