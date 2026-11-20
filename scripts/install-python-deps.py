"""Install pinned pure-Python wheels from PyPI with published SHA256 verification."""
from pathlib import Path
import hashlib,json,subprocess,sys,urllib.request
root=Path(__file__).resolve().parents[1]
cache=root/'.cache/wheels';cache.mkdir(parents=True,exist_ok=True)
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
paths=[]
for line in (root/'backend/requirements.txt').read_text(encoding='utf-8-sig').splitlines():
    line=line.strip()
    if not line or line.startswith('#'): continue
    name,version=line.split('==')
    with opener.open(f'https://pypi.org/pypi/{name}/{version}/json',timeout=20) as response: manifest=json.load(response)
    item=next(value for value in manifest['urls'] if value['filename'].endswith('none-any.whl'))
    target=cache/item['filename']
    if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest()!=item['digests']['sha256']:
        with opener.open(item['url'],timeout=30) as response: data=response.read()
        if hashlib.sha256(data).hexdigest()!=item['digests']['sha256']: raise RuntimeError('Dependency hash mismatch')
        target.write_bytes(data)
    paths.append(str(target))
python=root/'.venv'/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
raise SystemExit(subprocess.call([str(python),'-m','pip','install','--no-index','--no-deps',*paths],cwd=root))
