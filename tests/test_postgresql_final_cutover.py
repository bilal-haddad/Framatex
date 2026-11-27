import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from scripts import postgresql_cutover as cutover


ROOT = Path(__file__).resolve().parents[1]


def _run_core(env):
    return subprocess.run(
        [sys.executable, "-c", "import app.core"], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=20,
    )


def test_application_never_falls_back_to_sqlite(tmp_path):
    env = {**os.environ, "FRAMATEX_DATA_DIR": str(tmp_path)}
    env.pop("DATABASE_URL", None)
    result = _run_core(env)
    assert result.returncode != 0
    assert "Aucun repli SQLite" in result.stderr
    assert not (tmp_path / "framat.db").exists()


def test_sqlite_requires_explicit_historical_mode(tmp_path):
    env = {**os.environ, "FRAMATEX_DATA_DIR": str(tmp_path),
           "DATABASE_URL": f"sqlite:///{tmp_path / 'legacy.db'}"}
    env.pop("FRAMATEX_LEGACY_SQLITE_MODE", None)
    result = _run_core(env)
    assert result.returncode != 0
    assert "réservé aux outils historiques" in result.stderr


def test_windows_launchers_are_postgresql_only_and_keep_typed_options():
    common = (ROOT / "scripts/postgresql_windows_common.ps1").read_text(encoding="utf-8-sig")
    wrapper = (ROOT / "scripts/start_postgresql_windows.ps1").read_text(encoding="utf-8-sig")
    cmd = (ROOT / "scripts/start_windows.cmd").read_text(encoding="utf-8-sig")
    backup = (ROOT / "scripts/backup_framatex.py").read_text(encoding="utf-8")
    assert "$ErrorActionPreference = 'Continue'" in common
    assert "Invoke-FramatexNative $python @('-c','import psycopg, alembic') -Quiet" in common
    assert "print('Dependances PostgreSQL : OK')" in common
    assert "FRAMATEX_PG_PASSWORD'].Length -lt 20" in common
    assert "[int]$Port" in wrapper
    assert all(f"[switch]${name}" in wrapper for name in ("Demo", "NoBrowser", "CheckOnly", "Reload"))
    assert "$start = @{ Port = $Port }" in wrapper and "@start" in wrapper
    assert "FRAMATEX_PG_DEMO_DATABASE" in wrapper and "FRAMATEX_DEMO_DATA_DIR" in wrapper
    assert "start_postgresql_windows.ps1" in cmd
    assert "docker" not in backup.lower()


def test_migrator_has_no_destructive_replace_option():
    migrator = (ROOT / "scripts/migrate_sqlite_to_postgresql.py").read_text(encoding="utf-8")
    launcher = (ROOT / "scripts/migrate_to_postgresql_windows.ps1").read_text(encoding="utf-8-sig")
    assert "--replace" not in migrator
    assert "TRUNCATE" not in migrator.upper()
    assert "[switch]$Replace" not in launcher
    assert "BASCULER VERS POSTGRESQL" in launcher
    copy_position = launcher.index("'copy-storage'")
    target_activation = launcher.index("-DataDirOverride $TargetData", copy_position)
    assert target_activation > copy_position


def _legacy_source(root: Path):
    root.mkdir()
    files = root / "files"; files.mkdir()
    client_files = root / "client_order_files"; client_files.mkdir()
    first = b"version historique"
    second = b"piece client historique"
    (files / "a.bin").write_bytes(first)
    (client_files / "b.bin").write_bytes(second)
    database = root / "framat.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE document_versions (disk_name TEXT, sha256 TEXT)")
        connection.execute("CREATE TABLE client_order_document_versions (disk_name TEXT, sha256 TEXT)")
        connection.execute("INSERT INTO document_versions VALUES (?, ?)",
                           ("a.bin", hashlib.sha256(first).hexdigest()))
        connection.execute("INSERT INTO client_order_document_versions VALUES (?, ?)",
                           ("b.bin", hashlib.sha256(second).hexdigest()))
    return database


def test_source_backup_storage_copy_and_guarded_activation(tmp_path):
    source = tmp_path / "legacy"
    database = _legacy_source(source)
    inspected = cutover.inspect_source(database, source)
    assert inspected["status"] == "conforme"
    assert inspected["referenced_files_verified"] == 2

    backup = cutover.backup_source(database, source, tmp_path / "backups")
    assert backup["status"] == "conforme"
    assert Path(backup["archive"]).is_file()

    target = tmp_path / "pg-data"
    assert cutover.copy_storage(source, target)["files"] == 2
    with pytest.raises(RuntimeError, match="existe déjà"):
        cutover.copy_storage(source, target)

    env_file = tmp_path / ".env"
    env_file.write_text("FRAMATEX_PG_DATABASE=framatex_test\nFRAMATEX_DATA_DIR=old\n", encoding="utf-8")
    verification = tmp_path / "verification.json"
    verification.write_text(json.dumps({"status": "conforme", "anomalies": [],
                                        "target_database": "framatex"}), encoding="utf-8")
    result = cutover.activate_config(env_file, "framatex", target, verification)
    assert result["storage_files_verified"] == 2
    assert "FRAMATEX_PG_DATABASE=framatex" in env_file.read_text(encoding="utf-8")
    assert Path(result["backup"]).is_file()

    (target / "files" / "a.bin").write_bytes(b"altered")
    with pytest.raises(RuntimeError, match="altéré"):
        cutover.activate_config(env_file, "framatex", target, verification)


def test_activation_refuses_demo_database(tmp_path):
    with pytest.raises(RuntimeError, match="démonstration"):
        cutover.activate_config(tmp_path / ".env", "framatex_test", tmp_path, tmp_path / "report.json")


def test_only_dates_generated_on_copy_are_neutralized(tmp_path):
    from sqlalchemy import Column, MetaData, String, Table, create_engine
    from scripts.verify_postgresql_migration import table_digest

    table = Table("schema_migrations", MetaData(),
                  Column("version", String, primary_key=True), Column("applied_at", String))
    left = create_engine(f"sqlite:///{tmp_path / 'left.db'}")
    right = create_engine(f"sqlite:///{tmp_path / 'right.db'}")
    try:
        table.metadata.create_all(left); table.metadata.create_all(right)
        with left.begin() as connection:
            connection.execute(table.insert(), [
                {"version": "0016_order_sheet", "applied_at": "historique-A"},
                {"version": "0017_optional_documents", "applied_at": "copie-A"},
            ])
        with right.begin() as connection:
            connection.execute(table.insert(), [
                {"version": "0016_order_sheet", "applied_at": "historique-B"},
                {"version": "0017_optional_documents", "applied_at": "copie-B"},
            ])
        with left.connect() as a, right.connect() as b:
            da = table_digest(a, table, {"0017_optional_documents"})
            db = table_digest(b, table, {"0017_optional_documents"})
        assert da[("0017_optional_documents",)] == db[("0017_optional_documents",)]
        assert da[("0016_order_sheet",)] != db[("0016_order_sheet",)]
    finally:
        left.dispose(); right.dispose()
