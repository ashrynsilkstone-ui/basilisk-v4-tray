#!/bin/sh
set -eu

packaging=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
out=${1:-"$packaging/../dist"}
version=$(cat "$packaging/version")
staging=$(mktemp -d)
trap 'rm -rf -- "$staging"' EXIT

mkdir -p -- "$out" "$staging/DEBIAN"
chmod 0755 "$staging"
sh "$packaging/stage.sh" "$staging"
sed "s/@VERSION@/$version/" "$packaging/deb.control" > "$staging/DEBIAN/control"
dpkg-deb --root-owner-group -Zxz --build "$staging" "$out/basilisk-v4-tray_${version}_all.deb"
