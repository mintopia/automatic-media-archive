# Automatic Media Archive

Put a Disc in, it turns up in Plex. AMA runs on the Windows PC with your optical drive:
it rips your CDs, DVDs and Blu-rays, works out what each one is, encodes it and archives it
into your Plex Libraries, named the way Plex expects. It only asks you when it can't tell,
in a web UI you can open from any device at home.

- **Download:** the installer is on the
  [latest release](https://github.com/mintopia/automatic-media-archive/releases/latest)
  (Windows 10 and 11). DVDs and Blu-rays also need [MakeMKV](https://www.makemkv.com).
- **Docs:** [mintopia.github.io/automatic-media-archive](https://mintopia.github.io/automatic-media-archive/):
  install, Setup, how a Disc flows, Naming Patterns and every setting.
- **Licence:** [MIT](LICENSE). The tools and libraries AMA uses are listed, with their
  licences, in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- **Contributing:** [CONTRIBUTING.md](CONTRIBUTING.md). Run it from source with
  `uv sync` and `uv run ama`, and test it with `uv run pytest` (no drive needed).
