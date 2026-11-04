#!/bin/bash
# Builds AMA's portable Windows cyanrip (ADR 0007) inside MSYS2 MINGW64.
# Run it through build.ps1, which sets up the pinned MSYS2 first.
#
#   build.sh [step...]   no steps = everything; e.g. "build_ffmpeg build_cyanrip"
#   build.sh publish     PUT the zip to the Forgejo generic package registry
#
# Every third-party library is built from a pinned, SHA-256 checked source
# and linked statically, so cyanrip.exe needs nothing but Windows DLLs.
# Work happens under $AMA_BUILD_ROOT (outside any git checkout, so meson's
# vcs_tag sees cyanrip's commit, not AMA's).

set -eo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/versions.sh"

[[ $MSYSTEM == MINGW64 ]] || { echo "run this in MSYS2 MINGW64 (use build.ps1)" >&2; exit 1; }
ROOT="${AMA_BUILD_ROOT:?set AMA_BUILD_ROOT (build.ps1 does)}"
SRC="$ROOT/sources"         # downloads, kept between runs
WORK="$ROOT/work"           # unpacked sources, wiped per library
PREFIX="$ROOT/install"      # static libraries
OUT="$ROOT/out"
JOBS="$(nproc)"

export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig"
export CPPFLAGS="-I$PREFIX/include -D_FORTIFY_SOURCE=0 -D__USE_MINGW_ANSI_STDIO=1 -DLIBXML_STATIC -DCURL_STATICLIB"
export CFLAGS="-O2 -pipe -mtune=generic"
export CXXFLAGS="$CFLAGS"
export LDFLAGS="-L$PREFIX/lib -static -static-libgcc"

# "name version url sha256" from SOURCES, by name.
src_field() {
    local name=$1 field=$2 line
    for line in "${SOURCES[@]}"; do
        set -- $line
        [[ $1 == "$name" ]] && { case $field in version) echo "$2" ;; url) echo "$3" ;; sha) echo "$4" ;; esac; return; }
    done
    echo "no source pinned for $name" >&2; exit 1
}

# Downloads (once) and checks a pinned tarball, unpacks it fresh and enters it.
unpack() {
    local name=$1 url sha file dir
    url="$(src_field "$name" url)"; sha="$(src_field "$name" sha)"
    file="$SRC/${url##*/}"
    mkdir -p "$SRC" "$WORK"
    if [[ ! -f $file ]] || ! echo "$sha *$file" | sha256sum -c --status; then
        curl -fL --retry 10 --retry-all-errors --retry-delay 15 --connect-timeout 30 -o "$file.part" "$url"
        mv -f "$file.part" "$file"
    fi
    echo "$sha *$file" | sha256sum -c --status || { echo "$file failed its SHA-256 check" >&2; exit 1; }
    dir="$name-$(src_field "$name" version)"
    rm -rf "$WORK/$dir"
    tar -xf "$file" -C "$WORK"
    cd "$WORK/$dir"
}

# Fetches exactly one commit; git checks the content against the hash.
checkout() {
    local url=$1 commit=$2 dir=$3
    rm -rf "$WORK/$dir"
    git init -q "$WORK/$dir"
    cd "$WORK/$dir"
    git fetch -q --depth 1 "$url" "$commit"
    git -c advice.detachedHead=false checkout -q FETCH_HEAD
    [[ $(git rev-parse HEAD) == "$commit" ]]
}

confmakeinstall() {
    ./configure --disable-shared --enable-static --prefix="$PREFIX" "$@"
    make -j"$JOBS"
    make install
}

cmakeinstall() {
    cmake -B _build -G Ninja -DBUILD_SHARED_LIBS=OFF \
        -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
        -DCMAKE_INSTALL_PREFIX="$(cygpath -m "$PREFIX")" \
        -DCMAKE_INSTALL_LIBDIR=lib \
        -DCMAKE_PREFIX_PATH="$(cygpath -m "$PREFIX")" \
        -DCMAKE_BUILD_TYPE=Release "$@"
    ninja -C _build
    ninja -C _build install
}

build_curl() {
    # HTTPS through Windows' own TLS (Schannel) and certificate store.
    # CMake, not autotools: libtool under MSYS2 takes ages, and this skips the
    # curl tool and the test libraries. Same protocol set as upstream's build.
    unpack curl
    cmakeinstall -DBUILD_STATIC_LIBS=ON -DBUILD_CURL_EXE=OFF -DBUILD_TESTING=OFF \
        -DBUILD_LIBCURL_DOCS=OFF -DBUILD_MISC_DOCS=OFF -DENABLE_CURL_MANUAL=OFF \
        -DCURL_USE_SCHANNEL=ON -DCURL_USE_OPENSSL=OFF -DCURL_USE_LIBPSL=OFF -DCURL_USE_LIBSSH2=OFF \
        -DUSE_NGHTTP2=OFF -DUSE_LIBIDN2=OFF -DUSE_WIN32_IDN=OFF -DCURL_ZLIB=OFF -DCURL_BROTLI=OFF -DCURL_ZSTD=OFF \
        -DCURL_DISABLE_{LDAP,LDAPS,RTSP,DICT,TELNET,TFTP,POP3,IMAP,SMB,SMTP,GOPHER,MQTT,FTP,FILE,NTLM}=ON \
        -DENABLE_UNIX_SOCKETS=OFF
}

build_libxml2() {
    unpack libxml2
    confmakeinstall --without-{python,lzma,icu,http,zlib} --with-iconv
}

build_neon() {
    unpack neon
    ./configure --disable-shared --enable-static --prefix="$PREFIX" \
        --disable-{nls,debug,webdav} --without-ssl --with-libxml2
    make -j"$JOBS"
    make install-lib install-headers install-config
}

build_libmusicbrainz() {
    checkout "$LIBMUSICBRAINZ_REPO" "$LIBMUSICBRAINZ_COMMIT" libmusicbrainz
    cmakeinstall
}

build_libcdio() {
    unpack libcdio
    confmakeinstall --disable-{cxx,example-progs,cddb,vcd-info} \
        --without-{cd-drive,cd-info,cdda-player,cd-read,iso-info,iso-read}
}

build_libcdio_paranoia() {
    # Its cd-paranoia program has K&R declarations, which GCC 15's default C23 rejects.
    unpack libcdio-paranoia
    CFLAGS="$CFLAGS -std=gnu17" confmakeinstall --disable-{cxx,example-progs}
}

build_lame() {
    unpack lame
    CFLAGS="$CFLAGS -std=gnu17" confmakeinstall --disable-{frontend,decoder,gtktest}
}

build_libogg() {
    unpack libogg
    cmakeinstall -DBUILD_TESTING=OFF -DINSTALL_DOCS=OFF
}

build_libvorbis() {
    unpack libvorbis
    cmakeinstall
}

build_opus() {
    unpack opus
    cmakeinstall -DOPUS_BUILD_PROGRAMS=OFF -DOPUS_BUILD_TESTING=OFF -DOPUS_BUILD_SHARED_LIBRARY=OFF
}

build_ffmpeg() {
    # The pinned commit's own feature set (.github/static-build.sh).
    unpack ffmpeg
    ./configure --prefix="$PREFIX" --pkg-config-flags=--static \
        --disable-shared --enable-static \
        --disable-{programs,devices,filters,decoders,hwaccels,encoders,muxers} \
        --disable-{debug,protocols,demuxers,parsers,doc,swscale,network} \
        --disable-{avdevice,autodetect} \
        --disable-bsfs --enable-protocol=file,data \
        --enable-encoder=flac,tta,aac,wavpack,alac,pcm_s16le,pcm_s32le,pcm_f64le \
        --enable-muxer=flac,tta,ipod,wv,mp3,opus,ogg,wav,pcm_s16le,pcm_s32le,image2,singlejpeg \
        --enable-parser=png,mjpeg --enable-decoder=mjpeg,png \
        --enable-demuxer={image2,image_jpeg_pipe,image_png_pipe} \
        --enable-{bzlib,zlib,iconv} \
        --enable-filter={hdcd,aemphasis,ebur128,anullsink,aresample} \
        --enable-lib{mp3lame,vorbis,opus} \
        --enable-encoder={libmp3lame,libvorbis,libopus}
    make -j"$JOBS"
    make install
}

build_cyanrip() {
    # libqrencode and chromaprint are left out on purpose: AMA does its own
    # MusicBrainz work, and no QR codes or AcoustID fingerprints are wanted.
    checkout "$CYANRIP_REPO" "$CYANRIP_COMMIT" cyanrip
    meson setup _build --buildtype=release --default-library=static --prefer-static \
        "-Dc_link_args=['-static','-Wl,--no-insert-timestamp']"
    ninja -C _build
    # Upstream runs its tests on Linux/macOS only. Two harness gaps on Windows:
    # the FUN512 unit test needs POSIX mkstemp (verify_log below covers log
    # checksums), and meson hands the image tests a relative exe path that
    # Windows can't start. So: the other unit tests via meson, and every
    # disc-image rip scenario directly, with an absolute path.
    meson test -C _build --print-errorlogs "Naming schemes" "JSON reader" "Option parsing"
    local s scenarios
    scenarios="$(sed -n "/^rip_scenarios = \[/,/^\]/s/^ *'\([a-z_]*\)',*/\1/p" tests/meson.build)"
    [[ -n $scenarios ]] || { echo "no rip scenarios found in tests/meson.build" >&2; exit 1; }
    for s in $scenarios; do
        PYTHONUTF8=1 CUE_TRACK_NUMBERS=0 python tests/rip_images.py \
            "$PWD/_build/src/cyanrip.exe" "$PWD/tests/fixtures" "$s"
    done
    strip --strip-all _build/src/cyanrip.exe -o cyanrip.exe
}

# Proves the exe is portable and is the pinned commit, then zips it.
package() {
    local exe="$WORK/cyanrip/cyanrip.exe" stage="$OUT/stage" dlls bad version
    dlls="$(objdump -p "$exe" | sed -n 's/^\s*DLL Name: //p' | tr 'A-Z' 'a-z' | sort -u)"
    bad="$(grep -vxE '(kernel32|kernelbase|user32|advapi32|shell32|ole32|oleaut32|ws2_32|crypt32|bcrypt|secur32|winmm|msvcrt|ntdll|shlwapi|iphlpapi|normaliz|wldap32|winhttp|setupapi|cfgmgr32|api-ms-win-[a-z0-9-]+)\.dll' <<<"$dlls" || true)"
    [[ -z $bad ]] || { echo "cyanrip.exe needs non-system DLLs: $bad" >&2; exit 1; }
    version="$("$exe" -v | head -1 | tr -d '\r')"
    [[ $version == "cyanrip $CYANRIP_VERSION (${CYANRIP_COMMIT:0:7})" ]] \
        || { echo "unexpected version line: $version" >&2; exit 1; }

    rm -rf "$stage"; mkdir -p "$stage"
    cp "$exe" "$stage/cyanrip.exe"
    cp "$WORK/cyanrip/LICENSE.md" "$stage/LICENSE.md"
    {
        echo "$version"
        echo "Built by AMA's tools/cyanrip/build.sh (ADR 0007)."
        echo "cyanrip $CYANRIP_REPO @ $CYANRIP_COMMIT"
        echo "libmusicbrainz $LIBMUSICBRAINZ_REPO @ $LIBMUSICBRAINZ_COMMIT"
        local line; for line in "${SOURCES[@]}"; do set -- $line; echo "$1 $2 sha256:$4"; done
        echo "toolchain: $(gcc --version | head -1)"
    } > "$stage/BUILDINFO.txt"
    # Fixed timestamps, so the same exe gives the same zip.
    touch -d "2000-01-01 00:00:00 UTC" "$stage"/*
    rm -f "$OUT/$PACKAGE_FILE"
    (cd "$stage" && TZ=UTC zip -X -q "$OUT/$PACKAGE_FILE" cyanrip.exe LICENSE.md BUILDINFO.txt)
    echo "$version"
    echo "cyanrip.exe sha256: $(sha256sum "$stage/cyanrip.exe" | cut -d' ' -f1)"
    echo "$PACKAGE_FILE sha256: $(sha256sum "$OUT/$PACKAGE_FILE" | cut -d' ' -f1)"
}

# Uploads the zip. Reads FORGEJO_BASE_URL / FORGEJO_API_KEY from the file in
# $FORGEJO_CREDENTIALS (default ~/.forgejo); the key goes in a header file,
# never on a command line or in output.
publish() {
    local creds="${FORGEJO_CREDENTIALS:-$HOME/.forgejo}" hdr url code
    [[ -f $OUT/$PACKAGE_FILE ]] || { echo "build first: $OUT/$PACKAGE_FILE is missing" >&2; exit 1; }
    set -a; . "$creds"; set +a
    url="${FORGEJO_BASE_URL%/}/api/packages/$PACKAGE_OWNER/generic/$PACKAGE_NAME/$PACKAGE_VERSION/$PACKAGE_FILE"
    hdr="$(mktemp)"; trap 'rm -f "$hdr"' RETURN
    printf 'Authorization: token %s\n' "$FORGEJO_API_KEY" > "$hdr"
    code="$(curl -s -o /dev/null -w '%{http_code}' -H @"$hdr" --upload-file "$OUT/$PACKAGE_FILE" "$url")"
    case $code in
        201) echo "published $url" ;;
        409) echo "already published (a version's files can't be replaced; bump PACKAGE_VERSION or delete it in Forgejo): $url" ;;
        *) echo "upload failed: HTTP $code for $url" >&2; exit 1 ;;
    esac
    echo "sha256: $(sha256sum "$OUT/$PACKAGE_FILE" | cut -d' ' -f1)"
}

all() {
    rm -rf "$PREFIX"
    build_curl
    build_libxml2
    build_neon
    build_libmusicbrainz
    build_libcdio
    build_libcdio_paranoia
    build_lame
    build_libogg
    build_libvorbis
    build_opus
    build_ffmpeg
    build_cyanrip
    package
}

if [[ $# -eq 0 ]]; then
    all
else
    for step; do (cd "$ROOT" && "$step"); done
fi
