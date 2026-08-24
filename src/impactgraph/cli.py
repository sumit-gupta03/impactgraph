"""impactgraph CLI.

    impactgraph check [options]     what breaks if I merge this? (text | json | markdown | html)
    impactgraph pr    [options]     same as `check --format markdown` (PR comment)
    impactgraph <anything else>     passed straight to datagraph (impact, lineage, nodes, html, ...)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from .core import BUILD_FLAGS, LEVELS, check, safe_console_text, to_markdown

_OWN = {"check", "pr"}


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="impactgraph", description="Pre-merge safety net: what breaks if I merge this?")
    p.add_argument("--version", action="version", version=_version())
    sub = p.add_subparsers(dest="command")
    for name, help_text in (("check", "Diff -> blast radius -> risk -> tests; gate CI with --fail-on"),
                            ("pr", "Same as check --format markdown (PR comment)")):
        c = sub.add_parser(name, help=help_text)
        c.add_argument("--repo", default=".", help="Git repository (also the code root unless --code is given)")
        c.add_argument("--code", default=None, help="Code directory to scan (default: --repo)")
        c.add_argument("--base", default="HEAD", help="Base ref to diff against (e.g. origin/main); default HEAD = uncommitted changes")
        c.add_argument("--head", default=None, help="Optional head ref (base...head)")
        c.add_argument("--graph", default=None, help="Use an existing datagraph graph instead of building one")
        c.add_argument("--save-graph", default=None, help="Keep the built graph at this path")
        c.add_argument("--update", action="store_true", help="Skip the build if inputs are unchanged (with --save-graph)")
        for key, flag in BUILD_FLAGS.items():
            c.add_argument(flag, dest=key, default=None, help=f"datagraph build {flag}")
        c.add_argument("--max-depth", type=int, default=None)
        c.add_argument("--no-inferred", action="store_true", help="Artifact-backed edges only")
        c.add_argument("--fail-on", default="NONE", choices=LEVELS + ["NONE", "low", "medium", "high", "critical", "none"],
                       help="Exit 1 when risk is at or above this level")
        c.add_argument("--format", default="markdown" if name == "pr" else "text", choices=["text", "json", "markdown"])
        c.add_argument("--html", default=None, help="Also write the interactive HTML view here")
        c.add_argument("--output", "-o", default=None, help="Write the report to a file instead of stdout")
        c.add_argument("--title", default="impactgraph — change impact")
    return p


def _version() -> str:
    from . import __version__
    import datagraph

    return f"impactgraph {__version__} (datagraph {datagraph.__version__})"


def _run_check(args: argparse.Namespace) -> int:
    quiet = args.format != "text"
    inputs = {k: getattr(args, k) for k in BUILD_FLAGS}
    try:
        result = check(args.repo, base=args.base, head=args.head, code=args.code, graph_path=args.graph, inputs=inputs,
                       save_graph=args.save_graph, update=args.update, max_depth=args.max_depth,
                       include_inferred=not args.no_inferred, quiet=quiet)
    except Exception as exc:  # noqa: BLE001 - surface as a clean CLI error
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.html and result.analysis is not None:
        from datagraph.html_report import render_html

        Path(args.html).write_text(render_html(result.graph, result.analysis), encoding="utf-8")
        print(f"html view -> {args.html}", file=sys.stderr)

    if args.format == "json":
        text = json.dumps(result.to_dict(), indent=2, sort_keys=True)
    elif args.format == "markdown":
        text = to_markdown(result, title=args.title)
    else:
        text = None

    if text is not None:
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")   # always UTF-8 on disk
        else:
            print(safe_console_text(text))                          # never crash a legacy console
    else:
        from datagraph.report import render_analysis

        print(f"changed files ({len(result.changed_files)}): " + ", ".join(result.changed_files[:10])
              + (" ..." if len(result.changed_files) > 10 else ""))
        if result.analysis is None:
            print("; ".join(result.notes) or "no impact")
        else:
            render_analysis(result.graph, result.analysis)

    if result.breaches(args.fail_on):
        print(f"impactgraph: risk {result.level} >= --fail-on {args.fail_on.upper()}", file=sys.stderr)
        return 1
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in _OWN and argv[0] not in ("-h", "--help", "--version"):
        # everything else is the engine's CLI: impact, diff, lineage, relationships, nodes, html, wiki, context, mcp ...
        from datagraph.cli import main as dg_main

        return dg_main(argv)
    args = _parser().parse_args(argv)
    if args.command in _OWN:
        return _run_check(args)
    _parser().print_help()
    print("\nAny other command is passed to datagraph, e.g.  impactgraph impact dbt:customer  |  impactgraph lineage X  |  impactgraph nodes --search x")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
