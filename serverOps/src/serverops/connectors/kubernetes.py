"""Kubernetes connector (official `kubernetes` client).

The kubernetes client is synchronous, so calls run in a worker thread via
``anyio.to_thread.run_sync`` to stay non-blocking inside the async server.
"""

from __future__ import annotations

from typing import Any

from ..connectors.base import AsyncConnector, HealthStatus
from ..errors import ConnectionFailed, MissingDependency

_HINT = "Kubernetes support requires the 'k8s' extra: pip install 'serverops[k8s]'"


def _import_kubernetes() -> tuple[Any, Any]:
    try:
        from kubernetes import client, config  # type: ignore[import-not-found]
    except ImportError as e:  # optional extra not installed
        raise MissingDependency(_HINT) from e
    return client, config


class KubernetesConnector(AsyncConnector):
    kind = "kubernetes"

    def __init__(self, name: str, profile: Any) -> None:
        super().__init__(name, profile)
        self._core: Any = None
        self._client: Any = None

    def _namespace(self, namespace: str | None) -> str:
        return namespace or self.profile.namespace

    async def connect(self) -> None:
        import anyio

        client, config = _import_kubernetes()

        def _load() -> None:
            if self.profile.in_cluster:
                config.load_incluster_config()
            else:
                config.load_kube_config(
                    config_file=self.profile.kubeconfig, context=self.profile.context
                )

        try:
            await anyio.to_thread.run_sync(_load)
        except Exception as e:  # noqa: BLE001
            raise ConnectionFailed(f"Kube config load failed: {e}") from e
        self._client = client
        self._core = client.CoreV1Api()

    async def health(self) -> HealthStatus:
        if self._core is None:
            return HealthStatus(healthy=False, detail="not connected")
        try:
            await self.list_pods(self.profile.namespace)
            return HealthStatus(healthy=True)
        except Exception as e:  # noqa: BLE001
            return HealthStatus(healthy=False, detail=str(e))

    # -- operations ------------------------------------------------------

    async def list_pods(self, namespace: str | None = None) -> list[dict[str, Any]]:
        import anyio

        ns = self._namespace(namespace)

        def _call() -> list[dict[str, Any]]:
            result = self._core.list_namespaced_pod(ns)
            return [_pod_summary(p) for p in result.items]

        return await anyio.to_thread.run_sync(_call)

    async def pod_logs(self, name: str, namespace: str | None = None, tail: int = 200) -> str:
        import anyio

        ns = self._namespace(namespace)

        def _call() -> str:
            return self._core.read_namespaced_pod_log(
                name=name, namespace=ns, tail_lines=tail
            )

        return await anyio.to_thread.run_sync(_call)

    async def describe(self, name: str, namespace: str | None = None) -> dict[str, Any]:
        import anyio

        ns = self._namespace(namespace)

        def _call() -> dict[str, Any]:
            pod = self._core.read_namespaced_pod(name=name, namespace=ns)
            return _pod_detail(pod)

        return await anyio.to_thread.run_sync(_call)

    async def exec(self, name: str, command: list[str], namespace: str | None = None) -> dict[str, Any]:
        import anyio
        from kubernetes.stream import stream  # type: ignore[import-not-found]

        ns = self._namespace(namespace)

        def _call() -> str:
            return stream(
                self._core.connect_get_namespaced_pod_exec,
                name,
                ns,
                command=command,
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )

        output = await anyio.to_thread.run_sync(_call)
        return {"output": output}

    async def close(self) -> None:
        # The kubernetes client has no per-instance resource to release here.
        self._core = None
        self._client = None


def _pod_summary(pod: Any) -> dict[str, Any]:
    status = getattr(pod, "status", None)
    return {
        "name": _attr(getattr(pod, "metadata", None), "name"),
        "namespace": _attr(getattr(pod, "metadata", None), "namespace"),
        "phase": _attr(status, "phase"),
        "pod_ip": _attr(status, "pod_ip"),
        "node": _attr(getattr(pod, "spec", None), "node_name"),
    }


def _pod_detail(pod: Any) -> dict[str, Any]:
    summary = _pod_summary(pod)
    status = getattr(pod, "status", None)
    summary["host_ip"] = _attr(status, "host_ip")
    summary["started_at"] = _attr(status, "start_time")
    return summary


def _attr(obj: Any, name: str) -> Any:
    return getattr(obj, name, None) if obj is not None else None


def build(name: str, profile: Any) -> KubernetesConnector:
    return KubernetesConnector(name, profile)
