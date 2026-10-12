"""直接向贯通HTTP服务发送非法包/绑定，核对正确拒绝原因。"""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import stat
import zipfile
from run import archive, json_request, request, pg, HERE, ARTIFACT

value=json.loads((HERE.parent/'themes/default.json').read_text())
cases=[]
for label, mutate in [
    ('unknown_component',lambda t:t['pages'][0]['blocks'][0].update(type='script')),
    ('arbitrary_api',lambda t:t['pages'][0]['blocks'][0].update(url='https://example.invalid')),
    ('wrong_data_shape',lambda t:t['pages'][0]['blocks'][0].update(binding='topics')),
    ('duplicate_page',lambda t:t['pages'].append(deepcopy(t['pages'][0]))),
    ('unregistered_layout',lambda t:t.update(layout='js')),
]:
    target=deepcopy(value);mutate(target)
    json_request('A','/_chain/a-energy/import',method='POST',raw=archive(target),status=422,reason='package_contract');cases.append(label)
for label, raw, code, reason in [
    ('raw_size',b'x'*(2*1024*1024+1),413,'package_size'),
    ('member_count',archive(value,extra={f'bad-{i}':b'x' for i in range(13)}),413,'expanded_size'),
    ('expanded_size',archive(value,extra={'bad':b'x'*(2*1024*1024+1)}),413,'expanded_size'),
    ('not_zip',b'not a zip',422,'package_contract'),
]:
    json_request('A','/_chain/a-energy/import',method='POST',raw=raw,status=code,reason=reason);cases.append(label)
raw=archive(value);output=BytesIO()
with zipfile.ZipFile(BytesIO(raw)) as old, zipfile.ZipFile(output,'w') as new:
    for name in old.namelist():
        info=zipfile.ZipInfo(name);blob=old.read(name)
        if name=='assets/logo.png':info.external_attr=(stat.S_IFLNK|0o777)<<16;blob=b'/secret'
        new.writestr(info,blob)
json_request('A','/_chain/a-energy/import',method='POST',raw=output.getvalue(),status=422,reason='member_kind');cases.append('zip_symlink')
json_request('A','/_chain/a-energy/import',method='POST',raw=archive(value,files={}),status=422,reason='resource_contract');cases.append('required_file_missing')
raw=archive(value);output=BytesIO()
with zipfile.ZipFile(BytesIO(raw)) as old, zipfile.ZipFile(output,'w') as new:
    for name in old.namelist():
        blob=old.read(name)
        if name=='manifest.json':
            manifest=json.loads(blob);manifest['assets']['logo']='../outside.png';blob=json.dumps(manifest).encode()
        new.writestr(name,blob)
json_request('A','/_chain/a-energy/import',method='POST',raw=output.getvalue(),status=422,reason='resource_contract');cases.append('asset_manifest_path')
selected=json_request('A','/_chain/a-energy/theme')
json_request('A','/_chain/a-energy/asset/secret',status=403,reason='asset_not_declared');cases.append('undeclared_asset')
project_root=Path('/tmp/yuanlei-s02-chain/A/user-data/shared/lab-user-a/workspace/projects/a/evidence')
for name, invalid, label in [('sample.png',b'not a png','wrong_png'),('report.html',b'<html><script>alert(1)</script></html>','active_html'),('report.html',b'<html><a href="https://example.invalid">navigate</a></html>','html_external_navigation'),('metrics.json',b'not json','wrong_json'),('metrics.json',b'x'*(2*1024*1024+1),'file_size')]:
    target=project_root/name;saved=target.read_bytes();target.write_bytes(invalid)
    alias={'sample.png':'image','report.html':'report','metrics.json':'metrics'}[name]
    try:json_request('A',f"/_chain/a-energy/file/{alias}?generation={selected['generation']}",status=422,reason='file_boundary_or_type')
    finally:target.write_bytes(saved)
    cases.append(label)
assert json_request('A','/_chain/a-energy/theme')==selected
record={'cases':cases,'count':len(cases),'activeSelectionUnchanged':True,'scope':'Real isolated HTTP; synthetic identity; production endpoints not tested'}
(ARTIFACT/'chain-negative-checks.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record,indent=2))
