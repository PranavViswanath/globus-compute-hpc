# Troubleshooting & Error Handling

## Exception types — catch these, not bare `Exception`

All from `globus_compute_sdk.errors`:

| Exception | Meaning | Action |
|---|---|---|
| `TaskExecutionFailed` | Your function raised on the worker; carries the remote traceback | Read the traceback (`str(e)`); it appends serialization hints when dill/pickle is implicated |
| `VersionMismatch` | Client/endpoint version conflict, or version unavailable | Align Python minor versions and SDK versions |
| `SerializationError` / `DeserializationError` (both subclass `SerdeError`) | Payload (de)serialization failed | Imports inside the function; try a different strategy (below) |
| `MaxResultSizeExceeded` | Return value over the result-size limit (~10 MB) | Write outputs to the filesystem, return the path |
| `TaskPending` | No result yet (low-level `Client` polling) | Wait; `Executor` futures handle this for you |
| `ComputeError` | Base class for SDK errors | Catch-all backstop |

```python
from globus_compute_sdk.errors import (
    TaskExecutionFailed, VersionMismatch,
    SerializationError, DeserializationError, MaxResultSizeExceeded,
)

try:
    result = future.result()
except TaskExecutionFailed as e:
    print("Function raised remotely:", e)        # includes remote traceback
except VersionMismatch as e:
    print("Align Python/SDK versions:", e)
except MaxResultSizeExceeded as e:
    print("Return a file path instead:", e)
except (SerializationError, DeserializationError) as e:
    print("Payload didn't serialize:", e)
```

Serialization-strategy fallback (the help text Compute itself suggests when a
task failure looks serde-related):

```python
from globus_compute_sdk import Executor
from globus_compute_sdk.serialize import ComputeSerializer, AllCodeStrategies

with Executor("<endpoint-id>") as gcx:
    gcx.serializer = ComputeSerializer(strategy_code=AllCodeStrategies())
```

## Failure tree

**Endpoint won't start**
→ `cat ~/.globus_compute/<name>/endpoint.log`. Template render errors surface
here; reproduce offline with `globus-compute-endpoint render-user-config -e <name> ...`
(pipe through `yq` to validate the YAML). Stale PID after a crash → exit code
73 (`EX_CANTCREAT`); check for a lingering process before removing the pidfile.

**Tasks submitted, nothing ever runs, no scheduler job appears**
→ The provider failed to submit. Check `endpoint.log` for the scheduler's
rejection (bad `account`, nonexistent `queue`/`partition`, malformed
`scheduler_options`, missing mandatory directives — e.g. Aurora requires
`-l filesystems=...`). Raise `cmd_timeout` if the scheduler CLI is slow.

**Scheduler job visible and running, but tasks still hang**
→ Workers can't connect back to the UEP: wrong `address.ifname` (below), or
`worker_init` crashed before the worker started — check the block's
stdout/stderr files under `~/.globus_compute/<name>/` worker logs and your
scheduler job output.

**Tasks ran before but now queue forever**
→ Allocation exhausted, or walltime killed the block mid-task. Consider
`max_retries_on_system_failure: 2` for walltime-related worker deaths.

**"Worker lost"**
→ Python minor-version mismatch between submitter and endpoint in the vast
majority of cases. Match versions (e.g. both 3.11.x), or have the admin enable
multiple Python environments.

**`Identity failed to map to a local user name` (multi-user)**
→ Identity mapping config doesn't cover the submitting identity. Admins:
iterate with `globus-idm-validator`; find the submitted identity in
`endpoint.log` (search `Globus effective identity`, or `globus_identity_set`
with debug logging).

**`SystemExit` with a number (multi-user UEP start failure)** — exit codes:

| Code | Constant | Likely reason |
|---|---|---|
| 65 | `EX_DATAERR` | Endpoint registration rejected (HTTP 400/422) — see logs |
| 69 | `EX_UNAVAILABLE` | Registration blocked (HTTP 404/409/423) |
| 70 | `EX_SOFTWARE` | Unexpected API response — endpoint install likely very outdated |
| 73 | `EX_CANTCREAT` | Can't create PID file — another instance may be running |
| 77 | `EX_NOPERM` | Can't read identity mapping config (permissions) |
| 78 | `EX_CONFIG` | Identity mapping config unreadable/unparseable |

## Finding the right ifname

Workers reach the UEP over the cluster's **internal** network. From the
upstream docs, on the endpoint host:

```bash
ip addr                       # list interfaces; candidates show UP
# The INTERNAL interface is the one where pinging the outside world FAILS:
ping -c 1 -I <ifname> google.com >/dev/null 2>&1; echo $?
#   0 → external-facing (wrong);  nonzero → likely internal (try it)
```

Known values: `hsn0` (Polaris, Perlmutter — Slingshot), `ib0` (Expanse —
InfiniBand), `bond0` (Midway). When unsure, ask the system admin — and prefer
copying a known-good config for the system.

## Verifying what workers actually see

```python
from globus_compute_sdk import Executor

with Executor(endpoint_id=EP_ID) as ex:
    print(ex.get_worker_hardware_details())   # CPU/GPU/memory report from a worker node
```

If this returns, your full chain (auth → endpoint → scheduler → worker) works.
A lighter-weight check of just the service linkage:

```python
from globus_compute_sdk import Client
print(Client().get_endpoint_status(EP_ID))    # {'status': 'online', ...}
```

## Collecting a full diagnostic bundle

The SDK ships a standalone `globus-compute-diagnostic` command (entry point
`globus_compute_sdk.sdk.diagnostic`) — note this is a **separate executable**,
not a `globus-compute-endpoint` subcommand (there is no `self-diagnostic`
subcommand, despite older posts). It gathers OS, Python, package versions,
network reachability to the Compute services, and recent endpoint logs into a
gzip bundle for support tickets:

```bash
globus-compute-diagnostic -p                 # print to console instead of a gzip file
globus-compute-diagnostic -e <ENDPOINT_UUID> # include a specific endpoint
globus-compute-diagnostic -k 2048            # read up to 2 MB per log file
```

For quick local checks prefer `endpoint.log`, `render-user-config`, and the
status/hardware checks above.

## Idle/lifecycle behavior worth knowing

- Heartbeat = 30 s. `idle_heartbeats_soft: 10` → an idle UEP exits after ~5 min;
  `idle_heartbeats_hard: 5760` → an apparently-stuck UEP is killed after 48 h.
  The endpoint re-launches a UEP on the next task; brief cold-start latency
  after idle periods is normal.
- `globus-compute-endpoint enable-on-boot <name>` survives machine restarts
  (login-node policy permitting).
