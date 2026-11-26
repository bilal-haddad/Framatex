"""Vérification d'intégrité après transfert SQLite → PostgreSQL.

    python scripts/verify_postgresql_migration.py --sqlite data/framat.db [--files-dir data]

Compare la base SQLite (copie, mise au niveau 0019 comme lors du transfert) et la base PostgreSQL
désignée par DATABASE_URL :
- tables présentes, nombre de lignes, ensembles d'identifiants ;
- contenu de chaque ligne (empreinte normalisée : dates en UTC, booléens, NULL conservés) — comptes,
  mots de passe hachés, habilitations, commandes, fiches, documents, versions, empreintes SHA-256,
  validations, historique, suppressions logiques, corbeille, conservation, idempotence… ;
- lignes orphelines dans PostgreSQL (toutes les clés étrangères) ;
- index de recherche (une ligne par ligne de l'index FTS5 d'origine) ;
- fichiers physiques : présence et empreinte SHA-256 de chaque version référencée (documents internes
  et pièces Client) ; un problème préexistant est signalé, jamais corrigé ;
- révision du schéma PostgreSQL.

La migration n'est réussie que si ce script se termine sans anomalie (code de sortie 0).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))


def normalize(value):
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (float, Decimal)):
        return repr(float(value))
    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest()
    return value


def table_digest(conn, table):
    from sqlalchemy import select
    keys = [c.name for c in table.primary_key.columns]
    columns = [c.name for c in table.columns]
    rows = {}
    for row in conn.execute(select(table)):
        data = row._mapping
        key = tuple(str(data[k]) for k in keys)
        rows[key] = hashlib.sha256(json.dumps([normalize(data[c]) for c in columns], ensure_ascii=False, default=str).encode()).hexdigest()
    return rows


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--files-dir", type=Path, default=Path(os.getenv("FRAMATEX_DATA_DIR", ROOT / "data")))
    parser.add_argument("--report-dir", type=Path, default=ROOT / "data" / "migration-reports")
    args = parser.parse_args()
    if not os.getenv("DATABASE_URL", "").startswith(("postgresql", "postgres")):
        sys.exit("DATABASE_URL doit désigner la base PostgreSQL migrée.")
    os.environ.setdefault("FRAMATEX_SECRET_KEY", "verification-sans-session-" * 2)
    from sqlalchemy import create_engine, text
    import app.all_models  # noqa: F401
    from app.core import Base, engine as pg_engine
    from app.migrate import postgresql_heads
    from migrate_sqlite_to_postgresql import bring_copy_to_0019, snapshot, source_tables
    work = Path(tempfile.mkdtemp(prefix="framatex-verification-"))
    anomalies, summary = [], {}
    try:
        copy = snapshot(args.sqlite.resolve(), work)
        bring_copy_to_0019(copy)
        src_engine = create_engine(f"sqlite:///{copy}")
        tables, present = source_tables(src_engine, Base.metadata)
        current, head = postgresql_heads()
        summary["schema"] = {"revision": current, "attendue": head}
        if current != head:
            anomalies.append({"type": "schéma", "détail": f"révision {current} au lieu de {head}"})
        with src_engine.connect() as src, pg_engine.connect() as dst:
            pg_tables = set(dst.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).scalars())
            for table in tables:
                if table.name not in pg_tables:
                    anomalies.append({"type": "table_absente", "table": table.name}); continue
                a, b = table_digest(src, table), table_digest(dst, table)
                summary[table.name] = {"sqlite": len(a), "postgresql": len(b)}
                if len(a) != len(b):
                    anomalies.append({"type": "comptes", "table": table.name, "sqlite": len(a), "postgresql": len(b)})
                missing, extra = set(a) - set(b), set(b) - set(a)
                changed = [k for k in set(a) & set(b) if a[k] != b[k]]
                for kind, keys in (("absents_postgresql", missing), ("en_trop_postgresql", extra), ("contenu_différent", changed)):
                    if keys:
                        anomalies.append({"type": kind, "table": table.name, "lignes": len(keys), "exemples": [list(k) for k in list(keys)[:5]]})
                for fk in table.foreign_keys:
                    orphans = dst.execute(text(
                        f'SELECT COUNT(*) FROM "{table.name}" c WHERE c."{fk.parent.name}" IS NOT NULL AND NOT EXISTS '
                        f'(SELECT 1 FROM "{fk.column.table.name}" p WHERE p."{fk.column.name}" = c."{fk.parent.name}")')).scalar()
                    if orphans:
                        anomalies.append({"type": "orphelin_postgresql", "table": table.name, "colonne": fk.parent.name, "lignes": orphans})
            if "document_content_fts" in present:
                fts = src.execute(text("SELECT COUNT(*) FROM document_content_fts")).scalar()
                idx = dst.execute(text("SELECT COUNT(*) FROM document_search_index")).scalar()
                summary["index_recherche"] = {"sqlite_fts5": fts, "postgresql": idx}
                if fts != idx:
                    anomalies.append({"type": "index_recherche", "sqlite": fts, "postgresql": idx})
            files = {"vérifiés": 0}
            for table, folder in (("document_versions", "files"), ("client_order_document_versions", "client_order_files")):
                for disk, digest in dst.execute(text(f"SELECT disk_name, sha256 FROM {table}")):
                    path = args.files_dir / folder / disk
                    files["vérifiés"] += 1
                    if not path.is_file():
                        anomalies.append({"type": "fichier_absent", "table": table, "fichier": f"{folder}/{disk}"})
                    elif file_sha256(path) != digest:
                        anomalies.append({"type": "empreinte_différente", "table": table, "fichier": f"{folder}/{disk}"})
            summary["fichiers"] = files
        report = {"verified_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "status": "conforme" if not anomalies else "anomalies",
                  "tables": len(tables), "rows": sum(v["sqlite"] for k, v in summary.items() if isinstance(v, dict) and "sqlite" in v),
                  "anomalies": anomalies, "summary": summary}
        args.report_dir.mkdir(parents=True, exist_ok=True)
        path = args.report_dir / f"verification-{report['verified_at'].replace(':', '').replace('-', '')}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(json.dumps({"status": report["status"], "tables": report["tables"], "lignes": report["rows"], "fichiers": summary["fichiers"],
                          "index_recherche": summary.get("index_recherche"), "anomalies": len(anomalies),
                          "exemples": anomalies[:5], "rapport": str(path)}, ensure_ascii=False, indent=1))
        return 0 if not anomalies else 2
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
