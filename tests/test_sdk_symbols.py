#!/usr/bin/env python3
"""Verify every globus-compute-sdk symbol this skill references actually exists.

Guards against the skill drifting from the real API (or hallucinated members).
Validated against globus-compute-sdk 4.12.0.

    pip install globus-compute-sdk
    python tests/test_sdk_symbols.py
"""
import inspect
import sys


def main() -> int:
    oks: list[str] = []
    fails: list[str] = []

    def check(desc, fn):
        try:
            fn()
            oks.append(desc)
        except Exception as e:  # noqa: BLE001
            fails.append(f"{desc}  ->  {type(e).__name__}: {e}")

    try:
        import globus_compute_sdk as g
    except ImportError:
        print("globus-compute-sdk not installed: pip install globus-compute-sdk")
        return 2

    for sym in ["Client", "Executor", "MPIFunction", "ShellFunction", "ShellResult"]:
        check(f"top-level export: {sym}", lambda s=sym: getattr(g, s))

    sig = inspect.signature(g.Executor.__init__)
    for p in ["resource_specification", "user_endpoint_config", "endpoint_id",
              "batch_size", "label"]:
        check(f"Executor.__init__ param: {p}", lambda p=p: sig.parameters[p])

    for meth in ["submit", "map", "register_function",
                 "submit_to_registered_function", "get_worker_hardware_details",
                 "reload_tasks"]:
        check(f"Executor method: {meth}", lambda m=meth: getattr(g.Executor, m))

    for meth in ["get_endpoint_status", "register_function",
                 "get_worker_hardware_details"]:
        check(f"Client method: {meth}", lambda m=meth: getattr(g.Client, m))

    def check_errors():
        from globus_compute_sdk.errors import (  # noqa: F401
            ComputeError, DeserializationError, MaxResultSizeExceeded,
            SerdeError, SerializationError, TaskExecutionFailed, TaskPending,
            VersionMismatch)
    check("errors: all 8 types import from globus_compute_sdk.errors", check_errors)

    def check_serialize():
        from globus_compute_sdk.serialize import (  # noqa: F401
            AllCodeStrategies, ComputeSerializer)
    check("serialize: ComputeSerializer + AllCodeStrategies", check_serialize)

    check("MPIFunction subclasses ShellFunction",
          lambda: issubclass(g.MPIFunction, g.ShellFunction) or 1 / 0)
    check("MPIFunction uses $PARSL_MPI_PREFIX",
          lambda: "PARSL_MPI_PREFIX" in inspect.getsource(g.MPIFunction) or 1 / 0)

    print(f"PASS: {len(oks)}")
    for o in oks:
        print("  [OK]", o)
    if fails:
        print(f"FAIL: {len(fails)}")
        for f in fails:
            print("  [XX]", f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
