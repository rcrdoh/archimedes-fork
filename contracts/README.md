# Archimedes contracts (Foundry)

Solidity sources for the Arc deployment — `Vault`, `VaultFactory`, `SyntheticVault`,
`SyntheticFactory`, `SyntheticToken`, `AMMPool`, `AMMRouter`, `AssetRegistry`,
`StrategyRegistry`, `ReasoningTraceRegistry`, `PriceOracle`. ABIs are cached in
[`abis/`](abis/) for backend + UI consumption.

## Build + test from a clean clone — one command

Dependencies (`forge-std` v1.16.1, `openzeppelin-contracts` v5.6.1) are tracked as
**git submodules** under [`lib/`](lib/), pinned to the exact revisions recorded in
[`foundry.lock`](foundry.lock). Restore them from a fresh checkout with:

```bash
git submodule update --init --recursive
```

(If you cloned the repo with `git clone --recurse-submodules`, they are already
present and you can skip this.) Then, from this directory:

```bash
forge build && forge test
```

Both run with **zero** import changes — Foundry auto-remaps the submodule layout:

| Import prefix in `.sol`        | Resolves to                              |
| ------------------------------ | ---------------------------------------- |
| `@openzeppelin/contracts/...`  | `lib/openzeppelin-contracts/contracts/`  |
| `forge-std/...`                | `lib/forge-std/src/`                     |

No `remappings.txt` is needed; the implicit remapping is derived from the `lib/`
submodule directory names.

> **Why submodules (not `forge install` no-args / soldeer):** the standard Foundry
> layout records each dep as a git submodule gitlink + a `.gitmodules` entry, so a
> clean clone restores them deterministically with a single stock-git command and
> the `lib/` auto-remapping keeps every existing `import` unchanged. `forge install`
> with no args previously failed (`git submodule exited with code 1`) because the
> gitlinks and `.gitmodules` entries were never committed — this directory documents
> the now-committed, restore-from-clean layout that fixes that.

## Updating a dependency

To bump a pinned dependency, check the submodule out at the new tag and re-commit the
gitlink, keeping [`foundry.lock`](foundry.lock) in sync:

```bash
cd lib/forge-std && git fetch --tags && git checkout v1.16.1 && cd ../..
git add lib/forge-std
# update the matching rev/tag entry in foundry.lock
```

## CI

`forge build` + `forge test` run automatically on any PR touching `contracts/**` via
[`.github/workflows/contracts-test.yml`](../.github/workflows/contracts-test.yml)
(a required check). The workflow checks out submodules (`submodules: recursive`) and
installs Foundry with `foundry-rs/foundry-toolchain@v1`.
