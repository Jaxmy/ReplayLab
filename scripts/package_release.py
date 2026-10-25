"""Build the portable release ZIP after setup.ps1 has prepared chart assets/VSIX."""
import argparse,hashlib,re,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def build(output=None):
    version=re.search(r"^VERSION='([^']+)'",(ROOT/'app/session.py').read_text('utf-8'),re.M)[1]
    target=Path(output) if output else ROOT/'dist'/f'Replay-Lab-v{version}-windows-x64.zip'
    extension=f'local-replay-lab-{version}.vsix'
    for p in (ROOT/'vscode'/extension,ROOT/'web/lightweight-charts.js'):
        if not p.is_file():raise ValueError('请先运行 setup.ps1 构建发布资源：'+p.name)
    roots=['app','config','docs','scripts','strategies','tests','vscode','web','vendor/akshare-decoder']
    files=[p for p in ROOT.iterdir() if p.is_file() and p.suffix in ('.md','.txt','.json','.ps1','.cmd')]
    files += [ROOT/'.gitignore',ROOT/'LICENSE',ROOT/'pytest.ini']
    for name in roots:
        files.extend(p for p in (ROOT/name).rglob('*') if p.is_file())
    selected=[]
    for p in files:
        rel=p.relative_to(ROOT)
        if any(part in ('node_modules','__pycache__','.pytest_cache','.git') for part in rel.parts):continue
        if p.suffix in ('.pyc','.pyo','.zip','.log'):continue
        if p.suffix=='.vsix' and p.name!=extension:continue
        if rel.parts[0]=='config' and not p.name.endswith('.example.json'):continue
        selected.append(p)
    target.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for p in sorted(set(selected)):archive.write(p,'ReplayLab/'+p.relative_to(ROOT).as_posix())
        for name in ('data','reports','sessions'):archive.writestr(f'ReplayLab/{name}/.gitkeep','')
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(target.suffix+'.sha256').write_text(f'{digest}  {target.name}\n','utf-8')
    return target,digest

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path)
    args=parser.parse_args();target,digest=build(args.output);print(target);print('SHA-256: '+digest)
