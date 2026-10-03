from unittest.mock import Mock

import pytest
from pymilvus import MilvusException

from yuxi.knowledge.implementations import milvus


@pytest.mark.parametrize("failures", [0, 1, 5, 6])
def test_milvus_connection_waits_then_succeeds_or_preserves_failure(monkeypatch, failures):
    """暂时未就绪可恢复，持续故障必须耗尽并传播。"""
    kb = object.__new__(milvus.MilvusKB)
    kb.connection_alias = "startup_test"
    kb.milvus_uri = "http://milvus:19530"
    kb.milvus_token = ""
    kb.milvus_db = "yuxi"
    unavailable = MilvusException(code=2, message="Milvus Proxy is not ready yet")
    connect = Mock(side_effect=[unavailable] * failures + [None])
    sleep = Mock()
    databases = Mock(return_value=["yuxi"])
    monkeypatch.setattr(milvus.connections, "connect", connect)
    monkeypatch.setattr(milvus.time, "sleep", sleep)
    monkeypatch.setattr(milvus.db, "list_database", databases)
    using_database = Mock()
    monkeypatch.setattr(milvus.db, "using_database", using_database)

    if failures == 6:
        with pytest.raises(MilvusException, match="Proxy is not ready"):
            kb._init_connection()
        databases.assert_not_called()
    else:
        kb._init_connection()
        databases.assert_called_once_with()
        using_database.assert_called_once_with("yuxi")
    assert connect.call_count == min(failures + 1, 6)
    assert sleep.call_count == min(failures, 5)
    assert all(call.kwargs["timeout"] == 10 for call in connect.call_args_list)
    assert all(call.args == (5,) for call in sleep.call_args_list)


def test_milvus_connection_does_not_retry_invalid_parameters(monkeypatch):
    """非连接异常立即失败，避免掩盖编程错误。"""
    kb = object.__new__(milvus.MilvusKB)
    kb.connection_alias, kb.milvus_uri, kb.milvus_token = "test", "invalid", ""
    connect = Mock(side_effect=ValueError("invalid parameters"))
    sleep = Mock()
    monkeypatch.setattr(milvus.connections, "connect", connect)
    monkeypatch.setattr(milvus.time, "sleep", sleep)
    with pytest.raises(ValueError, match="invalid parameters"):
        kb._init_connection()
    sleep.assert_not_called()
