"""Bundle this project's Python runtime and relocate non-system Mach-O libraries."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig

root=Path(sys.argv[1]).absolute()
source=Path(sys.base_prefix).resolve()
purelib=Path(sysconfig.get_path('purelib'))
identity=hashlib.sha256((sys.version+str(purelib)+str((purelib/'numpy').stat().st_mtime_ns)).encode()).hexdigest()
marker=root/'.negativemaster-runtime'
if marker.is_file() and marker.read_text()==identity:
    print('Bundled runtime is current.');sys.exit(0)
if root.exists():
    if not marker.exists():raise RuntimeError('Refusing to replace an unrecognized runtime folder')
    shutil.rmtree(root)
root.mkdir(parents=True)
marker.write_text('building')
version=f'{sys.version_info.major}.{sys.version_info.minor}'
(root/'bin').mkdir()
interpreter=source/'Resources'/'Python.app'/'Contents'/'MacOS'/'Python'
shutil.copy2(interpreter if interpreter.exists() else source/'bin'/('python'+version),root/'bin'/'python3')
shutil.copy2(source/'Python',root/'Python')
stdlib=root/'lib'/('python'+version)
shutil.copytree(source/'lib'/('python'+version),stdlib,symlinks=True,
                ignore=shutil.ignore_patterns('site-packages','__pycache__','test','tests','tkinter','idlelib','_tkinter*'))
shutil.copytree(purelib,stdlib/'site-packages',symlinks=True,
                ignore=shutil.ignore_patterns('__pycache__','tests','test','pip','pip-*','setuptools','setuptools-*'))

def macho(path):
    if path.is_symlink() or not path.is_file():return False
    with path.open('rb') as f:magic=f.read(4)
    return magic in (b'\xcf\xfa\xed\xfe',b'\xce\xfa\xed\xfe',b'\xca\xfe\xba\xbe',b'\xca\xfe\xba\xbf')

def deps(path):
    text=subprocess.check_output(['/usr/bin/otool','-L',str(path)],text=True)
    install_ids=subprocess.check_output(['/usr/bin/otool','-D',str(path)],text=True).splitlines()[1:]
    return [line.strip().split(' (')[0] for line in text.splitlines()[1:] if line.strip().split(' (')[0] not in install_ids]

binaries=[p for p in root.rglob('*') if macho(p)]
queue=list(binaries)
external=root/'lib'/'native';external.mkdir()
known={}
while queue:
    binary=queue.pop()
    for dependency in deps(binary):
        if not dependency.startswith('/') or dependency.startswith(('/usr/lib/','/System/Library/')):continue
        resolved=Path(dependency).resolve()
        if resolved==source/'Python':target=root/'Python'
        elif resolved.is_relative_to(source) and (root/resolved.relative_to(source)).exists():target=root/resolved.relative_to(source)
        elif resolved.is_relative_to(purelib.resolve()):target=stdlib/'site-packages'/resolved.relative_to(purelib.resolve())
        else:
            target=external/resolved.name
            if resolved.name in known and known[resolved.name]!=resolved:raise RuntimeError('Conflicting native library: '+str(resolved))
            known[resolved.name]=resolved
            if not target.exists():
                shutil.copy2(resolved,target);queue.append(target);binaries.append(target)
        relative='@loader_path/'+os.path.relpath(target,binary.parent)
        subprocess.run(['/usr/bin/install_name_tool','-change',dependency,relative,str(binary)],check=True,stderr=subprocess.PIPE)
# Re-sign every modified or copied Mach-O object, including extension modules.
for binary in binaries:
    subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(binary)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
# A self-contained import check, with no PATH/PYTHONPATH from the developer environment.
subprocess.run([str(root/'bin'/'python3'),'-c','import flask, numpy, PIL, rawpy, tifffile, imagecodecs, piexif; print("Bundled image runtime verified.")'],check=True,
               env={'PATH':'/usr/bin:/bin','PYTHONHOME':str(root),'PYTHONDONTWRITEBYTECODE':'1'})
marker.write_text(identity)
