```
.---------------------------------------.
|                                       |
|             _            _            |
|            / )          ( \           |
|           | |            | |          |
|          _| |     __     | |_         |
|         (_  |    (__)    |  _)        |
|           | |            | |          |
|           | |_          _| |          |
|     \\     \__)        (__/     //    |
|      \\                        //     |
|       \\__                  __//      |
|       |   ''--..      ..--''   |      |
|       |         ''--''         |      |
|       |           ||           |      |
|       |           ||           |      |
|       |           ||           |      |
|       '--..       ||       ..--'      |
|            ''--.. || ..--''           |
|                 ''--''                |
|                                       |
'---------------------------------------'
```

# installed-api

[![tests](https://github.com/ajwann/installed-api/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/ajwann/installed-api/actions/workflows/tests.yml)
[![version](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fajwann%2Finstalled-api%2Fmain%2F.claude-plugin%2Fplugin.json&query=%24.version&label=version)](https://github.com/ajwann/installed-api/tags)
[![license](https://img.shields.io/github/license/ajwann/installed-api)](LICENSE)

**Stop letting your agent guess at APIs. Ask the code you actually installed.**

installed-api is a Claude Code plugin (an MCP server, Python standard library only) that answers
"what's the signature of X?", "does Y take that argument?" and "which version do we have?" from the
packages **installed in this project**: your `.venv`, your `node_modules`. It doesn't answer from
training data or from web docs written for some other version.

## Why your Claude Code install needs this

**The model's memory doesn't know your lockfile.** Training data is a blend of many versions of every
library, and web docs describe `latest`. Your project pins one specific version. That gap produces
invented keyword arguments, calls to methods that were renamed two releases ago, wrong defaults, and
then a round of run, read the traceback, fix, run again.

**Looking it up the hard way burns tokens.** When Claude isn't sure, it falls back to grepping
`site-packages` or `node_modules`, `cat`-ing whole modules or bundled `.d.ts` files, or fetching doc
pages. All of that text goes into your context window, and you pay for it on every turn after that.
installed-api replaces it with one call that returns only the parts that matter.

To be clear about what it doesn't do: it doesn't search or index your own working directory. It saves
tokens on looking up **dependencies**, the code your project calls but didn't write.

| Without installed-api | With installed-api |
|---|---|
| `grep -rn "def approx" .venv/` → open `_pytest/python_api.py` (922 lines, ~36 KB) | `py_inspect pytest.approx` → ~2 KB: signature, docstring, `file:line`, `pytest 9.1.1` |
| Fetch a docs page for whatever version the site documents | The declaration from the package your project resolves |
| `cat node_modules/some-lib/dist/index.d.ts` (often thousands of lines) | `node_types some-lib createClient` → that declaration with its JSDoc |
| Guess, run, read the traceback, retry | Correct the first time |

The sizes in the first row were measured on one machine. Your savings depend on the library, but the
output is always bounded: up to 80 members per inspect, 12,000 characters of source, 80-line
declaration blocks, and at most 400 `.d.ts` files scanned per lookup.

### For humans

- **Code that runs against the versions you pinned**, not the ones the model remembers.
- **Smaller context, cheaper sessions.** Targeted answers instead of whole files dumped into the conversation.
- **Nothing to install or configure.** Python 3.11+ standard library only. It finds `.venv`/`venv`, `$VIRTUAL_ENV`, poetry and pdm environments, `node_modules` and `@types/*` on its own.
- **Private and read-only.** It makes no network requests, sends nothing anywhere, and writes nothing.
- **Tested on Python 3.11 through 3.15** in CI on every push and PR.

### For LLM agents reading this

If these tools are available to you, use them in preference to your memory for any third-party API:

- **Before you write a call to a library function or class**, call `py_inspect` (Python) or
  `node_types` (JS/TS) on it. Use the returned signature and the installed version. Trust them over what
  you recall.
- **When the user asks "which version" or you're about to suggest version-specific code**, call
  `py_versions` / `node_versions`.
- **When the docstring doesn't settle how something behaves**, call `py_source` instead of grepping
  `site-packages` or reading whole files.
- **For the user's own package** (`./src` layouts), pass `include_project: true`.

One call usually answers the question. Results include `defined_at` / `file` paths, so you can cite
exactly where the answer came from.

## Tools

| Tool | What it returns |
|---|---|
| `py_inspect` | Signature, docstring, members (for classes and modules), MRO, defining `file:line` and the distribution version (`requests 2.32.3`), from the project's own interpreter |
| `py_source` | The source of an installed function, class or module |
| `py_versions` | `name==version` for installed distributions matching a pattern |
| `node_types` | A symbol's TypeScript declaration with its JSDoc, from `node_modules` (falling back to `@types/*`), or a package's version and export list |
| `node_versions` | `name@version` for packages in the nearest `node_modules` |

The interpreter is chosen in this order: `.venv` / `venv` (searched upward to the repo root), then
`$VIRTUAL_ENV`, the poetry or pdm env, and finally `python3`. Python lookups import the target module in
a subprocess (`python -I`), so they run that package's import-time code, as using it would.
`include_project: true` also imports from `./src` and `./`.

Example (`py_inspect` with `target: "pytest.approx"`, output trimmed):

```json
{
 "target": "pytest.approx",
 "kind": "function",
 "version": "pytest 9.1.1",
 "defined_at": ".../site-packages/_pytest/python_api.py:646",
 "signature": "(expected: 'Any', rel: 'float | Decimal | timedelta | None' = None, abs: 'float | Decimal | timedelta | None' = None, nan_ok: 'bool' = False) -> 'ApproxBase'",
 "doc": "Assert that two numbers (or two ordered sequences of numbers) are equal to each other\nwithin some tolerance. ..."
}
```

## Supported versions

installed-api supports the Python and Node.js release lines that still receive at least security
updates; a line is dropped once it reaches end of life. As of October 2026 that is Python 3.11–3.15
and Node.js 22, 24 and 26. Node.js is never executed: `node_types` and `node_versions` read
`package.json` and `.d.ts` files from `node_modules`.

## Install

From Anthropic's plugin directory, once listed: search for `installed-api` in `/plugin directory` in Claude Code, or under **Customize > Plugins** on claude.ai.

To try it from a clone for one session: `claude --plugin-dir /path/to/installed-api`.

## What it runs and stores

It is Python 3.11+ standard library only, makes no network requests, and sends nothing anywhere.

- Runs the project's Python interpreter (`python -I`) to import and inspect the module you ask about, which runs that package's import-time code.
- Reads `.d.ts` files and `package.json` under `node_modules`. It writes nothing.

## Development

```
python3 -m pytest -q
claude plugin validate --strict .
```

## License

MIT. See `LICENSE`.
