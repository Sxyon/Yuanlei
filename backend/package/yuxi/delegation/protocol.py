"""协作文本协议的版本、字节边界与正式交付解析 Owner。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from yuxi.delegation.contracts import DelegationError

SCHEMA_ROOT = Path(__file__).with_name("schemas")
PROTOCOL = "yuanlei.collaboration/1.0"
MAX_MESSAGE_BYTES = 262144


def validate_contract(kind: str, value: dict) -> None:
    """在真实任务和模型返回边界执行固定版本结构校验。"""
    schema = json.loads((SCHEMA_ROOT / f"{kind}-v1.json").read_text())
    if next(Draft202012Validator(schema).iter_errors(value), None) is not None:
        raise DelegationError("协作载荷结构不符合约定", error_code="collaboration_protocol_invalid")
    if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_MESSAGE_BYTES:
        raise DelegationError("协作载荷超过字节上限", error_code="collaboration_payload_too_large")


def parse_delivery(text: str, task: dict) -> tuple[dict, dict | None]:
    """核对正式输出及受控补充，保留超任务预算摘要的原文。"""
    if len(text.encode()) > MAX_MESSAGE_BYTES:
        raise DelegationError("协作输出超过字节上限", error_code="collaboration_payload_too_large")
    try:
        value = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise DelegationError("协作输出不是约定JSON", error_code="collaboration_protocol_invalid") from exc
    validate_contract("return", value)
    if value["operation_id"] != task["operation_id"] or value["attempt_id"] != task["attempt_id"]:
        raise DelegationError("输出与当前尝试不一致", error_code="delivery_source_unverified")
    if value["outcome"] != "completed":
        raise DelegationError("本次输出未形成正式交付，保留原输出供后续办理", error_code="delivery_not_completed")
    formal = value["formal_delivery"]
    if (
        formal["criteria_revision"] != task["work"]["criteria_revision"]
        or formal["context_snapshot_id"] != task["context"]["snapshot_id"]
    ):
        raise DelegationError("交付依据与任务快照不一致", error_code="delivery_source_unverified")
    if (
        len(formal["text"].encode()) > 131072
        or len(formal["text"]) > 100000
        or not formal["text"].strip()
        or formal["artifact_refs"]
    ):
        raise DelegationError("首版只接受有界正式文本，不接受未验附件", error_code="delivery_format_unsupported")
    supplement = value["supplement"]
    if supplement is not None:
        details = supplement["details_ref"]
        if details is not None:
            data = details["text"].encode()
            if len(data) != details["size_bytes"] or hashlib.sha256(data).hexdigest() != details["sha256"]:
                raise DelegationError("补充详细报告字节或指纹错误", error_code="supplement_reference_unverified")
        budget = task["delivery"]["supplement_max_code_points"]
        supplement = {
            **supplement,
            "summary_budget": budget,
            "summary_conforming": len(supplement["summary"]) <= budget,
            "summary_preview": supplement["summary"][:budget],
        }
    return formal, supplement
