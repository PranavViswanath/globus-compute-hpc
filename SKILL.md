---
name: globus-compute-hpc
description: >
  Configure and run Globus Compute endpoints on HPC systems, and execute
  multi-node/MPI applications through them. Use when:
  (1) installing/configuring globus-compute-endpoint on Slurm or PBS clusters
  (Polaris, Perlmutter, Aurora, Expanse);
  (2) writing endpoint config templates — user_config_template.yaml.j2,
  GlobusComputeEngine/GlobusMPIEngine, SlurmProvider/PBSProProvider,
  launchers, worker_init, blocks;
  (3) running MPI codes with MPIFunction and resource_specification;
  (4) parametrizing shared multi-user endpoints with user_endpoint_config;
  (5) debugging endpoints — worker lost, version mismatch, tasks never
  starting. Never use the deprecated funcx package or the removed
  HighThroughputEngine.
compatibility: Requires globus-compute-endpoint installed on the target system and an account/allocation there. Client side requires globus-compute-sdk.
metadata:
  version: "1.0"
  service: globus-compute
  schedulers: pbs, slurm
allowed-tools: Bash(globus-compute-endpoint *) Bash(gce *) Bash(pip *) Bash(pipx *) Bash(python *) Bash(ip *) Read Write
---

# Globus Compute Endpoints — HPC Configuration & MPI Execution

| | |
|---|---|
| **Owns** | Endpoint configuration for HPC + MPI/multi-node execution |
| **Defers to** | `globus-sdk` skill (client SDK basics) · `pbs`/`slurm`/`aurora`/`perlmutter` skills (scheduler & system specifics) |
| **Packages** | `globus-compute-endpoint` (target machine) · `globus-compute-sdk` (client) |
| **Key files** | `~/.globus_compute/<name>/user_config_template.yaml.j2` (the config) · `config.yaml` (manager) · `endpoint.log` (debugging) |
| **Hard rules** | `init_blocks: 0` · launcher matches scheduler · MPI = `GlobusMPIEngine`+`SimpleLauncher`+`MPIFunction` · never `funcx`/`HighThroughputEngine` |

Globus Compute (formerly **funcX** — never use the `funcx` package) is
Function-as-a-Service for research computing: submit a Python function from
anywhere and run it on a remote machine, without SSH or hand-written scheduler
scripts. It has two sides:

- **Client** (`globus-compute-sdk`): `Executor`, `submit()`, `result()` — covered
  by the `globus-sdk` skill. Defer client-SDK basics there.
- **Endpoint** (`globus-compute-endpoint`, a separate package): a daemon on the
  target machine that receives functions and runs them. **This skill owns the
  endpoint side, plus MPI/multi-node execution.**

**The key reframe:** an endpoint config encodes the same knowledge as a PBS/Slurm
job script — rearranged as YAML so the endpoint submits scheduler jobs for you
and your Python function runs in the worker instead of `./my_app`. For scheduler
directive syntax and system specifics (queues, modules, filesystems), defer to
the `pbs`, `slurm`, `aurora`, `perlmutter`, and `frontier` skills; this skill
teaches only the Globus Compute translation layer.

## Process Model (where did my job die?)

| Process | Role | Configured by |
|---|---|---|
| **MEP** — Manager Endpoint Process | Renders config template, launches/manages UEPs | `config.yaml` |
| **UEP** — User Endpoint Process | Talks to Globus services, requests scheduler jobs, launches workers | `user_config_template.yaml.j2` |
| **Worker** | Executes tasks on compute nodes | (engine settings) |

**The engine/provider block goes in `user_config_template.yaml.j2`** — even for
a single-user endpoint. `config.yaml` only configures the manager process
(display_name, amqp_port, and multi-user fields). Older endpoints can be
upgraded with `globus-compute-endpoint migrate-to-template-capable <name>`.

## Quickstart

```bash
pipx install globus-compute-endpoint     # on the TARGET machine (login node)
globus-compute-endpoint configure my-ep  # creates ~/.globus_compute/my-ep/
# edit ~/.globus_compute/my-ep/user_config_template.yaml.j2  (see below)
globus-compute-endpoint start my-ep      # prints the endpoint UUID
globus-compute-endpoint stop my-ep
```

`gce` is installed as a shell alias for `globus-compute-endpoint`. Other
subcommands: `list`, `restart`, `delete`, `login`, `logout`, `whoami`,
`enable-on-boot`, `disable-on-boot`, `render-user-config` (test a template
without starting anything — see workflow below), `migrate-to-template-capable`.

> `configure` generates a **LocalProvider** template — tasks run on the login
> node, NOT on compute nodes. To use the cluster you must replace the provider
> block. This is the single most-skipped step.

## Universal Config Anatomy

Every HPC endpoint template is this shape (it is a job script, rearranged):

```yaml
engine:                      # HOW work runs on a node
  type: GlobusComputeEngine  #   or GlobusMPIEngine for multi-node MPI tasks
  max_workers_per_node: 4    #   concurrent tasks per node
  # available_accelerators: 4  # pin 1 worker per GPU (omit for CPU-only)
  address:
    type: address_by_interface
    ifname: hsn0             # the internal/fast NIC — SYSTEM-SPECIFIC, never guess
  provider:                  # HOW to get nodes (= the #PBS/#SBATCH knowledge)
    type: PBSProProvider     #   or SlurmProvider | LocalProvider | KubernetesProvider
    launcher:
      type: MpiExecLauncher  #   MUST match scheduler — see routing table
    account: {{ ACCOUNT }}   #   -A / --account     (allocation to charge)
    queue: debug             #   -q  (PBS)   — Slurm uses `partition:` instead
    scheduler_options: "#PBS -l filesystems=home:flare"  # raw extra directives
    worker_init: {{ COMMAND }}  # shell run before workers, e.g. "module load ...; conda activate env"
    walltime: 01:00:00
    nodes_per_block: 1       # nodes per scheduler job ("block")
    init_blocks: 0           # ★ blocks grabbed AT STARTUP — keep 0
    min_blocks: 0            # ★ floor — 0 lets it scale to nothing when idle
    max_blocks: 2            # ceiling on concurrent scheduler jobs
```

A **block** = one scheduler job holding `nodes_per_block` nodes. The endpoint
auto-scales between `min_blocks` and `max_blocks` as tasks arrive.

`{{ VAR }}` placeholders are Jinja variables: supply values from the client via
`Executor(user_endpoint_config={...})`, or replace them with literal values for
a personal endpoint.

## Non-Negotiable Rules

1. **`init_blocks: 0`, `min_blocks: 0`** — anything else grabs and holds compute
   nodes the moment the endpoint starts, burning allocation with zero work
   queued. This is the #1 allocation-wasting mistake.
2. **Launcher must match the scheduler** — `MpiExecLauncher` with
   `PBSProProvider`; `SrunLauncher` with `SlurmProvider`. Never `srun` on a PBS
   system (Polaris, Aurora).
3. **MPI is a package deal** — `MPIFunction` + `Executor.resource_specification`
   on the client REQUIRES `type: GlobusMPIEngine` + `launcher: SimpleLauncher`
   in the endpoint template. Mixing with `GlobusComputeEngine` fails.
4. **Never emit `funcx` or `HighThroughputEngine`** — funcx is the dead pre-2023
   brand; `HighThroughputEngine` has been removed from the codebase. Valid
   engines: `GlobusComputeEngine`, `GlobusMPIEngine`, `ThreadPoolEngine`,
   `ProcessPoolEngine` (last two: single-host only).
5. **Imports inside the function body**; required packages must exist in the
   endpoint's `worker_init` environment; submitter and endpoint Python **minor
   versions must match** (mismatch → "worker lost" / serialization failures).
6. **Don't guess `ifname`** — copy it from a known config for that system, or
   discover it (see [references/troubleshooting.md](references/troubleshooting.md)).

## Engine / Provider / Launcher Routing

| Target | engine | provider | launcher |
|---|---|---|---|
| Laptop / login node / workstation | `GlobusComputeEngine` | `LocalProvider` | (default) |
| PBS cluster (Polaris, Aurora) | `GlobusComputeEngine` | `PBSProProvider` | `MpiExecLauncher` |
| Slurm cluster (Perlmutter, Expanse) | `GlobusComputeEngine` | `SlurmProvider` | `SrunLauncher` |
| MPI / multi-node tasks (any scheduler) | `GlobusMPIEngine` + `mpi_launcher: srun\|mpiexec` | scheduler provider | `SimpleLauncher` (required) |
| Kubernetes | `GlobusComputeEngine` | `KubernetesProvider` | — |

Known-good configs to adapt (bundled, copied verbatim from the globus-compute
repo): [assets/configs/](assets/configs/) — `polaris.yaml` (PBS+GPU),
`perlmutter.yaml` (Slurm), `expanse_mpi.yaml` (GlobusMPIEngine),
`aurora.yaml` (**DRAFT** — composed, not yet validated on a live endpoint;
verify flagged lines against ALCF docs before relying on it).

## Workflow: configure → render → start → smoke-test → debug

1. **Configure**: `gce configure my-ep`; replace the template with an adapted
   known-good config for the target system
   ([references/endpoint-config.md](references/endpoint-config.md)).
2. **Validate the template before starting** (catches Jinja/YAML errors offline):
   ```bash
   echo '{"ACCOUNT": "myproject", "COMMAND": "module load conda; conda activate myenv"}' > opts.json
   globus-compute-endpoint render-user-config -e my-ep -o opts.json
   ```
3. **Start**: `gce start my-ep` → note the endpoint UUID.
4. **Smoke-test from the client machine** (proves config end-to-end — the task
   only returns if the scheduler job ran and a worker executed it):
   ```bash
   python scripts/smoke_test.py <ENDPOINT_UUID>
   ```
5. **Debug**: logs live in `~/.globus_compute/my-ep/endpoint.log`. Failure tree
   in [references/troubleshooting.md](references/troubleshooting.md).

## Common Gotchas

- Endpoint starts fine but tasks hang forever → provider/queue/account wrong, or
  scheduler job is queued: check the scheduler directly (`qstat -u $USER` /
  `squeue --me`) — a block IS a visible scheduler job.
- Tasks hang with blocks running → wrong `ifname`; workers can't reach the UEP.
- "Worker lost" → almost always Python minor-version mismatch client↔endpoint.
- `MaxResultSizeExceeded` → return values traverse the network (10 MB limit);
  write large outputs to the filesystem and return the path.
- Allocation draining while idle → `init_blocks`/`min_blocks` not 0.
- Catch specific exceptions (`TaskExecutionFailed`, `VersionMismatch`, ...), not
  bare `Exception` — see [references/troubleshooting.md](references/troubleshooting.md).

## Additional Resources

- Annotated per-system configs, blocks model, GPU pinning, retries, auto-scaling:
  [references/endpoint-config.md](references/endpoint-config.md)
- MPI/multi-node execution (`MPIFunction`, `resource_specification`,
  `GlobusMPIEngine`): [references/mpi-execution.md](references/mpi-execution.md)
- Shared/templated endpoints (`user_endpoint_config`, Jinja templates, identity
  mapping): [references/multi-user-endpoints.md](references/multi-user-endpoints.md)
- Error types, failure tree, ifname discovery, exit codes:
  [references/troubleshooting.md](references/troubleshooting.md)
- Verbatim + draft configs: [assets/configs/](assets/configs/) · Smoke test:
  [scripts/smoke_test.py](scripts/smoke_test.py)
- Upstream docs: https://globus-compute.readthedocs.io/ (endpoints section)
- Related skills: `globus-sdk` (client SDK), `pbs`, `slurm`, `aurora`,
  `perlmutter`, `frontier` (scheduler/system specifics)
