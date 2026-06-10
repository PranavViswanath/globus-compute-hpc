# Endpoint Configuration Reference

How to write `user_config_template.yaml.j2` for real HPC systems. Every config
here is grounded in the globus-compute repo (`docs/endpoints/configs/` and the
endpoint package defaults); verbatim copies live in [../assets/configs/](../assets/configs/).

## Which file does what

```
~/.globus_compute/<endpoint-name>/
├── config.yaml                    # MANAGER process: display_name, amqp_port,
│                                  #   multi-user fields (identity mapping, admins, ...)
├── user_config_template.yaml.j2   # ★ THE config: engine + provider + launcher.
│                                  #   Jinja template, rendered per user/submission.
├── user_config_schema.json        # JSON Schema validating user-supplied variables
├── user_environment.yaml          # site env vars exported to the UEP
└── endpoint.log                   # first place to look when debugging
```

For a personal single-user endpoint you can hardcode values in the template
(no Jinja variables needed). Keep the `{{ VAR }}` placeholders if you want to
pass values from the client via `Executor(user_endpoint_config={...})` — see
[multi-user-endpoints.md](multi-user-endpoints.md).

## What `configure` gives you (and why it's not enough)

The generated template is functional but **local-only**:

```yaml
endpoint_setup: {{ endpoint_setup|default() }}
engine:
  type: GlobusComputeEngine
  max_workers_per_node: 1
  provider:
    type: LocalProvider        # ← runs on the endpoint host (login node), NOT compute nodes
    min_blocks: 0
    max_blocks: 1
    init_blocks: 1
    worker_init: {{ worker_init|default() }}
idle_heartbeats_soft: 10       # idle UEP shuts down after ~5 min (heartbeat = 30 s)
idle_heartbeats_hard: 5760     # apparently-stuck UEP killed after 48 h
```

To use the cluster: swap `LocalProvider` for the scheduler provider and fill in
account/queue/launcher/worker_init, as below.

## The blocks model (read this before setting any numbers)

A **block** is one scheduler job that acquires `nodes_per_block` nodes and runs
workers on them. The engine auto-scales the number of blocks between
`min_blocks` and `max_blocks` based on queued tasks.

| Field | Meaning | Rule |
|---|---|---|
| `nodes_per_block` | nodes per scheduler job | size to your largest task (1 for single-node functions) |
| `init_blocks` | blocks requested at endpoint startup | **always 0** — nonzero holds idle nodes |
| `min_blocks` | floor while running | **0** so an idle endpoint costs nothing |
| `max_blocks` | ceiling | your concurrency budget |

Auto-scaling knobs (optional, on the engine):

```yaml
engine:
  type: GlobusComputeEngine
  job_status_kwargs:
    max_idletime: 60.0       # seconds workers may idle before scale-down (default 120)
    strategy_period: 120.0   # seconds between scaling decisions (default 5)
```

Infrastructure retries (default 0 — functions may not be idempotent):

```yaml
engine:
  type: GlobusComputeEngine
  max_retries_on_system_failure: 2
```

## Polaris (ALCF) — PBS + GPUs [verbatim upstream]

```yaml
engine:
  type: GlobusComputeEngine
  max_workers_per_node: 4
  # available_accelerators: 4      # uncomment → each worker gets exclusive use of 1 GPU
  address:
    type: address_by_interface
    ifname: hsn0                   # Polaris Slingshot fabric — system-specific
  provider:
    type: PBSProProvider
    launcher:
      type: MpiExecLauncher        # PBS → mpiexec (NOT srun)
      bind_cmd: --cpu-bind
      overrides: --depth=64 --ppn 1   # 1 manager per node, all 64 cores
    account: {{ POLARIS_ACCOUNT }}
    queue: debug-scaling
    cpus_per_node: 32
    select_options: ngpus=4        # appended to the PBS select statement
    scheduler_options: "#PBS -l filesystems=home:grand:eagle"   # raw directives
    worker_init: {{ COMMAND }}     # e.g. "module load conda; conda activate my-env"
    walltime: 01:00:00
    nodes_per_block: 1
    init_blocks: 0
    min_blocks: 0
    max_blocks: 2
```

GPU pinning: `available_accelerators: N` gives each of N workers one exclusive
GPU (sets the appropriate visibility env var per worker). Match it to
`max_workers_per_node`.

## Perlmutter (NERSC) — Slurm [verbatim upstream]

```yaml
engine:
    type: GlobusComputeEngine
    worker_debug: False
    address:
        type: address_by_interface
        ifname: hsn0
    provider:
        type: SlurmProvider
        partition: debug             # Slurm: partition (PBS uses queue)
        launcher:
            type: SrunLauncher       # Slurm → srun
            overrides: -c 128        # all hyperthreads (GPU nodes: 128)
        scheduler_options: {{ OPTIONS }}   # e.g. "#SBATCH --constraint=gpu\n#SBATCH --gpus-per-node=4"
        account: {{ NERSC_ACCOUNT }}       # e.g. "m0000"
        worker_init: {{ COMMAND }}
        cmd_timeout: 120             # slow scheduler? raise command timeout
        nodes_per_block: 2
        init_blocks: 0
        min_blocks: 0
        max_blocks: 1
        walltime: 00:10:00
```

**PBS vs Slurm contrast** — the fields that change:
`PBSProProvider`+`MpiExecLauncher`+`queue`+`select_options`+`#PBS ...`
vs `SlurmProvider`+`SrunLauncher`+`partition`+`#SBATCH ...`. Everything else
(engine, address, blocks) is identical in shape.

## Aurora (ALCF) — DRAFT

There is **no public Aurora example** in the globus-compute repo (verified June
2026), although Aurora endpoints exist in practice. The bundled
[../assets/configs/aurora.yaml](../assets/configs/aurora.yaml) composes the
Polaris structure (same facility, scheduler, and fabric family) with Aurora
system facts from the `aurora` skill / ALCF docs. Every uncertain line is
marked `VERIFY`. Confirm against https://docs.alcf.anl.gov/aurora/ or ALCF
support before depending on it; key Aurora-specific facts: PBS scheduler,
`mpiexec` (never srun), mandatory `#PBS -l filesystems=home:flare`, queues
`debug`/`prod`/`prod-large`, 104 cores + 6 Intel PVC GPUs per node, oneAPI
modules via `module use /soft/modulefiles`.

## `address` — the interface field LLMs guess wrong

Workers on compute nodes must reach the UEP on the login node over the
**internal** network. `ifname` is system-specific: `hsn0` on Polaris/Perlmutter
(Slingshot), `ib0` on Expanse (InfiniBand), `bond0` on Midway. Copy from a
known config; otherwise discover it per
[troubleshooting.md](troubleshooting.md#finding-the-right-ifname).

## Other engines (single-host only)

`ThreadPoolEngine` and `ProcessPoolEngine` wrap Python's executors — fine for a
workstation endpoint, never for a cluster:

```yaml
engine:
  type: ProcessPoolEngine
  max_workers: 4
```

## Manager `config.yaml` quick reference

Single-user endpoints rarely need more than:

```yaml
display_name: My Polaris endpoint   # how it appears in app.globus.org/compute
```

Multi-user fields (`public`, `identity_mapping_config_path`, `admins`,
`allowed_functions`, `authentication_policy`, `pam`,
`user_config_template_path`, `user_config_schema_path`) are covered in
[multi-user-endpoints.md](multi-user-endpoints.md).
