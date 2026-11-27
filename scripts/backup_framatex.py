"""Sauvegarde, vérification et restauration de FRAMATEX (PostgreSQL et fichiers).

Le moteur courant est obligatoirement PostgreSQL (postgresql+psycopg://…, mot de passe via
PGPASSWORD) : `pg_dump` au format personnalisé, vérification par `pg_restore` dans une base
temporaire neuve (supprimée ensuite), restauration dans une base NOUVELLE (--pg-database) — jamais
dans la base en service. Outils pg_dump/pg_restore : installation PostgreSQL locale, via PATH ou
FRAMATEX_PG_BIN. L'import historique SQLite utilise `postgresql_cutover.py backup-source`.

    python scripts/backup_framatex.py restore archive.zip --to D:/Restauration --pg-database framatex_restauration

    python scripts/backup_framatex.py backup  --data-dir data --dest D:/Sauvegardes --keep 14
    python scripts/backup_framatex.py verify  D:/Sauvegardes/framatex-backup-20261126T020000Z.zip
    python scripts/backup_framatex.py restore D:/Sauvegardes/framatex-backup-….zip --to D:/Restauration-test

- La base est copiée par l'API de sauvegarde en ligne de SQLite (cohérente même pendant l'utilisation),
  puis contrôlée (`PRAGMA integrity_check`).
- Chaque fichier est accompagné de son empreinte SHA-256 dans `manifest.json` ; la vérification
  contrôle l'archive, la base restaurée et la présence, avec la bonne empreinte, de chaque version
  documentaire référencée en base.
- La restauration n'écrase jamais un dossier existant : elle crée un dossier neuf, puis le vérifie.
- Non inclus, à conserver à part de façon sécurisée : FRAMATEX_SECRET_KEY et la configuration de
  l'hôte. Sans la même clé, les sessions sont simplement à rouvrir ; les documents ne dépendent pas
  de cette clé.
- Chiffrement : l'archive n'est pas chiffrée par ce script ; la déposer sur un support chiffré ou
  dans un outil de sauvegarde qui chiffre (voir docs/PRODUCTION_ARCHITECTURE.md).
"""
import argparse, hashlib, json, os, shutil, sqlite3, subprocess, sys, tempfile, zipfile
from datetime import datetime, timezone
from pathlib import Path

FILE_DIRS = ("files", "client_order_files")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def backup(data_dir: Path, dest: Path, keep: int) -> Path:
    source = data_dir / "framat.db"
    if not source.is_file():
        sys.exit(f"Base introuvable : {source}")
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    work = Path(tempfile.mkdtemp(prefix="framatex-backup-"))
    try:
        snapshot = work / "framat.db"
        with sqlite3.connect(str(source)) as origin, sqlite3.connect(str(snapshot)) as copy:
            origin.backup(copy)                                     # copie cohérente, base en service
        with sqlite3.connect(str(snapshot)) as db:
            check = db.execute("PRAGMA integrity_check").fetchone()[0]
            revision = db.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
            counts = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("launches", "documents", "document_versions", "users", "audit_events")}
        if check != "ok":
            sys.exit(f"Base source incohérente (integrity_check : {check}) : sauvegarde interrompue")
        manifest = {"created_at": stamp, "schema_revision": revision, "counts": counts, "database_sha256": sha256(snapshot),
                    "files": {}, "excluded": ["FRAMATEX_SECRET_KEY (à conserver séparément)", "configuration de l'hôte"]}
        archive = dest / f"framatex-backup-{stamp}.zip"
        partial = archive.with_suffix(".zip.partial")
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            zf.write(snapshot, "framat.db")
            for folder in FILE_DIRS:
                for path in sorted((data_dir / folder).glob("*")) if (data_dir / folder).is_dir() else []:
                    if path.is_file():
                        name = f"{folder}/{path.name}"
                        manifest["files"][name] = sha256(path)
                        zf.write(path, name)
            zf.writestr("manifest.json", json.dumps(manifest, indent=1))
        partial.replace(archive)                                    # archive complète ou absente
        rotate(dest, keep)
        print(f"Sauvegarde : {archive} ({archive.stat().st_size // 1024} Ko, {len(manifest['files'])} fichiers, révision {revision})")
        return archive
    finally:
        shutil.rmtree(work, ignore_errors=True)


def rotate(dest: Path, keep: int):
    archives = sorted(dest.glob("framatex-backup-*.zip"))
    for old in archives[:-keep] if keep > 0 else []:
        old.unlink()


def verify(archive: Path, target: Path | None = None, pg_database: str | None = None) -> dict:
    """Contrôle complet ; `target` : dossier où restaurer (sinon dossier temporaire supprimé ensuite)."""
    report = {"archive": str(archive), "errors": []}
    temporary = target is None
    target = target or Path(tempfile.mkdtemp(prefix="framatex-verify-"))
    try:
        with zipfile.ZipFile(archive) as zf:
            bad = zf.testzip()
            if bad:
                report["errors"].append(f"archive corrompue : {bad}")
            manifest = json.loads(zf.read("manifest.json"))
            zf.extractall(target)
        if manifest.get("engine") == "postgresql":
            result = verify_postgres(archive, target, manifest, pg_database, keep_database=bool(pg_database))
            result["errors"] = report["errors"] + result["errors"]
            result["status"] = "ok" if not result["errors"] else "échec"
            return result
        if sha256(target / "framat.db") != manifest["database_sha256"]:
            report["errors"].append("empreinte de la base différente du manifeste")
        for name, digest in manifest["files"].items():
            path = target / name
            if not path.is_file() or sha256(path) != digest:
                report["errors"].append(f"fichier absent ou altéré : {name}")
        with sqlite3.connect(str(target / "framat.db")) as db:
            report["integrity_check"] = db.execute("PRAGMA integrity_check").fetchone()[0]
            if report["integrity_check"] != "ok":
                report["errors"].append("integrity_check SQLite en échec")
            missing = 0
            for disk, digest in db.execute("SELECT disk_name, sha256 FROM document_versions"):
                path = target / "files" / disk
                if not path.is_file() or sha256(path) != digest:
                    missing += 1
            report["versions_checked"] = db.execute("SELECT COUNT(*) FROM document_versions").fetchone()[0]
            # Préalable à l'activation de PRAGMA foreign_keys : lignes orphelines (signalées, non bloquantes).
            report["foreign_key_violations"] = len(db.execute("PRAGMA foreign_key_check").fetchall())
            if missing:
                report["errors"].append(f"{missing} version(s) documentaire(s) sans fichier conforme")
        report.update(schema_revision=manifest["schema_revision"], counts=manifest["counts"], files=len(manifest["files"]))
        report["status"] = "ok" if not report["errors"] else "échec"
        return report
    finally:
        if temporary:
            shutil.rmtree(target, ignore_errors=True)


# --------------------------------------------------------------------------- PostgreSQL
COUNT_TABLES = ("launches", "documents", "document_versions", "users", "audit_events")


def postgres_url() -> str | None:
    url = os.getenv("DATABASE_URL", "")
    return url if url.startswith(("postgresql", "postgres")) else None


def pg_params(database: str | None = None) -> dict:
    from urllib.parse import urlparse
    parsed = urlparse(postgres_url().replace("postgresql+psycopg://", "postgresql://", 1))
    return {"host": parsed.hostname or "127.0.0.1", "port": str(parsed.port or 5432),
            "user": parsed.username or os.getenv("PGUSER", "framatex"), "dbname": database or parsed.path.lstrip("/")}


def pg_tool(tool: str, params: dict, extra: list[str], **run) -> subprocess.CompletedProcess:
    """Exécute les outils clients PostgreSQL locaux ; mot de passe via PGPASSWORD."""
    env = {**os.environ, "PGHOST": params["host"], "PGPORT": params["port"], "PGUSER": params["user"], "PGDATABASE": params["dbname"]}
    executable = shutil.which(tool)
    configured = os.getenv("FRAMATEX_PG_BIN", "").strip()
    if not executable and configured:
        candidate = Path(configured) / (tool + (".exe" if os.name == "nt" else ""))
        if candidate.is_file():
            executable = str(candidate)
    if not executable:
        sys.exit(f"{tool} introuvable. Configurez FRAMATEX_PG_BIN vers le dossier bin de PostgreSQL 17.")
    return subprocess.run([executable, *extra], env=env, check=True, **run)


def pg_connect(database: str | None = None, autocommit: bool = False):
    import psycopg
    params = pg_params(database)
    return psycopg.connect(host=params["host"], port=params["port"], user=params["user"], dbname=params["dbname"], autocommit=autocommit)


def backup_postgres(data_dir: Path, dest: Path, keep: int) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    work = Path(tempfile.mkdtemp(prefix="framatex-backup-"))
    try:
        dump = work / "framat.pgdump"
        with dump.open("wb") as out:                            # instantané cohérent (transaction de pg_dump)
            pg_tool("pg_dump", pg_params(), ["--format=custom", "--no-owner", "--no-privileges"], stdout=out)
        with pg_connect() as conn:
            revision = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            counts = {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in COUNT_TABLES}
        manifest = {"created_at": stamp, "engine": "postgresql", "schema_revision": revision, "counts": counts,
                    "database_sha256": sha256(dump), "files": {},
                    "excluded": ["FRAMATEX_SECRET_KEY (à conserver séparément)", "mot de passe PostgreSQL", "configuration de l'hôte"]}
        archive = dest / f"framatex-backup-{stamp}.zip"
        partial = archive.with_suffix(".zip.partial")
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            zf.write(dump, "framat.pgdump")
            for folder in FILE_DIRS:
                for path in sorted((data_dir / folder).glob("*")) if (data_dir / folder).is_dir() else []:
                    if path.is_file():
                        manifest["files"][f"{folder}/{path.name}"] = sha256(path)
                        zf.write(path, f"{folder}/{path.name}")
            zf.writestr("manifest.json", json.dumps(manifest, indent=1))
        partial.replace(archive)
        rotate(dest, keep)
        print(f"Sauvegarde PostgreSQL : {archive} ({archive.stat().st_size // 1024} Ko, {len(manifest['files'])} fichiers, révision {revision})")
        return archive
    finally:
        shutil.rmtree(work, ignore_errors=True)


def verify_postgres(archive: Path, target: Path, manifest: dict, database: str | None, keep_database: bool) -> dict:
    """Restaure le dump dans une base NOUVELLE puis contrôle comptes, intégrité référentielle et fichiers."""
    report = {"archive": str(archive), "errors": [], "engine": "postgresql"}
    if sha256(target / "framat.pgdump") != manifest["database_sha256"]:
        report["errors"].append("empreinte du dump différente du manifeste")
    for name, digest in manifest["files"].items():
        path = target / name
        if not path.is_file() or sha256(path) != digest:
            report["errors"].append(f"fichier absent ou altéré : {name}")
    database = database or f"framatex_verification_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    with pg_connect(pg_params()["dbname"], autocommit=True) as admin:
        if admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,)).fetchone():
            report["errors"].append(f"la base {database} existe déjà : restauration refusée (aucun écrasement)")
            report["status"] = "échec"; return report
        admin.execute(f'CREATE DATABASE "{database}" TEMPLATE template0 ENCODING \'UTF8\'')
    try:
        with (target / "framat.pgdump").open("rb") as dump:
            pg_tool("pg_restore", pg_params(database), ["--no-owner", "--no-privileges", "--exit-on-error", f"--dbname={database}"], stdin=dump)
        with pg_connect(database) as conn:
            counts = {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in COUNT_TABLES}
            report["schema_revision"] = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            missing = 0
            for disk, digest in conn.execute("SELECT disk_name, sha256 FROM document_versions"):
                path = target / "files" / disk
                if not path.is_file() or sha256(path) != digest:
                    missing += 1
            report["versions_checked"] = counts["document_versions"]
        if counts != manifest["counts"]:
            report["errors"].append(f"comptes restaurés différents du manifeste : {counts} ≠ {manifest['counts']}")
        if missing:
            report["errors"].append(f"{missing} version(s) documentaire(s) sans fichier conforme")
        report.update(counts=counts, restored_database=database if keep_database else None, files=len(manifest["files"]))
    finally:
        if not keep_database:
            with pg_connect(pg_params()["dbname"], autocommit=True) as admin:
                admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
    report["status"] = "ok" if not report["errors"] else "échec"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("backup"); b.add_argument("--data-dir", type=Path, default=Path(os.getenv("FRAMATEX_DATA_DIR", "data")))
    b.add_argument("--dest", type=Path, required=True); b.add_argument("--keep", type=int, default=14)
    v = sub.add_parser("verify"); v.add_argument("archive", type=Path)
    r = sub.add_parser("restore"); r.add_argument("archive", type=Path); r.add_argument("--to", type=Path, required=True)
    r.add_argument("--pg-database", help="PostgreSQL : nom de la NOUVELLE base à créer pour la restauration")
    args = parser.parse_args()
    if args.command == "backup":
        if not postgres_url():
            sys.exit("DATABASE_URL PostgreSQL est obligatoire : aucun repli vers une sauvegarde SQLite courante.")
        archive = backup_postgres(args.data_dir.resolve(), args.dest.resolve(), args.keep)
        report = verify(archive)
    elif args.command == "verify":
        report = verify(args.archive)
    else:
        if args.to.exists() and any(args.to.iterdir()):
            sys.exit("Le dossier de restauration doit être vide (aucune donnée existante n'est écrasée)")
        args.to.mkdir(parents=True, exist_ok=True)
        report = verify(args.archive, args.to.resolve(), args.pg_database)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    sys.exit(0 if report["status"] == "ok" else 2)


if __name__ == "__main__":
    main()
