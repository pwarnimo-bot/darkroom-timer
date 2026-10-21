#!/usr/bin/env bash
# Build the Arch package from the current project tree.
# Usage: packaging/arch/build-package.sh [extra makepkg args, e.g. -si]
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)"
pkgver="$(sed -n 's/^pkgver=//p' "$here/PKGBUILD")"
name="darkroom-timer-$pkgver"

rm -f "$here/$name.tar.gz"
tar -czf "$here/$name.tar.gz" -C "$root" \
  --exclude=.venv --exclude=__pycache__ --exclude='*.egg-info' \
  --exclude=packaging/arch/src --exclude=packaging/arch/pkg \
  --exclude='*.tar.gz' --exclude='*.pkg.tar.*' \
  --transform "s,^\.,$name," .

cd "$here"
makepkg -f "$@"
