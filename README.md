# globus-compute-hpc — Agent Skill

An [Agent Skill](https://agentskills.io/specification) (for Claude Code and
compatible tools) that helps a model write Globus Compute endpoint config and
multi-node/MPI code that actually runs. These are the parts of the API that
LLMs tend to botch, and that the existing Globus skills don't cover.

> **Status:** independent draft, up for review. The content is checked against
> the current `globus-compute` source and the published SDK (see
> [Testing](#testing)). The one piece that still needs a human to sign off is
> the Aurora config — see [What still needs ALCF/Polaris review](#what-still-needs-alcfpolaris-review).

## The gap it fills

Globus Compute (formerly funcX) has two sides, with a seam between them that
nothing currently owns:

| Side | Package | Covered by |
|---|---|---|
| Client — write a function, submit it, get results | `globus-compute-sdk` | [`ryanchard/globus-skill`](https://github.com/ryanchard/globus-skill) (the `globus-sdk` skill) |
| Scheduler / system specifics — PBS/Slurm directives, queues, modules | — | Genesis `hpc-skills` (`pbs`, `slurm`, `aurora`, `perlmutter`, `frontier`) |
| Endpoint config + MPI execution — turn scheduler knowledge into a running endpoint | `globus-compute-endpoint` | this skill |

Ryan Chard's `globus-sdk` skill takes you up to `globus-compute-endpoint
configure`, but that command hands you a `LocalProvider` endpoint that runs on
the login node, not on the cluster. The Genesis HPC skills cover the scheduler
side, but as job-script syntax. Neither one explains how to turn that into a
working endpoint config, and neither touches MPI. That's the job here.

The config is less mysterious than it looks. It holds the same information you'd
put in a PBS or Slurm job script, written as YAML so the endpoint daemon submits
the job for you and your Python function runs in the worker instead of
`./my_app`. The skill sticks to that translation step and points elsewhere for
the rest: client usage goes to Ryan's skill, scheduler syntax to the hpc-skills.

### What LLMs get wrong here

- **MPI / multi-node.** `MPIFunction` with `resource_specification` and a
  `GlobusMPIEngine`/`SimpleLauncher` endpoint. It's a top-level SDK export but
  barely appears in training data, so models hand-roll `mpirun` inside a
  `ShellFunction` and get it wrong.
- **`init_blocks: 0`.** Any other value grabs idle compute nodes the moment the
  endpoint starts and burns allocation for no reason. Easily the most expensive
  mistake.
- **Dead APIs.** Most training data predates the funcX → Globus Compute rebrand,
  so models still reach for `funcx` and the long-removed `HighThroughputEngine`.
- **Launcher/scheduler mismatch.** `MpiExecLauncher` belongs with PBS,
  `SrunLauncher` with Slurm; mixing them fails.
- **The login-node trap.** Not realizing `configure` produces a LocalProvider
  endpoint that never touches a compute node.

## Layout

```
globus-compute-hpc/
├── SKILL.md                          # entry point: mental model, rules, routing, workflow
├── references/
│   ├── endpoint-config.md            # engines, providers, launchers, the blocks model
│   ├── mpi-execution.md              # MPIFunction + resource_specification + GlobusMPIEngine
│   ├── multi-user-endpoints.md       # user_endpoint_config, Jinja templating, identity mapping
│   └── troubleshooting.md            # error types, failure tree, ifname discovery, diagnostics
├── assets/configs/
│   ├── polaris.yaml                  # verbatim from globus-compute repo (PBS + GPU)
│   ├── perlmutter.yaml               # verbatim (Slurm)
│   ├── expanse_mpi.yaml              # verbatim (GlobusMPIEngine)
│   └── aurora.yaml                   # DRAFT — composed, needs ALCF review (see below)
├── scripts/
│   └── smoke_test.py                 # prove an endpoint works end-to-end (--hardware / --ase)
└── tests/                            # self-verification, see Testing
```

## Using the skill

Drop the `globus-compute-hpc/` directory into your skills folder (for example
`~/.claude/skills/globus-compute-hpc/`) and start a session. It activates on
prompts like:

- "Set up a Globus Compute endpoint on Perlmutter / Polaris"
- "Run LAMMPS across 4 nodes through Globus Compute"
- "My Compute tasks hang forever / worker lost"
- "Our facility runs one shared endpoint — how do users pass their own account?"

## Testing

Anything that can be checked without an HPC allocation is, and the checks live
in the repo so you can re-run them:

```bash
pip install -r tests/requirements-dev.txt
python tests/test_skill_format.py     # frontmatter + links vs the Agent Skills spec
python tests/test_sdk_symbols.py      # every SDK symbol the skill cites is real (vs 4.12.0)
python tests/test_render_configs.py   # every bundled config renders to valid YAML + invariants
```

What that covers, run against `globus-compute-sdk`/`-endpoint` 4.12.0:

- Every SDK member the skill names (23 of them) exists in the published package:
  `MPIFunction`, `Executor.resource_specification`/`user_endpoint_config`, the
  eight error types, `ComputeSerializer`/`AllCodeStrategies`,
  `get_worker_hardware_details`, and the rest.
- All four bundled configs render through the same Jinja→YAML path
  `render-user-config` uses and hold to the skill's invariants: only
  `GlobusComputeEngine`/`GlobusMPIEngine`, `init_blocks`/`min_blocks` at 0, and
  `GlobusMPIEngine` paired with `SimpleLauncher`. Writing this test turned up two
  real bugs in the Aurora draft (a JSON-quoted variable interpolated inside a
  quoted string, and a `{{ }}` left in a YAML comment, which Jinja still
  renders). Both are fixed and the test now catches them.
- `smoke_test.py` handles its arguments, runs both payloads, gives a useful
  message when ASE is missing, and gets as far as the Globus auth prompt.
- SKILL.md passes the spec: name matches the directory, description is 703/1024
  characters, the body is 179 lines, and every relative link resolves.

What's left for a real machine: an actual end-to-end `smoke_test.py` run against
a configured endpoint, which needs interactive Globus auth and an allocation.
The script is correct up to the auth prompt. Run it against a `LocalProvider`
endpoint on any Linux host to exercise the full client→endpoint→worker path, or
against Polaris/Perlmutter for the HPC path. One caveat: `globus-compute-endpoint`
is POSIX-only (the CLI imports `pwd`), so the endpoint daemon doesn't run on
Windows. The SDK and these tests do.

## What still needs ALCF/Polaris review

`assets/configs/aurora.yaml` was composed, not validated against a running
Aurora endpoint. There's no public Aurora example in the globus-compute repo (as
of June 2026), so it borrows the Polaris config's structure and fills in Aurora
specifics from ALCF docs and the Genesis `aurora` skill. Every line I wasn't sure
about is tagged `VERIFY`. Before trusting it, check these against the
[ALCF Aurora docs](https://docs.alcf.anl.gov/aurora/) or with ALCF support:

- `address.ifname` — Aurora has 8 NICs per node; which interface to use
- GPU granularity — `available_accelerators`/`max_workers_per_node`: 6 devices
  or 12 tiles
- `overrides: --depth=104` and the cpus/gpus-per-node counts
- whether to target a single-user or an ALCF-managed multi-user endpoint

The other three (`polaris`, `perlmutter`, `expanse_mpi`) are copied byte-for-byte
from `globus/globus-compute` under `docs/endpoints/configs/`.

## Provenance

Built and checked against `globus/globus-compute` @ `94b69e5` (2026-06-08), the
published `globus-compute-sdk` / `globus-compute-endpoint` 4.12.0, and the
conventions used by the Genesis `hpc-skills`. The aim is to contribute it to the
Genesis Mission skills catalog under `hpc-skills/`.

## License

Apache-2.0, matching the Genesis skills catalog. See [LICENSE](LICENSE).
