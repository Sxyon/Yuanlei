"""固定协作协议的正负例与补充预算边界。"""

import copy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from yuxi.delegation.contracts import DelegationError
from yuxi.delegation.protocol import SCHEMA_ROOT, parse_delivery, validate_contract

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures/collaboration"
SAMPLES = FIXTURE_ROOT / "collaboration-v1-c0.json"


def fixtures():
    """读取已审阅固定oracle；测试不改写它。"""
    return json.loads(SAMPLES.read_text())


def task_and_output():
    """固定当次输出的来源标识与依据。"""
    cases = fixtures()["positive"]
    task = copy.deepcopy(next(x["value"] for x in cases if x["name"] == "task-blocked"))
    value = copy.deepcopy(next(x["value"] for x in cases if x["name"] == "return-completed"))
    value["formal_delivery"]["context_snapshot_id"] = task["context"]["snapshot_id"]
    return task, value


def test_fixed_schemas_and_examples():
    """固定文档派生Schema与运行边界Owner一致。"""
    data = fixtures()
    for name, schema in data["schemas"].items():
        assert json.loads((SCHEMA_ROOT / f"{name}-v1.json").read_text()) == schema
    for case in data["positive"]:
        validate_contract(case["schema"], case["value"])
    for case in data["negative"]:
        with pytest.raises(DelegationError, match="结构"):
            validate_contract(case["schema"], case["value"])


@pytest.mark.parametrize("budget,conforming", [(200, False), (300, True)])
def test_summary_uses_task_budget_and_preserves_formal(budget, conforming):
    """可选摘要超预算不丢正式文本和原文。"""
    task, output = task_and_output()
    task["delivery"]["supplement_max_code_points"] = budget
    output["supplement"]["summary"] = "字" * 201
    formal, supplement = parse_delivery(json.dumps(output), task)
    assert formal["text"] == output["formal_delivery"]["text"]
    assert supplement["summary"] == "字" * 201
    assert supplement["summary_conforming"] is conforming
    assert len(supplement["summary_preview"]) == min(201, budget)


def test_controlled_details_hash_and_nonblocking_notice():
    """详细引用只取同次受控字节，非阻塞事项能正常交付。"""
    task, output = task_and_output()
    text = "检查依据与过程"
    ref = {
        "kind": "inline-text",
        "text": text,
        "size_bytes": len(text.encode()),
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
    }
    output["supplement"].update(details_ref=ref, complete=False)
    output["formal_delivery"]["notices"] = [{"kind": "risk", "text": "交付范围外波动", "blocking": False}]
    formal, supplement = parse_delivery(json.dumps(output), task)
    assert formal["notices"][0]["blocking"] is False
    assert supplement["complete"] is False
    ref["sha256"] = "0" * 64
    with pytest.raises(DelegationError) as caught:
        parse_delivery(json.dumps(output), task)
    assert caught.value.error_code == "supplement_reference_unverified"


def test_joint_projection_schema():
    """五个联合状态采用同一个唯一读Schema。"""
    schema = json.loads((SCHEMA_ROOT / "collaboration-read-v1.json").read_text())
    examples = json.loads((FIXTURE_ROOT / "collaboration-read-v1-joint.json").read_text())["examples"]
    validator = Draft202012Validator(schema)
    for case in examples:
        validator.validate(case["projection"])
    broken = copy.deepcopy(examples[0]["projection"])
    broken["allowed_actions"][0]["question_revision"] = None
    assert list(validator.iter_errors(broken))
    broken = copy.deepcopy(examples[0]["projection"])
    broken["handler"]["run_id"] = "untrusted"
    assert list(validator.iter_errors(broken))


@pytest.mark.parametrize("length,accepted", [(100000, True), (100001, False)])
def test_formal_budget_matches_result_owner(length, accepted):
    """正式交付超出Result全文预算时明确拒绝，不能静默截断。"""
    task, output = task_and_output()
    output["formal_delivery"]["text"] = "a" * length
    if accepted:
        formal, _ = parse_delivery(json.dumps(output), task)
        assert formal["text"] == "a" * length
    else:
        with pytest.raises(DelegationError) as caught:
            parse_delivery(json.dumps(output), task)
        assert caught.value.error_code == "delivery_format_unsupported"
