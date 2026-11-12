"""Jalankan satu kasus benchmark di dalam worktree varian.

Dipanggil sebagai subprocess oleh `orchestrator.run_pipeline`, dengan `cwd` dan
`PYTHONPATH` menunjuk worktree. Itu penting: pipeline yang diuji harus kode
yang sudah dipatch di worktree, bukan `swarmfold` yang kebetulan sudah
ter-import di proses orkestrator.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path


def run(case_id: str, input_dir: Path, data_root: Path, replica: int) -> Path:
    from swarmfold.config import Settings
    from swarmfold.ingest import ingest
    from swarmfold.loop import AgentLoop, Brief, build_client
    from swarmfold.runtime import RunPaths

    settings = Settings.from_env()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    paths = RunPaths(data_root, f"{case_id}-r{replica}-{stamp}").ensure()
    ingest(sorted(Path(input_dir).glob("*.csv")), paths)
    brief = Brief(business_type="benchmark", main_kpi="temukan cacat data", decision="verifikasi")
    AgentLoop(paths, settings, build_client(settings), brief).run()
    return paths.dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="swarmfold-eval-run", description=__doc__)
    parser.add_argument("--case", required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--replica", type=int, default=0)
    args = parser.parse_args(argv)

    run_dir = run(args.case, args.input, args.data_root, args.replica)
    print(json.dumps({"case_id": args.case, "run_dir": str(run_dir)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
