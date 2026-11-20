#!/bin/sh
set -eu

packaging=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
project=$(dirname -- "$packaging")
out=${1:-"$project/dist"}
version=$(cat "$packaging/version")
build=$(mktemp -d)
trap 'rm -rf -- "$build"' EXIT

mkdir -p -- "$out"
out=$(CDPATH='' cd -- "$out" && pwd)
archive="$build/basilisk-v4-tray-$version.tar.gz"
tar -czf "$archive" -C "$project" \
    --transform "s,^,basilisk-v4-tray-$version/," \
    razer_tray.py README.md README.de.md packaging
checksum=$(sha256sum "$archive" | cut -d ' ' -f1)
sed -e "s/^pkgver=.*/pkgver=$version/" -e "s/'SKIP'/'$checksum'/" \
    "$packaging/cachyos/PKGBUILD" > "$build/PKGBUILD"

cd "$build"
PKGDEST="$out" SRCDEST="$build" BUILDDIR="$build" makepkg --noconfirm
