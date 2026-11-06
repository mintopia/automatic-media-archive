# Pins for AMA's self-built cyanrip (ADR 0007). Sourced by build.sh.
# Bumping anything here means a new build, a new package version and a new pin
# in src/ama/tools.py.

# Upstream master after the AccurateRip (958e1ade, #145) and -D drive letter
# (e843c0b4, #109) fixes, and the media-change polling fix (7dbe56aa, #165)
# that halved rip speed on PIONEER drives. Commits after 7dbe56aa only touch CI.
CYANRIP_REPO=https://github.com/cyanreg/cyanrip.git
CYANRIP_COMMIT=648b1dddd265cfd2bb69483a826eb5a5c7e7079e
CYANRIP_VERSION=0.9.4-rc3   # meson.build at that commit

# cyanreg's libmusicbrainz fork has no releases; this is its master.
LIBMUSICBRAINZ_REPO=https://github.com/cyanreg/libmusicbrainz.git
LIBMUSICBRAINZ_COMMIT=2398b8765ed8fa2644bdcef70f764ce6ec209431

# Release tarballs: "name version url sha256". The versions are the ones the
# pinned commit's own static build uses (.github/static-build.sh), plus
# libxml2, which upstream takes from MSYS2 for Windows.
SOURCES=(
  "curl 8.23.0 https://github.com/curl/curl/releases/download/curl-8_23_0/curl-8.23.0.tar.xz 8dadd7d2536a314f982ad05a651b713f426bf7d02cc2c76cffb9796f2218e6c5"
  "libxml2 2.15.4 https://download.gnome.org/sources/libxml2/2.15/libxml2-2.15.4.tar.xz 98087fd181d9070724f3fbc65c7377db03038eb92bd882374daff44940138821"
  "neon 0.37.1 https://notroj.github.io/neon/neon-0.37.1.tar.gz a99b7262525a454d1065cf76dd17240fd808dfc4ef15636990ff83a5d0d9e740"
  "libcdio 2.4.0 https://github.com/libcdio/libcdio/releases/download/2.4.0/libcdio-2.4.0.tar.gz bf7cde63762bb12db7755c395c441e49406fde7e1d9f9a9be7e3b940b1f405d7"
  "libcdio-paranoia 10.2+2.0.2 https://ftp.gnu.org/gnu/libcdio/libcdio-paranoia-10.2+2.0.2.tar.bz2 186892539dedd661276014d71318c8c8f97ecb1250a86625256abd4defbf0d0c"
  "lame 4.0 https://downloads.sourceforge.net/project/lame/lame/4.0/lame-4.0.tar.gz 3df5124d5ad3a98312ffd7ba6a9b36230e4f8a3e66d3ce0f425e336c32d216eb"
  "libogg 1.3.6 https://downloads.xiph.org/releases/ogg/libogg-1.3.6.tar.gz 83e6704730683d004d20e21b8f7f55dcb3383cdf84c0daedf30bde175f774638"
  "libvorbis 1.3.7 https://downloads.xiph.org/releases/vorbis/libvorbis-1.3.7.tar.xz b33cc4934322bcbf6efcbacf49e3ca01aadbea4114ec9589d1b1e9d20f72954b"
  "opus 1.6.1 https://downloads.xiph.org/releases/opus/opus-1.6.1.tar.gz 6ffcb593207be92584df15b32466ed64bbec99109f007c82205f0194572411a1"
  "ffmpeg 9.0.2 https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz 8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e"
)

# The GitHub Release the zip is published as (ADR 0015). The version names the
# upstream commit, git-describe style. The tag isn't v*.*.*, so it never starts
# the app release workflow.
PACKAGE_VERSION="$CYANRIP_VERSION-g${CYANRIP_COMMIT:0:7}"
PACKAGE_FILE="cyanrip-$PACKAGE_VERSION-win64.zip"
RELEASE_REPO=mintopia/automatic-media-archive
RELEASE_TAG="cyanrip-$PACKAGE_VERSION"
