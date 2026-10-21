"""Local runtime shared by the Windows launcher, diagnostics and acceptance tests.

PowerShell does preparation only. This foreground supervisor owns the exclusive
socket, a gated Uvicorn worker and (Windows) a KILL_ON_JOB_CLOSE job. Probes and
browser checks never control the lifetime of the server. Only Ctrl+C, window
closure, explicit --check-only, or a dead worker end supervision.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import json
import ntpath
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
HOST = '127.0.0.1'
CHECKPOINTS = (0, 2, 10, 30, 60)
HEADERS = {'X-Framatex-Request': '1'}
SCRIPT = Path(__file__).resolve()
_JSON_LOCK = threading.Lock()


def data_dir():
    return Path(os.getenv('FRAMATEX_DATA_DIR', ROOT / 'data')).resolve()


def emit(message):
    print(message, flush=True)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return default


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    with _JSON_LOCK:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)


def parse_netstat(lines):
    """All listening sockets, IPv4/IPv6, independent of the Windows UI language."""
    listeners = []
    for line in lines:
        parts = line.split()
        if len(parts) != 5 or parts[0] != 'TCP' or parts[2] not in ('0.0.0.0:0', '[::]:0'):
            continue
        try:
            address, port = parts[1].rsplit(':', 1)
            listeners.append({'address': address, 'port': int(port), 'pid': int(parts[-1])})
        except ValueError:
            continue
    return listeners


def windows_snapshot():
    # Fixed command, no interpolated paths/passwords. One CIM query for the whole
    # process graph, rather than a slow query per PID. Bounded diagnostic cost.
    command = r"""$ErrorActionPreference='Stop'; [Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false); $p=@(Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine,CreationDate); ConvertTo-Json -Depth 3 -Compress -InputObject $p"""
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                            capture_output=True, timeout=8)
    if result.returncode:
        raise RuntimeError('Inventaire CIM impossible : aucun processus ne sera arrêté sans identification.')
    # PowerShell 5.1 redirected output uses the system OEM code page unless set.
    raw = result.stdout.decode('utf-8-sig', errors='replace')
    try:
        processes = json.loads(raw or '[]')
    except ValueError as exc:
        raise RuntimeError('Inventaire CIM illisible : nettoyage refusé.') from exc
    if isinstance(processes, dict):
        processes = [processes]
    netstat = subprocess.run(['netstat.exe', '-ano', '-p', 'tcp'], capture_output=True, timeout=4)
    if netstat.returncode:
        raise RuntimeError('Inventaire netstat impossible : sélection du port refusée.')
    listeners = parse_netstat(netstat.stdout.decode(errors='replace').splitlines())
    # Windows venvs often execute the *global* python.exe, and orphan reload
    # workers have only spawn_main in argv. Read their real cwd (not available in
    # CIM) to establish repository ownership. AccessDenied stays unknown/safe.
    import psutil
    listening = {item['pid'] for item in listeners}
    for process in processes:
        if not re.fullmatch(r'(pythonw?|py|uvicorn)[\d.]*\.exe', str(process.get('Name', '')), re.I):
            continue
        process['IsListener'] = int(process['ProcessId']) in listening
        try:
            process['WorkingDirectory'] = psutil.Process(int(process['ProcessId'])).cwd()
        except (psutil.Error, OSError):
            process['WorkingDirectory'] = None
    return {'processes': processes, 'listeners': listeners}


def repository_processes(processes, root=ROOT, exclude=()):
    """Return positively identified servers + their descendants, never generic
    python/uvicorn/spawn_main alone. ExecutablePath is often *global* Python on
    Windows venvs, so also inspect argv[0], the absolute runtime script and app-dir.
    Unknown/orphan processes without repo evidence are deliberately not killed.
    """
    repo = ntpath.normcase(ntpath.normpath(str(root)))
    rows = {int(p['ProcessId']): p for p in processes}
    excluded = set(exclude)
    owned = set()
    for pid, process in rows.items():
        if pid in excluded:
            continue
        command = ntpath.normcase(str(process.get('CommandLine') or '').replace('/', '\\'))
        exe = ntpath.normcase(str(process.get('ExecutablePath') or ''))
        name = str(process.get('Name') or '')
        python = re.fullmatch(r'(pythonw?|py|uvicorn)[\d.]*\.exe', name, re.I)
        cwd = ntpath.normcase(ntpath.normpath(process.get('WorkingDirectory') or ''))
        local_cwd = cwd == repo
        orphan_worker = local_cwd and process.get('IsListener') and 'spawn_main' in command
        server = ('uvicorn' in command and 'app.main:app' in command) or (
            repo + '\\scripts\\windows_runtime.py' in command and ('--worker' in command or ' serve' in command)) or orphan_worker
        venv = repo + '\\.venv\\scripts\\'
        # Exact path boundaries, not C:\\repo matching C:\\repo-other.
        local_python = any(venv + binary in command or exe == venv + binary
                           for binary in ('python.exe', 'pythonw.exe', 'uvicorn.exe'))
        app_dir = bool(re.search(r'--app-dir(?:\s+|=)["\']?' + re.escape(repo) + r'["\']?(?:\s|$)', command))
        runtime = bool(re.search(r'(?:^|[\s"\'])' + re.escape(repo + '\\scripts\\windows_runtime.py') + r'(?=[\s"\']|$)', command))
        if python and server and (local_python or app_dir or runtime or local_cwd):
            owned.add(pid)
    changed = True
    while changed:
        changed = False
        for pid, process in rows.items():
            parent = int(process.get('ParentProcessId') or 0)
            if pid in owned or pid in excluded or parent not in owned:
                continue
            # PID reuse: do not attach a process older than its supposed parent.
            created, parent_created = process.get('CreationDate'), rows[parent].get('CreationDate')
            if created and parent_created and str(created) < str(parent_created):
                continue
            owned.add(pid)
            changed = True
    return owned


def clean_repository_servers(snapshot_fn=windows_snapshot, stop_fn=None, timeout=12):
    before = snapshot_fn()
    # Never kill this launcher or one of its ancestors (CIM includes ourselves).
    parents = {int(p['ProcessId']): int(p.get('ParentProcessId') or 0) for p in before['processes']}
    excluded, current = set(), os.getpid()
    while current and current not in excluded:
        excluded.add(current)
        current = parents.get(current, 0)
    owned = repository_processes(before['processes'], exclude=excluded)
    roots = sorted(pid for pid in owned if parents.get(pid) not in owned)
    rows = {int(p['ProcessId']): p for p in before['processes']}
    for pid in roots:
        emit(f"Ancien FRAMATEX de ce dépôt : PID {pid}, parent {parents.get(pid)}, {rows[pid]['Name']} (arbre arrêté)")
        if stop_fn:
            stop_fn(pid)
        else:
            # Re-read and re-identify immediately before a destructive operation.
            fresh = snapshot_fn()
            same = next((p for p in fresh['processes'] if int(p['ProcessId']) == pid), None)
            if not same:
                continue
            if same.get('CreationDate') != rows[pid].get('CreationDate') or pid not in repository_processes(fresh['processes'], exclude=excluded):
                raise RuntimeError(f'Identité du PID {pid} changée : arrêt refusé.')
            killed = subprocess.run(['taskkill.exe', '/PID', str(pid), '/T', '/F'], capture_output=True, timeout=5)
            if killed.returncode:
                raise RuntimeError(f'Impossible d’arrêter l’ancien FRAMATEX PID {pid} (droits Windows).')
    deadline = time.monotonic() + timeout
    after = before
    while roots and time.monotonic() < deadline:
        after = snapshot_fn()
        remaining = repository_processes(after['processes'], exclude=excluded)
        stale_sockets = [s for s in after['listeners'] if s['pid'] in owned]
        if not remaining and not stale_sockets:
            break
        time.sleep(.2)
    else:
        if roots:
            raise RuntimeError('Ancien FRAMATEX ou socket encore actif : aucun basculement silencieux sur un autre port.')
    unknown = ambiguous_listeners(after, excluded)
    if unknown:
        raise RuntimeError(f'Processus Python en écoute non identifiables (PID {unknown}, cwd inaccessible). '
                           'Aucun arrêt et aucun basculement silencieux : relancez avec le compte Windows qui les a démarrés.')
    return {'before': before['listeners'], 'stopped_pids': sorted(owned), 'after_cleanup': after['listeners']}


def ambiguous_listeners(snapshot, excluded=()):
    listeners = {item['pid'] for item in snapshot['listeners']}
    return sorted(int(p['ProcessId']) for p in snapshot['processes']
                  if int(p['ProcessId']) in listeners - set(excluded)
                  and re.fullmatch(r'(pythonw?|py|uvicorn)[\d.]*\.exe', str(p.get('Name', '')), re.I)
                  and not p.get('WorkingDirectory'))


def reserve_port(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == 'nt':
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            # Linux TIME_WAIT reuse; an existing LISTEN socket still excludes us.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((HOST, port))
        sock.listen(128)
        return sock
    except OSError:
        sock.close()
        raise


def select_port(requested, listeners, reserve=reserve_port):
    if not 1 <= requested <= 65535:
        raise ValueError('Port attendu entre 1 et 65535.')
    for port in range(requested, min(requested + 20, 65535) + 1):
        owners = [s for s in listeners if s['port'] == port]
        if owners:
            emit(f"Port {port} occupé : PID {sorted({s['pid'] for s in owners})}, programmes non identifiés comme FRAMATEX de ce dépôt ; laissés intacts.")
            continue
        try:
            return port, reserve(port)
        except OSError as exc:
            emit(f'Port {port} non réservable exclusivement : {exc}')
    raise RuntimeError(f'Aucun port réservable entre {requested} et {min(requested + 20, 65535)}.')


class WindowsJob:
    """The supervisor alone holds this non-inheritable handle. No PowerShell event,
    GC-managed Process handle, redirected pipe or browser owns server lifetime.
    """
    def __init__(self, pid):
        self.handle = None
        if os.name != 'nt':
            return
        from ctypes import wintypes as w
        class Basic(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64), ('flags', w.DWORD),
                        ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t), ('active', w.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
        class Limits(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', ctypes.c_uint64 * 6), ('process_memory', ctypes.c_size_t),
                        ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateJobObjectW.argtypes, kernel.CreateJobObjectW.restype = [ctypes.c_void_p, w.LPCWSTR], w.HANDLE
        kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        kernel.SetInformationJobObject.restype = w.BOOL
        kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
        kernel.AssignProcessToJobObject.argtypes, kernel.AssignProcessToJobObject.restype = [w.HANDLE, w.HANDLE], w.BOOL
        kernel.IsProcessInJob.argtypes, kernel.IsProcessInJob.restype = [w.HANDLE, w.HANDLE, ctypes.POINTER(w.BOOL)], w.BOOL
        kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [w.HANDLE], w.BOOL
        self.kernel = kernel
        self.handle = kernel.CreateJobObjectW(None, None)
        limits = Limits(); limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try:
            if not self.handle or not kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise OSError(ctypes.get_last_error(), 'Job Windows impossible : démarrage refusé pour éviter un serveur orphelin.')
            self.attach(pid)
        except BaseException:
            self.close()
            raise

    def attach(self, pid):
        if os.name != 'nt':
            return
        from ctypes import wintypes as w
        process = self.kernel.OpenProcess(0x0100 | 0x0001 | 0x1000, False, pid)  # SET_QUOTA | TERMINATE | QUERY_LIMITED
        try:
            already = w.BOOL()
            if process and self.kernel.IsProcessInJob(process, self.handle, ctypes.byref(already)) and already.value:
                return  # redirector spawned Python after attachment: inherited job
            if not process or not self.kernel.AssignProcessToJobObject(self.handle, process):
                raise OSError(ctypes.get_last_error(), f'Impossible de rattacher le worker {pid} au Job Windows.')
        finally:
            if process:
                self.kernel.CloseHandle(process)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def start_worker(reservation, runtime_id, logs):
    """Transfer the *already reserved* socket, including on Windows. The venv
    redirector's PID can differ from Python's real PID; the gated worker reports
    its actual PID before WSADuplicateSocket, then waits for the socket payload.
    """
    handshake = logs / f'worker-{runtime_id}.pid'
    out_path, err_path = logs / f'uvicorn-{runtime_id}.out.log', logs / f'uvicorn-{runtime_id}.err.log'
    env = {**os.environ, 'FRAMATEX_RUNTIME_ID': runtime_id, 'PYTHONUNBUFFERED': '1', 'PYTHONIOENCODING': 'utf-8'}
    for name in ('FRAMATEX_SECRET_INPUT', 'FRAMATEX_DEMO_PASSWORD'):
        env.pop(name, None)
    options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {
        'start_new_session': True, 'pass_fds': (reservation.fileno(),)}
    server, job = None, None
    try:
        with out_path.open('wb') as out, err_path.open('wb') as err:
            server = subprocess.Popen([sys.executable, str(SCRIPT), '--worker', str(handshake)], cwd=ROOT, env=env,
                                      stdin=subprocess.PIPE, stdout=out, stderr=err, **options)
        job = WindowsJob(server.pid)
        deadline = time.monotonic() + 15
        worker_pid = None
        while worker_pid is None:
            if server.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('Worker non démarré : ' + err_path.read_text(encoding='utf-8', errors='replace')[-4000:])
            try:
                worker_pid = int(handshake.read_text(encoding='ascii'))
            except (OSError, ValueError):
                time.sleep(.05)
        if worker_pid != server.pid:
            # venv redirector may already have spawned Python *before* root job
            # assignment: explicitly attach the gated actual worker as well.
            job.attach(worker_pid)
        payload = {'socket': base64.b64encode(reservation.share(worker_pid)).decode('ascii')} if os.name == 'nt' else {'fd': reservation.fileno()}
        server.stdin.write(json.dumps(payload).encode('ascii') + b'\n')
        server.stdin.close()
        return server, job, worker_pid, out_path, err_path
    except BaseException:
        if server:
            stop_worker(server, job)
        raise
    finally:
        reservation.close()
        handshake.unlink(missing_ok=True)


def run_worker(handshake):
    Path(handshake).write_text(str(os.getpid()), encoding='ascii')
    payload = json.loads(sys.stdin.buffer.readline())
    sock = socket.fromshare(base64.b64decode(payload['socket'])) if os.name == 'nt' else socket.socket(fileno=payload['fd'])
    sys.path.insert(0, str(ROOT))
    import uvicorn
    config = uvicorn.Config('app.main:app', host=HOST, port=sock.getsockname()[1], reload=False, log_level='info')
    try:
        uvicorn.Server(config).run(sockets=[sock])
    finally:
        sock.close()


def stop_worker(server, job):
    if server.poll() is None:
        try:
            server.send_signal(signal.CTRL_BREAK_EVENT if os.name == 'nt' else signal.SIGINT)
            server.wait(timeout=8)
        except (OSError, subprocess.TimeoutExpired):
            if os.name != 'nt':
                try:
                    os.killpg(server.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif job:
                job.close()
            else:
                server.kill()
            server.wait(timeout=5)
    if job:
        job.close()


def health_sample(client, base, pid, runtime_id):
    start = time.monotonic()
    response = client.get(base + '/api/health')
    response.raise_for_status()
    value = response.json()
    if value.get('status') != 'ok' or value.get('pid') != pid or value.get('runtime_id') != runtime_id:
        raise RuntimeError('Une autre instance a répondu : PID/runtime_id différents.')
    elapsed = round(1000 * (time.monotonic() - start))
    if elapsed > 3000:
        raise RuntimeError(f'/api/health trop lent : {elapsed} ms')
    return {'pid': pid, 'status': response.status_code, 'ms': elapsed, 'listening': True}


def check_platform(base, client, email=None, password=None):
    checks = []
    assets = set()
    for path, marker in (('/', 'Choisissez votre espace'), ('/espace-client', '/assets/client/'), ('/espace-framatex', '/assets/app.js')):
        response = client.get(base + path)
        assert response.status_code == 200 and 'text/html' in response.headers.get('content-type', '') and marker in response.text, f'{path} invalide'
        assert response.headers.get('cache-control') == 'no-store', path
        assets.update(re.findall(r'(?:src|href)="(/assets/[^"?#]+\.(?:js|css)(?:\?[^"#]*)?)"', response.text))
        checks.append(path + ' 200')
    for asset in sorted(assets):
        response = client.get(base + asset)
        expected = ('text/javascript', 'application/javascript') if asset.split('?')[0].endswith('.js') else ('text/css',)
        assert response.status_code == 200 and response.headers.get('content-type', '').split(';')[0] in expected, f'Asset/MIME invalide : {asset}'
    checks.append(f'{len(assets)} assets et types MIME vérifiés')
    if email:
        assert password, 'Mot de passe admin requis : vérification non passée.'
        response = client.post(base + '/api/auth/login', json={'email': email, 'password': password}, headers=HEADERS)
        assert response.status_code == 200, f'POST /api/auth/login : {response.status_code}'
        response = client.get(base + '/api/auth/me')
        identity = response.json()
        assert response.status_code == 200 and identity.get('email') == email and identity.get('admin') is True and 'Administrateur' in identity.get('roles', []), 'Profil administrateur incorrect'
        assert client.get(base + '/espace-framatex').status_code == 200
        assert client.get(base + '/api/workspace/dashboard').status_code == 200
        assert client.post(base + '/api/auth/logout', headers=HEADERS).status_code == 200
        checks.append(f'{email} : POST login 200 / GET me Administrateur / page et dashboard avec session 200')
    return checks


def browser_executable():
    for candidate in (shutil.which('chromium'), shutil.which('google-chrome'), shutil.which('chrome'),
                      str(Path(os.getenv('PROGRAMFILES', 'C:/Program Files')) / 'Google/Chrome/Application/chrome.exe'),
                      str(Path(os.getenv('LOCALAPPDATA', 'C:/Users/Default/AppData/Local')) / 'Google/Chrome/Application/chrome.exe'),
                      str(Path(os.getenv('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe')):
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def browser_smoke(base, email, password):
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=browser_executable(), headless=True)
        try:
            page = browser.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/')
            expect(page.locator('a[href="/espace-client"]').first).to_be_visible()
            page.locator('a[href="/espace-client"]').first.click()
            expect(page.locator('a[href="#/inscription"]').first).to_be_visible()
            page.locator('a[href="#/connexion"]').first.click()
            expect(page.locator('#login-email')).to_be_visible()
            page.goto(base + '/espace-framatex')
            page.fill('#email', email); page.fill('#password', password)
            page.click('#login-form button[type=submit]')
            expect(page.locator('.ops-heading h1')).to_have_text('Tableau de bord', timeout=15000)
            expect(page.locator('.ops-kpi')).to_have_count(8)
            page.locator('.sidebar [data-view="launches"]').click()
            expect(page.locator('#ops-launch-results')).to_be_visible()
            assert not page.locator('.boot').count() and not errors, errors
            page.locator('#logout').click()
            expect(page.locator('#login-form')).to_be_visible()
        finally:
            browser.close()


def ensure_browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=browser_executable(), headless=True)
        browser.close()


def supervise(port=8000, demo_email=None, no_browser=False, check_only=False):
    import httpx
    secret = os.environ.pop('FRAMATEX_SECRET_INPUT', None)
    os.environ.pop('FRAMATEX_DEMO_PASSWORD', None)
    directory = data_dir(); logs = directory / 'logs'; logs.mkdir(parents=True, exist_ok=True)
    record_path = directory / 'runtime.json'
    runtime_id = secrets.token_hex(12)
    report = {'runtime_id': runtime_id, 'started_at': datetime.now(timezone.utc).isoformat(), 'checks': [],
              'health': [], 'errors': [], 'native_windows': os.name == 'nt', 'status': 'starting'}
    server = job = None
    stop = threading.Event()
    checkpoints_done = threading.Event()
    monitor = None
    try:
        cleanup = clean_repository_servers() if os.name == 'nt' else {
            'before': [], 'after_cleanup': [], 'stopped_pids': [], 'windows_inventory_not_applicable': True}
        report['processes'] = cleanup
        port, reserved = select_port(port, cleanup['after_cleanup'])
        base = f'http://{HOST}:{port}'
        emit(f'PORT CHOISI : {port} — URL UNIQUE : {base}/')
        server, job, worker_pid, out, err = start_worker(reserved, runtime_id, logs)
        report.update(host=HOST, port=port, url=base + '/', pid=worker_pid, supervisor_pid=os.getpid(), process_pid=server.pid,
                      stdout=str(out), stderr=str(err))
        deadline = time.monotonic() + 90
        with httpx.Client(timeout=3, trust_env=False) as client:
            while True:
                if server.poll() is not None:
                    raise RuntimeError('Uvicorn arrêté pendant le démarrage.')
                try:
                    health_sample(client, base, worker_pid, runtime_id)
                    break
                except (httpx.HTTPError, ValueError, RuntimeError):
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Aucune réponse de la bonne instance après 90 s.')
                    time.sleep(.2)
        epoch = time.monotonic()
        report['status'] = 'checking'
        write_json(record_path, report)

        def watch_health():
            with httpx.Client(timeout=3, trust_env=False) as probe:
                for offset in CHECKPOINTS:
                    if stop.wait(max(0, epoch + offset - time.monotonic())):
                        return
                    try:
                        assert server.poll() is None, 'Processus Uvicorn arrêté'
                        sample = health_sample(probe, base, worker_pid, runtime_id)
                        # A successful HTTP response proves LISTEN on this exact
                        # instance; Windows additionally records all socket owners.
                        if os.name == 'nt':
                            listeners = windows_snapshot()['listeners']
                            assert any(s['port'] == port and s['pid'] in (worker_pid, server.pid) for s in listeners), 'Socket LISTENING absent'
                        sample.update(at=offset, elapsed=round(time.monotonic() - epoch, 2), ok=True)
                        report['health'].append(sample)
                        emit(f"T+{offset:02d}s : PID {worker_pid} identique, LISTENING, /api/health 200 ({sample['ms']} ms)")
                    except Exception as exc:
                        report['health'].append({'at': offset, 'ok': False, 'error': str(exc)})
                        report['errors'].append(f'T+{offset}s : {exc}')
                        emit(f'ÉCHEC T+{offset}s : {exc} — le serveur reste supervisé.')
                    if stop.is_set():
                        return
                    write_json(record_path, report)
                checkpoints_done.set()
                # Startup proof is not a permanent health certificate. Keep
                # supervising HTTP after T+60 without coupling failures to kill.
                while not stop.wait(15):
                    try:
                        sample = health_sample(probe, base, worker_pid, runtime_id)
                        report['latest_health'] = {**sample, 'ok': True, 'elapsed': round(time.monotonic() - epoch, 2)}
                    except Exception as exc:
                        report['status'] = 'degraded'
                        report['latest_health'] = {'ok': False, 'error': str(exc)}
                        report['errors'].append(f'Surveillance continue : {exc}')
                        emit(f'ÉCHEC de santé après T+60 : {exc}. Serveur laissé actif pour diagnostic.')
                    if stop.is_set():
                        return
                    write_json(record_path, report)

        monitor = threading.Thread(target=watch_health, name='framat-health', daemon=True)
        monitor.start()
        try:
            with httpx.Client(timeout=5, trust_env=False) as client:
                report['checks'].extend(check_platform(base, client, demo_email, secret))
            if demo_email:
                browser_smoke(base, demo_email, secret)
                report['checks'].append('Chromium : Client interactif, login admin, dashboard et commandes interactifs')
            emit('Pages, assets et contrôles initiaux terminés ; surveillance en cours (pas encore de succès T+60).')
        except Exception as exc:
            # Playwright action traces can contain fill() arguments: never log
            # a password even when the browser fails while filling the login.
            detail = str(exc).replace(secret, '[masqué]') if secret else str(exc)
            report['errors'].append(f'Contrôle initial : {type(exc).__name__}: {detail}')
            emit(f'ÉCHEC de vérification : {detail}. Le serveur reste actif ; voir les journaux.')
        finally:
            secret = None
        if not no_browser:
            try:
                import webbrowser
                if not webbrowser.open(base + '/'):
                    raise RuntimeError('Navigateur non disponible')
            except Exception as exc:
                emit(f'Ouverture facultative impossible : {exc}. Ouvrez {base}/ ; serveur inchangé.')
        emit(f'FRAMATEX : {base}/ — laisser cette fenêtre ouverte. Ctrl+C = arrêt volontaire.')
        announced = False
        while server.poll() is None:
            if (checkpoints_done.is_set() or not monitor.is_alive()) and not announced:
                announced = True
                good = len(report['health']) == len(CHECKPOINTS) and all(s['ok'] for s in report['health']) and not report['errors']
                report['status'] = 'ready' if good else 'degraded'
                write_json(record_path, report)
                emit('T+60 : toutes les vérifications exécutées sont passées, serveur toujours actif.' if good else 'VÉRIFICATIONS EN ÉCHEC : aucun succès global annoncé. Serveur laissé actif pour diagnostic.')
                if check_only:
                    return 0 if good else 1
            stop.wait(.2)
        raise RuntimeError(f'Uvicorn s’est arrêté de lui-même (code {server.returncode}).')
    except KeyboardInterrupt:
        emit('Ctrl+C : arrêt volontaire de FRAMATEX.')
        return 0
    except Exception as exc:
        report['status'] = 'failed'; report['errors'].append(str(exc))
        emit(f'ÉCHEC : {exc}')
        if report.get('stderr'):
            emit('Vraie sortie stderr Uvicorn :\n' + Path(report['stderr']).read_text(encoding='utf-8', errors='replace')[-12000:])
        return 1
    finally:
        stop.set()
        if monitor:
            monitor.join(timeout=13)
        if server:
            stop_worker(server, job)
        report['stopped_at'] = datetime.now(timezone.utc).isoformat()
        if os.name == 'nt':
            try:
                report['processes_after'] = windows_snapshot()['listeners']
            except Exception as exc:
                report['errors'].append(f'Inventaire final : {exc}')
        write_json(logs / f'runtime-{runtime_id}.json', report)
        if read_json(record_path, {}).get('runtime_id') == runtime_id:
            record_path.unlink(missing_ok=True)
        emit(f'Rapport : {logs / ("runtime-" + runtime_id + ".json")}')


def diagnose():
    """Read-only; deliberately does not import app.core (it creates data/secrets)."""
    import httpx
    for label, command in (('branche', ['git', 'branch', '--show-current']), ('commit', ['git', 'rev-parse', 'HEAD'])):
        try:
            value = subprocess.check_output(command, cwd=ROOT, timeout=2, text=True).strip()
        except (OSError, subprocess.SubprocessError):
            value = 'indisponible'
        emit(f'{label} : {value}')
    emit(f'Python : {sys.version.split()[0]} ({sys.executable})')
    database_url = os.getenv('DATABASE_URL', '')
    database = Path(database_url.removeprefix('sqlite:///')) if database_url.startswith('sqlite:///') else data_dir() / 'framat.db'
    emit(f'DB : {database if not database_url or database_url.startswith("sqlite:///") else "externe (URL masquée)"}')
    if (not database_url or database_url.startswith('sqlite:///')) and database.exists():
        try:
            with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True, timeout=1) as connection:
                revisions = [row[0] for row in connection.execute('SELECT version FROM schema_migrations ORDER BY version')]
            emit('Migrations appliquées (lecture seule) : ' + ', '.join(revisions))
        except sqlite3.Error as exc:
            emit(f'Migrations : {exc}')
    else:
        emit('Migrations : DB absente ou externe, aucune création / migration effectuée.')
    runtime = read_json(data_dir() / 'runtime.json', {})
    listeners = []
    if os.name == 'nt':
        try:
            snapshot = windows_snapshot(); listeners = snapshot['listeners']
            owned = repository_processes(snapshot['processes'])
            emit(f'Anciens/actuels processus FRAMATEX identifiés : {sorted(owned)}')
            emit('Ports/PID : ' + json.dumps([s for s in listeners if s['pid'] in owned or 8000 <= s['port'] <= 8020]))
        except Exception as exc:
            emit(f'Ports/PID : inventaire impossible ({type(exc).__name__}), aucun arrêt effectué.')
    port = runtime.get('port', 8000)
    emit(f'Port actuel déclaré : {port}, PID : {runtime.get("pid", "inconnu")}')
    base = f'http://{HOST}:{port}'  # never contact an arbitrary URL from a stale record
    try:
        with httpx.Client(timeout=2, trust_env=False) as client:
            response = client.get(base + '/api/health')
            identity = response.json()
        verified = response.status_code == 200 and runtime.get('runtime_id') and identity.get('runtime_id') == runtime['runtime_id'] and identity.get('pid') == runtime.get('pid')
        emit(f'/api/health : {response.status_code}, identité vérifiée : {bool(verified)}')
    except (httpx.HTTPError, ValueError) as exc:
        emit(f'/api/health : indisponible ({type(exc).__name__})')
    emit(f'URL finale déclarée (ne prouve pas la disponibilité) : {base}/')
    return 0


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--worker':
        run_worker(sys.argv[2]); return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('serve', 'cleanup', 'diagnose', 'browser-deps'))
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--demo-email')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    if args.command == 'diagnose':
        return diagnose()
    if args.command == 'cleanup':
        if os.name == 'nt':
            clean_repository_servers()
        return 0
    if args.command == 'browser-deps':
        try:
            ensure_browser()
        except Exception:
            subprocess.run([sys.executable, '-m', 'playwright', 'install', 'chromium'], check=True)
            ensure_browser()
        return 0
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    return supervise(args.port, args.demo_email, args.no_browser, args.check_only)


if __name__ == '__main__':
    sys.exit(main())
