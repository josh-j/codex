# Releasing a Collection

Each `internal.<col>` collection lives in its own local git repo at
`/home/sio/ncs-ansible-<col>/`. This doc is the day-two workflow for
cutting a new version of one collection and rolling it into the
`ncs-ansible` app repo.

Prior reading: `docs/EXTRACTING_COLLECTIONS.md` covers the one-time split;
this doc covers everything after.

## The release recipe

From `ncs-ansible/`:

```bash
just release-collection <name> <version> "<message>"
```

Example:

```bash
just release-collection vmware 1.2.0 "Add vCenter 8.0 STIG controls"
```

That single recipe, inside `/home/sio/ncs-ansible-<name>/`:

1. Asserts the sibling repo is clean (no staged or unstaged changes).
2. Asserts the target tag doesn't already exist.
3. Rewrites `galaxy.yml: version:` to the new version.
4. Prepends a dated entry to `CHANGELOG.md` using `<message>` as the
   first bullet.
5. `git add galaxy.yml CHANGELOG.md && git commit -m "Release v<version>: <message>"`.
6. `git tag v<version>`.
7. Returns to `ncs-ansible/` and calls `just build-collection <name>` to
   produce `dist/internal-<name>-<version>.tar.gz`.

Nothing is pushed to a remote — the collection repos are local-only.

## After release: update the app

```bash
# Option A — sibling-dir mode (Mode B in requirements.yml, the default):
# nothing to change in requirements.yml; just re-install.
just install-collections

# Option B — tarball mode (Mode A):
# bump the pinned filename in requirements.yml to match the new
# version, then re-install.
$EDITOR requirements.yml
just install-collections
```

Verify the new version is live:

```bash
.venv/bin/ansible-galaxy collection list | grep internal.<name>
```

## Pre-release checks

Run these in the sibling repo or via the Justfile before you cut a
release; the release recipe does not run them for you.

```bash
just lint-collection <name>               # ansible-lint on the sibling repo
just verify-fqcn-contract                 # every reporter-config FQCN still resolves
```

`verify-fqcn-contract` is the most important one. It catches the case
where a release removes or renames a playbook that
`ncs_configs/ncs-reporter/*.yaml` pins as an FQCN string.
The script reads every `stig.ansible_playbook.path:` from those configs
and syntax-checks each one against the currently-installed collections.
Run it after `install-collections` in the main repo.

## Cross-collection coordination

When changes in `internal.core` break a platform collection's
dependency range (the `dependencies: { internal.core: ">=1.0.0,<2.0.0" }`
in each platform's `galaxy.yml`), the order is:

1. Release `internal.core` first (`just release-collection core X.Y.Z …`).
2. In each affected platform collection's sibling repo, widen the
   `dependencies:` range in `galaxy.yml` to allow the new core version.
   Commit that change as part of a follow-up release of the platform
   collection.
3. `just release-collection vmware X.Y.Z "Bump internal.core range"`.
4. Back in `ncs-ansible/`: `just install-collections`, then
   `just verify-fqcn-contract`.

The `galaxy.yml: dependencies:` range is enforced at install time, so a
mismatch fails fast with a clear error.

## Rolling back a release

Tags and commits are local, so rollback is just `git`:

```bash
cd /home/sio/ncs-ansible-<name>
git tag -d v<version>
git reset --hard HEAD~1
cd -
rm -f dist/internal-<name>-<version>.tar.gz
```

In the app repo, if the old version is still pinned in
`requirements.yml` (tarball mode), re-run `just install-collections`.
In sibling-dir mode there's no filename pin, so the app will pick up
the rolled-back version automatically on the next install.

## Linting

`just lint-collection <name>` runs `ansible-lint` against the sibling
repo. It's picky about the top-level directory name (the dir is named
`ncs-ansible-<name>`, which doesn't match ansible-lint's role-name
convention `^[a-z][a-z0-9_]*$`). Add a `.ansible-lint` config at the
collection root to suppress that specific warning:

```yaml
# /home/sio/ncs-ansible-<name>/.ansible-lint
skip_list:
  - role-name
```

This is a per-collection polish item — add it once, commit to that
sibling repo; the Justfile target does not touch the sibling repo's
lint config.
