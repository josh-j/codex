# Path Conventions

`ncs-reporter` consumes collector-written tree bundles and renders static HTML
reports into the same report root. There is no separate platform input root.

## Source Of Truth

Product and report structure is inferred from collector-written folders. The
important contract is the first path segment names a product schema, and the
remaining segments are the rendered inventory tree:

- top-level directory: product slug, such as `vsphere` or `ubuntu`
- child directories: inventory nodes, such as host names or vSphere hierarchy
- `raw.yaml`: the node's primary inventory bundle
- `inventory.yaml`: optional vSphere graph bundle used to project child nodes

`platforms.yaml` remains the registry for product metadata, STIG target mapping,
and template defaults. It is not a second directory structure.

## Input Structure

Collector output lives under `<REPORTS_ROOT>` as tree leaves:

```text
<REPORTS_ROOT>/
  vsphere/
    vc-lab/
      raw.yaml
  ubuntu/
    web-01/
      raw.yaml
  stig/
    esxi/
      esxi-01/
        raw_stig_esxi.yaml
```

The optional `--bundle-root` argument lets a run read bundles from a different
tree while still writing HTML under `--reports-root`.

## Output Structure

Generated reports are static files under `<REPORTS_ROOT>`:

```text
<REPORTS_ROOT>/
  site.html
  site.stig.html
  search_index.js
  all_hosts_state.yaml
  vsphere/
    vsphere.html
    vc-lab/
      vc-lab.html
  ubuntu/
    ubuntu.html
    web-01/
      web-01.html
  stig/
    esxi/
      esxi-01/
        esxi-01_stig_esxi.html
  cklb/
    esxi-01_esxi.cklb
```

For inventory pages, the canonical rule is:

```text
<REPORTS_ROOT>/<product>/<tree...>/<node>/<node>.html
```

For STIG pages, the canonical rule is:

```text
<REPORTS_ROOT>/stig/<target_type>/<hostname>/<hostname>_stig_<target_type>.html
```

If a host also has a tree page, site navigation and search point at that tree
page. The STIG-specific report remains under `stig/<target_type>/...`.

## History Navigation

Historical node reports are written beside the current node report using the
configured stamp:

```text
<node>/<node>_<YYYYMMDD>.html
```

The breadcrumb history dropdown is populated by scanning the node directory, so
reports remain static and serverless.

## Relative Paths

Templates calculate `data-root` from the generated page location. This keeps
`search_index.js`, breadcrumbs, and cross-report links working when the reports
are served from a static web server or opened directly from disk.
