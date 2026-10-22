---
name: release-workflow
description: How changes reach main and how releases are tagged in the Next Context repo. Use for any change to this repository (code, README, manifest, CI, docs), and whenever asked to commit, push, open or merge a PR, bump the version, cut or push a tag, release, or prepare for the Anthropic Plugin Directory.
---

# Release workflow for Next Context

`main` is protected. Every change reaches it through a pull request whose **Tests** check has passed. A release is an annotated `vX.Y.Z` tag on a merge commit of `main`, with the same version as `.claude-plugin/plugin.json`.

## Rules

- Never commit or push to `main` directly. Branch protection refuses it, admins included.
- Never bypass the gate: no `gh pr merge --admin`, no disabling protection, no force-push.
- Never move, delete or re-push a tag once it has been pushed. If a release is wrong, release the next patch version.
- The version in `plugin.json` rises with every change that alters what users install or what the directory listing shows. That includes code, the manifest, the README, `PRIVACY.md` and the listing icon. A change to CI or this skill alone doesn't need a bump, but it may ride along with one.
- Commits and PR bodies end with the attribution lines the session provides.

## 1. Branch

```
git checkout main && git pull
git checkout -b <short-kebab-description>
```

Start from an up-to-date `main`, with one branch per change.

## 2. Change, then check locally

Run every check before pushing:

```
claude plugin validate --strict .
claude plugin test .
```

- **Type-check** with `npx tsc -p .` once Claude Code has written `.claude-plugin/types/`, which happens after the plugin has been loaded once, for example with `claude --plugin-dir .`.
- **Add or update tests** in `hooks/register.test.ts` for any behaviour change.
- **Keep the README accurate.** Every claim about behaviour must match `hooks/register.tsx`. Update the "What each hook does" table if hooks change. Keep the `/config` descriptions in `plugin.json` in step with it.
- **Bump `version`** in `.claude-plugin/plugin.json` if the rules above call for it. Use a patch bump for fixes and wording, minor for new items or options, and major for removed options or changed defaults.

Avoid what the directory's validator flags. These all came back from a real submission:
- **No settings writes.** Don't write settings from the plugin through the engine's config noun. A key the validator can't read as fixed text blocks the listing, and any settings write is held for review. `claude plugin validate` lists every call the module makes, and no config call should appear there. Toggles from the slash command are session-only, held in `$.state`.
- **Don't name binary files in text files.** Anything that mentions the icon's filename (only the manifest's `icon` field may) is held as "an image a script could run". In prose, say "the listing icon".
- **No credential-looking names, and no `$<digit>` in tests.** An identifier of ours ending in "Tokens" read as a credential, and a test regex with a literal dollar sign before a digit read as a shell command; together they were held as "a credential leaving the machine". Name counts `...Count` or `...Size`, and match prices without the dollar sign, e.g. `/2\.25/`.
- **Keep the name clear of existing listings.** Names within a few characters of another plugin's are held for review, so check the directory before renaming.
- **Expected, not fixable:** warnings for `icon`, `documentationUrl`, `supportUrl` and `privacyPolicyUrl` say "no action needed". The directory reads them for the listing. Keep them. Info notes about registering a command, about hooking `session.compact` or `command.run` (the README explains both), and about the icon passing unread are records, not faults.

Before committing, also check:
- the secret scan (`mcp__plugin-authoring__scan_secrets` on the repo folder) is clean
- `grep` finds no private paths or usernames
- there are no `.DS_Store` files, and no file is over 256 KiB

## 3. Pull request

```
git add <files> && git commit
git push -u origin <branch>
gh pr create --base main --head <branch> --title "..." --body "..."
```

- The **Tests** workflow runs when a PR is opened, gets new commits, is reopened or is marked ready for review.
- **Tests**, on the pinned Claude Code version, must pass. It's the required check and is accepted only from GitHub Actions.
- **Tests (latest Claude Code, advisory)** doesn't block merging. If it fails, investigate: an upstream API change may be coming.
- The branch must be up to date with `main`. If it falls behind, run `gh pr update-branch <n>` and wait for the checks again.

Wait for the checks to finish:

```
gh pr checks <n>
```

Then merge:

```
gh pr merge <n> --squash --delete-branch
```

Use squash merges only, so `main` gets one commit per PR. If the merge is refused, fix the cause; don't bypass it.

## 4. Tag a release

Only after a version-bumping PR has merged:

```
git checkout main && git pull
grep '"version"' .claude-plugin/plugin.json      # e.g. 0.3.2
git tag -a v0.3.2 -m "Next Context 0.3.2"         # annotated, on main's merge commit
git push origin v0.3.2                            # the tag only
```

- The tag goes on the merge commit at the tip of `main`, and its version matches `plugin.json` exactly.
- Pushing a tag adds no commits, so branch protection doesn't apply to it. That's why the rules above never allow moving a tag.

Then confirm:
- `git ls-remote --tags origin` lists the tag
- the README's version badge shows it
- the **Tests** run on `main` for the merge commit passed

## 5. Anthropic Plugin Directory

The directory validates and security-scans each commit. Before submitting or relisting:

- `claude plugin validate --strict .` passes.
- The README is at least 40 words outside code blocks, and describes everything the plugin runs, sends or fetches.
- `LICENSE` exists. `plugin.json` has `name`, `description`, `author` and a raised `version`, plus `icon`, `documentationUrl`, `supportUrl` and `privacyPolicyUrl` as `https://` URLs that resolve.
- `PRIVACY.md` still matches what the plugin does.
- A fresh install works in an isolated home: `env -i PATH=/usr/bin:/bin HOME=<tmp> claude plugin install next-context --marketplace ajwann/next-context`. The installed copy validates and passes its tests.

To submit: claude.ai/directory/manage, then **Submit new**, then **Plugin bundle**. Choose `ajwann/next-context`, plugin folder `/`. Answer the data-handling questions (no personal data, no sharing, no retention, not aimed at under-18s), then **Validate** and **Submit**.
