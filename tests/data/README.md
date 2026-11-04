# Test fixtures

- `makemkv-licence-too-old.txt`: **real** output of `makemkvcon64 -r --cache=1 info disc:9999`
  on the archive PC (MakeMKV 1.18.2, unregistered), 2026-11-04.
- `makemkv-info-bd.txt`, `makemkv-mkv-title.txt`: **synthetic** but format-accurate
  robot output (line grammar, attribute ids and MSG codes per MakeMKV's usage.txt,
  apdefs.h and other projects' captures). The PRGT codes, 3309 and the 6202/6203
  stream-type codes are unverified. Replace them with real captures once MakeMKV
  is registered and a Disc can be scanned.
