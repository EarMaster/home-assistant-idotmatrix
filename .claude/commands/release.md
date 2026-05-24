---
allowed-tools:
  - Bash(git:*)
  - Read
  - Edit
  - Write
  - AskUserQuestion
---

You are running the release workflow for this Home Assistant integration. Work through the steps below in order.

## 1. Inspect current changes

Run `git status` and `git diff HEAD` to see all uncommitted changes. Read the current version from `custom_components/idotmatrix/manifest.json` and the latest tag from `git tag --sort=-v:refname | head -1`.

## 2. Check documentation

Read `README.md` and compare it against the changed code. Note any features, services, or behavior that is new, removed, or altered but not yet reflected in the README.

Ask the user:

```
AskUserQuestion: "Does the README need updates before this release? Here is what I found: [list any gaps, or 'Nothing — README matches the current code']. Should I update it, or proceed as-is?"
Options: ["README is fine as-is", "Please update it as described"]
```

If the user wants updates, apply them now before continuing.

## 3. Group changes into conventional commits

Analyse the diff and group files by change type:

- `feat:` — new user-visible functionality
- `fix:` — bug fixes
- `docs:` — documentation-only changes (README, comments)
- `chore:` — maintenance (config, dependencies, build)
- `refactor:` — internal restructuring with no behaviour change

One commit per type is enough; only split further if two changes within the same type are logically unrelated.

## 4. Determine version bump

Apply semver rules to the highest-priority change type found:

| Change | Bump |
|---|---|
| Any `BREAKING CHANGE` in a commit body | major |
| Any `feat:` commit | minor |
| Anything else | patch |

Calculate the next version from the current one.

## 5. Draft the release plan

Present the full plan to the user and ask for a single confirmation before touching git:

```
AskUserQuestion: "Here is the release plan — confirm to proceed or cancel to adjust:

Commits:
  [list each proposed commit message and the files it will stage]

CHANGELOG entry:
  ## [X.Y.Z] - YYYY-MM-DD
  ### Fixed / Added / Changed
  - ...

Version bump: X.Y.Z (current) → A.B.C (new)
Tag: vA.B.C

Proceed?"
Options: ["Proceed", "Cancel — I'll make changes first"]
```

If the user cancels, stop here.

## 6. Execute the release

Perform these steps in order:

1. **Stage and commit each group** using `git add <specific files>` and `git commit -m "<type>: <description>"`. Never use `git add -A`.

2. **Update the version** in `custom_components/idotmatrix/manifest.json` (the `"version"` field).

3. **Update CHANGELOG.md** — insert a new `## [A.B.C] - YYYY-MM-DD` block at the top (after the header), using Keep a Changelog format (`### Added`, `### Fixed`, `### Changed` as applicable). Use today's date.

4. **Commit the release** with:
   ```
   git add custom_components/idotmatrix/manifest.json CHANGELOG.md
   git commit -m "chore(release): vA.B.C"
   ```

5. **Create the tag**:
   ```
   git tag vA.B.C
   ```

6. **Push commits and tag**:
   ```
   git push && git push origin vA.B.C
   ```

Report the result of each step and confirm the tag was pushed successfully.
