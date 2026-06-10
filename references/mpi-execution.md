# MPI / Multi-Node Execution

How to run real MPI applications (LAMMPS, VASP, CP2K, ...) through Globus
Compute. This is the least-known part of the API — `MPIFunction` is a top-level
SDK export, but almost no training data covers it. Do NOT hand-roll `mpirun`
inside a plain `ShellFunction`; use the machinery below.

## The package deal

MPI execution requires BOTH sides to agree:

| Side | Requirement |
|---|---|
| Endpoint template | `engine.type: GlobusMPIEngine` + `engine.mpi_launcher: srun\|mpiexec` + `provider.launcher.type: SimpleLauncher` |
| Client code | `MPIFunction(...)` + `Executor.resource_specification = {...}` |

Submitting an `MPIFunction` to a `GlobusComputeEngine` endpoint, or omitting
`SimpleLauncher`, are the two canonical failures.

Why `SimpleLauncher`? With `GlobusComputeEngine` the provider's launcher
(srun/mpiexec) spreads *workers* across nodes. With `GlobusMPIEngine` the
engine itself partitions the block's nodes per task and builds the MPI launch
command — so the provider must NOT also spread things, hence the no-op
`SimpleLauncher`.

## Endpoint template (Expanse example — verbatim upstream)

```yaml
engine:
    type: GlobusMPIEngine
    mpi_launcher: srun               # the MPI program launcher: srun | mpiexec
    address:
        type: address_by_interface
        ifname: ib0                  # Expanse = InfiniBand; copy per system
    provider:
        type: SlurmProvider
        partition: compute
        account: {{ ACCOUNT }}
        launcher:
            type: SimpleLauncher     # REQUIRED with GlobusMPIEngine
        scheduler_options: {{ OPTIONS }}
        worker_init: {{ COMMAND }}
        nodes_per_block: 4           # block size = the node pool MPI tasks carve up
        init_blocks: 0
        min_blocks: 0
        max_blocks: 1
        walltime: 00:05:00
```

Optionally cap concurrent MPI tasks per block on the engine:

```yaml
engine:
    type: GlobusMPIEngine
    mpi_launcher: srun
    max_workers_per_block: 4         # ≤ 4 MPI tasks share the block at once
```

On a PBS system (Polaris/Aurora) the same shape applies with
`mpi_launcher: mpiexec` and `provider.type: PBSProProvider` (launcher stays
`SimpleLauncher`).

## Client code

`MPIFunction` subclasses `ShellFunction`; it prepends `$PARSL_MPI_PREFIX`
(the engine-built launch command, e.g. `srun -N 2 -n 128 ...`) to your command:

```python
from globus_compute_sdk import Executor, MPIFunction

mpi_func = MPIFunction("lmp -in in.melt")        # your MPI binary + args

with Executor(endpoint_id=MPI_EP_ID) as ex:
    ex.resource_specification = {
        "num_nodes": 2,        # nodes for this task (≤ nodes_per_block)
        "ranks_per_node": 64,  # MPI ranks per node
    }
    future = ex.submit(mpi_func)
    result = future.result()   # a ShellResult
    print(result.returncode, result.stdout)
```

`resource_specification` keys (Parsl MPI spec):

| Key | Meaning |
|---|---|
| `num_nodes` | nodes allocated to this task |
| `ranks_per_node` | MPI ranks per node |
| `num_ranks` | total ranks (alternative to ranks_per_node) |

Each submission can use a different `resource_specification` — set it before
each `submit()` to right-size individual tasks:

```python
with Executor(endpoint_id=MPI_EP_ID) as ex:
    for nodes in (1, 2, 4):
        ex.resource_specification = {"num_nodes": nodes, "ranks_per_node": 64}
        print(ex.submit(mpi_func).result().stdout)
```

Like all `ShellFunction`s, the command string supports `{placeholders}` filled
from kwargs at submit time: `MPIFunction("lmp -in {deck}")` →
`ex.submit(mpi_func, deck="in.melt")`.

## Gotchas

- `nodes_per_block` is the *pool*; `num_nodes` is the per-task *slice*. A task
  asking for more nodes than a block holds never starts.
- The MPI application, modules, and environment come from `worker_init` — the
  function command runs in that shell environment on the compute nodes.
- The result is a `ShellResult` (`.returncode`, `.stdout`, `.cmd`) — check
  `returncode`; a crashed MPI run still "succeeds" as a task.
- Plain Python functions can still be submitted to a `GlobusMPIEngine` endpoint
  but each one consumes an MPI slot; keep a separate `GlobusComputeEngine`
  endpoint for non-MPI work.
