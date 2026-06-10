# Multi-User & Templated Endpoints

Facilities often run ONE shared endpoint per system instead of every user
standing up their own. Users then parametrize it at submit time. LLMs
generally don't know this model exists — they tell users to configure a
personal endpoint even when a shared one is available. Check for a facility
endpoint first.

## The two halves

1. **Templating** (works on ANY endpoint, single- or multi-user): the
   `user_config_template.yaml.j2` is Jinja; users supply variables via
   `Executor(user_endpoint_config={...})`.
2. **Multi-user** (privileged): the manager runs as root, maps the submitting
   user's Globus identity to a local POSIX account, and forks a UEP *as that
   user*.

## Client side: parametrizing a shared endpoint

```python
from globus_compute_sdk import Executor

with Executor(
    endpoint_id=SHARED_EP_ID,
    user_endpoint_config={
        "ACCOUNT_ID": "myproject",
        "NODES_PER_BLOCK": 2,
        "WORKER_INIT_COMMAND": "module load conda; conda activate my-env",
    },
) as ex:
    fut = ex.submit(my_function, *args)
    print(fut.result())
```

The variable names must match the `{{ ... }}` placeholders in the endpoint's
template — ask the endpoint admin or read its docs for the supported variables.

## Admin side: writing the template

Real ALCF-style example (from upstream multi-user docs, Polaris debug-scaling):

```yaml
display_name: Polaris at ALCF - debug-scaling queue
engine:
  type: GlobusComputeEngine
  address:
    type: address_by_interface
    ifname: bond0
  strategy:
    type: SimpleStrategy
    max_idletime: 30            # scale down 30 s after work dries up
  provider:
    type: PBSProProvider
    queue: debug-scaling
    account: {{ ACCOUNT_ID }}                       # user MUST supply
    worker_init: {{ WORKER_INIT_COMMAND|default() }} # optional (|default() → "")
    init_blocks: 0
    min_blocks: 0
    max_blocks: 1
    nodes_per_block: {{ NODES_PER_BLOCK|default(1) }}
    walltime: 1:00:00
    launcher:
      type: MpiExecLauncher
idle_heartbeats_soft: 10        # idle UEP exits after ~5 min (heartbeat = 30 s)
idle_heartbeats_hard: 5760      # stuck UEP killed after 48 h
```

Template rules and quirks:

- `{{ var|default() }}` makes a variable optional; without the filter, a
  missing variable fails the render.
- **User strings are JSON-serialized before rendering** (injection defense), so
  string comparisons need the quoted form:
  `{% if environment == '"test"' %}` — NOT `== 'test'`.
- Reserved variables available in every template: `parent_config`,
  `user_runtime` (e.g. `user_runtime.python.version`,
  `user_runtime.globus_compute_sdk_version`), and on multi-user endpoints
  `mapped_identity` (`mapped_identity.local.uname/uid/gid/groups/dir`). Useful
  for per-group routing:
  ```yaml
  {% if 1001 in mapped_identity.local.groups %}
      partition: {{ partition }}
  {% else %}
      partition: default
  {% endif %}
  ```
- Templates can be composed with `extends`/`include`/`import`; the included
  files must be readable by all mapped users, and the main template path set
  via `user_config_template_path` in `config.yaml`.

## Validating user variables: `user_config_schema.json`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "ACCOUNT_ID": { "type": "string" },
    "NODES_PER_BLOCK": { "type": "integer", "maximum": 8 },
    "WORKER_INIT_COMMAND": { "type": "string" }
  },
  "required": ["ACCOUNT_ID"],
  "additionalProperties": false
}
```

The default schema allows anything (`additionalProperties: true`); tighten it
to `false` for clear failures on typo'd variable names.

## Testing templates without starting anything

```bash
# Render with a local endpoint's template + schema:
globus-compute-endpoint render-user-config -e my-ep -o user_options.json

# Or fully offline against bare files (stdin works for any file option):
cat user_options.json | globus-compute-endpoint render-user-config \
    -t user_config_template.yaml.j2 -s user_config_schema.json -o -

# Pipe through yq to validate the rendered YAML syntax:
globus-compute-endpoint render-user-config -e my-ep -o opts.json | yq - >/dev/null
```

## Setting up a true multi-user endpoint (admins)

1. Run `globus-compute-endpoint configure my-mu-ep` **as root** — this
   additionally generates `example_identity_mapping_config.json`.
2. Write the identity mapping config (Globus identity → local username), per
   the Globus Connect Server Identity Mapping guide. Point to it from
   `config.yaml`:
   ```yaml
   identity_mapping_config_path: /root/.globus_compute/my-mu-ep/idmap.json
   ```
   Test mappings without submitting tasks using the bundled
   `globus-idm-validator` tool.
3. Optional `config.yaml` hardening:
   - `public: false` — hide from the Globus web UI (discovery only; NOT access control)
   - `authentication_policy: <uuid>` — restrict who can submit (needs subscription)
   - `admins: [<identity-uuid>, ...]` — co-managers (needs `subscription_id`)
   - `allowed_functions: [<function-uuid>, ...]` — function allow-list, enforced
     at both the web service and the UEP
   - `pam: {enable: true}` — site-specific PAM authorization
4. Start as root: `globus-compute-endpoint start my-mu-ep`. Each submitting
   user gets their own UEP forked under their mapped POSIX account.

Common failure: `"Identity failed to map to a local user name"` → the identity
mapping config doesn't cover the submitter; see
[troubleshooting.md](troubleshooting.md).
