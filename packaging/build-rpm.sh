#!/bin/sh
set -eu

packaging=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
project=$(dirname -- "$packaging")
out=${1:-"$project/dist"}
version=$(cat "$packaging/version")
top=$(mktemp -d)
trap 'rm -rf -- "$top"' EXIT

mkdir -p -- "$out" "$top/SOURCES" "$top/db" "$top/tmp"
out=$(CDPATH='' cd -- "$out" && pwd)
tar -czf "$top/SOURCES/basilisk-v4-tray-$version.tar.gz" -C "$project" \
    --transform "s,^,basilisk-v4-tray-$version/," \
    razer_tray.py README.md README.de.md packaging
rpmbuild -bb --define "_topdir $top" --define "_rpmdir $out" \
    --define "_dbpath $top/db" --define "_tmppath $top/tmp" \
    --define "_rpmformat 4" --define "tray_version $version" "$packaging/basilisk-v4-tray.spec"
