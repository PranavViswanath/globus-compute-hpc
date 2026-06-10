#!/usr/bin/env python3
"""Render every bundled config template and assert it produces valid YAML.

Faithfully mimics `globus-compute-endpoint render-user-config`: user-supplied
strings are JSON-serialized before templating (Globus's injection defense),
then Jinja-rendered, then the result must parse as YAML. Also asserts the
skill's invariants on the rendered output.

This is the test that catches the two most common template bugs:
  - interpolating a JSON-quoted user var inside another quoted string
  - leaving init_blocks/min_blocks > 0 (silently burns allocation)

    pip install jinja2 pyyaml
    python tests/test_render_configs.py
"""
import glob
import json
import os
import pathlib
import sys

import jinja2
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "assets" / "configs"

# A value for every {{ VAR }} placeholder used across the bundled configs.
USER_VARS = {
    "POLARIS_ACCOUNT": "MyProject", "COMMAND": "module load conda; conda activate env",
    "OPTIONS": "#SBATCH --constraint=gpu", "ACCOUNT": "MyProject",
    "NERSC_ACCOUNT": "m0000", "AURORA_PROJECT": "MyProject",
    "WORKER_INIT": "module use /soft/modulefiles; module load oneapi",
    "ACCOUNT_ID": "MyProject", "NODES_PER_BLOCK": 2,
    "endpoint_setup": "", "worker_init": "echo hi",
}


def main() -> int:
    # JSON-serialize string values exactly as the endpoint does before rendering.
    render_vars = {k: (json.dumps(v) if isinstance(v, str) else v)
                   for k, v in USER_VARS.items()}
    env = jinja2.Environment(undefined=jinja2.Undefined)
    fails = 0

    for path in sorted(glob.glob(str(CONFIG_DIR / "*.yaml"))):
        name = os.path.basename(path)
        raw = pathlib.Path(path).read_text(encoding="utf-8")
        try:
            doc = yaml.safe_load(env.from_string(raw).render(**render_vars))
            eng = doc["engine"]
            etype = eng["type"]
            assert etype in ("GlobusComputeEngine", "GlobusMPIEngine"), \
                f"unexpected engine {etype!r} (funcx/HighThroughputEngine is removed)"
            prov = eng.get("provider", {})
            ib, mb = prov.get("init_blocks"), prov.get("min_blocks")
            assert ib in (0, None), f"init_blocks={ib} (must be 0 — allocation safety)"
            assert mb in (0, None), f"min_blocks={mb} (must be 0 — allocation safety)"
            extra = ""
            if etype == "GlobusMPIEngine":
                lt = prov.get("launcher", {}).get("type")
                assert lt == "SimpleLauncher", \
                    f"GlobusMPIEngine requires SimpleLauncher, got {lt!r}"
                extra = "  [MPI+SimpleLauncher OK]"
            print(f"[OK] {name:18s} engine={etype} provider={prov.get('type')}{extra}")
        except Exception as e:  # noqa: BLE001
            fails += 1
            print(f"[XX] {name:18s} {type(e).__name__}: {e}")

    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
