#!/usr/bin/env bash
# Build the browser version and publish it to GitHub Pages (branch `gh-pages`).
#
# The branch always holds a single commit with just the built files: each run creates it from
# scratch and force-pushes it, so old builds do not pile up in git history and `main` stays free
# of binaries. Extra arguments are passed to tools/duck_wasm.py (e.g. --emsdk PATH).
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
cd "$repo"
tools/duck_wasm.py . -o build-web -O 2 "$@"

site=$(mktemp -d)
trap 'rm -rf "$site"' EXIT
cp build-web/index.html build-web/index.js build-web/index.wasm build-web/index.data "$site"/
touch "$site/.nojekyll"  # serve files as they are, without Jekyll

rev=$(git rev-parse --short HEAD)
remote=$(git remote get-url origin)
git -C "$site" init -q -b gh-pages
git -C "$site" add -A
git -C "$site" commit -q -m "Web demo built from $rev"
git -C "$site" push --force "$remote" gh-pages
echo "published $rev to gh-pages"
