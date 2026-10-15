"""主题纯契约的正向和拒绝案例。"""

from copy import deepcopy

import pytest
from pydantic import TypeAdapter, ValidationError

from yuxi.services.project_theme_contract import (
    DecisionSourceRevision,
    LoadedThemePackage,
    NavigationEvent,
    ThemePackage,
    WorkTaskDto,
    contract_schemas,
)


def valid_package():
    """最小真实消费者形状，不复用实现生成expected。"""
    return {
        "manifest": {
            "formatVersion": 1,
            "componentAbi": 1,
            "theme": "theme.json",
            "source": "测试作者声明",
            "files": {"survey": "application/json"},
            "assets": {"chart": {"path": "assets/nested/chart.png", "mediaType": "image/png", "sha256": "a" * 64}},
        },
        "theme": {
            "id": "sample",
            "name": "样例",
            "version": "1.0.0",
            "topicLabel": "战略规划",
            "pages": [
                {
                    "id": "home",
                    "title": "阅读",
                    "description": "说明",
                    "layout": "reading",
                    "blocks": [
                        {
                            "id": "topics",
                            "type": "records",
                            "title": "议题",
                            "region": "aside",
                            "variant": "selector",
                            "binding": {"kind": "business", "resource": "topics", "scope": "project"},
                        },
                        {
                            "id": "json",
                            "type": "json",
                            "title": "资料",
                            "region": "main",
                            "binding": {"kind": "file", "alias": "survey"},
                            "action": {"kind": "page", "pageId": "home"},
                        },
                        {
                            "id": "image",
                            "type": "image",
                            "title": "图像",
                            "region": "main",
                            "alt": "等价描述",
                            "binding": {"kind": "asset", "alias": "chart"},
                        },
                    ],
                }
            ],
        },
    }


def test_valid_definition_preserves_display_alias_and_normalizes_defaults():
    """显示别名不改变业务绑定，缺省受控属性可规范化。"""
    package = ThemePackage.model_validate(valid_package())
    assert package.theme.topicLabel == "战略规划"
    assert package.theme.pages[0].blocks[0].binding.resource == "topics"
    assert package.theme.pages[0].blocks[0].statuses == []


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda p: p["manifest"].update(componentAbi=3), "componentAbi"),
        (lambda p: p["manifest"].update(formatVersion="1"), "formatVersion"),
        (lambda p: p["manifest"].update(formatVersion=True), "formatVersion"),
        (lambda p: p["theme"].update(script="alert(1)"), "extra_forbidden"),
        (lambda p: p["theme"].update(layout="arbitrary"), "extra_forbidden"),
        (lambda p: p["theme"]["pages"].append(deepcopy(p["theme"]["pages"][0])), "duplicate_page"),
        (
            lambda p: p["theme"]["pages"][0]["blocks"].append(deepcopy(p["theme"]["pages"][0]["blocks"][0])),
            "duplicate_block",
        ),
        (lambda p: p["theme"]["pages"][0]["blocks"][0].update(type="iframe"), "union_tag_invalid"),
        (lambda p: p["theme"]["pages"][0]["blocks"][0]["binding"].update(resource="tasks"), "literal_error"),
        (lambda p: p["theme"]["pages"][0]["blocks"][0]["binding"].update(resource="workTasks"), "record_variant"),
        (lambda p: p["theme"]["pages"][0]["blocks"][0]["binding"].update(scope="selectedTopic"), "record_scope"),
        (lambda p: p["theme"]["pages"][0]["blocks"][1]["binding"].update(url="https://example.com"), "extra_forbidden"),
        (lambda p: p["theme"]["pages"][0]["blocks"][1]["binding"].update(alias="not-declared"), "resource_reference"),
        (lambda p: p["manifest"]["files"].update(survey="image/png"), "resource_reference"),
        (lambda p: p["theme"]["pages"][0]["blocks"][1]["action"].update(pageId="absent"), "page_reference"),
        (lambda p: p["manifest"]["assets"]["chart"].update(path="assets/../outside.png"), "asset_path"),
        (lambda p: p["manifest"]["assets"]["chart"].update(path="https://example.com/a.png"), "asset_path"),
        (lambda p: p["manifest"]["assets"].update(other=deepcopy(p["manifest"]["assets"]["chart"])), "duplicate_asset"),
    ],
)
def test_illegal_definitions_fail_for_the_intended_reason(mutation, reason):
    """每个新guard恢复目标缺陷后在正确原因失败。"""
    package = valid_package()
    mutation(package)
    with pytest.raises(ValidationError, match=reason):
        ThemePackage.model_validate(package)


@pytest.mark.parametrize(
    "event",
    [
        {"kind": "object", "objectType": "topic", "id": "topic-a"},
        {"kind": "object", "objectType": "decision", "id": "decision-a"},
        {"kind": "object", "objectType": "workTask", "id": "work-a"},
        {"kind": "page", "pageId": "home"},
        {"kind": "selectTopic", "id": "topic-a"},
    ],
)
def test_navigation_is_typed_and_does_not_embed_project_authority(event):
    """项目与用户来自宿主，而非主题事件。"""
    assert TypeAdapter(NavigationEvent).validate_python(event).kind == event["kind"]
    with pytest.raises(ValidationError, match="extra_forbidden"):
        TypeAdapter(NavigationEvent).validate_python({**event, "project_id": "other-project"})


def test_task_input_keeps_frozen_source_and_upstream_extensions():
    """前端投影保留来源版本及原Owner新增字段。"""
    data = {
        "id": "work-a",
        "project_id": "project-a",
        "title": "工作",
        "topic_id": None,
        "source_decision_id": "decision-a",
        "source_decision_revision": 1,
        "number": "DEMO-GEN-000001",
        "description": None,
        "status": "in_progress",
        "acceptance_criteria": "原Owner的验收说明",
    }
    task = WorkTaskDto.model_validate(data)
    assert task.source_decision_revision == 1
    assert task.model_dump()["acceptance_criteria"] == data["acceptance_criteria"]
    with pytest.raises(ValidationError, match="task_source"):
        WorkTaskDto.model_validate({**data, "source_decision_revision": None})


def test_schema_exports_actual_component_and_event_consumers():
    """Schema由真实模型生成，可供前端与维护工具消费。"""
    schemas = contract_schemas()
    assert set(schemas) == {
        "package",
        "loadedPackage",
        "navigation",
        "project",
        "topics",
        "decisions",
        "workTasks",
        "selectedTopic",
        "discussions",
        "resource",
        "sourceRevision",
    }
    assert schemas["package"]["$defs"]["RecordsBinding"]["properties"]["resource"]["enum"] == [
        "topics",
        "decisions",
        "workTasks",
    ]


def test_source_revision_projection_keeps_snapshot_and_rejects_invalid_version():
    """来源版本投影保留原快照，并拒绝无效版本或非正文内容。"""
    data = {
        "decision_id": "decision-a",
        "revision_number": 1,
        "conclusion": "当次依据",
        "snapshot": {"title": "历史标题"},
    }
    assert DecisionSourceRevision.model_validate(data).model_dump()["snapshot"] == data["snapshot"]
    with pytest.raises(ValidationError):
        DecisionSourceRevision.model_validate({**data, "revision_number": 0})
    with pytest.raises(ValidationError):
        DecisionSourceRevision.model_validate({**data, "conclusion": {}})


def test_loaded_reference_is_host_metadata_and_cross_references_still_validate():
    """作者ID或digest不能代替宿主来源引用，加载DTO不绕过包校验。"""
    data = {**valid_package(), "reference": "host-version-uuid", "digest": "a" * 64}
    loaded = LoadedThemePackage.model_validate(data)
    assert loaded.reference != loaded.theme.id
    with pytest.raises(ValidationError):
        LoadedThemePackage.model_validate({**valid_package(), "digest": "a" * 64})
    data["theme"]["pages"][0]["blocks"][1]["binding"]["alias"] = "absent"
    with pytest.raises(ValidationError, match="resource_reference"):
        LoadedThemePackage.model_validate(data)


def test_workspace_capabilities_require_explicit_abi_and_base():
    """新能力只能由ABI2消费者解释，旧包与未知能力拒绝误读。"""
    package = valid_package()
    package["theme"]["pages"] = [
        {"id": "read-custom", "title": "研究文稿", "description": "蓝图读写", "layout": "reading", "capability": "blueprints"}
    ]
    with pytest.raises(ValidationError, match="capability_abi"):
        ThemePackage.model_validate(package)
    package["manifest"]["componentAbi"] = 2
    with pytest.raises(ValidationError, match="base_version"):
        ThemePackage.model_validate(package)
    package["theme"]["baseVersion"] = 1
    parsed = ThemePackage.model_validate(package)
    assert parsed.theme.pages[0].capability == "blueprints"
    assert parsed.theme.pages[0].blocks == []
    duplicate = deepcopy(package)
    duplicate["theme"]["pages"].append({**duplicate["theme"]["pages"][0], "id": "other"})
    with pytest.raises(ValidationError, match="duplicate_capability"):
        ThemePackage.model_validate(duplicate)
    package["theme"]["pages"][0]["capability"] = "arbitrary-api"
    with pytest.raises(ValidationError):
        ThemePackage.model_validate(package)
