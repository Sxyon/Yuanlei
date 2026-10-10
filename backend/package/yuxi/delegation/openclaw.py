"""OpenClaw 安装版协议4的准确文本委派与公开输出核对。"""

from __future__ import annotations

import asyncio
import hashlib
import uuid

import aiohttp

from yuxi.delegation.contracts import DelegationError, DelegationHandle, DelegationResult, ObservedDeliveryError
from yuxi.delegation.protocol import parse_delivery


RPC_TIMEOUT_SECONDS = 35


class OpenClawGateway:
    """固定版本、有限权限的Gateway RPC运输；不记录凭据及远端错误正文。"""

    def __init__(self, endpoint: str, token: str):
        self.endpoint = endpoint
        self.token = token

    async def call(self, method: str, params: dict) -> dict:
        """执行单个公开RPC，并核验协议、版本与有效scope。"""
        try:
            async with asyncio.timeout(RPC_TIMEOUT_SECONDS):
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=35)) as session:
                    async with session.ws_connect(self.endpoint, max_msg_size=1048576) as socket:
                        await asyncio.wait_for(socket.receive_json(), 10)
                        scopes = ["operator.read", "operator.write"]
                        await socket.send_json(
                            {
                                "type": "req",
                                "id": "connect",
                                "method": "connect",
                                "params": {
                                    "minProtocol": 4,
                                    "maxProtocol": 4,
                                    "client": {
                                        "id": "gateway-client",
                                        "version": "2026.9.8",
                                        "platform": "linux",
                                        "mode": "backend",
                                    },
                                    "role": "operator",
                                    "scopes": scopes,
                                    "caps": [],
                                    "commands": [],
                                    "permissions": {},
                                    "auth": {"token": self.token},
                                },
                            }
                        )
                        hello = await self._response(socket, "connect")
                        if (
                            hello.get("protocol") != 4
                            or hello.get("server", {}).get("version") != "2026.9.8"
                            or not set(scopes).issubset(hello.get("auth", {}).get("scopes", []))
                        ):
                            raise DelegationError(
                                "Gateway版本或有效权限不符合核验范围", error_code="gateway_contract_mismatch"
                            )
                        identifier = uuid.uuid4().hex
                        await socket.send_json({"type": "req", "id": identifier, "method": method, "params": params})
                        return await self._response(socket, identifier)
        except DelegationError:
            raise
        except (TimeoutError, aiohttp.ClientError, ValueError, TypeError) as exc:
            raise DelegationError("Gateway调用结局未知，禁止自动重派", error_code="delivery_outcome_unknown") from exc

    @staticmethod
    async def _response(socket, identifier: str) -> dict:
        """忽略非本RPC事件，仅采纳匹配回执。"""
        while True:
            response = await socket.receive_json()
            if response.get("type") != "res" or response.get("id") != identifier:
                continue
            if not response.get("ok"):
                raise DelegationError("Gateway拒绝当前动作", error_code="gateway_action_rejected")
            payload = response.get("payload")
            if not isinstance(payload, dict):
                raise DelegationError("Gateway回执结构错误", error_code="gateway_contract_mismatch")
            return payload


class OpenClawExecutor:
    """复用持久attempt执行唯一session，回收同Run正式文本。"""

    key = "openclaw"

    def __init__(self, db, resolver):
        self.db = db
        self.resolver = resolver

    def capabilities(self) -> dict[str, bool]:
        """首包只提供准确文本及补充，不承诺取消或恢复。"""
        return {"multi_turn": False, "remote_artifacts": False}

    async def dispatch(self, request):
        """先持久session/调用意图，已调用过的尝试仅核对不再执行。"""
        attempt, target, gateway = await self.resolver(
            request.metadata["attempt_id"], require_current=True, expected_owner=request.metadata.get("dispatch_owner")
        )
        binding = dict(attempt.remote_binding or {})
        if binding.get("dispatch_started"):
            observed = await gateway.call("agent.wait", {"runId": binding["run_id"], "timeoutMs": 1})
            receipt = observed.get("terminalReceipt") or {}
            if (
                observed.get("runId") == binding["run_id"]
                and observed.get("status") == "ok"
                and receipt.get("runId") == binding["run_id"]
                and receipt.get("sessionId") == binding["session_id"]
            ):
                return DelegationHandle(
                    request.operation_id,
                    self.key,
                    session_id=binding["session_id"],
                    external_ref=binding["run_id"],
                    remote_status="completed",
                    binding=binding,
                )
            raise DelegationError("运行接受结局待核对，禁止重派", error_code="delivery_outcome_unknown")
        from yuxi.services.collaborator_service import CollaboratorService, tools_are_denied

        await CollaboratorService.read_target_policy(
            gateway, target.remote_identity, attempt.snapshot_json["effective_config"]["model"]
        )
        key = f"agent:{target.remote_identity}:yuanlei-{attempt.id}"
        if not binding:
            # 未收到create回执也不能再次create；保留唯一key供人工核对。
            attempt.remote_binding = {"agent_id": target.remote_identity, "session_key": key, "create_started": True}
            await self.db.commit()
            created = await gateway.call("sessions.create", {"key": key, "agentId": target.remote_identity})
            entry = created.get("entry") or {}
            if (
                created.get("key") != key
                or not created.get("sessionId")
                or not entry.get("lifecycleRevision")
                or created.get("runStarted") is not False
            ):
                raise DelegationError("新session回执不完整", error_code="binding_unknown")
            binding = {
                "agent_id": target.remote_identity,
                "session_key": key,
                "session_id": created["sessionId"],
                "lifecycle_revision": entry["lifecycleRevision"],
            }
        if not binding.get("session_id"):
            raise DelegationError("session创建结局待核对", error_code="binding_unknown")
        attempt, target, gateway = await self.resolver(
            attempt.id, require_current=True, expected_owner=request.metadata.get("dispatch_owner")
        )
        await CollaboratorService.read_target_policy(
            gateway, target.remote_identity, attempt.snapshot_json["effective_config"]["model"]
        )
        inventory = await gateway.call("tools.effective", {"agentId": binding["agent_id"], "sessionKey": key})
        if not tools_are_denied(inventory, binding["agent_id"]) or inventory["toolAccess"]["checked"] != "live-session":
            raise DelegationError("新session工具范围未证", error_code="target_policy_unverified")
        run_id = f"yuanlei-{attempt.id}"
        binding.update(run_id=run_id, dispatch_started=True)
        attempt.remote_binding = binding
        await self.db.commit()
        # 最终副作用前重新检查当前个人/项目/目标许可。
        await self.resolver(attempt.id, require_current=True, expected_owner=request.metadata.get("dispatch_owner"))
        reply = await gateway.call(
            "agent",
            {
                "agentId": binding["agent_id"],
                "sessionKey": key,
                "sessionId": binding["session_id"],
                "expectedExistingSessionId": binding["session_id"],
                "expectedExistingSessionLifecycleRevision": binding["lifecycle_revision"],
                "idempotencyKey": run_id,
                "message": request.task,
                "deliver": False,
                "disableMessageTool": True,
                "timeout": 60,
            },
        )
        if (
            reply.get("runId") != run_id
            or reply.get("sessionKey") != key
            or reply.get("agentId") != binding["agent_id"]
        ):
            raise DelegationError("接受回执与当次目标不一致", error_code="binding_unknown")
        return DelegationHandle(
            request.operation_id,
            self.key,
            session_id=binding["session_id"],
            external_ref=run_id,
            remote_status="running",
            binding=binding,
        )

    async def status(self, handle):
        """准确终态来自agent.wait，不从session最新状态猜测。"""
        _, _, gateway = await self.resolver(handle.binding["attempt_id"], require_current=False)
        receipt = await gateway.call("agent.wait", {"runId": handle.external_ref, "timeoutMs": 1})
        if receipt.get("runId") != handle.external_ref:
            raise DelegationError("运行观察错配", error_code="binding_unknown")
        return "completed" if receipt.get("status") == "ok" else receipt.get("status")

    async def collect(self, handle):
        """公开协议结构损坏时拒绝交付，使owned collecting正常释放。"""
        try:
            return await self._collect_verified(handle)
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise DelegationError("公开来源回执结构错误", error_code="delivery_source_unverified") from exc

    async def _collect_verified(self, handle):
        """终态、持久assistant、输入与session/Run全部核对后解析交付。"""
        attempt, _, gateway = await self.resolver(handle.binding["attempt_id"], require_current=False)
        binding = attempt.remote_binding
        wait = await gateway.call("agent.wait", {"runId": binding["run_id"], "timeoutMs": 1})
        receipt = wait.get("terminalReceipt") or {}
        if wait.get("runId") != binding["run_id"]:
            raise DelegationError("等待回执Run错配", error_code="delivery_source_unverified")
        if wait.get("status") != "ok":
            raise DelegationError("当次运行尚未成功终态", error_code="delivery_not_ready")
        if (
            receipt.get("runId") != binding["run_id"]
            or receipt.get("sessionId") != binding["session_id"]
            or receipt.get("terminalDisposition") != "visible"
            or receipt.get("successfulToolNames") != []
            or not isinstance(receipt.get("turnId"), str)
            or not receipt["turnId"]
            or receipt.get("rerouted") is not False
        ):
            raise DelegationError("终态身份、工具或处置不符合任务", error_code="delivery_source_unverified")
        model_ref = attempt.snapshot_json["effective_config"]["model"]["primary"]
        provider, model = model_ref.split("/", 1)
        if any(
            receipt.get(kind, {}).get("provider") != provider or receipt.get(kind, {}).get("model") != model
            for kind in ("requested", "effective")
        ):
            raise DelegationError("实际模型与核验快照不一致", error_code="delivery_source_unverified")
        history = await gateway.call(
            "chat.history",
            {
                "sessionKey": binding["session_key"],
                "agentId": binding["agent_id"],
                "sessionId": binding["session_id"],
                "limit": 100,
                "maxChars": 262144,
                "maxBytes": 786432,
            },
        )
        if (
            history.get("sessionId") != binding["session_id"]
            or history.get("sessionKey") != binding["session_key"]
            or history.get("hasMore")
        ):
            raise DelegationError("公开历史不完整或session错配", error_code="delivery_source_unverified")
        messages = history.get("messages") or []
        users = [
            m for m in messages if m.get("role") == "user" and m.get("idempotencyKey") == binding["run_id"] + ":user"
        ]
        answers = [
            m
            for m in messages
            if m.get("role") == "assistant" and (m.get("__openclaw") or {}).get("runId") == binding["run_id"]
        ]
        if (
            len(users) != 1
            or hashlib.sha256(users[0]["content"].encode()).hexdigest() != attempt.rendered_input_hash
            or len(answers) != 1
        ):
            raise DelegationError("当次输入或持久输出来源不完整", error_code="delivery_source_unverified")
        message = answers[0]
        content = message.get("content")
        text = (
            content
            if isinstance(content, str)
            else "".join(x.get("text", "") for x in content or [] if x.get("type") == "text")
        )
        if len(text.encode("utf-16-le")) // 2 > 4096:
            raise DelegationError(
                "安装版终态正文仅证明4096 UTF-16单位以内输出", error_code="delivery_format_unsupported"
            )
        reply = wait.get("terminalReply") or {}
        if message.get("stopReason") != "stop" or reply.get("disposition") != "visible" or text != reply.get("text"):
            raise DelegationError("持久输出与终态正文不一致或截断", error_code="delivery_source_unverified")
        message_id = (message.get("__openclaw") or {}).get("id")
        if not message_id:
            raise DelegationError("持久消息缺少来源ID", error_code="delivery_source_unverified")
        source = {
            "attempt_id": attempt.id,
            **binding,
            "message_id": message_id,
            "content_hash": hashlib.sha256(text.encode()).hexdigest(),
            "terminal_receipt": receipt,
            "provenance_level": "verified-public-readback",
        }
        try:
            formal, supplement = parse_delivery(text, attempt.task_package)
        except DelegationError as exc:
            # 有界、准确公开输出可保留；不合规内容永不形成Result/artifact。
            if len(text.encode()) <= 262144:
                raise ObservedDeliveryError(exc, source=source, text=text) from exc
            raise
        return DelegationResult(
            text=formal["text"],
            summary=formal["text"][:512],
            remote_status="completed",
            source=source,
            supplement=supplement,
            notices=tuple(formal["notices"]),
            usage=message.get("usage") or {},
        )
