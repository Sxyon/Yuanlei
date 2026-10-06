"""项目管理属性的独立边界与日期语义。"""

from datetime import date

import pytest
from fastapi import HTTPException

from yuxi.services.project_settings_service import validate_project_settings

pytestmark = pytest.mark.unit


def settings(**changes):
    """构造完整管理属性。"""
    return {
        "work_status": "planned",
        "priority": "none",
        "owner_type": "member",
        "owner_id": "creator",
        "description": "",
        "start_date": None,
        "due_date": None,
        **changes,
    }


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"work_status": "active"}, "项目状态非法"),
        ({"project_type": "unknown"}, "项目类型非法"),
        ({"category": "长" * 51}, "分类最多 50 字符"),
        ({"tags": ["长" * 31]}, "标签最多 20 个，每个最多 30 字符"),
        ({"tags": [str(i) for i in range(21)]}, "标签最多 20 个，每个最多 30 字符"),
        ({"priority": "unknown"}, "优先级非法"),
        ({"owner_type": "unknown"}, "负责人类型非法"),
        ({"owner_type": "none"}, "负责人类型与身份不一致"),
        ({"owner_id": None}, "负责人类型与身份不一致"),
        ({"description": "描" * 256}, "项目描述最多 255 字符"),
        ({"start_date": date(2026, 10, 4), "due_date": date(2026, 10, 3)}, "截止日期不得早于开始日期"),
    ],
)
def test_invalid_settings_rejected_for_specific_reason(changes, message):
    with pytest.raises(HTTPException) as error:
        validate_project_settings(settings(**changes))
    assert error.value.status_code == 422
    assert error.value.detail == message


@pytest.mark.parametrize(
    "changes",
    [
        {"start_date": date(2026, 10, 3)},
        {"due_date": date(2026, 10, 3)},
        {"start_date": date(2026, 10, 3), "due_date": date(2026, 10, 3)},
        {"description": "描" * 255},
        {"owner_type": "none", "owner_id": None},
        *[{"work_status": value} for value in ("planned", "in_progress", "paused", "completed", "cancelled")],
    ],
)
def test_valid_calendar_and_management_values(changes):
    validate_project_settings(settings(**changes))


def test_project_attributes_normalize_without_changing_calendar():
    values = settings(project_type="ongoing", category="   ", tags=[" 成长 ", "成长", "", "复盘"])
    validate_project_settings(values)
    assert values["category"] is None and values["tags"] == ["成长", "复盘"]
    assert values["start_date"] is None and values["due_date"] is None
