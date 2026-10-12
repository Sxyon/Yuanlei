"""在指定临时目录校验并展开固定官方包，不执行安装脚本。"""
import base64
import concurrent.futures
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import urllib.request

root = Path(os.environ['S02_REUSE_DEPS']).resolve()
packages = ['vue', 'core', 'dev', 'i18n', 'inputs', 'observer', 'rules', 'themes', 'utils', 'validation']


def install(name):
    """按官方元数据校验包字节，并拒绝越界或链接成员。"""
    package = '@formkit/' + name
    url = 'https://registry.npmjs.org/' + package.replace('/', '%2f') + '/2.1.2'
    with urllib.request.urlopen(url, timeout=30) as response:
        metadata = json.load(response)
    with urllib.request.urlopen(metadata['dist']['tarball'], timeout=30) as response:
        blob = response.read()
    integrity = 'sha512-' + base64.b64encode(hashlib.sha512(blob).digest()).decode()
    if integrity != metadata['dist']['integrity']:
        raise ValueError('package_integrity_mismatch')
    target = root / 'node_modules' / package
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:gz') as archive:
        for member in archive.getmembers():
            path = Path(member.name)
            if path.parts[:1] != ('package',) or '..' in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError('package_member_denied')
            if member.isfile():
                destination = target.joinpath(*path.parts[1:])
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.extractfile(member).read())
    return {'name': package, 'version': metadata['version'], 'url': url, 'tarball': metadata['dist']['tarball'], 'integrity': integrity, 'dependencies': metadata.get('dependencies', {}), 'peerDependencies': metadata.get('peerDependencies', {})}


root.mkdir(parents=True, exist_ok=True)
(root / 'package.json').write_text('{"name":"s02-fixed-formkit-lab","private":true,"type":"module"}\n')
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
    result = list(pool.map(install, packages))
receipt = Path(__file__).resolve().parents[2] / 'reuse-packages.json'
receipt.write_text(json.dumps({'method': 'Official exact npm artifacts; SHA-512 verified; no lifecycle scripts; Vue supplied by existing host alias', 'packages': result}, indent=2) + '\n')
print(json.dumps(result, indent=2))
