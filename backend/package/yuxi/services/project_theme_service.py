"""项目主题维护、发布、选择及真实加载的事务Owner。"""

import asyncio
import io
import hashlib
import json
import os
import re
import stat
import uuid
import zipfile
from pathlib import Path

from yuxi.repositories.project_repository import ProjectRepository
from yuxi.repositories.project_theme_repository import ProjectThemeRepository
from yuxi.services.project_theme_contract import ThemePackage
from yuxi.themes.packages import (
    MAX_EXPANDED_BYTES,
    MAX_IMAGE_PIXELS,
    MAX_MEMBER_BYTES,
    ThemeError,
    parse_package,
    validate_resource,
)
from yuxi.themes.store import ThemeStore
from yuxi.workspace.workdir import Workdir
from yuxi.workspace.errors import FileTransferLimitError


class ProjectThemeService:
    """每个用例重新授权来源与Project，持久修订拒绝旧写入。"""

    def __init__(self, db, uid: str, store: ThemeStore | None = None):
        """绑定当前用例的持久化或错误上下文。"""
        self.db, self.uid = db, str(uid)
        self.repo = ProjectThemeRepository(db)
        self.projects = ProjectRepository(db)
        self.store = store or ThemeStore()

    async def project(self, project_id: str, *, lock: bool = False):
        """真实Project可见性是文件及选择授权的前置条件。"""
        method = self.projects.lock_active_selectable_for_user if lock else self.projects.get_active_selectable_for_user
        project = await method(project_id, self.uid)
        if project is None:
            raise ThemeError("project_denied", "项目不存在或已无权访问", 404)
        return project

    async def source(self, source_id, project_id=None, *, lock=False, maintain=False, active=False):
        """来源查询fail-closed，摘要和作者声明不能授予权限。"""
        source = await self.repo.source(source_id, self.uid, project_id, lock=lock)
        if source is None:
            raise ThemeError("source_denied", "来源不存在或当前项目无权使用", 404)
        if maintain and source["kind"] == "builtin":
            raise ThemeError("builtin_readonly", "内置来源只读；请先复制为个人来源", 403)
        if source["status"] == "withdrawn" and not maintain:
            raise ThemeError("source_withdrawn", f"来源已安全撤回：{source['reason']}", 409)
        if active and source["status"] != "active":
            raise ThemeError("source_disabled", "来源已停用，无法新发布或新选择", 409)
        return source

    async def catalog(self, project_id=None):
        """目录返回有权来源、候选状态和不可变版本。"""
        if project_id:
            await self.project(project_id)
        sources = await self.repo.sources(self.uid, project_id)
        for source in sources:
            source["versions"] = await self.repo.versions(source["id"])
        return {"sources": sources}

    async def create(self, name, description, kind, project_id=None, copy_version_id=None, copy_project_id=None):
        """来源身份由服务生成，复制仅转移有权原包字节。"""
        if kind == "project":
            await self.project(project_id)
        elif project_id:
            raise ThemeError("source_scope", "个人来源不携项目归属")
        copied = None
        if copy_version_id:
            copied, _ = await self.version(copy_version_id, copy_project_id)
        source_id = str(uuid.uuid4())
        await self.repo.create(source_id, kind, self.uid, project_id, name, description, copy_version_id)
        # 文件写入前持久化身份，复制失败的残留仍有可授权的对账入口。
        await self.db.commit()
        if copied:
            try:
                await self.source(source_id, project_id, lock=True, maintain=True)
                await asyncio.to_thread(self.store.put, source_id, copied["raw"], copied["parsed"].digest)
                await self.repo.candidate(source_id, copied["parsed"].digest)
                await self.db.commit()
            except Exception as exc:
                await self.db.rollback()
                raise ThemeError(
                    "copy_incomplete", f"来源 {source_id} 已建立，候选复制未完成；请重新上传或维护对账", 500
                ) from exc
        return await self.source(source_id, project_id)

    async def candidate(self, source_id, project_id=None):
        """候选读取不影响发布版本或项目绑定。"""
        source = await self.source(source_id, project_id, maintain=True)
        if not source["candidate_digest"]:
            return {"source": source, "package": None}
        raw = await asyncio.to_thread(self.store.read, source_id, source["candidate_digest"])
        parsed = await asyncio.to_thread(parse_package, raw)
        return {"source": source, "package": self.dto(parsed, f"candidate:{source_id}:{source['candidate_revision']}")}

    async def candidate_resource(self, source_id, alias, expected_revision, project_id=None):
        """预览资源绑定到准确候选修订，旧资源请求明确拒绝。"""
        source = await self.source(source_id, project_id, lock=True, maintain=True)
        if source["candidate_revision"] != expected_revision:
            raise ThemeError("candidate_conflict", "预览候选已更新，请重新读取", 409)
        if not source["candidate_digest"]:
            raise ThemeError("candidate_missing", "没有可预览候选", 409)
        raw = await asyncio.to_thread(self.store.read, source_id, source["candidate_digest"])
        return await asyncio.to_thread(parse_package, raw)

    async def save_candidate(self, source_id, raw, expected_revision, project_id=None):
        """来源锁覆盖文件快照及PG引用提交；失败保留旧候选。"""
        source = await self.source(source_id, project_id, lock=True, maintain=True)
        if expected_revision != source["candidate_revision"]:
            raise ThemeError("candidate_conflict", "候选已被另一窗口更新，请重新读取", 409)
        parsed = await asyncio.to_thread(parse_package, raw)
        await asyncio.to_thread(self.store.put, source_id, raw, parsed.digest)
        await self.repo.candidate(source_id, parsed.digest)
        await self.db.commit()
        return await self.candidate(source_id, project_id)

    async def edit_candidate(self, source_id, definition, expected_revision, project_id=None):
        """编辑受控JSON，资源内容只通过替换候选ZIP改变。"""
        source = await self.source(source_id, project_id, lock=True, maintain=True)
        if expected_revision != source["candidate_revision"]:
            raise ThemeError("candidate_conflict", "候选已更新，请重新读取", 409)
        if not source["candidate_digest"]:
            raise ThemeError("candidate_missing", "请先上传或复制一个候选包", 409)
        raw = await asyncio.to_thread(self.store.read, source_id, source["candidate_digest"])
        original = await asyncio.to_thread(parse_package, raw)
        # 资源取自已校验原包，主题JSON不能补入任何文件系统路径。
        resources = {asset.path: original.assets[alias] for alias, asset in original.definition.manifest.assets.items()}
        try:
            model = ThemePackage.model_validate(definition)
        except ValueError as exc:
            raise ThemeError("package_contract", "编辑定义不符合契约，请检查manifest与theme字段") from exc
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                zipfile.ZipInfo("manifest.json", (2000, 1, 1, 0, 0, 0)),
                json.dumps(model.manifest.model_dump(), ensure_ascii=False).encode(),
                compress_type=zipfile.ZIP_DEFLATED,
            )
            archive.writestr(
                zipfile.ZipInfo("theme.json", (2000, 1, 1, 0, 0, 0)),
                json.dumps(model.theme.model_dump(), ensure_ascii=False).encode(),
                compress_type=zipfile.ZIP_DEFLATED,
            )
            for asset in model.manifest.assets.values():
                if asset.path not in resources:
                    raise ThemeError("asset_missing", "新资源需要通过替换候选ZIP提供")
                archive.writestr(
                    zipfile.ZipInfo(asset.path, (2000, 1, 1, 0, 0, 0)),
                    resources[asset.path],
                    compress_type=zipfile.ZIP_DEFLATED,
                )
        return await self.save_candidate(source_id, output.getvalue(), expected_revision, project_id)

    async def publish(self, source_id, expected_revision, project_id=None):
        """完整文件已存在后登记不可变版本，发布不更新项目选择。"""
        source = await self.source(source_id, project_id, lock=True, maintain=True, active=True)
        if expected_revision != source["candidate_revision"]:
            raise ThemeError("candidate_conflict", "候选已更新，请重新校验后发布", 409)
        if not source["candidate_digest"]:
            raise ThemeError("candidate_missing", "没有可发布候选", 409)
        raw = await asyncio.to_thread(self.store.read, source_id, source["candidate_digest"])
        parsed = await asyncio.to_thread(parse_package, raw)
        if len(parsed.definition.theme.version) > 160 or "\x00" in parsed.definition.theme.version:
            raise ThemeError("version_length", "版本标识超过160字符或包含NUL")
        for version in await self.repo.versions(source_id):
            if version["version"] == parsed.definition.theme.version:
                if version["digest"] != parsed.digest:
                    raise ThemeError("version_conflict", "同来源同版本已发布不同字节；请使用新版本", 409)
                await self.db.commit()
                return version
        # put幂等回读原字节；数据库提交失败只留下完整未引用快照。
        await asyncio.to_thread(self.store.put, source_id, raw, parsed.digest)
        version = await self.repo.publish(source_id, parsed, expected_revision, self.uid)
        await self.db.commit()
        return version

    async def version(self, version_id, project_id=None):
        """精确版本经来源授权后回读ZIP；停用保留既有读取。"""
        version = await self.repo.version(version_id)
        if version is None:
            raise ThemeError("version_missing", "发布版本不存在", 404)
        source = await self.source(version["source_id"], project_id, lock=True)
        if source["kind"] == "project":
            await self.project(project_id)
        raw = await asyncio.to_thread(self.store.read, source["id"], version["digest"])
        parsed = await asyncio.to_thread(parse_package, raw)
        if parsed.size != version["size"] or parsed.definition.theme.version != version["version"]:
            raise ThemeError("package_corrupt", "发布记录与包内容不一致", 409)
        return {"raw": raw, "parsed": parsed, "version": version}, source

    async def binding(self, project_id):
        """返回准确持久选择及其故障原因，始终保留原绑定。"""
        await self.project(project_id)
        binding = await self.repo.binding(project_id)
        if binding is None:
            return {"binding": None, "state": "unbound", "generation": 0, "package": None}
        try:
            loaded, source = await self.version(binding["version_id"], project_id)
            return {
                "binding": binding,
                "state": "ready",
                "generation": binding["generation"],
                "source": source,
                "version": loaded["version"],
                "package": self.dto(loaded["parsed"], loaded["version"]["id"]),
            }
        except ThemeError as exc:
            return {
                "binding": binding,
                "state": "error",
                "generation": binding["generation"],
                "error": {"code": exc.code, "message": exc.message},
                "package": None,
            }

    async def project_resource(self, project_id, expected_generation):
        """来源→Project锁后重查选择，拒绝等待期间已切换的资源请求。"""
        await self.project(project_id)
        bound = await self.repo.binding(project_id)
        if bound is None:
            raise ThemeError("binding_unbound", "当前项目尚未选择主题", 409)
        if bound["generation"] != expected_generation:
            raise ThemeError("binding_conflict", "项目主题选择已变化，请重新读取", 409)
        loaded, _ = await self.version(bound["version_id"], project_id)
        await self.project(project_id, lock=True)
        current = await self.repo.binding(project_id)
        if (
            current is None
            or current["generation"] != expected_generation
            or current["version_id"] != bound["version_id"]
        ):
            raise ThemeError("binding_conflict", "项目主题选择已变化，请重新读取", 409)
        return loaded["parsed"]

    async def project_file(self, project_id, expected_generation, alias):
        """固定当前绑定后读取声明文件，锁内保证选择与字节属于同一上下文。"""
        parsed = await self.project_resource(project_id, expected_generation)
        media = parsed.definition.manifest.files.get(alias)
        if media is None:
            raise ThemeError("file_alias", "当前版本未声明此项目文件alias", 404)
        bound = await self.repo.binding(project_id)
        path = bound["files"].get(alias)
        if path is None:
            raise ThemeError("file_unbound", "指定项目文件尚未绑定", 409)
        project = await self.project(project_id)
        raw = await asyncio.to_thread(self.read_project_file, project, path, media)
        return raw, media, hashlib.sha256(raw).hexdigest()

    @staticmethod
    def read_project_file(project, path, media):
        """复用Workdir逐段no-follow；明确区分缺失、边界与实际类型失败。"""
        try:
            workdir = Workdir.open_existing(str(project.uid), project.workdir_path)
            raw = workdir.read_file(path, MAX_MEMBER_BYTES)
            validate_resource(raw, media)
            return raw
        except FileNotFoundError as exc:
            raise ThemeError("file_missing", "指定项目文件不存在", 404) from exc
        except FileTransferLimitError as exc:
            raise ThemeError("file_limit", "指定项目文件超过8 MiB", 413) from exc
        except PermissionError as exc:
            raise ThemeError("file_denied", "指定项目文件无权读取", 403) from exc
        except (OSError, ValueError) as exc:
            raise ThemeError("file_boundary", "指定项目文件不在安全的普通文件边界或读取失败", 409) from exc

    async def selection_conditions(self, project_id, version_id, files, expected_generation):
        """预检和应用共用授权、锁、文件和并发边界，调用方决定是否写入。"""
        await self.project(project_id)
        loaded, _ = await self.version(version_id, project_id)
        await self.source(loaded["version"]["source_id"], project_id, active=True)
        project = await self.project(project_id, lock=True)
        current = await self.repo.binding(project_id)
        generation = current["generation"] if current else 0
        if expected_generation != generation:
            raise ThemeError("binding_conflict", "项目选择已被另一窗口更新，请重新读取后确认", 409)
        await asyncio.to_thread(self.validate_files, project, loaded["parsed"], files)
        return generation

    async def check(self, project_id, version_id, files, expected_generation):
        """只读解释可选条件，不保存任何启用状态；最终应用再次校验。"""
        await self.project(project_id)
        try:
            await self.selection_conditions(project_id, version_id, files, expected_generation)
            return {"selectable": True, "error": None}
        except ThemeError as exc:
            return {"selectable": False, "error": {"code": exc.code, "message": exc.message,
                                                    "alias": getattr(exc, "alias", None)}}

    async def select(self, project_id, version_id, files, expected_generation):
        """确认后在同一事务推进唯一绑定，预检结果不替代最终校验。"""
        generation = await self.selection_conditions(project_id, version_id, files, expected_generation)
        await self.repo.bind(project_id, version_id, files, generation + 1, self.uid)
        await self.db.commit()
        return await self.binding(project_id)

    @staticmethod
    def validate_files(project, parsed, files):
        """S04校验普通文件路径、类型和归属，S05复用同一边界读取。"""
        if set(files) != set(parsed.definition.manifest.files):
            raise ThemeError("file_mapping", "必须提供此版本声明的全部文件alias，且不能添加额外项")
        if not files:
            return
        try:
            workdir = Workdir.open_existing(str(project.uid), project.workdir_path)
        except (OSError, ValueError) as exc:
            raise ThemeError("file_boundary", "当前项目文件目录不可安全读取") from exc
        total_bytes, total_pixels = 0, 0
        for alias, media in parsed.definition.manifest.files.items():
            try:
                raw = workdir.read_file(files[alias], MAX_MEMBER_BYTES)
                total_bytes += len(raw)
                total_pixels += validate_resource(raw, media)
                if total_bytes > MAX_EXPANDED_BYTES or total_pixels > MAX_IMAGE_PIXELS:
                    raise ThemeError("file_binding_limit", "文件绑定校验超过总字节或解码预算", 413)
            except ThemeError as exc:
                exc.alias = alias
                raise
            except FileTransferLimitError as exc:
                error = ThemeError("file_limit", f"项目文件超过8 MiB：{alias}", 413)
                error.alias = alias
                raise error from exc
            except (OSError, ValueError) as exc:
                error = ThemeError("file_boundary", f"文件绑定不可读或不在当前项目普通文件边界：{alias}")
                error.alias = alias
                raise error from exc

    async def status(self, source_id, status, reason, project_id=None):
        """停用保留加载；撤回与恢复必须保存可追溯原因。"""
        source = await self.source(source_id, project_id, lock=True, maintain=True)
        if (status == "withdrawn" or source["status"] == "withdrawn") and not reason.strip():
            raise ThemeError("reason_required", "安全撤回及恢复撤回需要填写原因")
        await self.repo.change_status(source_id, status, reason.strip(), self.uid)
        await self.db.commit()
        return await self.source(source_id, project_id, maintain=True)

    async def audit(self, source_id, project_id=None, *, clean=False):
        """按需对账；来源锁内重查引用后只清理未引用普通文件。"""
        await self.source(source_id, project_id, lock=True, maintain=True)
        references = await self.repo.references(source_id)
        results = await asyncio.to_thread(self.audit_files, source_id, references, clean)
        await self.db.commit()
        return {"files": results, "history": await self.repo.history(source_id)}

    def audit_files(self, source_id, references, clean):
        """文件清理与所有候选／发布写入共享来源事务锁。"""
        try:
            fd = self.store.source_fd(source_id)
        except FileNotFoundError:
            return [{"digest": digest, "state": "missing"} for digest in sorted(references)]
        results, seen = [], set()
        try:
            for name in sorted(os.listdir(fd)):
                metadata = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if not stat.S_ISREG(metadata.st_mode):
                    results.append({"state": "unsafe_entry"})
                    continue
                match = re.fullmatch(r"([a-f0-9]{64})\.zip", name)
                if match:
                    digest = match[1]
                    seen.add(digest)
                    try:
                        raw = self.store.read(source_id, digest)
                        parse_package(raw)
                        state = "referenced" if digest in references else "orphan"
                    except ThemeError as exc:
                        state = exc.code
                    if clean and state == "orphan":
                        os.unlink(name, dir_fd=fd)
                        state = "removed_orphan"
                    results.append({"digest": digest, "state": state})
                elif name.startswith(".pending-"):
                    if clean:
                        os.unlink(name, dir_fd=fd)
                    results.append({"state": "removed_temporary" if clean else "temporary"})
            os.fsync(fd)
        finally:
            os.close(fd)
        results.extend({"digest": digest, "state": "missing"} for digest in sorted(references - seen))
        return results

    @staticmethod
    def dto(parsed, reference):
        """同一S03加载契约保留来源版本引用。"""
        return {**parsed.definition.model_dump(), "reference": reference, "digest": parsed.digest}


async def install_builtin_themes(db, store=None):
    """正式migrator登记平台内置包，既存来源和版本字节保持。"""
    store = store or ThemeStore()
    repo = ProjectThemeRepository(db)
    legacy = {"default", "research", "workspace-default", "workspace-research"}
    for filename in (
        "default", "research", "workspace-default", "workspace-research", "workspace-research-reading",
        "current-default", "current-focus", "current-research",
    ):
        raw = (Path(__file__).parents[1] / "themes" / "builtin" / f"{filename}.theme.zip").read_bytes()
        parsed = parse_package(raw)
        source_name = "workspace-research" if filename == "workspace-research-reading" else filename
        source_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"yuanlei:theme:builtin:{source_name}"))
        source = await repo.source(source_id, "", None, lock=True)
        if source is None:
            await repo.create(source_id, "builtin", None, None, parsed.definition.theme.name, "平台随版本发布的内置包")
        if source_name in legacy and (source is None or source["status"] == "active"):
            await repo.change_status(
                source_id, "disabled", "历史样例已退役；原版本和绑定保留，请显式选择当前主题。", None
            )
        versions = await repo.versions(source_id)
        existing = next((v for v in versions if v["version"] == parsed.definition.theme.version), None)
        if existing and existing["digest"] != parsed.digest:
            raise RuntimeError("内置主题同版本字节冲突，必须发布新版本")
        store.put(source_id, raw, parsed.digest)
        if existing is None:
            await repo.publish(source_id, parsed, 0, None)
    await db.commit()
