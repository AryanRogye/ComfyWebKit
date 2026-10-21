#!/usr/bin/env python3
"""Ordered WebKit patches; source edits never require source commits."""
import argparse
import base64
import fcntl
import uuid
import contextlib
from email.utils import formatdate
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
PATCHES = ROOT / 'comfy-patches'
BASE = (PATCHES / 'base').read_text().strip()


def git(*args, cwd=ROOT, env=None, data=None):
    return subprocess.run(['git', *map(str, args)], cwd=cwd, env=env,
                          input=data, stdout=subprocess.PIPE, check=True).stdout


def fail(message):
    raise RuntimeError(message)


def series():
    names = (PATCHES / 'series').read_text().splitlines()
    if not names or len(names) != len(set(names)):
        fail('Empty or duplicate series')
    for name in names:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*\.patch', name):
            fail('Invalid patch name: ' + name)
        if not (PATCHES / name).is_file():
            fail('Missing patch: ' + name)
    if set(names) != {p.name for p in PATCHES.glob('*.patch')}:
        fail('series must list every .patch exactly once')
    return names


def fingerprint(names):
    return hashlib.sha256(b''.join(n.encode() + b'\0' + (PATCHES/n).read_bytes()
                                  for n in names)).hexdigest()


@contextlib.contextmanager
def index(tree, cwd=ROOT, seed=False):
    with tempfile.TemporaryDirectory(prefix='comfy-index-') as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp)/'index'))
        if seed:
            # Reuse stat data so unchanged WebKit files are not rehashed.
            # --reset affects this disposable index only; no -u/worktree update.
            actual = Path(git('rev-parse','--git-path','index',cwd=cwd).decode().strip())
            if not actual.is_absolute():
                actual = cwd/actual
            shutil.copyfile(actual, env['GIT_INDEX_FILE'])
            git('read-tree','--reset',tree,cwd=cwd,env=env)
        else:
            git('read-tree', tree, cwd=cwd, env=env)
        yield env


def tree(names, replacement=None):
    with index(BASE) as env:
        for name in names:
            content = replacement[1] if replacement and replacement[0] == name else (PATCHES/name).read_bytes()
            git('apply', '--cached', '--whitespace=nowarn', '-', env=env, data=content)
        return git('write-tree', env=env).decode().strip()


def atomic(path, content):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        f.write(content)
        temp = Path(f.name)
    temp.replace(path)


def allowed(path):
    return (path in {'ReadMe.md', 'README.md', '.gitignore', 'apply_patches.sh'}
            or path.startswith(('comfy-patches/', 'comfy-tools/')))


def guard(mode):
    if mode == 'pre-commit':
        paths = git('diff', '--cached', '--name-only', '--no-renames', '-z', cwd=Path.cwd()).decode().split('\0')
        if any(p and not allowed(p) for p in paths):
            fail('Source commits are disabled. Run ./apply_patches.sh to save edits as a patch.')
    else:
        for line in sys.stdin:
            local_ref, sha, remote_ref, remote_sha = line.split()
            if set(sha) == {'0'}:
                continue
            if remote_ref != 'refs/heads/main' or local_ref != 'refs/heads/main':
                fail('Only main -> main may be pushed; development, backup, detached refs and tags are local.')
            git('merge-base', '--is-ancestor', BASE, sha)
            # Inspect the complete post-snapshot history, including merges and new refs.
            for commit in git('rev-list', sha, '^'+BASE).decode().splitlines():
                paths = git('diff-tree', '--root', '-m', '--no-commit-id', '--name-only', '--no-renames', '-r', '-z', commit).decode().split('\0')
                if any(p and not allowed(p) for p in paths):
                    fail('Push contains upstream source changes: ' + commit)


def changed(before, after):
    return [p for p in git('diff', '--no-renames', '--name-only', '-z', before, after).decode().split('\0') if p]


def source_paths(before, after):
    return [p for p in changed(before, after) if not allowed(p)]


def source_diff(before, after):
    paths = source_paths(before, after)
    return git('--literal-pathspecs', 'diff', '--binary', '--full-index', before, after, '--', *paths) if paths else b''


def admin():
    return Path(git('rev-parse', '--absolute-git-dir').decode().strip())


def save(state):
    atomic(admin()/'comfy-inplace.json', (json.dumps(state, indent=2)+'\n').encode())


def read_state():
    path = admin()/'comfy-inplace.json'
    return json.loads(path.read_text()) if path.exists() else None


def branch():
    return git('symbolic-ref', '--quiet', '--short', 'HEAD').decode().strip()


def install_hooks():
    hooks = str(ROOT/'comfy-tools/hooks')
    current = subprocess.run(['git', 'config', '--get', 'core.hooksPath'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if current and current != hooks:
        fail('Existing core.hooksPath preserved; integrate hooks manually: ' + current)
    common = Path(git('rev-parse', '--git-common-dir').decode().strip())
    if not common.is_absolute():
        common = ROOT/common
    if any((common/'hooks'/h).exists() for h in ('pre-commit', 'pre-push')) and current != hooks:
        fail('Existing hooks preserved; integrate manually')
    git('config', '--local', 'core.hooksPath', hooks)


def snapshot(start, adds=()):
    with index(start, seed=True) as env:
        git('add', '-u', '--', '.', env=env)
        # Include explicitly staged new files, as well as --add arguments.
        staged = git('diff', '--cached', '--name-only', '--diff-filter=A', '-z', 'HEAD').decode().split('\0')
        for path in list(adds) + [p for p in staged if p and not allowed(p)]:
            target = (ROOT/path).absolute()
            relative = os.path.relpath(target, ROOT)
            if relative == '..' or relative.startswith('../') or target == ROOT or allowed(relative):
                fail('--add must name a source file inside this checkout')
            if not target.is_file() and not target.is_symlink():
                if path in adds:
                    fail('--add must name a file: ' + path)
                continue
            git('--literal-pathspecs', 'add', '--', relative, env=env)
        return git('write-tree', env=env).decode().strip()


def overlay(origin, patched):
    with index(origin) as env:
        diff = source_diff(BASE, patched)
        if diff:
            git('apply', '--cached', '--whitespace=nowarn', '-', env=env, data=diff)
        return git('write-tree', env=env).decode().strip()


def check_session(state):
    if branch() != state['branch'] or git('rev-parse', 'HEAD').decode().strip() != state['origin']:
        fail('Session branch or HEAD changed. Return to ' + state['branch'] + '; no files were restored.')


def setup(args, names):
    install_hooks()
    state = read_state()
    if state and state['phase'] != 'done':
        if state['fingerprint'] != fingerprint(names):
            fail('Patch series changed during this session; source edits preserved')
        if args.through and names[state['count']-1] != args.through:
            fail('Already editing at a different patch position; finish this session first')
        if state['phase'] == 'opening':
            # Resume an interruption immediately before/after switch or apply.
            head = git('rev-parse', 'HEAD').decode().strip()
            if head != state['origin'] or branch() not in (state['branch'],state['origin_branch']):
                fail('Interrupted setup: return to the original or session branch first')
            current = snapshot(state['origin'])
            is_applied = not source_paths(state['applied'], current)
            is_original = not source_paths(state['origin'], current)
            if not is_applied and not is_original:
                fail('Interrupted setup has additional source edits; recovery state preserved in .git')
            if branch() != state['branch']:
                exists = subprocess.run(['git','show-ref','--verify','--quiet','refs/heads/'+state['branch']],cwd=ROOT).returncode == 0
                if exists:
                    if git('rev-parse',state['branch']).decode().strip() != state['origin']:
                        fail('Interrupted session branch moved; refusing')
                    git('switch',state['branch'])
                else:
                    git('switch','-c',state['branch'])
            if not is_applied:
                diff = source_diff(state['origin'],state['applied'])
                subprocess.run(['git','update-index','--refresh'],cwd=ROOT,capture_output=True)
                if diff:
                    git('apply','--index','--whitespace=nowarn','-',data=diff)
            state['phase'] = 'active'
            save(state)
        check_session(state)
        if state['phase'] != 'active':
            fail('Finish was interrupted; rerun ./apply_patches.sh to resume it')
        print('Already set up here; source edits and WebKitBuild preserved.')
        return
    if state and state['phase'] == 'done':
        archive = admin()/'comfy-session-history'
        archive.mkdir(exist_ok=True)
        atomic(archive/(state['branch'].replace('/','-')+'.json'), (json.dumps(state,indent=2)+'\n').encode())
    origin_branch = branch()
    if origin_branch.startswith(('comfy-dev/', 'backup/')) or origin_branch == 'comfy-build':
        fail('Start setup on main or a publishing branch, not a historical development branch')
    origin = git('rev-parse', 'HEAD').decode().strip()
    git('merge-base', '--is-ancestor', BASE, origin)
    if source_paths(BASE, origin):
        fail('Publishing branch contains customized source; use a source-clean branch')
    # A session may carry dirty workflow files, but never unrelated source edits.
    working = snapshot(origin)
    if source_paths(origin, working) or source_paths(origin, git('write-tree').decode().strip()):
        fail('Uncommitted source edits already exist. Preserve them before setup; nothing was changed.')
    count = names.index(args.through)+1 if args.through else len(names)
    applied = overlay(origin, tree(names[:count]))
    diff = source_diff(origin, applied)
    # git apply --index checks both staged and working content and untracked collisions.
    if diff:
        # Refresh cached stat data after content-preserving local edits. Dirty
        # workflow files may make --refresh return 1; source checks above are strict.
        subprocess.run(['git','update-index','--refresh'], cwd=ROOT, capture_output=True)
        git('apply', '--check', '--index', '-', data=diff)
    dev = 'comfy-dev/' + uuid.uuid4().hex[:12]
    state = dict(phase='opening', branch=dev, origin_branch=origin_branch,
                 origin=origin, applied=applied, count=count, fingerprint=fingerprint(names))
    save(state)
    git('switch', '-c', dev)
    if diff:
        git('apply', '--index', '--whitespace=nowarn', '-', data=diff)
    state['phase'] = 'active'
    save(state)
    print('Patches applied in this directory on ' + dev + '. Build and edit here, then run ./apply_patches.sh.')


def finish(args, names):
    state = read_state()
    if not state or state['phase'] == 'done':
        print('No active session. Run python3 comfy-tools/patches.py setup to begin.')
        return
    if state['phase'] == 'finishing':
        return complete(state)
    check_session(state)
    if state['phase'] != 'active' or state['fingerprint'] != fingerprint(names):
        fail('Interrupted setup or changed patch series; local source preserved. Inspect ' + str(admin()/'comfy-inplace.json'))
    after = snapshot(state['applied'], args.add)
    # Only source enters patches; dirty docs, tooling, and index entries carry through.
    edit = source_diff(state['applied'], after)
    new_names = names[:]
    candidate = None
    name = None
    if edit:
        if args.refresh:
            if names[state['count']-1] != args.refresh:
                fail('Refresh requires setup --through ' + args.refresh)
            name = args.refresh
            before = overlay(state['origin'], tree(names[:state['count']-1]))
            raw = (PATCHES/name).read_bytes()
            marker = raw.find(b'\n---\n')
            first = raw.find(b'diff --git ')
            if marker < 0 or first < 0:
                fail('Missing format-patch header')
            # Retain historical documentation/ignore hunks verbatim.
            blocks = re.split(b'(?=^diff --git )', raw[first:], flags=re.M)
            metadata = b''.join(b for b in blocks if b.startswith(b'diff --git ') and allowed(b.split(b' b/', 1)[1].split(b'\n',1)[0].decode()))
            # The final block may contain the format-patch signature; Git ignores it.
            metadata = re.sub(rb'\n-- \n[^\n]*\n?$', b'\n', metadata)
            candidate = raw[:marker] + b'\n---\n' + metadata + source_diff(before, after)
        else:
            if state['count'] != len(names):
                fail('A prefix session must finish with --refresh PATCH_FILENAME')
            subject = args.subject or 'Local WebKit changes'
            if '\n' in subject or '\r' in subject:
                fail('Subject must be one line')
            number = max([int(m.group(1)) for n in names if (m := re.match(r'(\d+)-', n))] or [0])+1
            slug = re.sub(r'[^a-z0-9]+', '-', subject.lower()).strip('-')[:70] or 'local-changes'
            name = f'{number:04d}-{slug}.patch'
            if (PATCHES/name).exists():
                fail('Patch already exists: ' + name)
            author = git('var', 'GIT_AUTHOR_IDENT').decode().strip().rsplit(' ',2)[0]
            header = ('From '+'0'*40+' Mon Sep 17 00:00:00 2001\nFrom: '+author+'\nDate: '+formatdate(localtime=True)+'\nSubject: [PATCH] '+subject+'\n\n---\n').encode()
            candidate = header + edit
            new_names.append(name)
        # Verify the entire stack before saving anything or restoring source.
        tree(new_names, (name, candidate))
    elif args.refresh and names[state['count']-1] != args.refresh:
        fail('Refresh requires setup --through ' + args.refresh)
    # Durable transaction record contains the source tree, staged diff, and patch.
    # It precedes both patch writes and cleanup, so interrupted finish can resume.
    state.update(phase='finishing', after=after, patch=name,
                 candidate=base64.b64encode(candidate).decode() if candidate else None,
                 series=new_names,
                 previous_patch=base64.b64encode((PATCHES/name).read_bytes()).decode() if name and (PATCHES/name).exists() else None,
                 staged=base64.b64encode(git('diff','--cached','--binary','--full-index')).decode())
    save(state)
    complete(state)


def complete(state):
    if branch() == state['origin_branch'] and git('rev-parse','HEAD').decode().strip() == state['origin']:
        if source_paths(state['origin'], snapshot(state['origin'])):
            fail('Source changed after branch return; recovery state preserved')
        state['phase'] = 'done'
        save(state)
        print('Finish already restored source and returned to '+state['origin_branch']+'.')
        return
    check_session(state)
    if git('rev-parse', 'refs/heads/'+state['origin_branch']).decode().strip() != state['origin']:
        fail('Publishing branch moved during the session; source preserved')
    # Refuse to overwrite edits made after the saved transaction. Accept files
    # already restored by a previous interrupted finish, one path at a time.
    current = snapshot(state['after'])
    for path in source_paths(state['after'], current):
        if path in source_paths(state['origin'], current):
            fail('Source changed after finish started: ' + path + '; recovery snapshot preserved in .git')
    if state['candidate']:
        content = base64.b64decode(state['candidate'])
        dest = PATCHES/state['patch']
        if dest.exists() and dest.read_bytes() != content:
            if not state['previous_patch'] or dest.read_bytes() != base64.b64decode(state['previous_patch']):
                fail('Patch changed after finish started; refusing to overwrite it')
        atomic(dest, content)
        atomic(PATCHES/'series', ('\n'.join(state['series'])+'\n').encode())
    paths = sorted(set(source_paths(state['origin'], state['applied']) + source_paths(state['origin'], state['after'])))
    # New files must enter the index before restore can remove their working copy.
    indexed = set(git('ls-files', '-z').decode().split('\0'))
    for path in paths:
        if path not in indexed and ((ROOT/path).exists() or (ROOT/path).is_symlink()):
            git('--literal-pathspecs', 'add', '-N', '--', path)
    indexed = set(git('ls-files', '-z').decode().split('\0'))
    original = set(git('--literal-pathspecs','ls-tree','-r','--name-only','-z',state['origin'],'--',*paths).decode().split('\0')) if paths else set()
    paths = [p for p in paths if p in indexed or p in original]
    if paths:
        # Restore only the explicitly saved source delta. Workflow files and
        # ignored/untracked build outputs are never part of this path list.
        git('--literal-pathspecs', 'restore', '--source='+state['origin'], '--staged', '--worktree', '--', *paths)
    git('switch', state['origin_branch'])
    state['phase'] = 'done'
    save(state)
    print(('Saved '+state['patch']+'. ' if state['patch'] else 'No new source changes. ') +
          'Returned to '+state['origin_branch']+'; WebKitBuild and workflow edits preserved. Review and commit comfy-patches/.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    a = sub.add_parser('setup', help='Apply patches here on a fresh local branch')
    a.add_argument('--through', help='Stop at this patch for an existing-patch edit')
    a = sub.add_parser('finish', aliases=['create'], help='Save edits as a patch and return to publishing branch')
    a.add_argument('--subject', help='New patch subject (default: Local WebKit changes)')
    a.add_argument('--add', action='append', default=[], help='Include a new source file, relative to this checkout')
    a.add_argument('--refresh', help='Refresh the patch selected by setup --through')
    a = sub.add_parser('refresh', help='Save changes to the current prefix patch and return')
    a.add_argument('name')
    a.add_argument('--add', action='append', default=[])
    a = sub.add_parser('verify')
    a.add_argument('--against')
    a = sub.add_parser('export')
    a.add_argument('directory', type=Path)
    a = sub.add_parser('guard')
    a.add_argument('hook', choices=['pre-commit','pre-push'])
    args = p.parse_args()
    if args.command == 'guard':
        guard(args.hook)
        return
    # Serializes setup/finish/verification, including linked checkouts.
    with (admin()/'comfy-workflow.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail('Another patch command is running')
        state = read_state()
        if args.command in ('finish','create','refresh') and state and state['phase'] == 'finishing':
            complete(state)
            return
        if args.command == 'setup' and state and state['phase'] == 'finishing':
            fail('Finish was interrupted; rerun ./apply_patches.sh to resume it')
        names = series()
        if args.command == 'setup':
            setup(args, names)
        elif args.command in ('finish','create','refresh'):
            if args.command == 'refresh':
                args.refresh, args.subject = args.name, None
            finish(args, names)
        elif args.command == 'verify':
            result = tree(names)
            if args.against and source_paths(result, args.against):
                fail('Source mismatch against ' + args.against)
            print('Verified all patches. Tree: ' + result)
        else:
            tree(names)
            dest = args.directory.resolve()
            if dest == PATCHES.resolve() or dest.is_relative_to(ROOT):
                fail('Export outside this checkout to avoid mixing source and exports')
            dest.mkdir(parents=True, exist_ok=True)
            files = {n: (PATCHES/n).read_bytes() for n in names+['base','series']}
            if any((dest/n).exists() and (dest/n).read_bytes() != b for n,b in files.items()):
                fail('Export would overwrite differing files')
            for n,b in files.items():
                atomic(dest/n,b)
            print('Exported to ' + str(dest))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as e:
        print('error: '+str(e), file=sys.stderr)
        sys.exit(1)
