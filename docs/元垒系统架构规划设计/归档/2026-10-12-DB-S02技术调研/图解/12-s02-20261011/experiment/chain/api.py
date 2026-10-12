"""S02贯通可行性试验：真实HTTP/PG/包字节，身份与业务数据均为合成。"""
import asyncio
from contextlib import asynccontextmanager
from hashlib import sha256
from io import BytesIO
import json
import os
import re
from pathlib import Path
import shutil
import stat
from typing import Literal
import uuid
import zipfile

import asyncpg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from yuxi.workspace.workdir import Workdir
from yuxi.workspace.paths import user_workspace_dir
from yuxi.services.project_dashboard_service import _validate_static_page_html

ROOT = Path('/state/theme-sources')
ENV = os.environ['LAB_ENV']
OWNER = 'lab-user-' + ENV.lower()
PROJECT = ENV.lower() + '-energy'
LIMIT = 2 * 1024 * 1024
KINDS = {'metrics': 'application/json', 'image': 'image/png', 'report': 'text/html', 'notes': 'text/markdown'}

class Closed(BaseModel):
    """拒绝未知字段，保持生成输入有限。"""
    model_config = ConfigDict(extra='forbid', strict=True)

class Block(Closed):
    """声明可信组件及逻辑数据，不接受表达式和URL。"""
    type: Literal['summary', 'records', 'json', 'image', 'html', 'markdown']
    binding: Literal['project', 'topics', 'discussions', 'decisions', 'tasks', 'metrics', 'image', 'report', 'notes']
    title: str = Field(min_length=1, max_length=120)

    @model_validator(mode='after')
    def match_binding(self):
        """要求组件输入形状与数据类型一致。"""
        expected = {'summary': ['project'], 'records': ['topics', 'discussions', 'decisions', 'tasks'],
                    'json': ['metrics'], 'image': ['image'], 'html': ['report'], 'markdown': ['notes']}
        if self.binding not in expected[self.type]:
            raise ValueError('component_binding_mismatch')
        return self

class Page(Closed):
    """保存可返回的稳定页标识。"""
    id: str = Field(pattern=r'^[a-z][a-z0-9-]{0,39}$')
    title: str = Field(min_length=1, max_length=120)
    blocks: list[Block] = Field(min_length=1, max_length=12)

class Theme(Closed):
    """JSON定义只描述页面组织和显示名称。"""
    id: str = Field(pattern=r'^[a-z][a-z0-9-]{0,39}$')
    version: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    topicLabel: str = Field(min_length=1, max_length=40)
    layout: Literal['grid', 'reading']
    pages: list[Page] = Field(min_length=1, max_length=8)

    @model_validator(mode='after')
    def unique_pages(self):
        """重复页无法形成准确返回位置。"""
        if len({p.id for p in self.pages}) != len(self.pages):
            raise ValueError('duplicate_page')
        return self

class Manifest(Closed):
    """可携包仅含协议、资源需求及来源声明。"""
    format: Literal[1]
    componentAbi: Literal[1]
    theme: Literal['theme.json']
    files: dict[str, str]
    assets: dict[str, str]
    source: str = Field(min_length=1, max_length=120)

class Selection(Closed):
    """激活时显式绑定目标文件，项目由请求与后端决定。"""
    digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    files: dict[str, str]
    expectedGeneration: int = Field(ge=0)


def reject(code, reason):
    """使失败原因可由协议结果核对。"""
    raise HTTPException(code, reason)


def inspect_package(raw):
    """不解压到宿主路径；校验有限ZIP成员、模型及资源。"""
    if len(raw) > LIMIT:
        reject(413, 'package_size')
    try:
        with zipfile.ZipFile(BytesIO(raw)) as z:
            infos = z.infolist()
            if len(infos) > 12 or sum(i.file_size for i in infos) > LIMIT:
                reject(413, 'expanded_size')
            names = [i.filename for i in infos]
            if len(names) != len(set(names)):
                reject(422, 'duplicate_member')
            for i in infos:
                if i.flag_bits & 1 or stat.S_ISLNK(i.external_attr >> 16):
                    reject(422, 'member_kind')
                if i.filename not in {'manifest.json', 'theme.json'} and not re.fullmatch(r'assets/[a-z][a-z0-9_-]{0,39}\.png', i.filename):
                    reject(422, 'member_path')
            manifest = Manifest.model_validate_json(z.read('manifest.json'))
            theme = Theme.model_validate_json(z.read(manifest.theme))
            if any(KINDS.get(alias) != kind for alias, kind in manifest.files.items()):
                reject(422, 'resource_contract')
            needed = {block.binding for page in theme.pages for block in page.blocks if block.type in {'json','image','html','markdown'}}
            if not needed.issubset(manifest.files):
                reject(422, 'resource_contract')
            if any(not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}', alias) or not re.fullmatch(r'assets/[a-z][a-z0-9_-]{0,39}\.png', path) for alias, path in manifest.assets.items()):
                reject(422, 'resource_contract')
            if set(names) != {'manifest.json', 'theme.json', *manifest.assets.values()}:
                reject(422, 'missing_member')
            if any(not z.read(path).startswith(b'\x89PNG\r\n\x1a\n') for path in manifest.assets.values()):
                reject(422, 'asset_type')
            return manifest, theme
    except (zipfile.BadZipFile, KeyError, ValueError, ValidationError):
        reject(422, 'package_contract')


def read_blob(digest):
    """已发布包每次核对不可变字节，损坏不当作成功。"""
    path = ROOT / 'blobs' / (digest + '.zip')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            raw = os.read(fd, LIMIT + 1)
        finally:
            os.close(fd)
    except OSError:
        reject(409, 'package_unavailable')
    if sha256(raw).hexdigest() != digest:
        reject(409, 'package_integrity')
    return raw


def read_bound_file(workdir, path, kind):
    """直接使用当前仓库Workdir和全路径no-follow边界。"""
    try:
        raw = workdir.read_file(path, LIMIT)
        if kind == 'application/json':
            json.loads(raw)
        elif kind == 'image/png' and not raw.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('not_png')
        elif kind == 'text/html':
            _validate_static_page_html(raw.decode())
        elif kind == 'text/markdown':
            raw.decode()
        return raw
    except (OSError, ValueError):
        reject(422, 'file_boundary_or_type')


@asynccontextmanager
async def lifecycle(app):
    """连接独立试验数据库，并仅初始化自己的合成数据。"""
    ROOT.joinpath('blobs').mkdir(parents=True, exist_ok=True)
    pool = await asyncpg.create_pool(os.environ['LAB_DB'])
    app.state.pool = pool
    async with pool.acquire() as db:
        await db.execute('''CREATE SCHEMA IF NOT EXISTS yuanlei;
        CREATE TABLE IF NOT EXISTS yuanlei.lab_projects(id text PRIMARY KEY, owner text NOT NULL, workdir text NOT NULL);
        CREATE TABLE IF NOT EXISTS yuanlei.lab_revisions(project text NOT NULL REFERENCES yuanlei.lab_projects(id), digest text NOT NULL, theme text NOT NULL, version text NOT NULL, PRIMARY KEY(project,digest), UNIQUE(project,theme,version));
        CREATE TABLE IF NOT EXISTS yuanlei.lab_selection(project text PRIMARY KEY REFERENCES yuanlei.lab_projects(id), digest text NOT NULL, files jsonb NOT NULL, generation int NOT NULL, FOREIGN KEY(project,digest) REFERENCES yuanlei.lab_revisions(project,digest));''')
        await db.execute('INSERT INTO yuanlei.lab_projects VALUES($1,$2,$3) ON CONFLICT DO NOTHING', PROJECT, OWNER, 'projects/' + ENV.lower())
        await db.execute('INSERT INTO yuanlei.lab_projects VALUES($1,$2,$3) ON CONFLICT DO NOTHING', ENV.lower()+'-second', OWNER, 'projects/' + ENV.lower())
    directory = user_workspace_dir(OWNER) / 'projects' / ENV.lower()
    directory.mkdir(parents=True, exist_ok=True)
    # A/B目录和字节不同；包不能决定目标文件路径。
    prefix = 'evidence' if ENV == 'A' else 'different-location'
    files = directory / prefix
    files.mkdir(exist_ok=True)
    fixtures = Path('/fixtures')
    for name in ('sample.png', 'notes.md'):
        if not (files/name).exists():
            shutil.copyfile(fixtures/name, files/name)
    for name, content in {'metrics.json': json.dumps({'environment': ENV, 'samples': 24 if ENV == 'A' else 37}),
                          'report.html': '<!doctype html><html><body><h2>Static synthetic '+ENV+'</h2></body></html>'}.items():
        if not (files/name).exists():
            (files/name).write_text(content)
    yield
    await pool.close()

app = FastAPI(lifespan=lifecycle)


async def project_context(request, project):
    """合成身份字段仅用于试验，实际产品必须由认证依赖提供。"""
    actor = request.headers.get('x-lab-actor', '')
    row = await request.app.state.pool.fetchrow('SELECT * FROM yuanlei.lab_projects WHERE id=$1 AND owner=$2', project, actor)
    if row is None:
        reject(404, 'project_denied')
    return row


@app.get('/_chain/schema')
async def schema():
    """向生成端提供真实模型导出的JSON Schema。"""
    return {'manifest': Manifest.model_json_schema(), 'theme': Theme.model_json_schema()}


@app.post('/_chain/{project}/import')
async def import_package(project: str, request: Request):
    """先完整验证、独占写文件，再事务登记版本；不会隐式激活。"""
    await project_context(request, project)
    chunks = []
    length = 0
    async for chunk in request.stream():
        length += len(chunk)
        if length > LIMIT:
            reject(413, 'package_size')
        chunks.append(chunk)
    raw = b''.join(chunks)
    _, theme = inspect_package(raw)
    digest = sha256(raw).hexdigest()
    path = ROOT / 'blobs' / (digest + '.zip')
    temporary = ROOT / 'blobs' / ('.pending-' + uuid.uuid4().hex)
    try:
        with temporary.open('xb') as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        temporary.chmod(0o444)
        try:
            os.link(temporary, path)
        except FileExistsError:
            read_blob(digest)
        directory_fd = os.open(ROOT / 'blobs', os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)
    if request.headers.get('x-lab-failpoint') == 'before-db':
        reject(503, 'lab_before_db')
    # 文件先于PG提交；DB失败只可能留无引用文件，不会留下指向未完整文件的绑定。
    try:
        await request.app.state.pool.execute('INSERT INTO yuanlei.lab_revisions VALUES($1,$2,$3,$4) ON CONFLICT(project,digest) DO NOTHING', project, digest, theme.id, theme.version)
    except asyncpg.UniqueViolationError:
        reject(409, 'version_content_conflict')
    return {'digest': digest, 'state': 'imported_unbound', 'theme': theme.id, 'version': theme.version}


@app.get('/_chain/{project}/export/{digest}')
async def export_package(project: str, digest: str, request: Request):
    """下载已授权版本的原字节，不加入本地绑定。"""
    await project_context(request, project)
    if not await request.app.state.pool.fetchval('SELECT 1 FROM yuanlei.lab_revisions WHERE project=$1 AND digest=$2', project, digest):
        reject(404, 'revision_denied')
    return Response(read_blob(digest), media_type='application/zip')


@app.put('/_chain/{project}/selection')
async def select(project: str, payload: Selection, request: Request):
    """检查资源后在行锁事务内激活；旧代绑定请求不会覆盖新选择。"""
    row = await project_context(request, project)
    db = request.app.state.pool
    if not await db.fetchval('SELECT 1 FROM yuanlei.lab_revisions WHERE project=$1 AND digest=$2', project, payload.digest):
        reject(404, 'revision_denied')
    manifest, _ = inspect_package(read_blob(payload.digest))
    if set(payload.files) != set(manifest.files):
        reject(422, 'binding_required')
    workdir = Workdir.open_existing(row['owner'], row['workdir'])
    for alias, path in payload.files.items():
        read_bound_file(workdir, path, manifest.files[alias])
    async with db.acquire() as conn, conn.transaction():
        await conn.fetchrow('SELECT id FROM yuanlei.lab_projects WHERE id=$1 FOR UPDATE', project)
        old = await conn.fetchrow('SELECT generation FROM yuanlei.lab_selection WHERE project=$1', project)
        generation = old['generation'] if old else 0
        if generation != payload.expectedGeneration:
            reject(409, 'selection_conflict')
        await conn.execute('INSERT INTO yuanlei.lab_selection VALUES($1,$2,$3,$4) ON CONFLICT(project) DO UPDATE SET digest=$2, files=$3, generation=$4', project, payload.digest, json.dumps(payload.files), generation+1)
    return {'generation': generation+1, 'state': 'active'}


async def active(request, project):
    """没有选择或包损坏时显式失败，宿主仍可保留入口。"""
    row = await project_context(request, project)
    selected = await request.app.state.pool.fetchrow('SELECT * FROM yuanlei.lab_selection WHERE project=$1', project)
    if selected is None:
        reject(409, 'theme_unbound')
    return row, selected


@app.get('/_chain/{project}/theme')
async def theme_view(project: str, request: Request):
    """加载的是持久选择及校验后的包，而非内存模板。"""
    _, selected = await active(request, project)
    manifest, theme = inspect_package(read_blob(selected['digest']))
    return {'digest': selected['digest'], 'generation': selected['generation'], 'theme': theme.model_dump(), 'manifest': manifest.model_dump(), 'environment': ENV}


@app.get('/_chain/{project}/system')
async def system(project: str, request: Request):
    """合成业务DTO只用于检验宿主绑定，不冒充生产业务查询。"""
    await active(request, project)
    value = json.loads(Path('/fixtures/system.json').read_text())
    value['project'].update(id=project, name='Synthetic '+ENV+' · target project')
    value['topics'][0]['id'] = ENV.lower() + '-topic-1'
    return value


@app.get('/_chain/{project}/file/{alias}')
async def file_view(project: str, alias: str, request: Request):
    """只解析数据库本地绑定，调用真实Workdir读取路径。"""
    row, selected = await active(request, project)
    if set(request.query_params) - {'generation'}:
        reject(403, 'arbitrary_path_denied')
    if request.query_params.get('generation') != str(selected['generation']):
        reject(409, 'stale_selection')
    mappings = json.loads(selected['files'])
    if alias not in mappings:
        reject(403, 'file_not_declared')
    read_blob(selected['digest'])
    raw = read_bound_file(Workdir.open_existing(row['owner'], row['workdir']), mappings[alias], KINDS[alias])
    return Response(raw, media_type=KINDS[alias], headers={'X-Content-SHA256': sha256(raw).hexdigest()})


@app.get('/_chain/{project}/asset/{alias}')
async def asset_view(project: str, alias: str, request: Request):
    """包资源也通过项目授权读取，hash本身不授予访问权。"""
    _, selected = await active(request, project)
    raw = read_blob(selected['digest'])
    manifest, _ = inspect_package(raw)
    if alias not in manifest.assets:
        reject(403, 'asset_not_declared')
    with zipfile.ZipFile(BytesIO(raw)) as z:
        return Response(z.read(manifest.assets[alias]), media_type='image/png')


@app.get('/_chain/{project}/catalog')
async def catalog(project: str, request: Request):
    """列出当前项目真实登记的版本。"""
    await project_context(request, project)
    rows = await request.app.state.pool.fetch('SELECT digest, theme, version FROM yuanlei.lab_revisions WHERE project=$1 ORDER BY theme, version', project)
    return [dict(row) for row in rows]
