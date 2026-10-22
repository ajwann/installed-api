---
name: release-workflow
description: How changes reach main and how releases are tagged in the installed-api (Installed API) plugin repo. Use for any change to this repository (server code, tests, README, manifest, CI, docs), and whenever asked to commit, push, open or merge a PR, bump the version, cut or push a tag, release, change supported Python or Node versions, or prepare for the Anthropic Plugin Directory.
---

# Release workflow for installed-api

Every change reaches `main` through a pull request whose **tests** checks have all passed. A release is an annotated `vX.Y.Z` tag on a merge commit of `main`, with the same version as `.claude-plugin/plugin.json`.

## Rules

- Never commit or push to `main` directly, even though GitHub branch protection isn't turned on for this repo yet.
- Never merge with a failing or pending check. If a failure isn't caused by the change (for example, a runner image dropping a Python build), fix it in the same PR or in a separate one first.
- Never move, delete or re-push a tag once it has been pushed. If a release is wrong, release the next patch version.
- Bump the version with every change that alters what users install or what the directory listing shows: `server/`, the manifest, the README or the listing icon. A change to CI, tests or this skill alone doesn't need a bump, but it may ride along with one.
- The identifier is always `installed-api`: the `name` in `plugin.json`, the repo, the folder and the tool namespace. "Installed API" is only the display name in prose. Don't rename the identifier.
- Commits and PR bodies end with the attribution lines the session provides.

## 1. Branch

```
git checkout main && git pull
git checkout -b <type>/<short-kebab-description>   # e.g. docs/readme-pitch, ci/supported-versions, release/0.3.0
```

Start from an up-to-date `main`, with one branch per change.

## 2. Change, then check locally

Run every check before pushing:

```
python3 -m pytest -q
claude plugin validate --strict .
```

- **Tests live in `tests/`.** `test_installed_api.py` covers the tools. `test_manifest.py` covers the manifest, the README's minimum length, and that `SERVER_VERSION` in `server/server.py` matches `plugin.json`. Add or update tests for any behavior change.
- **Bump the version in both places:** `version` in `.claude-plugin/plugin.json` and `SERVER_VERSION` in `server/server.py`. Use a patch bump for fixes and wording, minor for new tools or options, and major for removed tools or options, changed defaults, or dropping a Python version line. While the version is below 1.0, a breaking change bumps the minor version instead (0.2.x to 0.3.0).
- **Keep the README accurate.** Every claim about behavior must match `server/server.py` and `server/pyprobe.py`: the tools table, the interpreter search order, output limits (`max_members`, `max_chars`, declaration block size, files scanned), and "What it runs and stores". Don't invent benchmark numbers. Any size or token figure must come from a real run.
- **Stay standard-library only and offline.** The server makes no network requests and writes nothing. The README says so, and the directory listing depends on it.
- **`server/pyprobe.py` runs inside the user's own project interpreter**, which may be older than what we support. Keep it dependency-free and keep its fallbacks for older interpreters.

### Supported versions

The plugin supports the Python and Node.js release lines that still receive at least security updates (check https://endoflife.date/python and https://endoflife.date/nodejs). When a line reaches end of life or a new one is released, update all of these together:

- the `python-version` matrix in `.github/workflows/tests.yml`
- the "Supported versions" section and the Python version mentions in the README
- the version bump (dropping a line is a major bump; see above)

Node.js is never executed, so CI has no Node matrix. `node_types` and `node_versions` only read `package.json` and `.d.ts` files.

### Before committing, also check

- `grep` finds no private paths or usernames (for example `/Users/`).
- There are no `.DS_Store` files.
- No identifier reads like a credential (avoid names ending in `Token`, `Secret` or `Key`), and no test contains a literal `$` followed by a digit.
- Text files don't name the listing icon by its filename. In prose, say "the listing icon".

## 3. Pull request

```
git add <files> && git commit
git push -u origin <branch>
gh pr create --base main --head <branch> --title "..." --body "..."
```

- The **tests** workflow runs `pytest` on every supported Python version for each PR and for each push to `main`. Every `pytest (3.x)` job must pass.
- If `main` has moved on, run `gh pr update-branch <n>` and wait for the checks again.

Wait for the checks to finish:

```
gh pr checks <n> --watch
```

Then merge with a merge commit, as this repo's history does:

```
gh pr merge <n> --merge --delete-branch
```

If the merge is refused, fix the cause. Don't bypass it.

## 4. Tag a release

Only after a version-bumping PR has merged:

```
git checkout main && git pull
grep '"version"' .claude-plugin/plugin.json          # e.g. 0.3.0
git tag -a v0.3.0 -m "installed-api 0.3.0"            # annotated, on main's merge commit
git push origin v0.3.0                                # the tag only
```

- The tag goes on the merge commit at the tip of `main`, and its version matches `plugin.json` and `SERVER_VERSION` exactly.

Then confirm:
- `git ls-remote --tags origin` lists the tag, and it appears on https://github.com/ajwann/installed-api/tags
- the README's version badge shows the new version
- the **tests** run on `main` for the merge commit passed

## 5. Anthropic Plugin Directory

The directory validates and security-scans each commit. Before submitting or relisting:

- `claude plugin validate --strict .` passes.
- The README is at least 40 words and describes everything the plugin runs, reads, sends or fetches.
- `LICENSE` exists. `plugin.json` has `name`, `version`, `description`, `author`, `license`, `homepage` and `repository`, with a raised `version`.
- Names within a few characters of another listed plugin get held for review, so check the directory before changing the name or display name.
