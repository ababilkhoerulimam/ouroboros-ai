"""CLI loop evolusi.

Tiga perintah yang mencerminkan urutan pemakaian:

- `selftest` — pin, split, dan rantai ledger utuh? Jalankan sebelum apa pun.
- `baseline` — ukur sistem tanpa patch, simpan `evals/baseline.json`.
- `evaluate` — nilai satu varian dari berkas JSON dan catat hasilnya.

Berkas varian berisi `variant_id`, `hypothesis`, `layer`, `expected`, `parent`,
dan `diff` (teks) atau `diff_path` (relatif terhadap berkas varian).
"""

from __future__ import annotations

import argparse
import json
from functools import partial
from pathlib import Path
from typing import Any

from swarmfold_verify import pins

from . import orchestrator


def _print(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _pin_root(root: Path) -> Path:
    store = root / "pins"
    lock = pins.read_lock(store / pins.LOCK_NAME)
    return pins.snapshot_dir(store, lock).parent


def _orchestrator(args: argparse.Namespace, *, with_runner: bool) -> orchestrator.Orchestrator:
    root = Path(args.root)
    if not with_runner:
        return orchestrator.Orchestrator(root, Path(args.repo))
    runner = partial(orchestrator.run_pipeline, data_root=root / "runs")
    scorer = orchestrator.pinned_scorer(_pin_root(root), root)
    return orchestrator.Orchestrator(root, Path(args.repo), runner, scorer, replicas=args.replicas)


def _selftest(args: argparse.Namespace) -> int:
    masalah = _orchestrator(args, with_runner=False).selftest()
    _print({"problems": masalah, "count": len(masalah)})
    return 1 if masalah else 0


def _baseline(args: argparse.Namespace) -> int:
    data = _orchestrator(args, with_runner=True).measure_baseline(Path(args.worktree))
    _print(
        {
            "baseline": str(Path(args.root) / orchestrator.BASELINE_FILE),
            "pin": data["pin"],
            "replicas": data["replicas"],
            "cases": {nama: len(items) for nama, items in data["splits"].items()},
        }
    )
    return 0


def _variant(path: Path) -> orchestrator.Variant:
    data = json.loads(path.read_text(encoding="utf-8"))
    diff = str(data.get("diff") or "")
    if not diff and data.get("diff_path"):
        diff = (path.parent / str(data["diff_path"])).read_text(encoding="utf-8")
    return orchestrator.Variant(
        variant_id=str(data["variant_id"]),
        hypothesis=str(data.get("hypothesis") or ""),
        layer=str(data.get("layer") or "prompt"),
        expected=str(data.get("expected") or ""),
        diff=diff,
        parent=str(data.get("parent") or "eval/base"),
    )


def _evaluate(args: argparse.Namespace) -> int:
    hasil = _orchestrator(args, with_runner=True).evaluate(_variant(Path(args.variant)))
    _print({"verdict": hasil.verdict, "reason": hasil.reason, "seq": hasil.entry.get("seq")})
    return 0 if hasil.verdict == "promoted" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="swarmfold-eval", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    for nama, fungsi, bantuan in (
        ("selftest", _selftest, "periksa pin, split, dan rantai ledger"),
        ("baseline", _baseline, "ukur sistem tanpa patch"),
        ("evaluate", _evaluate, "nilai satu varian"),
    ):
        sub_parser = sub.add_parser(nama, help=bantuan)
        sub_parser.add_argument("--root", type=Path, default=Path("evals"))
        sub_parser.add_argument("--repo", type=Path, default=Path("."))
        if nama != "selftest":
            sub_parser.add_argument("--replicas", type=int, default=3)
        if nama == "baseline":
            sub_parser.add_argument("--worktree", type=Path, default=Path("."))
        if nama == "evaluate":
            sub_parser.add_argument("--variant", type=Path, required=True)
        sub_parser.set_defaults(func=fungsi)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
