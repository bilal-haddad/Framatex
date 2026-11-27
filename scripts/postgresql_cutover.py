"""Outils sûrs de bascule locale SQLite -> PostgreSQL.

Ce module ne vide et ne supprime jamais une base PostgreSQL. Il prépare une base
absente (ou accepte une base existante totalement vide), sauvegarde la source,
copie le stockage dans un dossier neuf et active .env seulement sur demande.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
import sys
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIRS = ("files", "client_order_files")
VERSION_TABLES = (("document_versions", "files"), ("client_order_document_versions", "client_order_files"))


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def assert_server_stopped(host: str = "127.0.0.1", first: int = 8000, last: int = 8020) -> dict:
    listening = []
    for port in range(first, last + 1):
        with socket.socket() as probe:
            probe.settimeout(0.08)
            if probe.connect_ex((host, port)) == 0:
                listening.append(port)
    if listening:
        raise RuntimeError(
            "Un serveur écoute encore sur le(s) port(s) " + ", ".join(map(str, listening)) +
            ". Arrêtez FRAMATEX avec Ctrl+C avant la bascule."
        )
    return {"status": "arrêté", "host": host, "ports_checked": f"{first}-{last}"}


def sqlite_snapshot(source: Path, destination: Path) -> str:
    before = sha256(source)
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as origin, sqlite3.connect(destination) as target:
        origin.backup(target)
    after = sha256(source)
    if before != after:
        raise RuntimeError("La base SQLite source a changé pendant la copie. Arrêtez FRAMATEX et recommencez.")
    with sqlite3.connect(destination) as database:
        integrity = database.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise RuntimeError(f"Copie SQLite incohérente : integrity_check={integrity}")
    return before


def referenced_files(database: Path) -> list[dict]:
    rows: list[dict] = []
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table, folder in VERSION_TABLES:
            if table not in tables:
                continue
            columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
            if not {"disk_name", "sha256"} <= columns:
                continue
            for disk_name, digest in connection.execute(f'SELECT disk_name, sha256 FROM "{table}"'):
                rows.append({"table": table, "folder": folder, "disk_name": disk_name, "sha256": digest})
    return rows


def inspect_source(sqlite_path: Path, data_dir: Path) -> dict:
    sqlite_path, data_dir = sqlite_path.resolve(), data_dir.resolve()
    if not sqlite_path.is_file():
        raise RuntimeError(f"Base SQLite introuvable : {sqlite_path}")
    if not data_dir.is_dir():
        raise RuntimeError(f"Dossier source introuvable : {data_dir}")
    with tempfile.TemporaryDirectory(prefix="framatex-source-check-") as temporary:
        copy = Path(temporary) / "framat.db"
        original_sha = sqlite_snapshot(sqlite_path, copy)
        anomalies, verified = [], 0
        for item in referenced_files(copy):
            path = data_dir / item["folder"] / item["disk_name"]
            if not path.is_file():
                anomalies.append({"type": "fichier_absent", "table": item["table"], "fichier": str(path)})
            else:
                verified += 1
                actual = sha256(path)
                if actual != item["sha256"]:
                    anomalies.append({"type": "sha256_différent", "table": item["table"], "fichier": str(path),
                                      "attendu": item["sha256"], "obtenu": actual})
        with sqlite3.connect(copy) as connection:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'document_content_fts_%'")}
            counts = {table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in sorted(tables)}
        return {"status": "conforme" if not anomalies else "anomalies", "sqlite": str(sqlite_path),
                "source_data": str(data_dir), "sqlite_sha256": original_sha, "tables": len(counts),
                "rows": sum(counts.values()), "referenced_files_verified": verified, "anomalies": anomalies,
                "counts": counts}


def write_report(report: dict, report_dir: Path, prefix: str) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{prefix}-{stamp()}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def backup_source(sqlite_path: Path, data_dir: Path, destination: Path) -> dict:
    source = inspect_source(sqlite_path, data_dir)
    if source["anomalies"]:
        raise RuntimeError("Sauvegarde refusée : la source contient des anomalies documentaires.")
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / f"framatex-sqlite-before-postgresql-{stamp()}.zip"
    partial = archive.with_suffix(".zip.partial")
    with tempfile.TemporaryDirectory(prefix="framatex-legacy-backup-") as temporary:
        snapshot = Path(temporary) / "framat.db"
        database_sha = sqlite_snapshot(sqlite_path.resolve(), snapshot)
        manifest = {"created_at": stamp(), "purpose": "pre-postgresql-cutover", "database_sha256": database_sha,
                    "source_database": str(sqlite_path.resolve()), "files": {}}
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as bundle:
            bundle.write(snapshot, "framat.db")
            for folder in STORAGE_DIRS:
                root = data_dir.resolve() / folder
                if not root.is_dir():
                    continue
                for path in sorted(root.rglob("*")):
                    if path.is_symlink():
                        raise RuntimeError(f"Lien symbolique refusé dans le stockage : {path}")
                    if path.is_file():
                        relative = path.relative_to(data_dir.resolve()).as_posix()
                        manifest["files"][relative] = sha256(path)
                        bundle.write(path, relative)
            bundle.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        with zipfile.ZipFile(partial) as bundle:
            bad = bundle.testzip()
            if bad:
                raise RuntimeError(f"Archive de sauvegarde corrompue : {bad}")
        partial.replace(archive)
    return {"status": "conforme", "archive": str(archive), "archive_sha256": sha256(archive),
            "database_sha256": database_sha, "files": len(manifest["files"])}


def copy_storage(source: Path, target: Path) -> dict:
    source, target = source.resolve(), target.resolve()
    if not source.is_dir():
        raise RuntimeError(f"Stockage source introuvable : {source}")
    if target.exists():
        raise RuntimeError(f"Le stockage cible existe déjà : {target}. Aucun écrasement n'est autorisé.")
    staging = target.with_name(target.name + f".staging-{uuid.uuid4().hex[:8]}")
    manifest: dict[str, str] = {}
    try:
        staging.mkdir(parents=True)
        for folder in STORAGE_DIRS:
            src = source / folder
            dst = staging / folder
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                dst.mkdir()
            for path in sorted(dst.rglob("*")):
                if path.is_file():
                    relative = path.relative_to(staging).as_posix()
                    source_path = source / relative
                    source_hash, target_hash = sha256(source_path), sha256(path)
                    if source_hash != target_hash:
                        raise RuntimeError(f"Copie altérée : {relative}")
                    manifest[relative] = source_hash
        payload = {"copied_at": stamp(), "source": str(source), "target": str(target), "files": manifest}
        (staging / ".cutover-storage-manifest.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        staging.replace(target)
        return {"status": "conforme", "target": str(target), "files": len(manifest)}
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def verify_storage(data_dir: Path) -> dict:
    data_dir = data_dir.resolve()
    manifest_path = data_dir / ".cutover-storage-manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("Manifest du stockage migré absent : activation refusée.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if Path(manifest.get("target", "")).resolve() != data_dir:
        raise RuntimeError("Le manifest ne correspond pas au dossier de stockage cible.")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise RuntimeError("Manifest de stockage invalide.")
    for relative, expected in files.items():
        path = (data_dir / relative).resolve()
        try:
            path.relative_to(data_dir)
        except ValueError as error:
            raise RuntimeError(f"Chemin hors stockage dans le manifest : {relative}") from error
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"Stockage copié absent ou altéré : {relative}")
    return {"files": len(files), "manifest": str(manifest_path)}


def postgres_parts(database: str | None = None):
    raw = os.getenv("DATABASE_URL", "")
    if not raw.startswith(("postgresql", "postgres")):
        raise RuntimeError("DATABASE_URL PostgreSQL est obligatoire.")
    parsed = urlparse(raw.replace("postgresql+psycopg://", "postgresql://", 1))
    chosen = database or parsed.path.lstrip("/")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", chosen):
        raise RuntimeError(f"Nom de base PostgreSQL invalide : {chosen}")
    maintenance = os.getenv("FRAMATEX_PG_MAINTENANCE_DATABASE", "postgres")
    maintenance_url = urlunparse(parsed._replace(path="/" + maintenance))
    target_url = urlunparse(parsed._replace(path="/" + chosen))
    return maintenance_url, target_url, chosen


def prepare_target(database: str) -> dict:
    import psycopg
    maintenance_url, target_url, chosen = postgres_parts(database)
    with psycopg.connect(maintenance_url, autocommit=True) as connection:
        exists = connection.execute("SELECT 1 FROM pg_database WHERE datname=%s", (chosen,)).fetchone() is not None
        if not exists:
            connection.execute(f'CREATE DATABASE "{chosen}" TEMPLATE template0 ENCODING \'UTF8\'')
    with psycopg.connect(target_url) as target:
        objects = target.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'").fetchone()[0]
        if objects:
            raise RuntimeError(
                f"La base {chosen} existe et contient {objects} table(s). Bascule refusée : aucune base existante n'est vidée.")
    return {"status": "prête", "database": chosen, "created": not exists, "public_tables": 0}


def activate_config(env_file: Path, database: str, data_dir: Path, verification_report: Path) -> dict:
    env_file, data_dir = env_file.resolve(), data_dir.resolve()
    if database == "framatex_test":
        raise RuntimeError("La base de démonstration framatex_test ne peut jamais être activée comme base définitive.")
    storage = verify_storage(data_dir)
    verification_report = verification_report.resolve()
    if not verification_report.is_file():
        raise RuntimeError(f"Rapport de vérification introuvable : {verification_report}")
    verification = json.loads(verification_report.read_text(encoding="utf-8"))
    if (verification.get("status") != "conforme" or verification.get("anomalies") or
            verification.get("target_database") != database):
        raise RuntimeError("Le rapport de vérification n'est pas conforme à la base cible : activation refusée.")
    if not env_file.is_file():
        raise RuntimeError(f"Configuration introuvable : {env_file}")
    original = env_file.read_text(encoding="utf-8-sig")
    updates = {"FRAMATEX_PG_DATABASE": database, "FRAMATEX_DATA_DIR": str(data_dir),
               "FRAMATEX_PG_MODE": "local", "FRAMATEX_CUTOVER_COMPLETED_AT": stamp()}
    found = set()
    lines = []
    for line in original.splitlines():
        match = re.match(r"^\s*([A-Z0-9_]+)\s*=", line)
        if match and match.group(1) in updates:
            key = match.group(1); lines.append(f"{key}={updates[key]}"); found.add(key)
        else:
            lines.append(line)
    lines.extend(f"{key}={value}" for key, value in updates.items() if key not in found)
    backup = env_file.with_name(env_file.name + f".pre-cutover-{stamp()}.bak")
    shutil.copy2(env_file, backup)
    temporary = env_file.with_name(env_file.name + ".cutover.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(temporary, env_file)
    return {"status": "activée", "config": str(env_file), "backup": str(backup),
            "database": database, "data_dir": str(data_dir), "storage_files_verified": storage["files"],
            "verification_report": str(verification_report)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, default=ROOT / "data" / "migration-reports")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("assert-server-stopped")
    for name in ("source-check", "backup-source"):
        item = commands.add_parser(name); item.add_argument("--sqlite", type=Path, required=True)
        item.add_argument("--source-data", type=Path, required=True)
        if name == "backup-source": item.add_argument("--dest", type=Path, required=True)
    copy = commands.add_parser("copy-storage"); copy.add_argument("--source-data", type=Path, required=True)
    copy.add_argument("--target-data", type=Path, required=True)
    prepare = commands.add_parser("prepare-target"); prepare.add_argument("--database", required=True)
    activate = commands.add_parser("activate-config"); activate.add_argument("--env-file", type=Path, required=True)
    activate.add_argument("--database", required=True); activate.add_argument("--data-dir", type=Path, required=True)
    activate.add_argument("--verification-report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "assert-server-stopped": result = assert_server_stopped()
        elif args.command == "source-check": result = inspect_source(args.sqlite, args.source_data)
        elif args.command == "backup-source": result = backup_source(args.sqlite, args.source_data, args.dest)
        elif args.command == "copy-storage": result = copy_storage(args.source_data, args.target_data)
        elif args.command == "prepare-target": result = prepare_target(args.database)
        else: result = activate_config(args.env_file, args.database, args.data_dir, args.verification_report)
        report = write_report(result, args.report_dir, args.command)
        print(json.dumps({**result, "report": str(report)}, ensure_ascii=False, indent=2))
        return 0 if result.get("status") not in ("anomalies", "échec") else 2
    except Exception as error:
        result = {"status": "échec", "error": f"{type(error).__name__}: {error}"}
        report = write_report(result, args.report_dir, args.command)
        print(json.dumps({**result, "report": str(report)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
