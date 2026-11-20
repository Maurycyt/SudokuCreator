#!/usr/bin/env python3
"""Build a Duckling package for the browser as wasm64 (MEMORY64) with emscripten.

duckc has no wasm target, so this wraps it without changing it:

1. `duck build` resolves the package and writes `deps.json` (the package graph duckc uses).
2. `duckc compile_packages --dump-ir llvm` compiles every package (core, std, exp, deps, root)
   and dumps the LLVM IR of each module. duckc emits x86_64-linux IR; it is target-independent
   enough (LP64, no inline asm, no target attributes) to be retargeted.
3. Each `.ll` gets `target triple = wasm64-unknown-emscripten` (datalayout dropped, so the
   backend supplies its own) and is compiled with emscripten's clang.
4. The root's `main() -> i64` is renamed `__duck_main` and called from a tiny C `int main()`.
5. C sources listed by packages are compiled with emcc (see "Per-package config"). A Duckling
   `extern("C")` function whose symbol a C source also defines is turned into a declaration,
   so the C version is linked (used for by-value struct wrappers, see sdl2/src/shim.dk).
6. `emcc -m64 (MEMORY64) -sASYNCIFY` links everything into `index.html` + `.js` + `.wasm`.
   ASYNCIFY lets a plain `while` loop with `SDL_Delay` yield to the browser.

Per-package config: any package (root or dependency) may have `duck-wasm.json` next to its
`quackconfig.yaml`, with paths relative to that directory:

    {
      "c_sources": ["shim/sdl2_shim.c"],          # compiled with emcc and linked
      "cflags": ["-sUSE_SDL=2"],                  # for c_sources
      "link_flags": ["-sUSE_SDL=2"],              # added to the final link
      "preload": ["assets"]                       # files/dirs put in the virtual FS at the same path
    }

Usage:
    tools/duck_wasm.py examples/sdl_demo -o build-web [--emsdk ~/emsdk] [-O 2] [--serve]

Known limit: by-value C structs in `extern("C")` calls are lowered by duckc for the x86_64
SysV ABI, which differs from wasm's C ABI. Call a C wrapper that takes a pointer instead.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

MAIN_SHIM = """\
#include <stdint.h>
int64_t __duck_main(void);
int main(void) { return (int)__duck_main(); }
"""


def run(cmd: list[str], **kwargs) -> None:
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run(cmd, check=True, **kwargs)


def package_name(pkg: Path) -> str:
    text = (pkg / "quackconfig.yaml").read_text()
    match = re.search(r"^\s+name:\s*['\"]?([\w-]+)", text, re.M)
    if not match:
        sys.exit(f"no metadata.name in {pkg / 'quackconfig.yaml'}")
    return match.group(1)


def find_deps_json(pkg: Path, name: str) -> Path:
    candidates = sorted(
        (pkg / ".duck_build" / "dev").glob(f"{name}-*/deps.json"), key=lambda p: p.stat().st_mtime
    )
    if not candidates:
        sys.exit(f"`duck build` produced no deps.json for `{name}`")
    return candidates[-1]


def find_emsdk(arg: str | None) -> Path:
    for candidate in (arg, os.environ.get("EMSDK"), str(Path.home() / "emsdk")):
        if candidate and (Path(candidate) / "upstream" / "emscripten" / "emcc").exists():
            return Path(candidate)
    sys.exit("emscripten not found: pass --emsdk or set $EMSDK (https://emscripten.org/docs/getting_started/downloads.html)")


def retarget(ll: str, rename_main: bool) -> str:
    ll = re.sub(r"^target triple = .*$", 'target triple = "wasm64-unknown-emscripten"', ll, flags=re.M)
    ll = re.sub(r"^target datalayout = .*\n", "", ll, flags=re.M)
    if rename_main:
        ll, count = re.subn(r"^define (\S+) @main\(", r"define \1 @__duck_main(", ll, flags=re.M)
        if count != 1:
            sys.exit("could not find `main` in the root package's IR")
    return ll


def defined_symbols(emsdk: Path, objects: list[str]) -> set[str]:
    if not objects:
        return set()
    nm = emsdk / "upstream" / "bin" / "llvm-nm"
    output = subprocess.run([str(nm), "--defined-only", "--extern-only", "--format=just-symbols", *objects],
                            check=True, capture_output=True, text=True).stdout
    return {line.strip() for line in output.splitlines() if line.strip() and not line.endswith(":")}


DEFINE_RE = re.compile(r"^define (?P<head>[^@]*)@(?P<name>[\w.$]+)\((?P<params>.*)\)(?P<tail>[^{]*)\{\s*$")


def drop_definitions(ll: str, symbols: set[str]) -> tuple[str, list[str]]:
    """Turns `define`s of `symbols` into `declare`s, so the C definitions are linked instead."""
    out, replaced, skipping = [], [], False
    for line in ll.splitlines(keepends=True):
        if skipping:
            skipping = not line.startswith("}")
            continue
        match = DEFINE_RE.match(line)
        if match and match["name"] in symbols:
            head = re.sub(r"\b(dso_local|linkonce_odr|weak_odr|internal|private)\s+", "", match["head"])
            params = re.sub(r"\s+%[\w.]+(?=\s*(,|$))", "", match["params"])
            out.append(f"declare {head}@{match['name']}({params})\n")
            replaced.append(match["name"])
            skipping = True
            continue
        out.append(line)
    return "".join(out), replaced


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("package", type=Path, help="directory with quackconfig.yaml")
    parser.add_argument("-o", "--out", type=Path, default=None, help="output dir (default: <package>/build-web)")
    parser.add_argument("--emsdk", default=None)
    parser.add_argument("-O", "--opt", default="2", choices=list("0123sz"))
    parser.add_argument("--shell-file", type=Path, default=Path(__file__).with_name("wasm_shell.html"))
    parser.add_argument("--emcc-arg", action="append", default=[], help="extra emcc link flag (repeatable)")
    parser.add_argument("--serve", action="store_true", help="serve the output on http://localhost:8000")
    args = parser.parse_args()

    pkg = args.package.resolve()
    out = (args.out or pkg / "build-web").resolve()
    work = out / "work"
    shutil.rmtree(work, ignore_errors=True)
    (work / "obj").mkdir(parents=True)

    emsdk = find_emsdk(args.emsdk)
    emcc = str(emsdk / "upstream" / "emscripten" / "emcc")
    env = dict(os.environ, EMSDK=str(emsdk))

    # 1. Resolve the package graph with duck.
    name = package_name(pkg)
    # Only the package graph is needed here; the native link may fail (e.g. a C library that is
    # only available as an emscripten port), and real compile errors show up again in duckc below.
    print("+ duck -C", pkg, "build", flush=True)
    if subprocess.run(["duck", "-C", str(pkg), "build"]).returncode != 0:
        print("warning: native `duck build` failed; continuing with its deps.json", flush=True)
    deps = json.loads(find_deps_json(pkg, name).read_text())

    # 2. One duckc call that compiles every package and dumps IR.
    root = next(p for p in deps["packages"] if p["name"] == name)
    deps["tasks"] = [
        {"package": p["id"], "strategy": "lib", "output_file": str(work / f"{p['name']}.a")}
        for p in deps["packages"] if p is not root
    ] + [{"package": root["id"], "strategy": "native", "output_file": str(work / name), "linking_options": []}]
    (work / "deps.json").write_text(json.dumps(deps, indent=1))
    run(["duckc", "compile_packages", str(work / "deps.json"), "-a", str(work / "art"), "-O", "1",
         "--dump-ir", "llvm", "--no-link", "--no-incremental"])

    # 3. C sources and flags from each package's duck-wasm.json.
    objects: list[str] = []
    link_flags: list[str] = []
    for package in deps["packages"]:
        package_root = Path(package["path"]).parent
        config_path = package_root / "duck-wasm.json"
        if not config_path.exists():
            continue
        config = json.loads(config_path.read_text())
        for source in config.get("c_sources", []):
            obj = work / "obj" / f"{package['name']}.{Path(source).stem}.c.o"
            run([emcc, "-m64", f"-O{args.opt}", *config.get("cflags", []), "-c",
                 str(package_root / source), "-o", str(obj)], env=env)
            objects.append(str(obj))
        link_flags += [f for f in config.get("link_flags", []) if f not in link_flags]
        for item in config.get("preload", []):
            link_flags += ["--preload-file", f"{package_root / item}@{item}"]

    # Symbols the C sources define replace Duckling definitions of the same name (wrappers whose
    # by-value C calls duckc lowers for x86_64; see sdl2/src/shim.dk).
    c_symbols = defined_symbols(emsdk, objects)

    # 4. Retarget and compile every module.
    for ll in sorted((work / "art" / "duck_debug_artifacts").glob("*.ll")):
        is_root_module = ll.name == f"{root['id']}.src.ll"
        target = work / "obj" / ll.name
        text, replaced = drop_definitions(retarget(ll.read_text(), is_root_module), c_symbols)
        for symbol in replaced:
            print(f"  using the C definition of `{symbol}` instead of Duckling's ({ll.name})")
        target.write_text(text)
        obj = target.with_suffix(".o")
        run([emcc, "-m64", f"-O{args.opt}", "-c", str(target), "-o", str(obj)], env=env)
        objects.append(str(obj))

    shim = work / "obj" / "duck_main_shim.c"
    shim.write_text(MAIN_SHIM)
    run([emcc, "-m64", f"-O{args.opt}", "-c", str(shim), "-o", str(shim.with_suffix(".o"))], env=env)
    objects.append(str(shim.with_suffix(".o")))

    # 6. Link.
    link = [emcc, "-m64", "-sASYNCIFY=1", "-sALLOW_MEMORY_GROWTH=1", *link_flags,
            f"-O{args.opt}", *objects, "-o", str(out / "index.html"), *args.emcc_arg]
    if args.shell_file.exists():
        link += ["--shell-file", str(args.shell_file)]
    run(link, env=env)
    print(f"\nbuilt {out / 'index.html'}")

    if args.serve:
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out))
        print("serving on http://localhost:8000 (Ctrl+C to stop)")
        http.server.ThreadingHTTPServer(("127.0.0.1", 8000), handler).serve_forever()


if __name__ == "__main__":
    main()
