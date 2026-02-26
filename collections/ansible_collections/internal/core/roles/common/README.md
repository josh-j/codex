# internal.core.common

Shared helper role for reusable task snippets.

This role is primarily intended to be called with `tasks_from` from other roles
instead of executed directly as a standalone role.

## Available Task Snippets

### Validation

- `validate_typed_schema.yaml`: Validates a data structure against a YAML schema template. Ensures both key existence and basic type compatibility.
  - **Required Vars**:
    - `ncs_validate_data`: The data object to validate.
    - `ncs_validate_root_key`: The root key in the schema file to match against.
  - **Optional Vars**:
    - `ncs_validate_schema_ref`: Logical reference to schema (e.g., `internal.linux:schemas/ctx.yaml`).
    - `ncs_validate_schema_path`: Direct filesystem path to schema.

### Safeguarding

- `safeguarding/create_snapshot.yaml`: Takes a safety snapshot of the current host in vCenter if it is a VMware VM.
  - **Required Vars**:
    - `snapshot_prefix`: Prefix for the snapshot name (e.g., `Pre_STIG`).
    - `snapshot_desc`: Description for the snapshot.
  - **Requires**: `gather_facts: true` on the target host.

### Logging

- `logging/info.yaml`: Logs an informational message via `ansible.builtin.debug`.
- `logging/error.yaml`: Logs an error message (prefixed with `ERROR:`) via `ansible.builtin.debug`. Does not fail the task.
  - **Vars**:
    - `ncs_log_message`: The message to log.
