# Extracting `internal.*` Collections To Local Sibling Repos

This runbook splits the four NCS collections out of the `ncs-ansible`
monorepo into independent git repos **on local disk only** — no Galaxy,
no GitHub, no GitLab, no remote of any kind. The app repo then consumes
them via `requirements.yml` in one of two modes:

- **Tarballs** (`./dist/internal-*.tar.gz`) — for reproducible installs
  on production hosts or in CI
- **Sibling directories** (`../ncs-ansible-vmware`, etc.) — for
  simultaneous dev across multiple repos

Target layout after extraction:

```
~/code/
├── ncs-ansible/              ← the app shell (this repo)
├── ncs-ansible-core/
├── ncs-ansible-vmware/
├── ncs-ansible-linux/
└── ncs-ansible-windows/
```

## Prerequisites

- `git-filter-repo` installed. On Debian/Ubuntu: `apt install git-filter-repo`,
  or `pip install git-filter-repo`.
- A clean working tree in `ncs-ansible` (nothing uncommitted).
- Enough free space for four full history extractions (typically < 50 MB).

## Step 1 — Clone a scratch copy

Never run `git filter-repo` on your real working copy. Use a throwaway.

```bash
cd /tmp
git clone --no-local /path/to/ncs-ansible ncs-ansible-split
```

## Step 2 — Extract each collection

For each collection, create a fresh clone and rewrite it to contain only
that collection's files, rooted at the repo top.

### `internal.core` → `ncs-ansible-core`

```bash
cd /tmp
git clone --no-local ncs-ansible-split ncs-ansible-core
cd ncs-ansible-core
git filter-repo \
    --path internal/core/ \
    --path-rename internal/core/:
# Repo now looks like a standalone internal.core collection, preserving
# every commit that ever touched internal/core/.
git tag v1.0.0
```

Move it to its permanent local home:

```bash
mv /tmp/ncs-ansible-core ~/code/ncs-ansible-core
```

### `internal.vmware` → `ncs-ansible-vmware`

```bash
cd /tmp
git clone --no-local ncs-ansible-split ncs-ansible-vmware
cd ncs-ansible-vmware
git filter-repo --path internal/vmware/ --path-rename internal/vmware/:
git tag v1.1.0
mv /tmp/ncs-ansible-vmware ~/code/ncs-ansible-vmware
```

### `internal.linux` → `ncs-ansible-linux`

```bash
cd /tmp
git clone --no-local ncs-ansible-split ncs-ansible-linux
cd ncs-ansible-linux
git filter-repo --path internal/linux/ --path-rename internal/linux/:
git tag v1.1.0
mv /tmp/ncs-ansible-linux ~/code/ncs-ansible-linux
```

### `internal.windows` → `ncs-ansible-windows`

```bash
cd /tmp
git clone --no-local ncs-ansible-split ncs-ansible-windows
cd ncs-ansible-windows
git filter-repo --path internal/windows/ --path-rename internal/windows/:
git tag v1.1.0
mv /tmp/ncs-ansible-windows ~/code/ncs-ansible-windows
```

## Step 3 — Choose an install mode for `ncs-ansible`

Pick one of the two modes in `ncs-ansible/requirements.yml`. They are
mutually exclusive — uncomment one block and leave the other commented.

### Mode A — Install from built tarballs (production / CI)

Each collection repo builds its own tarball:

```bash
cd ~/code/ncs-ansible-vmware
ansible-galaxy collection build --output-path ~/code/ncs-ansible/dist/
# repeat for core / linux / windows
```

Or from `ncs-ansible` itself, once the four local repos exist, build
everything in one pass (the `Justfile`'s `build-collections-all` target
still works against `internal/<col>/` but you can point a similar
recipe at the sibling repos). The current `dist/` targets build from
the bundled `internal/<col>/`, which keeps working until you delete
that directory in Step 4 / 5.

Edit `ncs-ansible/requirements.yml` to uncomment the `./dist/internal-*.tar.gz`
block. Then:

```bash
cd ~/code/ncs-ansible
rm collections/ansible_collections/internal        # drop the monorepo symlink
just install-collections
```

### Mode B — Install from sibling directories (dev)

Edit `ncs-ansible/requirements.yml` to uncomment the `../ncs-ansible-*`
block. Adjust paths if your layout differs.

```bash
cd ~/code/ncs-ansible
rm collections/ansible_collections/internal        # drop the monorepo symlink
just install-collections
```

Note: `type: dir` copies the directory at install time — edits to
`~/code/ncs-ansible-vmware/...` will NOT propagate until you re-run
`just install-collections`. If you want live edits, keep the collection
repo checked out AND restore the symlink pointing at it:

```bash
ln -sfn ~/code/ncs-ansible-vmware \
    collections/ansible_collections/internal/vmware
```

(Any collection present as a live symlink inside `collections/` shadows
the `requirements.yml` install — useful for mixing live editing with
installed collections on a per-collection basis.)

## Step 4 — Delete `internal/` from `ncs-ansible`

Once the extraction is complete, `internal/` in `ncs-ansible` is dead
code — it's a snapshot of what the four sibling repos already contain.
Remove it so there's a single source of truth:

```bash
cd ~/code/ncs-ansible
git rm -r internal/
# the symlink in collections/ is already gone from Step 3
git commit -m "Remove bundled collections; consume via requirements.yml"
```

## Step 5 — Sanity-check the detached setup

```bash
cd ~/code/ncs-ansible
ansible-galaxy collection list | grep internal      # all four visible
ansible-playbook --syntax-check -i inventory/production \
    internal.vmware.esxi_stig_audit
ansible-playbook --syntax-check -i inventory/production \
    playbooks/site.yml
```

If both commands resolve cleanly, the decoupling is complete.

## Step 6 — Day-two workflow

After extraction each collection lives and releases independently, but
still locally:

- **Making a change**: `cd ~/code/ncs-ansible-vmware`, edit, commit. If
  you're in Mode B with a symlink, the change is already live. If you're
  in Mode A (tarball) or Mode B without a symlink, re-build and re-install.
- **Cutting a new version**: bump `galaxy.yml: version`, update
  `CHANGELOG.md`, `git tag vX.Y.Z`. Build the tarball with
  `ansible-galaxy collection build` and drop it in
  `~/code/ncs-ansible/dist/`. Update the version in
  `ncs-ansible/requirements.yml` and re-run `just install-collections`.
- **Cross-collection changes (e.g. `internal.core` API break)**: release
  `core` first, then bump the dependent `galaxy.yml: dependencies:` range
  in each platform collection, re-build, re-install. The `galaxy.yml`
  dependency check is enforced at install time.

## Troubleshooting

### `ansible-galaxy collection list` doesn't show the installed version

The monorepo symlink shadows installed collections. Remove it:

```bash
rm collections/ansible_collections/internal
```

Then re-run `just install-collections`.

### `ansible-galaxy collection install` refuses to install

It honors `--force` for overwrites. Check that `requirements.yml` has a
mode-A or mode-B block uncommented (the default monorepo placeholder
isn't installable — it's just metadata).

### `git filter-repo` error "expected freshly packed repo"

Filter-repo wants to protect you from rewriting a shared repo. Since
each extraction clones from the scratch `ncs-ansible-split`, the
`--no-local` flag and fresh clone should satisfy it. If it still
complains, add `--force`.

### `internal.core` version mismatch at install

Each platform collection's `galaxy.yml` declares
`dependencies: {internal.core: ">=1.0.0,<2.0.0"}`. A major bump of core
requires every platform collection to re-release with a widened range.
Document breaking changes in `core/CHANGELOG.md` before tagging.

### `ncs-reporter` FQCN references a playbook that moved/disappeared

`ncs_configs/ncs-reporter/*.yaml` pins FQCN strings like
`internal.vmware.vcsa_stig_remediate`. If a collection renames or
removes a playbook, the reporter's `stig-apply` command breaks
silently. Mitigate with a CI check that runs
`ansible-playbook --syntax-check` against each `ansible_playbook.path:`
listed in the reporter configs after a fresh `install-collections`.
