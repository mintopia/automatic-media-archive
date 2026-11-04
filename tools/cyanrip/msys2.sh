#!/bin/bash
# Pins the MSYS2 build toolchain for build.sh (ADR 0007). Run by build.ps1 in
# the MSYS environment of a freshly unpacked, pinned MSYS2 snapshot.
#
#   msys2.sh relock     update + install PACKAGES, then write msys2-packages.lock
#   msys2.sh core       install the locked upgrades of the snapshot's own packages
#   msys2.sh rest       install every other locked package
#
# The lock lists every package that differs from the snapshot, as
# "<repo dir> <file> <sha256>", so a rebuild installs exactly those files.
# The installs are split in two because upgrading msys2-runtime ends the shell
# that ran pacman.

set -eo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCK="$HERE/msys2-packages.lock"
BASE=/var/lib/ama-snapshot-packages.txt   # written on first use of the snapshot
MIRROR=https://repo.msys2.org
CACHE=/var/cache/pacman/pkg

PACKAGES=(
    base-devel autotools git zip
    mingw-w64-x86_64-toolchain mingw-w64-x86_64-meson mingw-w64-x86_64-ninja
    mingw-w64-x86_64-cmake mingw-w64-x86_64-nasm mingw-w64-x86_64-pkgconf
    mingw-w64-x86_64-zlib mingw-w64-x86_64-bzip2 mingw-w64-x86_64-xz mingw-w64-x86_64-libiconv
)

[[ -f $BASE ]] || pacman -Q > "$BASE"

repo_dir() {
    case $1 in
        mingw-w64-x86_64-*) echo mingw/mingw64 ;;
        *) echo msys/x86_64 ;;
    esac
}

relock() {
    # The first -Syuu may upgrade the runtime and end the shell; build.ps1
    # runs this again until nothing is left to upgrade.
    pacman -Syuu --noconfirm
    pacman -S --needed --noconfirm "${PACKAGES[@]}"
    local name version file tmp
    tmp="$(mktemp)"
    while read -r name version; do
        file="$(cd "$CACHE" && ls -1 "$name-$version-"{any,x86_64}.pkg.tar.* 2>/dev/null | grep -v '\.sig$' | head -1 || true)"
        [[ -n $file ]] || { echo "no cached package file for $name $version" >&2; exit 1; }
        echo "$(repo_dir "$name") $file $(sha256sum "$CACHE/$file" | cut -d' ' -f1)"
    done < <(comm -13 <(sort "$BASE") <(pacman -Q | sort)) > "$tmp"
    if comm -23 <(cut -d' ' -f1 "$BASE" | sort) <(pacman -Qq | sort) | grep -q .; then
        echo "the update removed snapshot packages; the lock can't express that" >&2; exit 1
    fi
    {
        echo "# MSYS2 packages for tools/cyanrip/build.sh: everything that differs from the"
        echo "# pinned snapshot. Regenerate with: build.ps1 -Relock"
        sort -k2 "$tmp"
    } > "$LOCK"
    rm -f "$tmp"
    echo "wrote $(grep -vc '^#' "$LOCK") packages to $LOCK"
}

# Downloads and checks the locked files whose package names pass the filter.
install_locked() {
    local want=$1 dir file sha name files=()
    local snapshot_names; snapshot_names="$(cut -d' ' -f1 "$BASE")"
    while read -r dir file sha; do
        [[ -z $dir || $dir == \#* ]] && continue
        if [[ ! -f $CACHE/$file ]] || ! echo "$sha *$CACHE/$file" | sha256sum -c --status; then
            curl -fsSL --retry 5 --retry-all-errors -o "$CACHE/$file.part" "$MIRROR/$dir/$file"
            mv -f "$CACHE/$file.part" "$CACHE/$file"
        fi
        echo "$sha *$CACHE/$file" | sha256sum -c --status || { echo "$file failed its SHA-256 check" >&2; exit 1; }
        name="${file%-*-*-*}"   # <name>-<pkgver>-<pkgrel>-<arch>.pkg.tar.*
        if grep -qxF "$name" <<<"$snapshot_names"; then
            [[ $want == core ]] && files+=("$CACHE/$file")
        else
            [[ $want == rest ]] && files+=("$CACHE/$file")
        fi
    done < "$LOCK"
    (( ${#files[@]} )) || return 0
    pacman -U --needed --noconfirm "${files[@]}"
}

case $1 in
    relock) relock ;;
    core) install_locked core ;;
    rest) install_locked rest ;;
    *) echo "usage: msys2.sh relock|core|rest" >&2; exit 2 ;;
esac
