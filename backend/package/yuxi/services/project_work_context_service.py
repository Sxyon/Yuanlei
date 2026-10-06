"""组装、预览并核对本次业务资料，运行配置仍由 manifest 拥有。"""

import codecs
import hashlib
import json
from typing import Annotated

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from yuxi.repositories.project_work_context_repository import ProjectWorkContextRepository
from yuxi.repositories.project_work_repository import ProjectWorkRepository
from yuxi.repositories.project_settings_repository import ProjectSettingsRepository
from yuxi.services.project_blueprint_service import validate_blueprint_name, MAX_BLUEPRINT_BYTES
from yuxi.services.project_work_service import require_task, writable_project
from yuxi.storage.minio import StorageError, get_minio_client
from yuxi.utils.datetime_utils import format_utc_datetime, utc_now_naive
from yuxi.workspace.workdir import Workdir

TEXT_BUDGET = 256_000
FILE_PREFIX_BYTES = 64 * 1024


ContextLocator = Annotated[str, Field(min_length=1, max_length=1024)]
ContextExcerpt = Annotated[str, Field(max_length=TEXT_BUDGET)]


class ContextSelection(BaseModel):
    """用户显式选择的资料，默认仅当前要求、已选来源和既有引用。"""

    model_config = ConfigDict(extra="forbid")
    topic_revision: int | None = Field(default=None, ge=1)
    blueprints: list[ContextLocator] = Field(default_factory=list, max_length=20)
    files: list[ContextLocator] = Field(default_factory=list, max_length=20)
    attachments: list[ContextLocator] = Field(default_factory=list, max_length=20)
    results: list[ContextLocator] = Field(default_factory=list, max_length=20)
    excerpts: dict[ContextLocator, ContextExcerpt] = Field(default_factory=dict, max_length=20)


class ContextInput(BaseModel):
    """预览与创建共用的资料选择和预期指纹。"""

    model_config = ConfigDict(extra="forbid")
    selection: ContextSelection = Field(default_factory=ContextSelection)
    expected_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)


async def preview_context(*, db, user, project_id, task_id, selection=None):
    """回读当前授权资料；预览不保存执行或运行记录。"""
    project = await writable_project(db, user, project_id)
    task = await require_task(db, user, project_id, task_id, lock=True)
    return await assemble_context(db=db, user=user, project=project, task=task, selection=selection)


async def assemble_context(*, db, user, project, task, selection=None, expected_fingerprint=None):
    """创建事务内读取正文并保存实际输入，指纹不一致显式拒绝。"""
    choices = ContextSelection.model_validate(selection or {}).model_dump()
    repo = ProjectWorkRepository(db, project_id=project.id, uid=str(user.uid))
    versions = ProjectWorkContextRepository(db, project.id)
    items = []
    required = (
        f"工作 {task.number}：{task.title}\n\n工作描述：\n{task.description or '未填写'}"
        f"\n\n验收条件：\n{task.acceptance_criteria or '未填写，请先核对工作要求'}"
    )
    if len(required) > TEXT_BUDGET:
        raise HTTPException(422, detail="工作要求超过资料预算，请精简后执行；不会截断必需要求")
    items.append(
        dict(
            kind="requirements",
            locator=task.id,
            revision=task.criteria_revision,
            description=task.description or "",
            acceptance_criteria=task.acceptance_criteria or "",
            text=required,
            mode="direct",
            note="工作要求完整保留",
        )
    )
    if task.source_decision_id:
        decision, version = await versions.decision(task.source_decision_id, task.source_decision_revision)
        body = version.snapshot if version else None
        source_detail = await repo.source_detail(
            topic_id=task.topic_id, decision_id=task.source_decision_id, revision=task.source_decision_revision
        )
        requires_review = bool((source_detail.get("decision") or {}).get("requires_review"))
        items.append(
            dict(
                kind="decision",
                locator=task.source_decision_id,
                revision=task.source_decision_revision,
                text=json.dumps(body, ensure_ascii=False, sort_keys=True) if body else "",
                mode="direct" if body else "missing",
                note=f"选定批准修订；当前状态：{decision.status}"
                + ("；原依据已变化，请复核；不会自动停工或切换来源" if requires_review else "")
                if decision
                else "选定决策版本缺失",
            )
        )
    if task.topic_id:
        topic, version = await versions.topic(task.topic_id, choices["topic_revision"])
        items.append(
            dict(
                kind="topic",
                locator=task.topic_id,
                revision=version.number if version else choices["topic_revision"],
                text=f"{version.title}\n\n{version.summary or ''}" if version else "",
                mode="direct" if version else "missing",
                note="议题研讨资料，不替代正式决策" if topic else "议题缺失",
            )
        )
    for result_id in choices["results"]:
        row = await versions.result(task.id, result_id)
        if row is None:
            raise HTTPException(404, detail="所选结果不属于当前工作或已不可访问")
        items.append(
            dict(
                kind="result",
                locator=row.id,
                revision=row.version,
                mode="direct",
                text=(
                    f"{row.summary}\n\n未解决事项：{row.unresolved or '无'}"
                    f"\n\n验收意见（要求修订 {row.criteria_revision or '未记录'}）：{row.review_comment or '尚无意见'}"
                ),
                note=f"业务结果状态：{row.status}；要求修订：{row.criteria_revision}",
            )
        )
    for name in choices["blueprints"]:
        try:
            name = validate_blueprint_name(name)
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        item = read_context_file(
            str(user.uid), project, f"/.yuanlei/blueprint/{name}", MAX_BLUEPRINT_BYTES, "blueprint"
        )
        if item["mode"] == "direct":
            item["original_text"] = item["text"]
        items.append(item)
    for path in choices["files"]:
        items.append(read_context_file(str(user.uid), project, path, FILE_PREFIX_BYTES, "file"))
    for attachment_id in choices["attachments"]:
        attachment = await repo.get_attachment(attachment_id)
        if attachment is None or attachment.task_id != task.id:
            raise HTTPException(404, detail="附件不属于当前工作或已不可访问")
        item = dict(
            kind="attachment", locator=attachment.id, name=attachment.file_name, mode="direct", text="", note=""
        )
        try:
            client = get_minio_client()
            data = await client.adownload_file(
                bucket_name=client.KB_BUCKETS["documents"], object_name=attachment.object_name
            )
            prefix = data[:FILE_PREFIX_BYTES]
            item.update(
                hash=digest(data),
                hash_scope="full",
                text=codecs.getincrementaldecoder("utf-8")().decode(prefix, final=len(data) <= FILE_PREFIX_BYTES),
                note="受控读取附件",
            )
            if len(data) > FILE_PREFIX_BYTES:
                item.update(truncated=True, note="附件仅摘录前缀，未保存其余字节；哈希不是内容备份")
        except UnicodeDecodeError:
            item.update(mode="reference", text="", note="非 UTF-8 文本，按需通过当前工作附件入口读取；未备份字节")
        except (OSError, StorageError):
            item.update(mode="missing", note="附件存储读取失败")
        items.append(item)
    settings = ProjectSettingsRepository(db)
    selected = set(task.knowledge_ids or [])
    if selected:
        candidates, visible = await settings.knowledge(user)
        linked = set(await settings.linked_ids(project.id))
        for kb_id in sorted(selected):
            if kb_id not in visible & linked:
                items.append(
                    dict(
                        kind="knowledge",
                        locator=kb_id,
                        text="",
                        mode="missing",
                        note="知识库当前无访问权限或未关联项目",
                    )
                )
            else:
                label = next((x.get("name", kb_id) for x in candidates if x["kb_id"] == kb_id), kb_id)
                items.append(
                    dict(
                        kind="knowledge", locator=kb_id, text=label, mode="reference", note="按需检索知识库，未读取正文"
                    )
                )
    for ref in await repo.list_references(task.id):
        items.append(
            dict(
                kind="url",
                locator=ref.url,
                text=ref.title or ref.url,
                mode="reference",
                note="网页仅 URL 引用，未抓取或验证",
            )
        )
    for item in items:
        excerpt = choices["excerpts"].get(f"{item['kind']}:{item['locator']}")
        if excerpt and item["mode"] == "direct" and item["kind"] != "requirements":
            item.update(text=excerpt, selection_mode="manual_excerpt", note=item["note"] + "；用户手动摘录")
    blocks = []
    remaining = TEXT_BUDGET
    for item in items:
        header = f"[{item['kind']} {item['locator']} · {item['mode']}] {item['note']}\n"
        separator = "\n\n" if blocks else ""
        block = separator + header + item["text"]
        if len(block) > remaining:
            if item["kind"] == "requirements":
                raise HTTPException(422, detail="工作要求超过资料预算，请精简后执行；不会截断必需要求")
            marker = "\n[资料受固定预算截断；其余内容未注入]"
            item.update(truncated=True, note=item["note"] + "；受固定预算截断")
            available = max(0, remaining - len(marker))
            block = block[:available] + marker if remaining >= len(marker) else ""
            item["injected_text"] = block
        else:
            item["injected_text"] = block
        blocks.append(block)
        remaining -= len(block)
    snapshot = dict(
        format_version=1,
        project_id=project.id,
        task_id=task.id,
        selection=choices,
        items=items,
        text_budget=TEXT_BUDGET,
        input_text="".join(blocks),
        knowledge_ids=sorted(selected),
    )
    snapshot["fingerprint"] = digest(json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode())
    if expected_fingerprint and snapshot["fingerprint"] != expected_fingerprint:
        raise HTTPException(
            409, detail={"code": "context_changed", "message": "预览后执行资料已变化，请刷新资料预览；选择仍可保留"}
        )
    snapshot["captured_at"] = format_utc_datetime(utc_now_naive())
    return snapshot


def digest(data):
    """计算明确字节范围的内容指纹。"""
    return hashlib.sha256(data).hexdigest()


def read_context_file(uid, project, path, limit, kind):
    """经过 Workdir no-follow 边界读取有界 UTF-8 文本。"""
    item = dict(kind=kind, locator=path, mode="direct", text="", note="受控读取项目文件")
    try:
        data, truncated = Workdir.open_existing(uid, project.workdir_path).read_file_prefix(path, limit)
        item.update(
            text=codecs.getincrementaldecoder("utf-8")().decode(data, final=not truncated),
            hash=digest(data),
            hash_scope="prefix" if truncated else "full",
            truncated=truncated,
        )
        if truncated:
            item["note"] = "文件仅摘录前缀，未保存其余字节；前缀哈希不是内容备份"
    except UnicodeDecodeError:
        item.update(mode="reference", note="非 UTF-8 文本，按需通过项目文件入口读取；未备份字节")
    except ValueError as exc:
        raise HTTPException(422, detail="文件路径须在当前项目目录内") from exc
    except (OSError, PermissionError):
        item.update(mode="missing", note="项目文件缺失或不可访问")
    return item


async def history_context(*, db, user, project_id, task_id, kind, record_id):
    """历史仅按真实执行 Owner 读取，旧行明确未记录。"""
    from yuxi.repositories.project_work_execution_repository import ProjectWorkExecutionRepository
    from yuxi.repositories.channel_delegation_repository import ChannelDelegationRepository

    await writable_project(db, user, project_id)
    await require_task(db, user, project_id, task_id)
    if kind == "execution":
        row = await ProjectWorkExecutionRepository(db).get_for_user(
            execution_id=record_id, project_id=project_id, uid=str(user.uid)
        )
    else:
        row = await ChannelDelegationRepository(db).get_by_operation_id(operation_id=record_id)
    if (
        row is None
        or row.project_id != project_id
        or getattr(row, "task_id", getattr(row, "work_task_id", None)) != task_id
    ):
        raise HTTPException(404, detail="执行资料不存在")
    return {
        "snapshot": row.context_snapshot,
        "message": "本次业务资料" if row.context_snapshot else "历史执行未记录完整业务资料，不推断补齐",
    }
