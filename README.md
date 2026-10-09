# installed-api

An MCP server (Python stdlib, stdio) that answers API questions from the code **installed in this
project** instead of from memory or web docs.

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

## Install

From Anthropic's plugin directory, once listed: search for `installed-api` in `/plugin directory` in Claude Code, or under **Customize > Plugins** on claude.ai.

To try it from a clone for one session: `claude --plugin-dir /path/to/installed-api`.

## What it runs and stores

It is Python 3.9+ standard library only, makes no network requests, and sends nothing anywhere.

- Runs the project's Python interpreter (`python -I`) to import and inspect the module you ask about, which runs that package's import-time code.
- Reads `.d.ts` files and `package.json` under `node_modules`. It writes nothing.

## Development

```
python3 -m pytest -q
claude plugin validate --strict .
```

## License

MIT. See `LICENSE`.
