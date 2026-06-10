# globus-compute-hpc — Agent Skill

A [Claude Code / Agent Skill](https://agentskills.io/specification) that helps an
LLM produce **correct Globus Compute endpoint configuration and multi-node/MPI
execution code** — the parts of the real API that models reliably get wrong and
that no existing skill covers.

> **Status:** independent draft for review. The skill content is verified against
> the live `globus-compute` source and the published SDK (see
> [Testing](#testing)). The one artifact that still needs human sign-off is the
> **Aurora config** — see [What needs ALCF/Polaris review](#what-needs-alcfpolaris-review).

## The gap it fills

Globus Compute (formerly funcX) has two sides:

| Side | Package | Covered by |
|---|---|---|
| **Client** — write a function, submit, get results | `globus-compute-sdk` | [`ryanchard/globus-skill`](https://github.com/ryanchard/globus-skill) (the `globus-sdk` skill) |
| **Scheduler / system specifics** — PBS/Slurm directives, queues, modules | — | Genesis `hpc-skills` (`pbs`, `slurm`, `aurora`, `perlmutter`, `frontier`) |
| **Endpoint config + MPI execution** — translate scheduler knowledge into a running endpoint | `globus-compute-endpoint` | **← this skill** |

Ryan's skill stops at `globus-compute-endpoint configure` — which produces a
**LocalProvider** endpoint that runs on the *login node*, not the cluster. The
Genesis HPC skills teach scheduler knowledge in *job-script* form. The seam
between them — the endpoint config YAML, plus `MPIFunction`/multi-node execution
— is unowned. That seam is this skill.

The core idea: **an endpoint config encodes the same knowledge as a PBS/Slurm job
script, rearranged as YAML** so the endpoint daemon submits jobs for you and your
Python function runs in the worker instead of `./my_app`. The skill teaches only
that translation layer and hands off in both directions (client basics → Ryan's
skill; scheduler syntax → the hpc-skills).

### What an LLM gets wrong that this fixes

1. **MPI / multi-node** — `MPIFunction` + `resource_specification` +
   `GlobusMPIEngine`/`SimpleLauncher`. A top-level SDK export with near-zero
   coverage in training data; models hand-roll `mpirun` in a `ShellFunction`.
2. **`init_blocks: 0`** — anything else silently holds idle compute nodes and
   burns allocation. The #1 cost mistake.
3. **Dead APIs** — training data predates the funcX→Globus Compute rebrand, so
   models emit `funcx` and the removed `HighThroughputEngine`.
4. **Launcher/scheduler mismatch** — `MpiExecLauncher` on PBS vs `SrunLauncher`
   on Slurm.
5. **Login-node trap** — not knowing `configure` gives a LocalProvider endpoint.

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

Drop the `globus-compute-hpc/` directory into your skills folder (e.g.
`~/.claude/skills/globus-compute-hpc/`) and start a session. It activates on
prompts like:

- "Set up a Globus Compute endpoint on Perlmutter / Polaris"
- "Run LAMMPS across 4 nodes through Globus Compute"
- "My Compute tasks hang forever / worker lost"
- "Our facility runs one shared endpoint — how do users pass their own account?"

## Testing

Everything that can be verified without an HPC allocation is, and the checks are
committed so you can re-run them:

```bash
pip install -r tests/requirements-dev.txt
python tests/test_skill_format.py     # frontmatter + links vs the Agent Skills spec
python tests/test_sdk_symbols.py      # every SDK symbol the skill cites is real (vs 4.12.0)
python tests/test_render_configs.py   # every bundled config renders to valid YAML + invariants
```

**Verified (this repo, against `globus-compute-sdk`/`-endpoint` 4.12.0):**

- All 23 SDK/API members the skill references exist in the published package
  (`MPIFunction`, `Executor.resource_specification`/`user_endpoint_config`, the
  8 error types, `ComputeSerializer`/`AllCodeStrategies`,
  `get_worker_hardware_details`, ...).
- All four bundled configs render through the real Jinja→YAML pipeline that
  `render-user-config` uses, and satisfy the skill's invariants
  (`GlobusComputeEngine`/`GlobusMPIEngine` only; `init_blocks`/`min_blocks` 0;
  `GlobusMPIEngine` paired with `SimpleLauncher`).
  - *This caught two real bugs in the Aurora draft* — a JSON-quoted variable
    interpolated inside a quoted string, and a `{{ }}` left in a YAML comment
    (Jinja renders comments too). Both fixed; the test now guards against
    regressions.
- `smoke_test.py`: argument handling, both payloads, and the missing-ASE error
  path all behave; it correctly reaches the Globus auth boundary.
- SKILL.md frontmatter conforms to the spec (name matches directory, description
  703/1024 chars, body 179 lines, all relative links resolve).

**Not verifiable here (needs a real endpoint + interactive Globus auth):** a true
end-to-end `smoke_test.py` run on a configured endpoint. The script is correct up
to the auth prompt; running it on a `LocalProvider` endpoint on any Linux host
validates the full client→endpoint→worker path, and on Polaris/Perlmutter
validates the HPC path. (Note: `globus-compute-endpoint` is POSIX-only — the CLI
imports `pwd` — so the endpoint daemon does not run on Windows; the SDK and these
tests do.)

## What needs ALCF/Polaris review

`assets/configs/aurora.yaml` is **composed, not validated against a running
Aurora endpoint.** There is no public Aurora example in the globus-compute repo
(verified June 2026), so it was built from the Polaris config's structure plus
Aurora facts from ALCF docs / the Genesis `aurora` skill. Every uncertain line is
marked `VERIFY`. Before relying on it, confirm with
[ALCF Aurora docs](https://docs.alcf.anl.gov/aurora/) or ALCF support:

- `address.ifname` — Aurora has 8 NICs/node; the correct interface name
- GPU granularity — `available_accelerators`/`max_workers_per_node`: 6 devices
  vs 12 tiles
- `overrides: --depth=104` and the cpus/gpus-per-node numbers
- whether to target a single-user or an ALCF-managed multi-user endpoint

The other three configs (`polaris`, `perlmutter`, `expanse_mpi`) are **copied
verbatim** from `globus/globus-compute` `docs/endpoints/configs/` and are
byte-for-byte identical to upstream.

## Provenance

Verified against `globus/globus-compute` @ `94b69e5` (2026-06-08), the published
`globus-compute-sdk` / `globus-compute-endpoint` 4.12.0, and the conventions of
the Genesis `hpc-skills`. Intended for eventual contribution to the Genesis
Mission skills catalog under `hpc-skills/`.

## License

Apache-2.0 (matching the Genesis skills catalog). See [LICENSE](LICENSE).
