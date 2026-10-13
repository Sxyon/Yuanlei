"""项目主题HTTP适配，认证与有界上传在请求边界执行。"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from server.utils.auth_middleware import get_db, get_required_user
from yuxi.services.project_theme_service import ProjectThemeService
from yuxi.themes.packages import MAX_ARCHIVE_BYTES, ThemeError


class ThemeRoute(APIRoute):
    """将领域错误装配为有限、可公开的协议原因。"""

    def get_route_handler(self):
        """不向客户端输出宿主路径或数据库错误。"""
        handler = super().get_route_handler()

        async def handle(request):
            """真实请求调用用例并映射公开错误。"""
            received = 0

            async def limited_receive():
                """JSON编辑和ZIP上传都限制实际请求字节。"""
                nonlocal received
                event = await request.receive()
                received += len(event.get("body", b""))
                if received > MAX_ARCHIVE_BYTES:
                    raise ThemeError("archive_limit", "主题请求超过8 MiB", 413)
                return event

            try:
                return await handler(Request(request.scope, receive=limited_receive))
            except ThemeError as exc:
                raise HTTPException(exc.status, {"code": exc.code, "message": exc.message}) from exc
            except StarletteHTTPException as exc:
                # FastAPI把JSON读流异常包装为400，限额仍应由本边界明确报告413。
                failure = exc.__cause__
                if isinstance(failure, ThemeError):
                    raise HTTPException(failure.status, {"code": failure.code, "message": failure.message}) from failure
                raise

        return handle


project_themes = APIRouter(tags=["project-themes"], route_class=ThemeRoute)


def service(db=Depends(get_db), user=Depends(get_required_user)):
    """身份只取后端认证上下文。"""
    return ProjectThemeService(db, str(user.uid))


class ClosedInput(BaseModel):
    """拒绝客户端补入来源身份、owner及可信状态。"""

    model_config = ConfigDict(extra="forbid", strict=True)


class SourceCreate(ClosedInput):
    """建立个人或项目来源，可显式复制有权版本。"""

    name: str = Field(min_length=1, max_length=160, pattern=r"^[^\x00]+$")
    description: str = Field(default="", max_length=2000, pattern=r"^[^\x00]*$")
    kind: Literal["personal", "project"]
    project_id: str | None = Field(default=None, max_length=64)
    copy_version_id: str | None = Field(default=None, max_length=36)
    copy_project_id: str | None = Field(default=None, max_length=64)


class CandidateEdit(ClosedInput):
    """候选编排及持久修订条件。"""

    expected_revision: int = Field(ge=0)
    manifest: dict
    theme: dict


class RevisionInput(ClosedInput):
    """发布只能指定已保存候选修订。"""

    expected_revision: int = Field(ge=1)


class StatusInput(ClosedInput):
    """来源维护状态和公开原因。"""

    status: Literal["active", "disabled", "withdrawn"]
    reason: str = Field(default="", max_length=2000, pattern=r"^[^\x00]*$")


class SelectionInput(ClosedInput):
    """Project选择不携用户或可信来源字段。"""

    version_id: str = Field(min_length=1, max_length=36)
    expected_generation: int = Field(ge=0)
    files: dict[str, str]


@project_themes.get("/theme-sources")
async def catalog(project_id: str | None = None, svc=Depends(service)):
    """读取真实有权来源目录。"""
    return await svc.catalog(project_id)


@project_themes.post("/theme-sources")
async def create(body: SourceCreate, svc=Depends(service)):
    """建立服务生成身份的来源。"""
    return await svc.create(**body.model_dump())


@project_themes.get("/theme-sources/{source_id}/candidate")
async def candidate(source_id: str, project_id: str | None = None, svc=Depends(service)):
    """读取候选定义及revision。"""
    return await svc.candidate(source_id, project_id)


@project_themes.put("/theme-sources/{source_id}/candidate")
async def upload_candidate(
    request: Request,
    source_id: str,
    expected_revision: int = Query(ge=0),
    project_id: str | None = None,
    svc=Depends(service),
):
    """流式限制原ZIP，上传只保存候选，不发布或启用。"""
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_ARCHIVE_BYTES:
            raise ThemeError("archive_limit", "压缩包超过8 MiB", 413)
    return await svc.save_candidate(source_id, bytes(raw), expected_revision, project_id)


@project_themes.put("/theme-sources/{source_id}/definition")
async def edit_candidate(source_id: str, body: CandidateEdit, project_id: str | None = None, svc=Depends(service)):
    """编排编辑复用同一包契约。"""
    return await svc.edit_candidate(
        source_id, {"manifest": body.manifest, "theme": body.theme}, body.expected_revision, project_id
    )


@project_themes.post("/theme-sources/{source_id}/publish")
async def publish(source_id: str, body: RevisionInput, project_id: str | None = None, svc=Depends(service)):
    """发布完整不可变版本。"""
    return await svc.publish(source_id, body.expected_revision, project_id)


@project_themes.put("/theme-sources/{source_id}/status")
async def source_status(source_id: str, body: StatusInput, project_id: str | None = None, svc=Depends(service)):
    """维护状态及原因同事务留痕。"""
    return await svc.status(source_id, body.status, body.reason, project_id)


@project_themes.get("/theme-sources/{source_id}/audit")
async def audit(source_id: str, project_id: str | None = None, svc=Depends(service)):
    """按需只读对账及历史。"""
    return await svc.audit(source_id, project_id)


@project_themes.post("/theme-sources/{source_id}/cleanup")
async def cleanup(source_id: str, project_id: str | None = None, svc=Depends(service)):
    """来源锁内复查引用，仅清理未使用文件。"""
    return await svc.audit(source_id, project_id, clean=True)


@project_themes.get("/theme-versions/{version_id}")
async def version(version_id: str, project_id: str | None = None, svc=Depends(service)):
    """读取准确授权版本的S03加载DTO。"""
    loaded, _ = await svc.version(version_id, project_id)
    return svc.dto(loaded["parsed"], version_id)


@project_themes.get("/theme-versions/{version_id}/assets")
async def version_asset(version_id: str, alias: str, project_id: str | None = None, svc=Depends(service)):
    """读取声明alias资源；不接受URL或文件路径。"""
    loaded, _ = await svc.version(version_id, project_id)
    return asset_response(loaded["parsed"], alias)


@project_themes.get("/theme-sources/{source_id}/candidate/assets")
async def candidate_asset(
    source_id: str,
    alias: str,
    expected_revision: int = Query(ge=1),
    project_id: str | None = None,
    svc=Depends(service),
):
    """预览资源必须与候选修订一致。"""
    parsed = await svc.candidate_resource(source_id, alias, expected_revision, project_id)
    return asset_response(parsed, alias)


def asset_response(parsed, alias):
    """字节及metadata来自同一已校验包。"""
    asset = parsed.definition.manifest.assets.get(alias)
    if asset is None:
        raise ThemeError("asset_missing", "该版本未声明此资源", 404)
    raw = parsed.assets[alias]
    return Response(
        raw,
        media_type=asset.mediaType,
        headers={
            "Cache-Control": "no-store, private",
            "X-Content-Type-Options": "nosniff",
            "X-Theme-Sha256": asset.sha256,
            "X-Theme-Size": str(len(raw)),
        },
    )


@project_themes.get("/projects/{project_id}/theme")
async def binding(project_id: str, svc=Depends(service)):
    """故障仍返回准确原绑定与公开原因。"""
    return await svc.binding(project_id)


@project_themes.put("/projects/{project_id}/theme")
async def select(project_id: str, body: SelectionInput, svc=Depends(service)):
    """授权并以持久generation保存项目选择。"""
    return await svc.select(project_id, body.version_id, body.files, body.expected_generation)


@project_themes.get("/projects/{project_id}/theme/assets")
async def project_asset(project_id: str, alias: str, expected_generation: int = Query(ge=1), svc=Depends(service)):
    """每次重新授权Project及当前版本，旧选择资源请求明确拒绝。"""
    return asset_response(await svc.project_resource(project_id, expected_generation), alias)


@project_themes.get("/projects/{project_id}/theme/files")
async def project_file(
    project_id: str, request: Request, alias: str, expected_generation: int = Query(ge=1), svc=Depends(service)
):
    """仅接受绑定alias，浏览器不能补入路径或身份。"""
    if set(request.query_params) - {"alias", "expected_generation"}:
        raise ThemeError("file_query", "项目文件读取只接受alias与当前选择修订")
    raw, media, digest = await svc.project_file(project_id, expected_generation, alias)
    return Response(
        raw,
        media_type=media,
        headers={
            "Cache-Control": "no-store, private",
            "X-Content-Type-Options": "nosniff",
            "X-Theme-Sha256": digest,
            "X-Theme-Size": str(len(raw)),
        },
    )
