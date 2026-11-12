"""Antarmuka baris perintah verifier.

Tiga perintah, satu per langkah pemakaian: `build` membuat kasus sintetis,
`check` memeriksa artefak run tanpa butuh ground truth, dan `score` menghitung
metrik terhadap truth kasus. Semua keluaran JSON ke stdout supaya bisa dipipe
ke gate tanpa parsing teks.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import cases, checks, scorer
from .truth import load as load_truth

#: `evals/` di akar repo: src/swarmfold_verify/cli.py → naik tiga tingkat.
DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "evals"


def _print(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _build(args: argparse.Namespace) -> int:
    ringkasan = cases.build_all(args.root)
    _print({"cases": ringkasan, "splits": cases.splits()})
    return 0


def _check(args: argparse.Namespace) -> int:
    defects = checks.check_all(args.run)
    _print({"run": str(args.run), "defects": defects, "count": len(defects)})
    return 1 if defects else 0


def _score(args: argparse.Namespace) -> int:
    truth_path = args.root / "truth" / f"{args.case}.json"
    if not truth_path.is_file():
        print(f"truth tidak ada: {truth_path}", file=sys.stderr)
        return 2
    hasil = scorer.score(args.run, load_truth(truth_path))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(hasil, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    _print(hasil)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="swarmfold-verify", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="tulis semua kasus sintetis + truth")
    p_build.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    p_build.set_defaults(func=_build)

    p_check = sub.add_parser("check", help="periksa artefak satu run")
    p_check.add_argument("--run", type=Path, required=True)
    p_check.set_defaults(func=_check)

    p_score = sub.add_parser("score", help="hitung metrik satu run terhadap truth kasus")
    p_score.add_argument("--run", type=Path, required=True)
    p_score.add_argument("--case", required=True)
    p_score.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    p_score.add_argument("--out", type=Path, default=None)
    p_score.set_defaults(func=_score)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
