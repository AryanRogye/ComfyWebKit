#!/usr/bin/env python3
"""Exercise the in-place lifecycle in small disposable repositories."""
from pathlib import Path
import base64
import json
import shutil
import subprocess
import tempfile

SCRIPT = Path(__file__).with_name('patches.py')


def run(*args, cwd, ok=True, data=None):
    p = subprocess.run(args, cwd=cwd, input=data, capture_output=True)
    if (p.returncode == 0) != ok:
        raise AssertionError((args, p.returncode, p.stdout.decode(), p.stderr.decode()))
    return p.stdout


with tempfile.TemporaryDirectory(prefix='comfy-tests-') as tmp:
    root = Path(tmp)/'repo'
    root.mkdir()
    def g(*a, **kw):
        return run('git', *a, cwd=root, **kw)
    def tool(*a, **kw):
        return run('python3', str(root/'comfy-tools/patches.py'), *map(str,a), cwd=root, **kw)
    g('init','-b','main')
    g('config','user.name','Workflow Test')
    g('config','user.email','test@example.invalid')
    (root/'comfy-patches').mkdir()
    (root/'comfy-tools').mkdir()
    shutil.copy(SCRIPT, root/'comfy-tools/patches.py')
    shutil.copytree(SCRIPT.parent/'hooks', root/'comfy-tools/hooks')
    (root/'engine').write_text('one\ntwo\nthree\n')
    (root/'ReadMe.md').write_text('original docs\n')
    (root/'.gitignore').write_text('WebKitBuild/\nDerivedData/\n')
    g('add','.')
    g('commit','-m','base')
    base = g('rev-parse','HEAD').decode().strip()
    header = b'From: Workflow Test <test@example.invalid>\nSubject: [PATCH] first\n\n---\n'
    (root/'engine').write_text('ONE\ntwo\nthree\n')
    (root/'ReadMe.md').write_text('patched docs\n')
    patch = header + g('diff','--binary','--full-index')
    (root/'comfy-patches/0001-first.patch').write_bytes(patch)
    g('restore','engine','ReadMe.md')
    (root/'comfy-patches/base').write_text(base+'\n')
    (root/'comfy-patches/series').write_text('0001-first.patch\n')
    (root/'WebKitBuild').mkdir()
    (root/'WebKitBuild/artifact').write_bytes(b'keep-this-build')
    # Carry dirty workflow files and their staging through both branch switches.
    (root/'ReadMe.md').write_text('my uncommitted docs\n')
    g('add','ReadMe.md')
    (root/'ReadMe.md').write_text('my unstaged docs\n')
    docs_index = g('show',':ReadMe.md')
    (root/'engine').write_text('preexisting work\n')
    tool('setup',ok=False)
    assert (root/'engine').read_text() == 'preexisting work\n'
    (root/'engine').write_text('one\ntwo\nthree\n')
    tool('setup')
    first_branch = g('branch','--show-current')
    assert first_branch.startswith(b'comfy-dev/')
    assert (root/'engine').read_text() == 'ONE\ntwo\nthree\n'
    assert g('diff','HEAD','--','engine') == b''
    assert g('diff','--cached','--','engine') == b''
    assert g('show','HEAD:ReadMe.md') == b'original docs\n'
    assert g('rev-parse','HEAD').decode().strip() != base
    (root/'engine').write_text('ONE\nTWO\nthree\n')
    (root/'new-file').write_text('new\n')
    (root/'unrelated-file').write_text('leave this alone\n')
    tool('setup')
    assert (root/'engine').read_text() == 'ONE\nTWO\nthree\n'
    g('commit','-m','source must fail',ok=False)
    tool('finish','--subject','New feature','--add','new-file')
    assert g('branch','--show-current').strip() == b'main'
    assert (root/'engine').read_text() == 'one\ntwo\nthree\n'
    assert not (root/'new-file').exists()
    assert (root/'ReadMe.md').read_text() == 'my unstaged docs\n'
    assert g('show',':ReadMe.md') == docs_index
    assert (root/'unrelated-file').read_text() == 'leave this alone\n'
    assert (root/'WebKitBuild/artifact').read_bytes() == b'keep-this-build'
    assert (root/'comfy-patches/0001-first.patch').read_bytes() == patch
    tool('finish')
    tool('verify')
    tool('setup')
    assert g('branch','--show-current') != first_branch
    assert (root/'engine').read_text() == 'ONE\nTWO\nthree\n'
    assert (root/'new-file').read_text() == 'new\n'
    tool('finish')  # no extra edits must not append a patch
    assert len(list((root/'comfy-patches').glob('*.patch'))) == 2
    # Refresh an early patch and preserve its historical README hunk.
    tool('setup','--through','0001-first.patch')
    (root/'engine').write_text('ONE\ntwo\nTHREE\n')
    # The dependent patch's context includes line three: must fail safely.
    old = (root/'comfy-patches/0001-first.patch').read_bytes()
    tool('refresh','0001-first.patch',ok=False)
    assert (root/'engine').read_text() == 'ONE\ntwo\nTHREE\n'
    assert (root/'comfy-patches/0001-first.patch').read_bytes() == old
    # A change with sufficiently distant context can be refreshed independently.
    (root/'engine').write_text('ONE\ntwo\nthree\n')
    (root/'extra').write_text('extra\n')
    tool('refresh','0001-first.patch','--add','extra')
    assert b'diff --git a/ReadMe.md' in (root/'comfy-patches/0001-first.patch').read_bytes()
    tool('verify')
    tool('setup')
    assert (root/'extra').read_text() == 'extra\n'
    tool('finish')
    assert not (root/'extra').exists()
    # Simulate interruption after baseline ref advancement, before marking active.
    tool('setup')
    state_path = root/'.git/comfy-inplace.json'
    state = json.loads(state_path.read_text())
    state['phase'] = 'baselining'
    state_path.write_text(json.dumps(state))
    tool('setup')
    (root/'engine').write_text('ONE\nTWO\nrecovery-test\n')
    # Stop finish after it writes its durable transaction, before complete().
    code = ("import importlib.util,sys; "
            "s=importlib.util.spec_from_file_location('workflow',sys.argv[1]); "
            "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
            "m.complete=lambda state: None; "
            "sys.argv=['patches.py','finish','--subject','Recovery test']; m.main()")
    run('python3','-c',code,str(root/'comfy-tools/patches.py'),cwd=root)
    state = json.loads(state_path.read_text())
    assert state['phase'] == 'finishing'
    # Simulate a crash between patch and series writes (series() would now fail).
    (root/'comfy-patches'/state['patch']).write_bytes(base64.b64decode(state['candidate']))
    tool('finish')
    assert g('branch','--show-current').strip() == b'main'
    assert (root/'engine').read_text() == 'one\ntwo\nthree\n'
    tool('verify')
    # Simulate a crash after branch return but before recording completion.
    state = json.loads(state_path.read_text())
    state['phase'] = 'finishing'
    state_path.write_text(json.dumps(state))
    tool('finish')
    assert json.loads(state_path.read_text())['phase'] == 'done'
    # Upgrade a legacy active session without committing the user's staged edits.
    legacy_code = ("import importlib.util,sys; "
                   "s=importlib.util.spec_from_file_location('workflow',sys.argv[1]); "
                   "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                   "m.baseline=lambda state: (state.update(phase='active'),m.save(state)); "
                   "sys.argv=['patches.py','setup']; m.main()")
    run('python3','-c',legacy_code,str(root/'comfy-tools/patches.py'),cwd=root)
    assert g('rev-parse','HEAD').decode().strip() == base
    (root/'engine').write_text('legacy staged edit\n')
    g('add','engine')
    prior_index = g('write-tree')
    tool('setup')
    assert g('write-tree') == prior_index
    assert (root/'engine').read_text() == 'legacy staged edit\n'
    assert g('show','HEAD:engine') == b'ONE\nTWO\nrecovery-test\n'
    assert g('rev-parse','HEAD^').decode().strip() == base
    tool('abort')
    # Abort keeps the patch series intact and saves edits before branch return.
    tool('setup')
    baseline_head = g('rev-parse','HEAD').decode().strip()
    tool('guard','pre-push',data=f'refs/heads/main {baseline_head} refs/heads/main {"0"*40}\n'.encode(),ok=False)
    old_patches = {p.name:p.read_bytes() for p in (root/'comfy-patches').glob('*')}
    (root/'engine').write_text('ONE\nTWO\nabort-edit\n')
    (root/'abort-added').write_text('saved staged addition\n')
    (root/'abort-untracked').write_text('keep untracked in place\n')
    g('add','engine','abort-added')
    tool('abort')
    assert g('branch','--show-current').strip() == b'main'
    assert (root/'engine').read_text() == 'one\ntwo\nthree\n'
    assert not (root/'abort-added').exists()
    assert (root/'abort-untracked').read_text() == 'keep untracked in place\n'
    assert old_patches == {p.name:p.read_bytes() for p in (root/'comfy-patches').glob('*')}
    state = json.loads(state_path.read_text())
    recovery = root/'.git/comfy-aborted-sessions'/(state['branch'].replace('/','-')+'.patch')
    assert recovery.exists() and recovery.read_bytes()
    assert state['staged_tree']
    tool('abort')
    tool('setup')
    g('apply',str(recovery))
    assert (root/'engine').read_text() == 'ONE\nTWO\nabort-edit\n'
    assert (root/'abort-added').read_text() == 'saved staged addition\n'
    tool('abort')
    assert (root/'WebKitBuild/artifact').read_bytes() == b'keep-this-build'
    assert g('show',':ReadMe.md') == docs_index
    # Staged deletion must be restored from origin, even when no longer indexed.
    tool('setup')
    g('rm','-f','engine')
    tool('finish','--subject','Remove engine')
    assert (root/'engine').read_text() == 'one\ntwo\nthree\n'
    assert g('diff','--cached','--name-only','--','engine') == b''
    tool('setup')
    assert not (root/'engine').exists()
    tool('finish')
    assert (root/'engine').exists()
    assert list((root/'.git/comfy-session-history').glob('*.json'))
    export = Path(tmp)/'export'
    tool('export',export)
    tool('export',export)
    (export/'series').write_text('different')
    tool('export',export,ok=False)
    tool('guard','pre-push',data=f'refs/heads/comfy-build {base} refs/heads/main {"0"*40}\n'.encode(),ok=False)
    tool('guard','pre-push',data=f'refs/heads/main {base} refs/heads/main {"0"*40}\n'.encode())
    assert g('rev-parse','HEAD').decode().strip() == base
    assert g('worktree','list','--porcelain').count(b'worktree ') == 1
    print('PASS: clean local baselines, in-place setup/finish/abort and edit recovery, dirty reruns, create/refresh, conflicts, new files, staged docs, unrelated files, unchanged base/patch, retained branches/builds, interruption recovery, export and guards')
