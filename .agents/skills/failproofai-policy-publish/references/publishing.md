# Policy pack publishing reference

## Command map

```bash
failproofai publish --init [file]
failproofai publish [policy-file] [options]
failproofai policies show <owner>/<repo>
failproofai policies show <owner>/<repo> --releases
failproofai policies add <owner>/<repo> [--policy a,b] [--category x,y] [--all]
failproofai policies remove <pack-id>
```

`policy`, `pack`, and `p` remain compatibility spellings for `policies`; write the current
`policies` spelling in new documentation.

## Source discovery

`publish` recognizes policy files by their contents: they import FailproofAI and register
one or more entries with `customPolicies.add` or `semanticPolicies.add`. Discovery is
non-recursive. If discovery finds multiple candidates, pass the intended source explicitly or organize the directory so the
set is unambiguous.

Every policy included in a pack needs a unique name. The pack build rejects an artifact that
registers no policy or registers duplicate names.

## Identity and versions

The default pack id is the GitHub repository, `<owner>/<repo>`. `--id` can override it, but
stable ids are important because consumer configuration and updates identify the pack by id.

Without `--version`, a tag on `HEAD` wins; otherwise the version is a 12-character commit
SHA. The full commit is recorded as provenance. The default tag is the version. A manual tag
must describe the selected version (a leading `v` is accepted).

Commit-derived versions are intentionally immutable but not naturally ordered. Use:

```bash
failproofai policies show <owner>/<repo> --releases
```

to see release history in publication order.

## Pack effect and defaults

The pack effect is `enforce` or `observe` and applies to every policy in the pack. Consumers
cannot override it per policy at install time.

Individual policies can define `category` and `defaultEnabled`. A bare installation enables
the publisher defaults; consumers can instead choose with `--policy`, `--category`, or
`--all`.

## Integrity model

The release contains a manifest, bundled entry module, and checksum file. Installation
verifies the manifest and content digest, and the installed artifact is rechecked before
loading. This detects changed or corrupted assets. It is not publisher identity verification:
whoever controls the GitHub release controls both the artifact and its checksum.

## Public repository requirement

Consumers fetch release assets anonymously. A private repository therefore cannot provide
the normal public install path. If the CLI warns about a private target, do not present the
pack as generally installable.

## Publishing boundaries

- `failproofai publish` publishes a GitHub release; it does not push source commits.
- Publishing does not install or enable the pack anywhere.
- `failproofai policies add <owner>/<repo>` is the consumer install step.
- Cloud policy publication and fleet rollout use `fp policies`, `fp fleet`, and
  `fp guardrails`; those belong to `fp-cloud-cli` and are not policy-pack publishing.

## Jev checks in a pack

Verified against failproofai 1.0.9 (`src/hooks/pack-cli.ts`, grep `async function build`;
`src/hooks/pack-manifest.ts`, grep `parsePackSemanticPolicy`).

### What the manifest carries

A pack with checks writes them to the manifest's `semantic` array, beside `policies`, and
sets `minCliVersion`. Each policy's `authority` and `reviewedBy` are copied into its
manifest entry; a machine reads them from there, never from the code. A pack of checks alone
has an empty `policies` array and is valid.

### What `publish` refuses

Every refusal exits 1 and builds nothing. The messages below are the CLI's own; `…` stands
for the pack id, the check's name or index, or a number.

| Refused | Message starts |
|---|---|
| one of the 16 `FailproofAI/jev-policies` names, from a repository that is not FailproofAI's | `"destructive-deletion" is a name reserved for FailproofAI's own Jev checks, so a pack from … would never have it asked. Pick a name of your own.` |
| questions over the budget | `This pack's … semantic policies compile to … characters of questions, over the 9101 a machine leaves a pack from outside FailproofAI: one Jev request has room for 27591, and FailproofAI/jev-policies' 16 checks take 18490 of it first where both are installed.` |
| `reviewedBy` naming a check the pack does not declare (when it declares any) | `One policy declares an authority this build cannot publish:` … `This pack declares Jev checks of its own, so reviewedBy may name only those.` |
| `--min-cli-version` below 1.0.8-beta.0 | `--min-cli-version 1.0.7 is older than the first failproofai that runs a pack's Jev checks (1.0.8-beta.0):` |
| `--min-cli-version` not plain semver | `--min-cli-version "…" is not a version that can be compared.` |
| `alwaysOn` on a check | `… semantic policy #0 declares alwaysOn, which packs may not set` |
| no `userCanOverride` | `… is missing userCanOverride, which has no default` |
| no `appliesTo`, or an unknown class | `… has no appliesTo tool classes` / `… applies to "…", which is not a tool class (…)` |
| a `mode` other than `deny` / `instruct` | `… has mode "…", which must be "deny" or "instruct"` |
| no probes, or more than 6 | `… declares no probes` / `… declares 7 probes, over the cap of 6` |
| an unknown precondition | `… names precondition "…", which this build does not have (always, protected_branch, in_git_repo, has_paths, paths_outside_project, system_or_root_paths)` |
| probe id `exempt` or `user_asked` | `… uses the reserved probe id "user_asked"` |
| two checks with one name | `two semantic policies are called "…"` |

Also refused, as for any pack: `alwaysOn` on a regex policy, a policy name with `/`, a
missing `description`, `category` or `match`, an entry that imports local files, and an entry
that registers nothing. `publish` does not count checks, but `policies add` refuses a pack
with more than 24 (`… declares … semantic policies, over the cap of 24`); the budget usually
stops one first.

### The budget, precisely

One Jev request has room for 27,591 characters of questions, shared by every installed pack
that enforces, FailproofAI's first. `FailproofAI/jev-policies` spends 18,490 of it, so
`publish` holds a pack from outside FailproofAI to the 9,101 left, whether or not the author
has `jev-policies` installed. The cost is the serialized question map: each probe's
`instructions` and `criteria`, the `exempt` probe, and a generated `user_asked` question for
a check with `userCanOverride: true`. A machine measures what is actually installed, so a
pack that passed `publish` can still have a check dropped beside another Jev pack.
`policies add` names the dropped check with a `▲` line; after that, only the hook log does.

### Reserved and contested names

The 16 names in `FailproofAI/jev-policies` are reserved for packs released from a FailproofAI
repository, judged by the repository the CLI fetched from (or `--id` for a dry run with no
`--repo`), never by the pack's own id. Anyone else's check with one of those names is void:
never asked, never a reviewer, and not a rival to FailproofAI's. A name two installed packs
declare differently is asked for neither and clears nothing. `policies add` also refuses a
pack whose id starts `FailproofAI/` unless its release comes from `github.com/FailproofAI`
(`… was not installed: the FailproofAI/ namespace is reserved for releases from
github.com/FailproofAI`).

### `minCliVersion`

A CLI too old for Jev checks ignores `semantic` (1.0.7) or replaces its built-in checks with
it (1.0.7-beta.x), so a pack with checks needs at least `1.0.8-beta.0`. `publish` writes that
when `--min-cli-version` is absent and refuses anything lower. An older CLI that does read the
field refuses to install the pack and prints `npm i -g "failproofai@>=<version>" &&
failproofai update`. For an `enforce` pack with regex policies, a machine that cannot load it
denies what those policies cover. A pack of Jev checks alone is read correctly from
1.0.8-beta.0, but an older build can deny every tool call over it, which is what the rollback
reminder is for.

### Try a dry-run pack before releasing

This is also the only way to exercise a Jev check before release, since a local policy file
never has its checks asked. `policies add` takes only `owner/repo[@tag]` and fetches
`$FAILPROOFAI_PACK_BASE_URL/<owner>/<repo>/releases/download/<tag>/<asset>` (default
`https://github.com`). To install a dry run locally, serve `dist-pack/` in that layout:

```bash
failproofai publish ./db-guard-policies.mjs --dry-run --id acme/db-guard --version 0.1.0
d=pack-mirror/acme/db-guard/releases/download/0.1.0; mkdir -p "$d" && cp dist-pack/* "$d"
python3 -m http.server 8765 -d pack-mirror &
FAILPROOFAI_PACK_BASE_URL=http://127.0.0.1:8765 failproofai policies add acme/db-guard@0.1.0 --all
```

The tag must describe the version (a leading `v` is fine). Unset the variable afterwards: it
redirects every pack fetch. Re-adding with a newer `@<version>` upgrades the pack, and
`failproofai policies remove acme/db-guard` uninstalls it.

### Observe and agent-scoped packs

`--effect observe` records the pack's regex verdicts without enforcing them, and its Jev
checks are **not asked at all**. A consumer who installs with `--cli <agent>` gets the checks
asked only for those agents. Either way, a policy naming a check that is not asked stays
hard.
