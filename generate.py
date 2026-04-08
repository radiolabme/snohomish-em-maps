#!/usr/bin/env python3
"""
Snohomish County Emergency Management Map Generator

Generate maps for emergency management, search and rescue, and hazard analysis.
All maps use US Census TIGER, FEMA, USGS, WA DNR, WSDOT, and OSM open data.
"""

import argparse
import importlib
import os
import subprocess
import sys
import time

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)

# ANSI helpers

_color = sys.stdout.isatty()

def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if _color else text

def _bold(t):    return _c("1", t)
def _dim(t):     return _c("2", t)
def _green(t):   return _c("32", t)
def _yellow(t):  return _c("33", t)
def _red(t):     return _c("31", t)
def _cyan(t):    return _c("36", t)

# Map registry

MAPS = {
    "state":      ("wa_counties_map",              "Washington State overview",          "washington_counties"),
    "flood":      ("snohomish_flood_zones",        "FEMA flood hazard zones",            None),
    "volcanic":   ("snohomish_volcanic",           "Volcanic & lahar hazards",           None),
    "services":   ("snohomish_emergency_services", "Fire & hospital districts",          None),
    "water":      ("snohomish_water_mgmt",         "Water management districts",         None),
    "combined":   ("snohomish_combined",           "Combined hazard & infrastructure",   None),
    "facilities": ("snohomish_facilities",         "Critical facilities",                None),
    "terrain":    ("snohomish_terrain",            "Terrain, trails & SAR access",       None),
    "population": ("snohomish_population",         "Population density & exposure",      None),
    "evacuation": ("snohomish_evacuation",         "Evacuation routes & bottlenecks",    None),
    "rivers":     ("snohomish_rivers",             "River systems & water access",       None),
}


def _png_path(key):
    module, _, override = MAPS[key]
    stem = override or module
    return os.path.join(DIR, f"{stem}.png")


def _svg_path(key):
    module, _, override = MAPS[key]
    stem = override or module
    return os.path.join(DIR, f"{stem}.svg")


def _file_age(path):
    if not os.path.exists(path):
        return None
    mtime = os.path.getmtime(path)
    age = time.time() - mtime
    if age < 3600:
        return f"{int(age/60)}m ago"
    if age < 86400:
        return f"{int(age/3600)}h ago"
    return f"{int(age/86400)}d ago"


# Commands

def cmd_list(args):
    print()
    print(_bold("  Snohomish County Emergency Management Maps"))
    print(_dim("  " + "-" * 50))
    print()
    for key, (module, desc, _) in MAPS.items():
        png = _png_path(key)
        svg = _svg_path(key)
        if os.path.exists(png):
            age = _file_age(png)
            has_svg = " +svg" if os.path.exists(svg) else ""
            status = _green(f"[built {age}{has_svg}]")
        else:
            status = _dim("[not built]")
        print(f"  {_cyan(key):>24s}  {desc:<42s} {status}")
    print()
    print(_dim(f"  Output directory: {DIR}"))
    print()


def cmd_generate(args):
    names = args.maps
    if "all" in names:
        names = list(MAPS.keys())

    unknown = [n for n in names if n not in MAPS]
    if unknown:
        print(_red(f"Unknown map(s): {', '.join(unknown)}"))
        print(f"Available: {', '.join(MAPS.keys())}")
        sys.exit(1)

    total_t0 = time.time()
    results = []

    for i, name in enumerate(names, 1):
        module_name, desc, _ = MAPS[name]
        header = f"[{i}/{len(names)}] {desc}"
        print(f"\n{_bold(header)}")
        print(_dim("-" * len(header)))

        t0 = time.time()
        try:
            mod = importlib.import_module(module_name)
            if hasattr(mod, "main"):
                mod.main()
            elapsed = time.time() - t0
            png = _png_path(name)
            size_mb = os.path.getsize(png) / (1024*1024) if os.path.exists(png) else 0
            results.append((name, True, elapsed, size_mb))
            print(f"\n{_green('OK')} {desc} ({elapsed:.1f}s, {size_mb:.1f} MB)")
        except Exception as e:
            elapsed = time.time() - t0
            results.append((name, False, elapsed, 0))
            print(f"\n{_red('FAIL')} {desc}: {e}")

    # Summary
    total = time.time() - total_t0
    ok = sum(1 for _, s, _, _ in results if s)
    print(f"\n{_bold('Summary')}")
    print(_dim("-" * 40))
    for name, success, elapsed, size in results:
        icon = _green("OK  ") if success else _red("FAIL")
        print(f"  {icon}  {name:12s}  {elapsed:5.1f}s  {size:5.1f} MB")
    print(_dim("-" * 40))
    print(f"  {ok}/{len(results)} maps in {total:.0f}s")

    if ok < len(results):
        sys.exit(1)


def cmd_test(args):
    result = subprocess.run(
        [sys.executable, "-m", "pytest", DIR, "-v", "--tb=short"],
        cwd=DIR,
    )
    sys.exit(result.returncode)


def cmd_open(args):
    names = args.maps or list(MAPS.keys())
    for name in names:
        if name not in MAPS:
            print(_red(f"Unknown map: {name}"))
            continue
        png = _png_path(name)
        if os.path.exists(png):
            subprocess.run(["open", png])
        else:
            print(_yellow(f"{name}: not built yet — run ./generate.py {name}"))


def cmd_clean(args):
    removed = 0
    for key in MAPS:
        for path in [_png_path(key), _svg_path(key)]:
            if os.path.exists(path):
                os.remove(path)
                print(f"  removed {os.path.basename(path)}")
                removed += 1
    print(f"\n{removed} files removed" if removed else "Nothing to clean")


# CLI

def build_parser():
    p = argparse.ArgumentParser(
        prog="generate.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""\
examples:
  %(prog)s list                    Show available maps and build status
  %(prog)s flood                   Generate the flood hazard map
  %(prog)s flood volcanic terrain  Generate multiple maps
  %(prog)s all                     Generate all 11 maps
  %(prog)s test                    Run the test suite (82 tests)
  %(prog)s open combined           Open a map in Preview
  %(prog)s clean                   Remove all generated PNG/SVG files
""",
    )
    sub = p.add_subparsers(dest="command")

    sub.add_parser("list", help="Show available maps and build status")
    sub.add_parser("test", help="Run the test suite")
    sub.add_parser("clean", help="Remove all generated PNG/SVG files")

    gen = sub.add_parser("generate", help="Generate one or more maps (default command)")
    gen.add_argument("maps", nargs="+", help="Map name(s) or 'all'")

    op = sub.add_parser("open", help="Open map(s) in Preview")
    op.add_argument("maps", nargs="*", help="Map name(s) — opens all if omitted")

    return p


def main():
    parser = build_parser()

    # Allow bare map names without 'generate' subcommand
    args = sys.argv[1:]
    if not args:
        cmd_list(parser.parse_args([]))
        return

    # If first arg looks like a map name or 'all', treat as generate
    if args[0] in MAPS or args[0] == "all":
        args = ["generate"] + args

    parsed = parser.parse_args(args)

    commands = {
        "list": cmd_list,
        "generate": cmd_generate,
        "test": cmd_test,
        "open": cmd_open,
        "clean": cmd_clean,
    }
    handler = commands.get(parsed.command)
    if handler:
        handler(parsed)
    else:
        cmd_list(parsed)


if __name__ == "__main__":
    main()
