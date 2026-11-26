"""Sauvegarde, vérification et restauration de FRAMATEX (base SQLite et fichiers documentaires).

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
import argparse, hashlib, json, os, shutil, sqlite3, sys, tempfile, zipfile
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


def verify(archive: Path, target: Path | None = None) -> dict:
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
            if missing:
                report["errors"].append(f"{missing} version(s) documentaire(s) sans fichier conforme")
        report.update(schema_revision=manifest["schema_revision"], counts=manifest["counts"], files=len(manifest["files"]))
        report["status"] = "ok" if not report["errors"] else "échec"
        return report
    finally:
        if temporary:
            shutil.rmtree(target, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("backup"); b.add_argument("--data-dir", type=Path, default=Path(os.getenv("FRAMATEX_DATA_DIR", "data")))
    b.add_argument("--dest", type=Path, required=True); b.add_argument("--keep", type=int, default=14)
    v = sub.add_parser("verify"); v.add_argument("archive", type=Path)
    r = sub.add_parser("restore"); r.add_argument("archive", type=Path); r.add_argument("--to", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "backup":
        archive = backup(args.data_dir.resolve(), args.dest.resolve(), args.keep)
        report = verify(archive)
    elif args.command == "verify":
        report = verify(args.archive)
    else:
        if args.to.exists() and any(args.to.iterdir()):
            sys.exit("Le dossier de restauration doit être vide (aucune donnée existante n'est écrasée)")
        args.to.mkdir(parents=True, exist_ok=True)
        report = verify(args.archive, args.to.resolve())
    print(json.dumps(report, ensure_ascii=False, indent=1))
    sys.exit(0 if report["status"] == "ok" else 2)


if __name__ == "__main__":
    main()
