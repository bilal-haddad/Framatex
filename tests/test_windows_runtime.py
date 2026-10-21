"""Portable tests of Windows process/port policy, plus real socket/worker tests.
Native CIM, WSADuplicateSocket and Job APIs still require the Windows smoke run.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
import pytest

from scripts import windows_runtime as runtime


def process(pid, command, parent=1, exe=r'C:\Python312\python.exe', created='2026-10-21T10:00:00'):
    return {'ProcessId': pid, 'ParentProcessId': parent, 'Name': 'python.exe',
            'ExecutablePath': exe, 'CommandLine': command, 'CreationDate': created}


def test_all_ipv4_ipv6_listeners_localized_and_duplicate_owners():
    lines = ['TCP 127.0.0.1:8000 0.0.0.0:0 LISTENING 42', 'TCP [::]:8000 [::]:0 ECOUTE 43',
             'TCP 0.0.0.0:8001 0.0.0.0:0 ABHOREN 44', 'TCP 127.0.0.1:8000 127.0.0.1:4567 ESTABLISHED 42',
             'UDP 0.0.0.0:8000 *:* 45', 'TCP invalid 0.0.0.0:0 LISTENING ?']
    result = runtime.parse_netstat(lines)
    assert [(s['port'], s['pid']) for s in result] == [(8000, 42), (8000, 43), (8001, 44)]


def test_repository_ownership_not_generic_uvicorn_or_python():
    root = r'C:\Work\Framatex'
    rows = [process(10, r'"C:\Work\Framatex\.venv\Scripts\python.exe" -m uvicorn app.main:app --reload'),
            process(11, 'python.exe -c "from multiprocessing.spawn import spawn_main; spawn_main(parent_pid=10)"', parent=10),
            process(12, 'python.exe -c resource_tracker', parent=11),
            process(20, 'python.exe -m uvicorn app.main:app'),  # another repo/global Python
            process(21, r'C:\Work\Framatex-other\.venv\Scripts\python.exe -m uvicorn app.main:app'),
            process(22, 'python.exe -c spawn_main(parent_pid=999)', parent=999),
            process(23, r'C:\Work\Framatex\.venv\Scripts\python.exe analysis.py')]
    assert runtime.repository_processes(rows, root) == {10, 11, 12}


def test_global_python_with_explicit_app_dir_is_owned():
    row = process(10, r'python.exe -m uvicorn app.main:app --app-dir "C:\Work\Framatex" --port 8001')
    assert runtime.repository_processes([row], r'C:\Work\Framatex') == {10}


def test_global_python_and_orphan_reload_worker_require_exact_repository_cwd():
    rows = [process(10, 'python.exe -m uvicorn app.main:app'),
            process(11, 'python.exe -c "from multiprocessing.spawn import spawn_main; spawn_main(parent_pid=999)"', parent=999),
            process(12, 'python.exe -c "from multiprocessing.spawn import spawn_main; spawn_main(parent_pid=998)"', parent=998),
            process(13, 'python.exe analysis.py')]
    for row in rows:
        row.update(WorkingDirectory=r'C:\Work\Framatex', IsListener=True)
    rows[2]['WorkingDirectory'] = r'C:\Work\Framatex-other'
    assert runtime.repository_processes(rows, r'C:\Work\Framatex') == {10, 11}


def test_access_denied_cwd_or_unknown_orphan_is_never_killed():
    row = process(11, 'python.exe -c "spawn_main(parent_pid=999)"', parent=999)
    row.update(WorkingDirectory=None, IsListener=True)
    assert runtime.repository_processes([row], r'C:\Work\Framatex') == set()


def test_worker_and_supervisor_absolute_script_are_owned():
    rows = [process(10, r'python.exe "C:\Work\Framatex\scripts\windows_runtime.py" serve --port 8001'),
            process(11, r'python.exe "C:\Work\Framatex\scripts\windows_runtime.py" --worker pidfile', 10)]
    assert runtime.repository_processes(rows, r'C:\Work\Framatex') == {10, 11}


def test_current_supervisor_does_not_own_its_transient_cim_probe():
    rows = [process(10, r'python.exe "C:\Work\Framatex\scripts\windows_runtime.py" serve'),
            {**process(11, 'powershell.exe -Command Get-CimInstance', parent=10), 'Name': 'powershell.exe'},
            process(20, r'python.exe "C:\Work\Framatex\scripts\windows_runtime.py" serve')]
    assert runtime.repository_processes(rows, r'C:\Work\Framatex', exclude={10}) == {20}


def test_pid_reuse_older_child_is_not_killed():
    rows = [process(10, r'C:\Work\Framatex\.venv\Scripts\python.exe -m uvicorn app.main:app'),
            process(11, 'python.exe analysis.py', 10, created='2026-10-20T00:00:00')]
    assert runtime.repository_processes(rows, r'C:\Work\Framatex') == {10}


def test_cleanup_stops_only_owned_tree_on_all_ports(monkeypatch):
    # Test actual root matching on this OS, same normalized policy as CIM paths.
    root = str(runtime.ROOT).replace('/', '\\')
    rows = [process(710001, f'python.exe "{root}\\scripts\\windows_runtime.py" serve'),
            process(710002, 'python.exe -c spawn_main', 710001),
            process(710003, 'python.exe -m uvicorn app.main:app')]
    before = {'processes': rows, 'listeners': [{'address': '127.0.0.1', 'port': 8000, 'pid': 710002},
                                             {'address': '127.0.0.1', 'port': 8001, 'pid': 710003}]}
    rows[2]['WorkingDirectory'] = r'C:\OtherProject'
    after = {'processes': rows[2:], 'listeners': before['listeners'][1:]}
    snapshots = iter((before, after))
    stopped = []
    result = runtime.clean_repository_servers(lambda: next(snapshots), stopped.append)
    assert stopped == [710001]
    assert result['stopped_pids'] == [710001, 710002]
    assert result['after_cleanup'] == before['listeners'][1:]


def test_ambiguous_python_listener_is_not_silently_left_on_old_port():
    snapshot = {'processes': [process(710001, 'python.exe -m uvicorn app.main:app')],
                'listeners': [{'address': '127.0.0.1', 'port': 8000, 'pid': 710001}]}
    stopped = []
    with pytest.raises(RuntimeError, match='non identifiables'):
        runtime.clean_repository_servers(lambda: snapshot, stopped.append)
    assert stopped == []


def test_cleanup_refuses_fallback_if_socket_still_owned():
    root = str(runtime.ROOT).replace('/', '\\')
    row = process(710001, f'python.exe "{root}\\scripts\\windows_runtime.py" serve')
    snapshot = {'processes': [row], 'listeners': [{'address': '127.0.0.1', 'port': 8000, 'pid': 710001}]}
    with pytest.raises(RuntimeError, match='aucun basculement silencieux'):
        runtime.clean_repository_servers(lambda: snapshot, lambda pid: None, timeout=.01)


def test_port_8000_preferred_and_reservation_kept():
    marker = object()
    assert runtime.select_port(8000, [], lambda port: marker) == (8000, marker)


def test_foreign_program_preserved_and_next_port_reserved():
    calls = []
    def reserve(port):
        calls.append(port)
        return 'reserved'
    assert runtime.select_port(8000, [{'port': 8000, 'pid': 42}], reserve) == (8001, 'reserved')
    assert calls == [8001]


def test_windows_excluded_port_moves_to_next_candidate():
    def reserve(port):
        if port == 8000:
            raise PermissionError('reserved by Hyper-V')
        return 'reserved'
    assert runtime.select_port(8000, [], reserve) == (8001, 'reserved')


def test_all_ports_unavailable_is_error():
    def unavailable(port):
        raise OSError('busy')
    with pytest.raises(RuntimeError):
        runtime.select_port(65535, [], unavailable)


def test_reserved_socket_rejects_second_listener():
    reserved = runtime.reserve_port(0)
    try:
        with pytest.raises(OSError):
            runtime.reserve_port(reserved.getsockname()[1])
    finally:
        reserved.close()


def test_health_rejects_stale_instance_and_wrong_pid():
    for value in ({'status': 'ok', 'pid': 10, 'runtime_id': 'old'}, {'status': 'ok', 'pid': 11, 'runtime_id': 'new'}):
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=value))) as client:
            with pytest.raises(RuntimeError, match='autre instance'):
                runtime.health_sample(client, 'http://test', 10, 'new')


def test_health_accepts_only_correct_identity():
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'status': 'ok', 'pid': 10, 'runtime_id': 'new'}))) as client:
        assert runtime.health_sample(client, 'http://test', 10, 'new')['listening'] is True


def test_diagnostic_does_not_create_data_or_secret(tmp_path):
    target = tmp_path / 'never-created'
    env = {**os.environ, 'FRAMATEX_DATA_DIR': str(target)}
    env.pop('DATABASE_URL', None)
    result = subprocess.run([sys.executable, str(runtime.SCRIPT), 'diagnose'], env=env, capture_output=True, timeout=27)
    assert result.returncode == 0, result.stderr
    assert not target.exists()


def test_real_gated_worker_socket_transfer_and_shutdown(tmp_path, monkeypatch):
    monkeypatch.setenv('FRAMATEX_DATA_DIR', str(tmp_path))
    monkeypatch.delenv('DATABASE_URL', raising=False)
    reserved = runtime.reserve_port(0)
    port = reserved.getsockname()[1]
    server, job, pid, out, err = runtime.start_worker(reserved, 'unit-runtime', tmp_path)
    try:
        with httpx.Client(timeout=1, trust_env=False) as client:
            deadline = time.monotonic() + 20
            while True:
                try:
                    value = runtime.health_sample(client, f'http://127.0.0.1:{port}', pid, 'unit-runtime')
                    assert value['status'] == 200
                    break
                except httpx.TransportError:
                    if time.monotonic() > deadline or server.poll() is not None:
                        pytest.fail(err.read_text())
                    time.sleep(.1)
        assert server.poll() is None
    finally:
        runtime.stop_worker(server, job)
    assert server.poll() is not None
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1', port)) != 0


def test_failed_optional_checks_keep_server_alive_and_never_report_success(tmp_path, monkeypatch):
    monkeypatch.setenv('FRAMATEX_DATA_DIR', str(tmp_path))
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setattr(runtime, 'CHECKPOINTS', (0, 1))  # unit test only; real recipe uses 0/2/10/30/60
    monkeypatch.setattr(runtime, 'check_platform', lambda *args: (_ for _ in ()).throw(RuntimeError('forced optional failure')))
    reservation = runtime.reserve_port(0)
    port = reservation.getsockname()[1]
    reservation.close()
    assert runtime.supervise(port, no_browser=True, check_only=True) == 1
    report = json.loads(next((tmp_path / 'logs').glob('runtime-*.json')).read_text())
    assert report['status'] == 'degraded'
    assert [s['ok'] for s in report['health']] == [True, True]
    assert report['errors'] and not (tmp_path / 'runtime.json').exists()


def test_check_platform_does_not_skip_admin_password():
    def reply(request):
        pages = {'/': 'Choisissez votre espace', '/espace-client': '/assets/client/', '/espace-framatex': '/assets/app.js'}
        return httpx.Response(200, text=pages[request.url.path], headers={'content-type': 'text/html', 'cache-control': 'no-store'})
    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        with pytest.raises(AssertionError, match='Mot de passe admin requis'):
            runtime.check_platform('http://test', client, 'admin.test@framatex.com', None)


def test_powershell_51_foreground_contract():
    script = (runtime.ROOT / 'scripts' / 'start_windows.ps1').read_text(encoding='utf-8-sig')
    assert 'Read-Host' in script and '-AsSecureString' in script
    assert 'Invoke-WithSecret $runtimeArgs' in script
    assert 'Start-Process -FilePath $Python' not in script
    assert 'Register-EngineEvent' not in script and 'WaitForExit' not in script.split('#>')[1]
    assert 'ConvertFrom-SecureString -AsPlainText' not in script
    assert 'Set-ItemProperty' not in script and '--clear' not in script
