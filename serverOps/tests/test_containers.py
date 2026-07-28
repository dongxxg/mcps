"""Docker + Kubernetes connectors and tools, against injected fake libraries.

The real aiodocker / kubernetes clients are hard to exercise without a daemon
or cluster and aren't trivially installable on Python 3.14, so we inject fakes
into sys.modules and validate the connector + tool + safety wiring end-to-end.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from serverops.connectors.docker import DockerConnector
from serverops.connectors.kubernetes import KubernetesConnector
from serverops.errors import MissingDependency, SafetyError
from serverops.models import DockerProfile, KubernetesProfile, ServerOpsConfig
from serverops.registry import ConnectorRegistry
from serverops.tools import container_tools

# ---------------------------------------------------------------------------
# async-iterator helper
# ---------------------------------------------------------------------------


class _AsyncIter:
    def __init__(self, items):
        self._items = list(items)
        self._i = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._i >= len(self._items):
            raise StopAsyncIteration
        v = self._items[self._i]
        self._i += 1
        return v


# ---------------------------------------------------------------------------
# Fake aiodocker
# ---------------------------------------------------------------------------


class _Container(dict):
    pass


class _FakeExec:
    def __init__(self, output):
        self._output = output

    async def start(self):
        return _AsyncIter([self._output])

    async def inspect(self):
        return {"ExitCode": 0}


class _FakeHandle:
    def __init__(self, name):
        self._name = name

    async def log(self, stdout=True, stderr=True, tail=200):
        return [f"{self._name} line\n"]

    async def exec(self, cmd):
        return _FakeExec("executed\n")

    async def show(self):
        return {"Name": "/" + self._name, "State": {"Status": "running"}}

    async def stats(self, stream=False):
        return {
            "memory_stats": {"usage": 1048576, "limit": 20971520},
            "cpu_stats": {"online_cpus": 2},
        }


class _FakeContainers:
    def __init__(self, listed, handles):
        self._listed = listed
        self._handles = handles

    async def list(self, all=True):  # noqa: A002 - matches aiodocker API
        return self._listed

    def container(self, name):
        return self._handles.setdefault(name, _FakeHandle(name))


class _FakeDocker:
    def __init__(self, listed):
        self.containers = _FakeContainers(listed, {})

    async def version(self):
        return {"Version": "24.0"}

    async def close(self):
        pass


def install_fake_aiodocker(monkeypatch, listed=None):
    listed = listed or [_Container({"Id": "abc", "Names": ["/web"], "Image": "nginx",
                                    "State": "running", "Status": "Up"})]
    mod = types.ModuleType("aiodocker")
    captured: dict[str, Any] = {}

    def Docker(url=None, **kw):
        captured["url"] = url
        return _FakeDocker(listed)

    mod.Docker = Docker
    monkeypatch.setitem(sys.modules, "aiodocker", mod)
    return captured


# ---------------------------------------------------------------------------
# Fake kubernetes
# ---------------------------------------------------------------------------


class _Meta:
    def __init__(self, name, ns="default"):
        self.name = name
        self.namespace = ns


class _Status:
    def __init__(self, phase, ip):
        self.phase = phase
        self.pod_ip = ip
        self.host_ip = None
        self.start_time = None


class _Spec:
    def __init__(self, node):
        self.node_name = node


class _Pod:
    def __init__(self, name, phase="Running", ip="10.0.0.1", node="n1", ns="default"):
        self.metadata = _Meta(name, ns)
        self.status = _Status(phase, ip)
        self.spec = _Spec(node)


class _PodList:
    def __init__(self, items):
        self.items = items


def install_fake_kubernetes(monkeypatch, pods=None):
    pods = pods or [_Pod("api-0"), _Pod("api-1")]

    k8s = types.ModuleType("kubernetes")
    config = types.ModuleType("kubernetes.config")
    config.load_incluster_config = lambda: None
    config.load_kube_config = lambda config_file=None, context=None: None

    client = types.ModuleType("kubernetes.client")

    class CoreV1Api:
        def __init__(self):
            self.last_namespace = None

        def list_namespaced_pod(self, ns):
            self.last_namespace = ns
            return _PodList(pods)

        def read_namespaced_pod_log(self, name, namespace, tail_lines=200):
            return f"{name} log\n"

        def read_namespaced_pod(self, name, namespace):
            for p in pods:
                if p.metadata.name == name:
                    return p
            raise KeyError(name)

        def connect_get_namespaced_pod_exec(self, *a, **k):
            return "exec-out"

    client.CoreV1Api = CoreV1Api

    stream_mod = types.ModuleType("kubernetes.stream")
    stream_mod.stream = lambda fn, *a, **k: fn(*a, **k)

    k8s.config = config
    k8s.client = client
    k8s.stream = stream_mod
    monkeypatch.setitem(sys.modules, "kubernetes", k8s)
    monkeypatch.setitem(sys.modules, "kubernetes.config", config)
    monkeypatch.setitem(sys.modules, "kubernetes.client", client)
    monkeypatch.setitem(sys.modules, "kubernetes.stream", stream_mod)
    return pods


# ---------------------------------------------------------------------------
# Docker connector tests
# ---------------------------------------------------------------------------


async def test_docker_ps_logs_exec_stats(monkeypatch) -> None:
    install_fake_aiodocker(monkeypatch)
    c = DockerConnector("dk", DockerProfile())
    await c.connect()

    rows = await c.ps()
    assert rows[0]["name"] == "web"
    assert rows[0]["image"] == "nginx"

    assert "line" in await c.logs("web")

    executed = await c.exec("web", ["ls", "-la"])
    assert executed["exit_code"] == 0
    assert "executed" in executed["output"]

    stats = await c.stats("web")
    assert stats["memory_usage_mb"] == 1.0
    assert stats["cpu_count"] == 2


async def test_docker_missing_extra_raises(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "aiodocker", raising=False)
    try:
        import aiodocker  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("aiodocker installed; cannot exercise missing-dependency path")
    c = DockerConnector("dk", DockerProfile())
    with pytest.raises(MissingDependency):
        await c.connect()


# ---------------------------------------------------------------------------
# Kubernetes connector tests
# ---------------------------------------------------------------------------


async def test_k8s_list_logs_describe_exec(monkeypatch) -> None:
    install_fake_kubernetes(monkeypatch)
    c = KubernetesConnector("kc", KubernetesProfile())
    await c.connect()

    pods = await c.list_pods()
    assert [p["name"] for p in pods] == ["api-0", "api-1"]
    assert pods[0]["phase"] == "Running"

    assert "log" in await c.pod_logs("api-0")

    desc = await c.describe("api-0")
    assert desc["name"] == "api-0"
    assert desc["pod_ip"] == "10.0.0.1"

    executed = await c.exec("api-0", ["uname", "-a"])
    assert executed["output"] == "exec-out"


async def test_k8s_namespace_override(monkeypatch) -> None:
    install_fake_kubernetes(monkeypatch)
    c = KubernetesConnector("kc", KubernetesProfile(namespace="default"))
    await c.connect()
    await c.list_pods(namespace="kube-system")
    assert c._core.last_namespace == "kube-system"  # type: ignore[attr-defined]


async def test_k8s_missing_extra_raises(monkeypatch) -> None:
    for sub in ("kubernetes", "kubernetes.client", "kubernetes.config", "kubernetes.stream"):
        monkeypatch.delitem(sys.modules, sub, raising=False)
    try:
        import kubernetes  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("kubernetes installed; cannot exercise missing-dependency path")
    c = KubernetesConnector("kc", KubernetesProfile())
    with pytest.raises(MissingDependency):
        await c.connect()


# ---------------------------------------------------------------------------
# Tool-level tests
# ---------------------------------------------------------------------------


def _registry(monkeypatch, *, settings_read_only=False):
    install_fake_aiodocker(monkeypatch)
    install_fake_kubernetes(monkeypatch)
    cfg = ServerOpsConfig.model_validate(
        {
            "settings": {"read_only": settings_read_only},
            "connections": {
                "dk": {"kind": "docker", "url": "unix:///var/run/docker.sock"},
                "kc": {"kind": "kubernetes", "namespace": "default"},
            },
        }
    )
    reg = ConnectorRegistry(cfg)
    from serverops.connectors import docker as d
    from serverops.connectors import kubernetes as k

    def _build(name, profile):
        if profile.kind == "docker":
            return d.build(name, profile)
        if profile.kind == "kubernetes":
            return k.build(name, profile)
        raise AssertionError("unexpected kind in test")

    reg._build = _build  # type: ignore[method-assign]
    return reg


async def test_docker_tool_roundtrip(fake_mcp, monkeypatch) -> None:
    reg = _registry(monkeypatch)
    container_tools.register(fake_mcp, reg)
    ps = await fake_mcp.tools["docker_ps"]("dk")
    assert ps["containers"][0]["image"] == "nginx"
    logs = await fake_mcp.tools["docker_logs"]("dk", "web")
    assert "line" in logs["logs"]
    ex = await fake_mcp.tools["docker_exec"]("dk", "web", "ls -la")
    assert ex["exit_code"] == 0


async def test_docker_exec_gated_by_readonly(fake_mcp, monkeypatch) -> None:
    reg = _registry(monkeypatch, settings_read_only=True)
    container_tools.register(fake_mcp, reg)
    with pytest.raises(SafetyError):
        await fake_mcp.tools["docker_exec"]("dk", "web", "ls -la")


async def test_k8s_tool_roundtrip(fake_mcp, monkeypatch) -> None:
    reg = _registry(monkeypatch)
    container_tools.register(fake_mcp, reg)
    pods = await fake_mcp.tools["k8s_list_pods"]("kc")
    assert len(pods["pods"]) == 2
    desc = await fake_mcp.tools["k8s_describe"]("kc", "api-0")
    assert desc["pod"]["name"] == "api-0"
    ex = await fake_mcp.tools["k8s_exec"]("kc", "api-0", "uname -a")
    assert ex["output"] == "exec-out"


async def test_k8s_exec_gated_by_readonly(fake_mcp, monkeypatch) -> None:
    reg = _registry(monkeypatch, settings_read_only=True)
    container_tools.register(fake_mcp, reg)
    with pytest.raises(SafetyError):
        await fake_mcp.tools["k8s_exec"]("kc", "api-0", "uname -a")


async def test_container_tool_rejects_wrong_kind(fake_mcp, monkeypatch) -> None:
    reg = _registry(monkeypatch)
    # remove the docker connection so docker_ps is pointed at a k8s connection
    container_tools.register(fake_mcp, reg)
    from serverops.errors import ServerOpsError

    with pytest.raises(ServerOpsError):
        await fake_mcp.tools["docker_ps"]("kc")  # kc is kubernetes, not docker
