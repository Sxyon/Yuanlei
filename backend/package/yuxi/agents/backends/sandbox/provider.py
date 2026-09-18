from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import weakref
from dataclasses import dataclass
from typing import Literal

from yuxi.config import get_int_env
from yuxi.utils.logging_config import logger
from yuxi.workspace.paths import normalize_workdir_path, workspace_uid_dirname

from .provisioner_client import ProvisionerClient, SandboxRecord


def sandbox_provisioner_token() -> str:
    token = os.getenv("SANDBOX_PROVISIONER_TOKEN") or ""
    if token != token.strip() or len(token) < 32:
        raise ValueError("SANDBOX_PROVISIONER_TOKEN must contain at least 32 characters")
    return token


def sandbox_id_for_thread(
    thread_id: str,
    *,
    uid: str | None = None,
) -> str:
    runtime_id = str(thread_id or "").strip()
    uid_id = str(uid or "").strip()
    identity = f"{uid_id}:{runtime_id}" if uid_id else runtime_id
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return digest[:12]


@dataclass(frozen=True, slots=True)
class SandboxScope:
    """Sandbox runtime 作用域：线程级（兼容存量）或 Agent+Project 专属。"""

    kind: Literal["thread", "agent_project"]
    uid: str
    thread_id: str | None = None
    agent_slug: str | None = None
    project_id: str | None = None

    @classmethod
    def thread(cls, *, uid: str, thread_id: str) -> "SandboxScope":
        scope = cls(kind="thread", uid=str(uid or "").strip(), thread_id=str(thread_id or "").strip())
        scope.validate()
        return scope

    @classmethod
    def agent_project(cls, *, uid: str, agent_slug: str, project_id: str) -> "SandboxScope":
        scope = cls(
            kind="agent_project",
            uid=str(uid or "").strip(),
            agent_slug=str(agent_slug or "").strip(),
            project_id=str(project_id or "").strip(),
        )
        scope.validate()
        return scope

    @classmethod
    def from_cache_key(cls, cache_key: str) -> "SandboxScope":
        """从缓存键恢复作用域；agent-project 与遗留 uid::thread 两种格式。"""
        raw = str(cache_key or "")
        if raw.startswith("agent-project:"):
            parts = raw.split(":", 3)
            if len(parts) != 4:
                raise ValueError(f"invalid agent-project scope key: {cache_key!r}")
            return cls.agent_project(uid=parts[1], agent_slug=parts[2], project_id=parts[3])
        uid, separator, thread_id = raw.partition("::")
        if not separator:
            raise ValueError(f"invalid thread scope key: {cache_key!r}")
        return cls.thread(uid=uid, thread_id=thread_id)

    @classmethod
    def from_runtime_scope(cls, *, uid: str, runtime_scope_id: str) -> "SandboxScope":
        """把 Run 的 runtime_scope_id 解析为作用域；线程形态兼容裸 thread_id。"""
        runtime_id = str(runtime_scope_id or "").strip()
        if runtime_id.startswith("agent-project:"):
            return cls.from_cache_key(runtime_id)
        return cls.thread(uid=uid, thread_id=runtime_id)

    def validate(self) -> None:
        if not self.uid:
            raise ValueError("sandbox scope uid is required")
        if self.kind == "thread":
            if not self.thread_id:
                raise ValueError("sandbox thread scope requires thread_id")
            return
        if self.kind == "agent_project":
            if not self.agent_slug or not self.project_id:
                raise ValueError("sandbox agent_project scope requires agent_slug and project_id")
            return
        raise ValueError(f"unsupported sandbox scope kind: {self.kind}")

    @property
    def cache_key(self) -> str:
        if self.kind == "thread":
            # 沿用 uid::thread 派生，兼容存量容器与既有缓存语义。
            return f"{self.uid}::{self.thread_id}"
        return f"agent-project:{self.uid}:{self.agent_slug}:{self.project_id}"

    @property
    def sandbox_id(self) -> str:
        if self.kind == "thread":
            return sandbox_id_for_thread(self.thread_id or "", uid=self.uid)
        return hashlib.sha256(self.cache_key.encode("utf-8")).hexdigest()[:12]

    @property
    def provisioner_identity(self) -> str:
        """提供给 provisioner 的身份段，只含字母数字与 -_。"""
        if self.kind == "thread":
            return self.thread_id or ""
        raw = f"agent-project-{self.uid}-{self.agent_slug}-{self.project_id}"
        return re.sub(r"[^A-Za-z0-9_-]", "-", raw)


def normalize_env(env: dict | None) -> dict[str, str]:
    if not isinstance(env, dict):
        return {}
    return {str(key): "" if value is None else str(value) for key, value in env.items() if str(key)}


def postgres_conninfo() -> str:
    db_url = os.getenv("POSTGRES_URL", "").strip()
    return db_url.replace("+asyncpg", "").replace("+psycopg", "")


def load_user_agent_env(uid: str) -> dict[str, str]:
    conninfo = postgres_conninfo()
    if not conninfo:
        return {}

    try:
        import psycopg

        with psycopg.connect(conninfo, connect_timeout=3) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT env FROM agent_envs WHERE uid = %s", (uid,))
                row = cursor.fetchone()
    except Exception as exc:
        raise RuntimeError(f"failed to load agent env for uid {uid}: {exc}") from exc

    if not row:
        return {}

    value = row[0]
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"stored agent env for uid {uid} is not valid JSON") from exc
    return normalize_env(value)


@dataclass(slots=True)
class SandboxConnection:
    cache_key: str
    thread_id: str | None
    uid: str
    sandbox_id: str
    sandbox_url: str
    generation: str | None = None
    workdir_path: str | None = None
    scope_kind: str = "thread"
    agent_slug: str | None = None
    project_id: str | None = None
    lifecycle: str | None = None
    idle_timeout_seconds: int | None = None


class SandboxIdentityMismatchError(RuntimeError):
    """Sandbox runtime 的持久挂载身份与请求不一致。"""


class SandboxReleaseLockTimeoutError(RuntimeError):
    """Sandbox release 等待同作用域 provider 锁超时。"""


class ProvisionerSandboxProvider:
    def __init__(self):
        provider_name = (os.getenv("SANDBOX_PROVIDER") or "provisioner").strip().lower()
        if provider_name != "provisioner":
            raise ValueError("Only SANDBOX_PROVIDER=provisioner is supported.")
        provisioner_url = (os.getenv("SANDBOX_PROVISIONER_URL") or "http://sandbox-provisioner:8002").strip()

        self._client = ProvisionerClient(
            provisioner_url,
            token=sandbox_provisioner_token(),
            delete_timeout_seconds=get_int_env("SANDBOX_PROVISIONER_DELETE_TIMEOUT_SECONDS", 120),
        )
        self._lock = threading.Lock()
        # 活跃或等待中的调用者持有强引用；空闲作用域的锁自动回收。
        self._thread_locks: weakref.WeakValueDictionary[str, threading.Lock] = weakref.WeakValueDictionary()
        self._connections: dict[str, SandboxConnection] = {}
        self._last_touch_at: dict[str, float] = {}
        self._touch_interval_seconds = int(os.getenv("SANDBOX_KEEPALIVE_INTERVAL_SECONDS") or 30)
        self._release_lock_timeout_seconds = get_int_env("SANDBOX_PROVIDER_RELEASE_LOCK_TIMEOUT_SECONDS", 30)

    def _thread_lock(self, cache_key: str) -> threading.Lock:
        with self._lock:
            lock = self._thread_locks.get(cache_key)
            if lock is None:
                lock = threading.Lock()
                self._thread_locks[cache_key] = lock
            return lock

    def _record_to_connection(
        self,
        *,
        scope: SandboxScope,
        record: SandboxRecord,
    ) -> SandboxConnection:
        connection = SandboxConnection(
            cache_key=scope.cache_key,
            thread_id=scope.thread_id,
            uid=scope.uid,
            sandbox_id=record.sandbox_id,
            sandbox_url=record.sandbox_url,
            generation=record.generation,
            workdir_path=record.workdir_path,
            scope_kind=scope.kind,
            agent_slug=scope.agent_slug,
            project_id=scope.project_id,
            lifecycle=getattr(record, "lifecycle", None),
            idle_timeout_seconds=getattr(record, "idle_timeout_seconds", None),
        )
        self._connections[scope.cache_key] = connection
        self._last_touch_at[scope.cache_key] = time.time()
        return connection

    def _should_touch(self, cache_key: str) -> bool:
        if self._touch_interval_seconds <= 0:
            return False
        last_touch = self._last_touch_at.get(cache_key)
        if last_touch is None:
            return True
        return (time.time() - last_touch) >= self._touch_interval_seconds

    def _touch_if_needed(self, connection: SandboxConnection) -> bool:
        if self._should_touch(connection.cache_key):
            is_alive = self._client.touch(connection.sandbox_id)
            self._last_touch_at[connection.cache_key] = time.time()
            if not is_alive:
                return False
        record = self._client.discover(connection.sandbox_id)
        if record is None:
            return False
        if record.workdir_path != connection.workdir_path:
            raise SandboxIdentityMismatchError("sandbox Workdir changed within one runtime scope")
        connection.sandbox_url = record.sandbox_url
        connection.generation = record.generation
        return True

    def get(
        self,
        thread_id: str,
        *,
        uid: str,
        create_if_missing: bool = False,
        inherit_env: bool = True,
        workdir_path: str | None = None,
    ) -> SandboxConnection | None:
        """按线程作用域获取 Sandbox（兼容入口）。"""
        return self.get_scope(
            SandboxScope.thread(uid=uid, thread_id=thread_id),
            create_if_missing=create_if_missing,
            inherit_env=inherit_env,
            workdir_path=workdir_path,
        )

    @staticmethod
    def _validate_connection_identity(
        connection: SandboxConnection,
        scope: SandboxScope,
        normalized_workdir_path: str | None,
    ) -> None:
        if connection.uid != scope.uid:
            raise RuntimeError(
                f"sandbox scope {connection.cache_key} belongs to uid {connection.uid}, not {scope.uid}"
            )
        if connection.scope_kind != scope.kind:
            raise SandboxIdentityMismatchError(
                "sandbox scope kind does not match the existing runtime scope"
            )
        if scope.kind == "agent_project" and (
            connection.agent_slug != scope.agent_slug
            or connection.project_id != scope.project_id
        ):
            raise SandboxIdentityMismatchError(
                "sandbox Agent/Project does not match the existing runtime scope"
            )
        if connection.workdir_path != normalized_workdir_path:
            raise SandboxIdentityMismatchError(
                "sandbox Workdir does not match the existing runtime scope"
            )

    def get_scope(
        self,
        scope: SandboxScope,
        *,
        create_if_missing: bool = False,
        inherit_env: bool = True,
        workdir_path: str | None = None,
        lifecycle: str | None = None,
        idle_timeout_seconds: int | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> SandboxConnection | None:
        """按作用域获取 Sandbox；命中缓存失败时按需创建或发现。"""
        scope.validate()
        normalized_workdir_path = normalize_workdir_path(workdir_path) if workdir_path else None
        cache_key = scope.cache_key
        lock = self._thread_lock(cache_key)
        with lock:
            current = self._connections.get(cache_key)
            if current:
                self._validate_connection_identity(current, scope, normalized_workdir_path)
                try:
                    if self._touch_if_needed(current):
                        return current
                    self._connections.pop(cache_key, None)
                    self._last_touch_at.pop(cache_key, None)
                except SandboxIdentityMismatchError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"Failed to touch sandbox {current.sandbox_id} for {cache_key}: {exc}")
                    return current

            if create_if_missing:
                env: dict[str, str] = load_user_agent_env(scope.uid) if inherit_env else {}
                if env_overrides and inherit_env:
                    env.update(env_overrides)
                record = self._client.create(
                    scope.sandbox_id,
                    scope.provisioner_identity,
                    workspace_uid_dirname(scope.uid),
                    env,
                    workdir_path=normalized_workdir_path,
                    inherit_env=inherit_env,
                    lifecycle=lifecycle,
                    idle_timeout_seconds=idle_timeout_seconds,
                )
                if record.workdir_path != normalized_workdir_path:
                    raise RuntimeError("created sandbox Workdir does not match requested scope")
            else:
                record = self._client.discover(scope.sandbox_id)
                if record is None:
                    return None
                if record.workdir_path != normalized_workdir_path:
                    raise RuntimeError("discovered sandbox Workdir does not match requested scope")

            return self._record_to_connection(scope=scope, record=record)

    def list_sandboxes(self) -> list[SandboxRecord]:
        """读取 provisioner 权威 inventory（不刷新 idle 活动）。"""
        return self._client.list()

    def release(
        self,
        thread_id: str,
        *,
        uid: str,
        clear_cache_on_delete_failure: bool = False,
        workdir_path: str | None = None,
    ) -> None:
        """释放指定线程作用域的 Sandbox（兼容入口）。"""
        self.release_scope(
            SandboxScope.thread(uid=uid, thread_id=thread_id),
            clear_cache_on_delete_failure=clear_cache_on_delete_failure,
            workdir_path=workdir_path,
        )

    def release_scope(
        self,
        scope: SandboxScope,
        *,
        clear_cache_on_delete_failure: bool = False,
        workdir_path: str | None = None,
    ) -> None:
        """释放指定作用域的 Sandbox，并清理本地连接缓存。"""
        scope.validate()
        normalized_workdir_path = normalize_workdir_path(workdir_path) if workdir_path else None
        cache_key = scope.cache_key
        lock = self._thread_lock(cache_key)
        acquired = lock.acquire(timeout=getattr(self, "_release_lock_timeout_seconds", 30))
        if not acquired:
            raise SandboxReleaseLockTimeoutError(
                f"sandbox release lock timed out for runtime scope {cache_key}"
            )
        try:
            connection = self._connections.get(cache_key)
            if connection and connection.workdir_path != normalized_workdir_path:
                raise SandboxIdentityMismatchError("sandbox Workdir does not match the existing runtime scope")
            if connection is None:
                record = self._client.discover(scope.sandbox_id)
                if record is None:
                    return
                if record.workdir_path != normalized_workdir_path:
                    raise SandboxIdentityMismatchError("sandbox Workdir does not match the requested release scope")
                generation = record.generation
                sandbox_id = scope.sandbox_id
            else:
                sandbox_id = connection.sandbox_id
                generation = connection.generation
            try:
                self._client.delete(sandbox_id, expected_generation=generation)
            except Exception:
                if clear_cache_on_delete_failure:
                    self._connections.pop(cache_key, None)
                    self._last_touch_at.pop(cache_key, None)
                raise
            self._connections.pop(cache_key, None)
            self._last_touch_at.pop(cache_key, None)
        finally:
            lock.release()

    def shutdown(self) -> None:
        with self._lock:
            connections = list(self._connections.values())
            self._connections.clear()
            self._last_touch_at.clear()

        for connection in connections:
            try:
                self._client.delete(
                    connection.sandbox_id,
                    expected_generation=connection.generation,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Failed to release sandbox {connection.sandbox_id} for {connection.cache_key}: {exc}")


_sandbox_provider: ProvisionerSandboxProvider | None = None
_sandbox_provider_lock = threading.Lock()


def init_sandbox_provider() -> ProvisionerSandboxProvider:
    global _sandbox_provider
    with _sandbox_provider_lock:
        if _sandbox_provider is None:
            _sandbox_provider = ProvisionerSandboxProvider()
        return _sandbox_provider


def get_sandbox_provider() -> ProvisionerSandboxProvider:
    provider = _sandbox_provider
    if provider is not None:
        return provider
    return init_sandbox_provider()


def shutdown_sandbox_provider() -> None:
    global _sandbox_provider
    with _sandbox_provider_lock:
        provider = _sandbox_provider
        _sandbox_provider = None
    if provider is not None:
        provider.shutdown()
