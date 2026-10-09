import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server" / "server.py"


class Client:
    def __init__(self, cwd):
        self.p = subprocess.Popen([sys.executable, str(SERVER)], cwd=cwd, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True)
        self.n = 0

    def request(self, method, params=None):
        self.n += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}) + "\n")
        self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())

    def notify(self, method):
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.p.stdin.flush()

    def call(self, name, **args):
        res = self.request("tools/call", {"name": name, "arguments": args})["result"]
        return res["content"][0]["text"], res["isError"]

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=5)


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    return p


@pytest.fixture
def client(project):
    c = Client(project)
    yield c
    c.close()


def test_handshake_and_tool_list(client):
    init = client.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}})
    assert init["result"]["protocolVersion"] == "2025-06-18" and "tools" in init["result"]["capabilities"]
    client.notify("notifications/initialized")
    names = [t["name"] for t in client.request("tools/list")["result"]["tools"]]
    assert names == ["py_inspect", "py_source", "py_versions", "node_types", "node_versions"]
    assert client.request("nope")["error"]["code"] == -32601


def test_py_inspect_stdlib(client):
    text, err = client.call("py_inspect", target="json.dumps")
    data = json.loads(text)
    assert not err and data["kind"] == "function" and "sort_keys=False" in data["signature"]
    assert data["version"].startswith("stdlib (Python ")
    assert data["defined_at"].endswith(".py:" + data["defined_at"].split(":")[-1])


def test_py_inspect_helpful_errors(client):
    text, err = client.call("py_inspect", target="json.dumpz")
    assert err and "similar: dump, dumps" in text
    text, err = client.call("py_inspect", target="surely_not_a_module_xyz.f")
    assert err and "cannot import" in text


def test_project_venv_is_used(project, client):
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(project / ".venv")], check=True)
    site = next((project / ".venv" / "lib").glob("python*/site-packages"))
    (site / "acme").mkdir()
    (site / "acme" / "__init__.py").write_text(
        "class Client:\n    '''Talks to Acme.'''\n    def fetch(self, key: str, *, retries: int = 3) -> bytes:\n"
        "        return b''\n")
    dist = site / "acme-2.4.1.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: acme\nVersion: 2.4.1\n")
    (dist / "top_level.txt").write_text("acme\n")
    text, err = client.call("py_inspect", target="acme.Client")
    data = json.loads(text)
    assert not err and data["version"] == "acme 2.4.1" and ".venv" in data["interpreter"]
    fetch = next(m for m in data["members"] if m["name"] == "fetch")
    assert fetch["signature"] == "(self, key: str, *, retries: int = 3) -> bytes"
    text, _ = client.call("py_source", target="acme.Client.fetch")
    assert "def fetch(self, key: str" in text
    assert "acme==2.4.1" in client.call("py_versions", pattern="acm")[0]


def test_include_project_imports_local_src(project, client):
    (project / "src" / "mylib").mkdir(parents=True)
    (project / "src" / "mylib" / "__init__.py").write_text("def go(n: int) -> int:\n    return n\n")
    assert client.call("py_inspect", target="mylib.go")[1] is True
    text, err = client.call("py_inspect", target="mylib.go", include_project=True)
    assert not err and json.loads(text)["signature"] == "(n: int) -> int"


def test_node_types(project, client):
    pkg = project / "node_modules" / "zed"
    (pkg / "dist").mkdir(parents=True)
    (pkg / "package.json").write_text(json.dumps({"name": "zed", "version": "3.1.0",
                                                  "exports": {".": {"types": "./dist/index.d.ts"}}}))
    (pkg / "dist" / "index.d.ts").write_text(
        "export * from './util';\n/**\n * Parse a thing.\n */\nexport declare function parse(input: string, opts?: Opts): Node;\n"
        "export interface Opts {\n  strict?: boolean;\n  depth: number;\n}\nexport declare const VERSION: string;\n")
    (pkg / "dist" / "util.d.ts").write_text("export type Node = { kind: string };\n")
    text, err = client.call("node_types", package="zed")
    assert not err and '"version": "3.1.0"' in text and '"parse"' in text and "./util" in text
    text, _ = client.call("node_types", package="zed", symbol="Opts")
    assert "depth: number;" in text and "index.d.ts:6" in text
    text, _ = client.call("node_types", package="zed", symbol="parse")
    assert "Parse a thing." in text and "opts?: Opts" in text
    text, _ = client.call("node_types", package="zed", symbol="Node")
    assert "util.d.ts:1" in text
    assert "zed@3.1.0" in client.call("node_versions", pattern="ze")[0]


def test_node_types_falls_back_to_definitely_typed(project, client):
    (project / "node_modules" / "plain").mkdir(parents=True)
    (project / "node_modules" / "plain" / "package.json").write_text('{"name":"plain","version":"1.0.0"}')
    t = project / "node_modules" / "@types" / "plain"
    t.mkdir(parents=True)
    (t / "package.json").write_text('{"name":"@types/plain","version":"1.0.3","types":"index.d.ts"}')
    (t / "index.d.ts").write_text("declare function plain(x: number): string;\nexport = plain;\n")
    text, _ = client.call("node_types", package="plain", symbol="plain")
    assert "@types/plain 1.0.3" in text and "plain(x: number): string" in text
    text, err = client.call("node_types", package="missing-pkg")
    assert err and "not installed" in text
