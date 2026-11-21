#!/usr/bin/env bash
# Build SudokuCreator to DVM bytecode with duckc and run it on the VM.
#
# `duck build` cannot do this yet: it rejects packages with `external-libs` on the DVM and never
# fills `dvm_linking_options.shared_libraries` (see #3666). So this script writes the duckc
# manifest itself, with SDL2, SDL2_ttf and the C shim as shared libraries.
#
# The `extern("C")` wrappers in sdl2/src/shim.dk become `ffi function`s on the DVM, so their
# C versions (sdl2/shim/sdl2_shim.c, also used by the wasm build) are compiled into a .so.
#
# Usage: tools/dvm_run.sh [--build-only] [program args...]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/.duck_build/dvm-manual"
ARTIFACTS="$OUT/artifacts"
MANIFEST="$OUT/manifest.json"
SHIM_SO="$OUT/libsdl2_shim.so"
SDL2_DBC="$OUT/sdl2.dbc"
APP_DBC="$OUT/SudokuCreator.dbc"

build_only=0
if [[ "${1:-}" == "--build-only" ]]; then
	build_only=1
	shift
fi

# Find a shared library by soname in the system linker cache.
find_lib() {
	local path
	path="$(ldconfig -p | awk -v name="$1" '$1 == name { print $NF; exit }')"
	if [[ -z "$path" ]]; then
		echo "error: shared library $1 not found (ldconfig -p)" >&2
		exit 1
	fi
	echo "$path"
}

SDL2_SO="$(find_lib libSDL2-2.0.so.0)"
SDL2_TTF_SO="$(find_lib libSDL2_ttf-2.0.so.0)"

mkdir -p "$ARTIFACTS"

if [[ ! -f "$SHIM_SO" || "$ROOT/sdl2/shim/sdl2_shim.c" -nt "$SHIM_SO" ]]; then
	echo "Compiling sdl2_shim.c -> $SHIM_SO"
	cc -shared -fPIC -O2 $(sdl2-config --cflags) -I"$ROOT/sdl2/c_bindings/include" \
		"$ROOT/sdl2/shim/sdl2_shim.c" -o "$SHIM_SO" "$SDL2_SO" "$SDL2_TTF_SO"
fi

cat > "$MANIFEST" <<EOF
{
  "packages": [
    {
      "id": "SudokuCreator",
      "name": "SudokuCreator",
      "version": "1.0.0",
      "features": [],
      "path": "$ROOT/src",
      "dependencies": [{ "id": "sdl2" }]
    },
    {
      "id": "sdl2",
      "name": "sdl2",
      "version": "2.32.4",
      "features": [],
      "path": "$ROOT/sdl2/src",
      "dependencies": []
    }
  ],
  "tasks": [
    {
      "package": "sdl2",
      "strategy": "dvm_lib",
      "output_file": "$SDL2_DBC"
    },
    {
      "package": "SudokuCreator",
      "strategy": "dvm_exe",
      "output_file": "$APP_DBC",
      "dvm_linking_options": {
        "link_libraries": ["$SDL2_DBC"],
        "shared_libraries": ["$SDL2_SO", "$SDL2_TTF_SO", "$SHIM_SO"]
      }
    }
  ]
}
EOF

duckc compile_packages "$MANIFEST" -a "$ARTIFACTS"

if (( build_only )); then
	echo "Built $APP_DBC"
	exit 0
fi

# Assets are loaded relative to the working directory.
cd "$ROOT"
if (( $# )); then
	args="$(IFS=,; echo "$*")"
	exec VM run -c "$args" "$APP_DBC"
fi
exec VM run "$APP_DBC"
