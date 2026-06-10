#!/usr/bin/env python3
"""Smoke-test a Globus Compute endpoint.

Proves the full chain works: auth -> endpoint -> scheduler job -> worker ->
result. If a task returns, the endpoint config (provider, launcher, account,
queue, ifname, worker_init) is correct end-to-end.

Usage:
    python smoke_test.py ENDPOINT_UUID              # basic checks
    python smoke_test.py ENDPOINT_UUID --hardware   # + worker hardware report
    python smoke_test.py ENDPOINT_UUID --ase        # + ASE/MLIP evaluation
                                                    #   (requires ase + an MLIP,
                                                    #    e.g. mace-torch, on the
                                                    #    endpoint environment)

Requires: globus-compute-sdk on this machine; the endpoint's Python minor
version must match this interpreter's (a mismatch is the #1 cause of
"worker lost" errors).

Note: the first block may sit in the scheduler queue for a while — that is the
scheduler, not a hang. Check `qstat -u $USER` / `squeue --me` on the system.
"""

import argparse
import concurrent.futures
import sys
import time


def hello(name: str) -> str:
    # Imports must live INSIDE the function body: it executes on the worker.
    import platform
    import socket

    return (
        f"Hello {name} from {socket.gethostname()} "
        f"(Python {platform.python_version()})"
    )


def ase_energy() -> float:
    """Tiny materials-shaped task: relax-free potential energy of bulk Cu.

    Uses ASE's built-in EMT calculator so it runs anywhere ASE is installed.
    Swap EMT for an MLIP calculator (MACE, CHGNet, ...) to validate a real
    simulation environment.
    """
    from ase.build import bulk
    from ase.calculators.emt import EMT

    atoms = bulk("Cu", "fcc", a=3.6)
    atoms.calc = EMT()
    return float(atoms.get_potential_energy())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("endpoint_id", help="Globus Compute endpoint UUID")
    parser.add_argument(
        "--hardware",
        action="store_true",
        help="also print a hardware report from a worker node",
    )
    parser.add_argument(
        "--ase",
        action="store_true",
        help="also run an ASE potential-energy evaluation on the endpoint",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        help="seconds to wait for each result (default: 600; scheduler queue "
        "time counts against this)",
    )
    args = parser.parse_args()

    try:
        from globus_compute_sdk import Client, Executor
        from globus_compute_sdk.errors import (
            MaxResultSizeExceeded,
            TaskExecutionFailed,
            VersionMismatch,
        )
    except ImportError:
        print(
            "globus-compute-sdk is not installed here. Run: "
            "pip install globus-compute-sdk",
            file=sys.stderr,
        )
        return 2

    print(f"[1/3] Endpoint status ...", flush=True)
    status = Client().get_endpoint_status(args.endpoint_id)
    print(f"      {status.get('status', status)}")
    if status.get("status") != "online":
        print(
            "      Endpoint is not online. Start it on the target machine:\n"
            "      globus-compute-endpoint start <name>",
            file=sys.stderr,
        )
        return 1

    with Executor(endpoint_id=args.endpoint_id) as ex:
        print("[2/3] Submitting hello-world (may wait in scheduler queue) ...")
        t0 = time.monotonic()
        try:
            result = ex.submit(hello, "Globus Compute").result(
                timeout=args.timeout
            )
        except VersionMismatch as e:
            print(f"      FAIL: version mismatch — {e}", file=sys.stderr)
            print(
                "      Match this interpreter's Python minor version to the "
                "endpoint's worker environment.",
                file=sys.stderr,
            )
            return 1
        except TaskExecutionFailed as e:
            print(f"      FAIL: function raised on the worker:\n{e}", file=sys.stderr)
            return 1
        except (TimeoutError, concurrent.futures.TimeoutError):
            print(
                f"      FAIL: no result within {args.timeout:.0f}s. Likely the "
                "block never started — check the scheduler queue and "
                "~/.globus_compute/<name>/endpoint.log on the endpoint host.",
                file=sys.stderr,
            )
            return 1
        print(f"      OK ({time.monotonic() - t0:.1f}s): {result}")

        print("[3/3] Optional checks ...")
        if args.hardware:
            print("      Worker hardware report:")
            print(ex.get_worker_hardware_details())
        if args.ase:
            try:
                energy = ex.submit(ase_energy).result(timeout=args.timeout)
                print(f"      ASE EMT bulk-Cu energy: {energy:.4f} eV — "
                      "simulation environment OK")
            except TaskExecutionFailed as e:
                print(
                    f"      ASE check failed (is `ase` installed in the "
                    f"endpoint's worker_init environment?):\n{e}",
                    file=sys.stderr,
                )
                return 1
        if not (args.hardware or args.ase):
            print("      (none requested — use --hardware / --ase)")

    print("\nSmoke test PASSED — the endpoint configuration works end-to-end.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
