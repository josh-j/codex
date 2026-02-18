# CODEX - Project TODO & Improvement Tracking

## ✅ Completed Refactorings

1.  **Standardized State Management**:
    *   Removed `__ops_run__` dummy host pattern.
    *   Implemented standard `Initialize -> Execute -> Aggregate` three-play structure.
    *   Use `ansible.builtin.set_stats` to publish `run_ctx` for global state sharing.
2.  **Decoupled Scheduling**:
    *   Removed `lookup('pipe', 'date ...')` from pre-tasks and inventory.
    *   Centralized run metadata generation in a single initialization play.
3.  **Schema Validation**:
    *   Added `internal.stig.validate_ops_data` filter.
    *   Integrated validation step in `aggregate.yaml` to catch malformed host data before reporting.
4.  **Collection Migration & Cleanup**:
    *   100% of roles moved to FQCN collections under the `internal` namespace.
    *   Removed legacy root `roles/` directory and consolidated logic.

## 🛠️ Remaining Maintenance Tasks

1.  **Automated Testing (Molecule)**:
    *   [x] Integrate `molecule test` into GitLab CI pipeline.
    *   [ ] Add Molecule scenarios for `internal.vsphere` and `internal.linux` collections.
2.  **Role Decoupling**:
    *   [x] Audit roles for Ubuntu ensure "Check" and "Discovery" tasks are strictly separated (SRP).
    *   [x] Ensure Ubuntu roles can run in `check_mode` reliably.
    *   [x] Audit vSphere/ESXi roles for similar SRP separation.
3.  **Documentation**:
    *   [x] Create `DEVELOPER_GUIDE.md` explaining the Data Flow (Discovery -> Audit -> Aggregate -> Render).
    *   [x] Document the `ops` dictionary schema for future role developers.
4.  **CI/CD Enhancements**:
    *   [x] Transition from GitHub Actions to GitLab CI.
    *   [x] Add `ansible-lint` to CI (Verify `.ansible-lint` is strictly enforced).
    *   [x] Add automated syntax checks for all playbooks on every PR.

## 📈 Long-term Goals
*   **AWX Integration**: Design inventory and playbooks to be fully compatible with AWX/Tower (e.g., using `set_stats`).
*   **Plug-and-Play Roles**: [x] Created `internal.templates.starter_role` to simplify adding new infrastructure platforms.
