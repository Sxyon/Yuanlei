"""启动两个完全独立试验数据库/文件域并回读跨环境协议事实。"""
import base64
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[5]
ARTIFACT = HERE.parents[1]
STATE = Path('/tmp/yuanlei-s02-chain')
EVIDENCE = {}


def command(*args):
    """仅控制本试验命名的容器，不读取日常凭据。"""
    return subprocess.check_output(args, text=True).strip()


def request(env, path, method='GET', raw=None, value=None, actor=None, extra=None, status=200, reason=None):
    """核对真实HTTP正文和拒绝原因。"""
    headers = {'X-Lab-Actor': actor or 'lab-user-' + env.lower(), **(extra or {})}
    if value is not None:
        raw = json.dumps(value).encode()
        headers['Content-Type'] = 'application/json'
    url = 'http://127.0.0.1:' + ('5190' if env == 'A' else '5191') + path
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=raw, headers=headers, method=method), timeout=10) as response:
            code, content, received = response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as response:
        code, content, received = response.code, response.read(), dict(response.headers)
    assert code == status, (path, code, content)
    if reason:
        assert json.loads(content)['detail'] == reason, (path, content)
    return content, received


def json_request(env, path, **kwargs):
    """从协议正文核对业务结果，不依赖状态码单独判断。"""
    return json.loads(request(env, path, **kwargs)[0])


def archive(theme, abi=1, extra=None, duplicate=False, files=None, include_logo=True):
    """显式生成确定性合成主题包，资源和业务文件分开。"""
    manifest = {'format': 1, 'componentAbi': abi, 'theme': 'theme.json',
                'files': {'metrics': 'application/json', 'image': 'image/png', 'report': 'text/html', 'notes': 'text/markdown'},
                'assets': {'logo': 'assets/logo.png'}, 'source': 'S02 synthetic fixture; not agent-generated'}
    parts = {'manifest.json': json.dumps(manifest, ensure_ascii=False).encode(),
             'theme.json': json.dumps(theme, ensure_ascii=False).encode(),
             'assets/logo.png': (HERE.parent/'fixtures/sample.png').read_bytes(), **(extra or {})}
    if files is not None:
        manifest['files'] = files
    if not include_logo:
        manifest['assets'] = {}
        del parts['assets/logo.png']
    parts['manifest.json'] = json.dumps(manifest, ensure_ascii=False).encode()
    output = BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, blob in parts.items():
            info = zipfile.ZipInfo(name, (2026, 10, 12, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, blob)
        if duplicate:
            z.writestr('theme.json', parts['theme.json'])
    return output.getvalue()


def start(env):
    """独立文件卷、独立PG数据库、只暴露本机试验端口。"""
    folder = STATE / env
    folder.mkdir(parents=True, exist_ok=True)
    args = ['docker','run','-d','--rm','--name','yuanlei-s02-chain-'+env.lower(), '--network','yuanlei-s02-chain',
            '--user','0:0','--entrypoint','python','--workdir','/lab',
            '-p','127.0.0.1:'+('5190' if env=='A' else '5191')+':8000',
            '-e','LAB_ENV='+env,'-e','LAB_DB=postgresql://postgres@yuanlei-s02-chain-pg:5432/s02_'+env.lower(),
            '-e','YUXI_USER_DATA_DIR=/state/user-data','-e','YUXI_RUNTIME_DIR=/state/runtime','-e','PYTHONPATH=/research-owner',
            '-v',str(HERE)+':/lab:ro','-v',str(folder)+':/state',
            '-v',str(REPO/'backend/package')+':/research-owner:ro',
            '-v',str(HERE.parent/'fixtures')+':/fixtures:ro',
            'yuanlei-api:0.7.3','-m','uvicorn','api:app','--host','0.0.0.0','--port','8000']
    command(*args)
    for _ in range(40):
        try:
            value = json_request(env, '/_chain/schema')
            assert value['theme']['additionalProperties'] is False
            return
        except (urllib.error.URLError, ConnectionError):
            time.sleep(.25)
    raise RuntimeError('isolated_api_not_ready')


def mapping(env):
    """目标环境本地选择，映射不写入可携包。"""
    prefix = '/evidence/' if env == 'A' else '/different-location/'
    return {'metrics': prefix+'metrics.json','image':prefix+'sample.png','report':prefix+'report.html','notes':prefix+'notes.md'}


def pg(env, sql):
    """独立数据库回读是持久化结果的oracle。"""
    return command('docker','exec','yuanlei-s02-chain-pg','psql','-U','postgres','-d','s02_'+env.lower(),'-Atc',sql)


def main():
    """同一技术链路覆盖S03页面、S04保存、S05文件、S06异环境迁移。"""
    for attempt in range(40):
        if subprocess.run(['docker','exec','yuanlei-s02-chain-pg','pg_isready','-U','postgres'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:
            break
        time.sleep(.25)
    else:
        raise RuntimeError('isolated_postgres_not_ready')
    for env in ('A','B'):
        command('docker','exec','yuanlei-s02-chain-pg','createdb','-U','postgres','s02_'+env.lower())
        start(env)
    default = json.loads((HERE.parent/'themes/default.json').read_text())
    research = json.loads((HERE.parent/'themes/research.json').read_text())
    packages = {t['id']: archive(t) for t in (default, research)}
    digests = {key: sha256(raw).hexdigest() for key,raw in packages.items()}
    for key, raw in packages.items():
        result = json_request('A','/_chain/a-energy/import',method='POST',raw=raw)
        assert result['digest'] == digests[key] and result['state']=='imported_unbound'
    json_request('A','/_chain/a-energy/theme',status=409,reason='theme_unbound')
    json_request('A','/_chain/a-energy/selection',method='PUT',value={'digest':digests['default'],'files':mapping('A'),'expectedGeneration':0})
    before = json_request('A','/_chain/a-energy/theme')
    assert before['theme']['id']=='default' and before['generation']==1
    assert pg('A',"SELECT digest||':'||generation FROM yuanlei.lab_selection WHERE project='a-energy'")==digests['default']+':1'
    assert pg('A',"SELECT count(*) FROM yuanlei.lab_selection WHERE project='a-second'")=='0'
    EVIDENCE['pgReadback'] = {'digest':before['digest'],'generation':1,'sameWorkdirOtherProjectBound':False}
    updated = json.loads(json.dumps(default)); updated['version']='0.2-lab'; updated['pages'][0]['title']='Dashboard v2'
    revised = archive(updated)
    json_request('A','/_chain/a-energy/import',method='POST',raw=revised)
    assert json_request('A','/_chain/a-energy/theme')['digest']==digests['default']
    assert pg('A',"SELECT count(*) FROM yuanlei.lab_revisions WHERE project='a-energy' AND theme='default' AND version='0.2-lab' AND digest='"+sha256(revised).hexdigest()+"'")=='1'
    conflict = json.loads(json.dumps(default)); conflict['pages'][0]['title']='Different bytes, same version'
    json_request('A','/_chain/a-energy/import',method='POST',raw=archive(conflict),status=409,reason='version_content_conflict')
    assert json_request('A','/_chain/a-energy/theme')['digest']==digests['default']
    EVIDENCE['editing']={'newVersionStored':True,'activeVersionUnchanged':True,'sameVersionDifferentBytesRejected':True}
    json_request('A','/_chain/a-energy/theme',actor='lab-user-b',status=404,reason='project_denied')
    json_request('A','/_chain/a-energy/file/secret?generation=1',status=403,reason='file_not_declared')
    json_request('A','/_chain/a-energy/file/metrics?generation=1&path=../secret',status=403,reason='arbitrary_path_denied')
    json_request('A','/_chain/a-energy/file/metrics?generation=0',status=409,reason='stale_selection')
    json_request('A','/_chain/a-energy/selection',method='PUT',value={'digest':digests['research'],'files':mapping('A'),'expectedGeneration':0},status=409,reason='selection_conflict')
    json_request('A','/_chain/a-energy/selection',method='PUT',value={'digest':digests['research'],'files':{},'expectedGeneration':1},status=422,reason='binding_required')
    invalid = mapping('A'); invalid['metrics']='/../outside'
    json_request('A','/_chain/a-energy/selection',method='PUT',value={'digest':digests['research'],'files':invalid,'expectedGeneration':1},status=422,reason='file_boundary_or_type')
    target = STATE/'A/user-data/shared/lab-user-a/workspace/projects/a/evidence/metrics.json'
    saved = target.read_bytes(); target.unlink(); target.symlink_to('../evidence/sample.png')
    try:
        json_request('A','/_chain/a-energy/file/metrics?generation=1',status=422,reason='file_boundary_or_type')
    finally:
        target.unlink(); target.write_bytes(saved)
    EVIDENCE['negativeHttp']=['project_denied','file_not_declared','arbitrary_path_denied','stale_selection','selection_conflict','binding_required','file_boundary_or_type:path','file_boundary_or_type:symlink']
    for raw, reason in [(archive(default,abi=2),'package_contract'),(archive(default,extra={'../escape':b'x'}),'member_path'),(archive(default,duplicate=True),'duplicate_member')]:
        json_request('A','/_chain/a-energy/import',method='POST',raw=raw,status=422,reason=reason)
    bad = json.loads(json.dumps(default));bad['project_id']='a-energy'
    json_request('A','/_chain/a-energy/import',method='POST',raw=archive(bad),status=422,reason='package_contract')
    EVIDENCE['packageRejections']=['componentAbi:2','zip_path_traversal','duplicate_member','embedded_project_id']
    orphan = json.loads(json.dumps(default)); orphan['version']='0.3-lab'
    orphan_raw=archive(orphan); orphan_digest=sha256(orphan_raw).hexdigest()
    json_request('A','/_chain/a-energy/import',method='POST',raw=orphan_raw,extra={'X-Lab-Failpoint':'before-db'},status=503,reason='lab_before_db')
    assert pg('A',"SELECT count(*) FROM yuanlei.lab_revisions WHERE digest='"+orphan_digest+"'")=='0'
    assert (STATE/'A/theme-sources/blobs'/ (orphan_digest+'.zip')).is_file()
    json_request('A','/_chain/a-energy/import',method='POST',raw=orphan_raw)
    assert json_request('A','/_chain/a-energy/theme')==before
    EVIDENCE['publishFailure']={'blobWithoutDbReference':True,'retryReusedVerifiedBlob':True,'activeSelectionUnchanged':True}
    blob = STATE/'A/theme-sources/blobs'/ (digests['default']+'.zip'); original=blob.read_bytes();blob.chmod(0o644);blob.write_bytes(b'corrupt')
    try:
        json_request('A','/_chain/a-energy/theme',status=409,reason='package_integrity')
    finally:
        blob.write_bytes(original);blob.chmod(0o444)
    EVIDENCE['integrityRejected']=True
    command('docker','stop','yuanlei-s02-chain-a');start('A')
    assert json_request('A','/_chain/a-energy/theme')==before
    EVIDENCE['restart']={'sameDefinitionDigestGeneration':True,'postgresAndFileVolume':True}
    for key in ('default','research'):
        exported=request('A','/_chain/a-energy/export/'+digests[key])[0]
        assert exported==packages[key]
        with zipfile.ZipFile(BytesIO(exported)) as z:
            assert set(z.namelist())=={'manifest.json','theme.json','assets/logo.png'}
            for name in ('manifest.json','theme.json'):
                text=z.read(name).decode()
                assert all(s not in text for s in ['lab-user-a','a-energy','/evidence/','expectedGeneration','filesBinding'])
        imported=json_request('B','/_chain/b-energy/import',method='POST',raw=exported)
        assert imported['digest']==digests[key]
    json_request('B','/_chain/b-energy/theme',status=409,reason='theme_unbound')
    json_request('B','/_chain/a-energy/theme',status=404,reason='project_denied')
    json_request('B','/_chain/b-energy/selection',method='PUT',value={'digest':digests['research'],'files':mapping('A'),'expectedGeneration':0},status=422,reason='file_boundary_or_type')
    json_request('B','/_chain/b-energy/selection',method='PUT',value={'digest':digests['research'],'files':mapping('B'),'expectedGeneration':0})
    loaded=json_request('B','/_chain/b-energy/theme')
    assert loaded['digest']==digests['research'] and loaded['environment']=='B'
    content,headers=request('B','/_chain/b-energy/file/metrics?generation=1')
    assert json.loads(content)=={'environment':'B','samples':37} and {key.lower():value for key,value in headers.items()}['x-content-sha256']==sha256(content).hexdigest()
    assert pg('B',"SELECT files->>'metrics' FROM yuanlei.lab_selection WHERE project='b-energy'")=='/different-location/metrics.json'
    png=request('B','/_chain/b-energy/asset/logo')[0]; assert png==(HERE.parent/'fixtures/sample.png').read_bytes()
    EVIDENCE['migration']={'samePackageDigest':True,'identitiesBindingsNotExported':True,'importDoesNotActivate':True,'sourcePathRejected':True,'targetProject':'b-energy','targetFileSha256':sha256(content).hexdigest(),'targetFileData':json.loads(content),'packagedLogoByteMatch':True}
    minimal=json.loads(json.dumps(default));minimal['id']='system-only';minimal['pages']=[{'id':'overview','title':'Only project','blocks':[{'type':'summary','binding':'project','title':'Project'}]}]
    minimum=archive(minimal,files={},include_logo=False);minimum_digest=sha256(minimum).hexdigest()
    json_request('A','/_chain/a-second/import',method='POST',raw=minimum)
    json_request('A','/_chain/a-second/selection',method='PUT',value={'digest':minimum_digest,'files':{},'expectedGeneration':0})
    assert json_request('A','/_chain/a-second/theme')['manifest']['files']=={}
    EVIDENCE['optionalContent']={'systemOnlyThemeWithoutProjectFilesOrAssets':True}
    EVIDENCE['scope']='Real FastAPI/Pydantic/asyncpg/PostgreSQL16, immutable ZIP/files, current Workdir/no-follow, restart/export/import; synthetic header identity and business DTO; no production routes/schema/Agent/tool/backup/load test'
    EVIDENCE['digests']=digests
    (ARTIFACT/'chain-checks.json').write_text(json.dumps(EVIDENCE,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(EVIDENCE,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
