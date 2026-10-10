"""公开策略核验在派发前拒绝没有明确模型身份的目标。"""

import pytest

from yuxi.delegation.contracts import DelegationError
from yuxi.services.collaborator_service import CollaboratorService


@pytest.mark.asyncio
@pytest.mark.parametrize("primary", [None, "", "model-only", "/model", "provider/"])
async def test_policy_refuses_missing_model_identity(primary):
    """空或继承模型不能被记录为已核实的当次模型。"""

    class Gateway:
        """仅公开只读oracle；调用执行方法即失败。"""

        async def call(self, method, params):
            """返回明确无工具/无技能策略，隔离模型身份缺陷。"""
            if method == "agents.list":
                return {"agents": [{"id": "C"}]}
            if method == "config.get":
                return {
                    "config": {
                        "agents": {
                            "entries": {
                                "C": {
                                    "model": {"primary": primary, "fallbacks": []},
                                    "tools": {"deny": ["*"]},
                                    "skills": [],
                                    "memory": {"search": {"enabled": False}},
                                }
                            }
                        }
                    }
                }
            assert method == "tools.effective"
            return {
                "agentId": "C",
                "groups": [],
                "toolAccess": {"checked": "local-config", "tools": [{"id": "read", "status": "excluded"}]},
            }

    with pytest.raises(DelegationError) as caught:
        await CollaboratorService.read_target_policy(Gateway(), "C")
    assert caught.value.error_code == "target_policy_unverified"


@pytest.mark.asyncio
async def test_gateway_rpc_total_timeout_covers_unanswered_websocket(monkeypatch):
    """握手成功但RPC永不回执时，总超时明确拒绝，不能无限持锁。"""
    import time
    from aiohttp import web
    from yuxi.delegation import openclaw

    async def websocket(request):
        """真实本地WS完成握手后故意不回复动作。"""
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        await socket.send_json({"type": "event", "event": "connect.challenge"})
        async for message in socket:
            import json

            value = json.loads(message.data)
            if value["method"] == "connect":
                await socket.send_json(
                    {
                        "type": "res",
                        "id": value["id"],
                        "ok": True,
                        "payload": {
                            "protocol": 4,
                            "server": {"version": "2026.9.8"},
                            "auth": {"scopes": ["operator.read", "operator.write"]},
                        },
                    }
                )
        return socket

    app = web.Application()
    app.router.add_get("/", websocket)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    monkeypatch.setattr(openclaw, "RPC_TIMEOUT_SECONDS", 0.1)
    started = time.monotonic()
    try:
        with pytest.raises(DelegationError) as caught:
            await openclaw.OpenClawGateway(f"ws://127.0.0.1:{port}", "synthetic").call("agents.list", {})
        assert caught.value.error_code == "delivery_outcome_unknown"
        assert time.monotonic() - started < 1
    finally:
        await runner.cleanup()
