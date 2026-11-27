"""Transfert complet d'une base FRAMATEX SQLite vers PostgreSQL.

    # 1. Simulation (aucune écriture dans PostgreSQL) :
    python scripts/migrate_sqlite_to_postgresql.py --sqlite data/framat.db --dry-run
    # 2. Transfert réel (base PostgreSQL vide, schéma créé ou mis à jour par Alembic) :
    python scripts/migrate_sqlite_to_postgresql.py --sqlite data/framat.db

La cible est lue dans DATABASE_URL (postgresql+psycopg://…, mot de passe via PGPASSWORD ou .pgpass).

Garanties :
- la base SQLite d'origine n'est jamais modifiée : une copie cohérente est prise par l'API de
  sauvegarde SQLite, mise si besoin à la révision 0019 (migrateur historique) sur la copie seule ;
- identifiants, empreintes SHA-256, mots de passe hachés, valeurs NULL, zéros initiaux, dates (UTC),
  données supprimées logiquement et historique sont copiés tels quels ; les fichiers documentaires ne
  sont pas déplacés (seules leurs références sont en base) ;
- contrôles préalables (simulation comme transfert réel) : lignes orphelines, valeurs plus longues que
  la colonne cible, NULL interdits, doublons sur contrainte d'unicité, booléens invalides. Toute anomalie
  est rapportée et **bloque** le transfert : rien n'est corrigé silencieusement ;
- transfert en une seule transaction PostgreSQL (tout ou rien), comptes vérifiés avant validation ;
  relance sans doublon : refus si la cible contient déjà des données. Ce script ne vide jamais une
  base existante et ne propose aucune option destructive.

Rapport : JSON et Markdown dans --report-dir (par défaut data/migration-reports/).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SEARCH_COLUMNS = ("version_id", "content", "title", "references")


def snapshot(source: Path, work: Path) -> Path:
    if not source.is_file():
        sys.exit(f"Base SQLite introuvable : {source}")
    copy = work / "source-copie.db"
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as origin, sqlite3.connect(str(copy)) as target:
        origin.backup(target)                                  # lecture seule de l'original
    with sqlite3.connect(str(copy)) as db:
        check = db.execute("PRAGMA integrity_check").fetchone()[0]
    if check != "ok":
        sys.exit(f"Copie SQLite incohérente (integrity_check : {check}) : transfert impossible")
    return copy


def bring_copy_to_0019(copy: Path):
    """Met la COPIE au niveau de schéma attendu (0019) avec le migrateur historique SQLite."""
    from sqlalchemy import create_engine
    import app.migrate as legacy
    engine = create_engine(f"sqlite:///{copy}")
    saved = legacy.engine
    legacy.engine = engine
    try:
        legacy._migrate()
    finally:
        legacy.engine = saved
        engine.dispose()
    return engine


def source_tables(src_engine, metadata):
    from sqlalchemy import inspect
    present = set(inspect(src_engine).get_table_names())
    return [t for t in metadata.sorted_tables if t.name in present], present


def preflight(src, metadata, tables) -> list[dict]:
    """Anomalies bloquantes, sans rien modifier."""
    from sqlalchemy import Boolean, String, func, select, text
    anomalies = []
    names = {t.name for t in tables}
    for table in tables:
        for column in table.columns:
            if isinstance(column.type, String) and column.type.length:
                over = src.execute(select(func.count()).select_from(table).where(func.length(column) > column.type.length)).scalar()
                if over:
                    longest = src.execute(select(func.max(func.length(column))).select_from(table)).scalar()
                    anomalies.append({"type": "longueur", "table": table.name, "colonne": column.name, "lignes": over,
                                      "limite": column.type.length, "maximum_trouvé": longest})
            if not column.nullable and not column.primary_key:
                nulls = src.execute(select(func.count()).select_from(table).where(column.is_(None))).scalar()
                if nulls:
                    anomalies.append({"type": "null_interdit", "table": table.name, "colonne": column.name, "lignes": nulls})
            if isinstance(column.type, Boolean):
                bad = src.execute(text(f'SELECT COUNT(*) FROM "{table.name}" WHERE "{column.name}" IS NOT NULL AND "{column.name}" NOT IN (0, 1)')).scalar()
                if bad:
                    anomalies.append({"type": "booléen_invalide", "table": table.name, "colonne": column.name, "lignes": bad})
        for fk in table.foreign_keys:
            parent = fk.column.table
            if parent.name not in names:
                continue
            orphans = src.execute(text(
                f'SELECT COUNT(*) FROM "{table.name}" c WHERE c."{fk.parent.name}" IS NOT NULL AND NOT EXISTS '
                f'(SELECT 1 FROM "{parent.name}" p WHERE p."{fk.column.name}" = c."{fk.parent.name}")')).scalar()
            if orphans:
                sample = src.execute(text(
                    f'SELECT c."{fk.parent.name}" FROM "{table.name}" c WHERE c."{fk.parent.name}" IS NOT NULL AND NOT EXISTS '
                    f'(SELECT 1 FROM "{parent.name}" p WHERE p."{fk.column.name}" = c."{fk.parent.name}") LIMIT 5')).scalars().all()
                anomalies.append({"type": "orphelin", "table": table.name, "colonne": fk.parent.name, "référence": f"{parent.name}.{fk.column.name}",
                                  "lignes": orphans, "exemples": sample})
        uniques = [list(c.columns) for c in table.constraints if c.__class__.__name__ == "UniqueConstraint"]
        uniques += [list(i.columns) for i in table.indexes if i.unique and i.dialect_options["postgresql"].get("where") is None]
        uniques += [[c] for c in table.columns if c.unique]
        for cols in uniques:
            col_list = ", ".join(f'"{c.name}"' for c in cols)
            not_null = " AND ".join(f'"{c.name}" IS NOT NULL' for c in cols)
            dup = src.execute(text(f'SELECT COUNT(*) FROM (SELECT {col_list} FROM "{table.name}" WHERE {not_null} '
                                   f'GROUP BY {col_list} HAVING COUNT(*) > 1) d')).scalar()
            if dup:
                anomalies.append({"type": "doublon_unicité", "table": table.name, "colonnes": [c.name for c in cols], "groupes": dup})
    return anomalies


def target_row_total(dst, tables) -> int:
    from sqlalchemy import func, select
    return sum(dst.execute(select(func.count()).select_from(t)).scalar() for t in tables)


def copy_rows(src, dst, tables, batch=1000) -> dict[str, int]:
    from sqlalchemy import select
    copied = {}
    for table in tables:
        result = src.execute(select(table))
        total = 0
        while True:
            rows = [dict(row._mapping) for row in result.fetchmany(batch)]
            if not rows:
                break
            dst.execute(table.insert(), rows)
            total += len(rows)
        copied[table.name] = total
    return copied


def copy_search_index(src, dst, present) -> int:
    from sqlalchemy import text
    if "document_content_fts" not in present:
        return 0
    rows = [dict(zip(SEARCH_COLUMNS, row)) for row in src.execute(
        text('SELECT version_id, content, title, "references" FROM document_content_fts'))]
    if rows:
        dst.execute(text('INSERT INTO document_search_index (version_id, content, title, "references") '
                         'VALUES (:version_id, :content, :title, :references)'), rows)
    return len(rows)


def write_report(report: dict, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = report["started_at"].replace(":", "").replace("-", "")
    path = directory / f"migration-{stamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    lines = [f"# Transfert SQLite → PostgreSQL ({report['mode']})", "", f"- Début : {report['started_at']}",
             f"- Source (copie) : {report['source']}", f"- Cible : {report['target']}", f"- Résultat : **{report['status']}**",
             f"- Tables : {len(report.get('tables', {}))} · lignes : {sum(report.get('tables', {}).values())}",
             f"- Index de recherche : {report.get('search_index_rows', 0)} ligne(s)", ""]
    if report["anomalies"]:
        lines += ["## Anomalies bloquantes (aucune correction automatique)", ""]
        lines += [f"- {json.dumps(a, ensure_ascii=False, default=str)}" for a in report["anomalies"]]
    else:
        lines += ["Aucune anomalie bloquante."]
    if report.get("tables"):
        lines += ["", "| Table | Lignes |", "|---|---|"] + [f"| {k} | {v} |" for k, v in report["tables"].items()]
    (directory / f"migration-{stamp}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sqlite", type=Path, required=True, help="base SQLite source (jamais modifiée)")
    parser.add_argument("--dry-run", action="store_true", help="simulation : contrôles et comptages, aucune écriture")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "data" / "migration-reports")
    args = parser.parse_args()
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith(("postgresql", "postgres")):
        sys.exit("DATABASE_URL doit désigner la base PostgreSQL cible (postgresql+psycopg://utilisateur@hôte:port/base).")
    os.environ.setdefault("FRAMATEX_SECRET_KEY", "transfert-sans-session-" * 2)   # aucune session n'est émise
    from sqlalchemy import create_engine, text
    import app.all_models  # noqa: F401
    from app.core import Base, engine as pg_engine
    from app.migrate import migrate
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    work = Path(tempfile.mkdtemp(prefix="framatex-transfert-"))
    report = {"started_at": started, "mode": "simulation" if args.dry_run else "transfert", "source": str(args.sqlite.resolve()),
              "target": f"{pg_engine.url.host}:{pg_engine.url.port}/{pg_engine.url.database}", "anomalies": [], "status": "en cours"}
    try:
        copy = snapshot(args.sqlite.resolve(), work)
        bring_copy_to_0019(copy)
        src_engine = create_engine(f"sqlite:///{copy}")
        tables, present = source_tables(src_engine, Base.metadata)
        missing = sorted(set(Base.metadata.tables) - present)
        if missing:
            report["anomalies"].append({"type": "tables_absentes_source", "tables": missing})
        with src_engine.connect() as src:
            report["anomalies"] += preflight(src, Base.metadata, tables)
            source_counts = {t.name: src.execute(text(f'SELECT COUNT(*) FROM "{t.name}"')).scalar() for t in tables}
        report["source_counts"] = source_counts
        if args.dry_run:
            report["status"] = "simulation : prêt" if not report["anomalies"] else "simulation : anomalies à traiter"
            report["tables"] = source_counts
            return report
        if report["anomalies"]:
            report["status"] = "refusé : anomalies à traiter avant transfert"
            return report
        migrate()                                              # schéma PostgreSQL à jour (Alembic, verrou consultatif)
        t0 = time.perf_counter()
        with src_engine.connect() as src, pg_engine.begin() as dst:
            existing = target_row_total(dst, tables)
            if existing:
                report["status"] = f"refusé : la base cible contient déjà {existing} ligne(s). Aucun vidage automatique n'est autorisé."
                return report
            report["tables"] = copy_rows(src, dst, tables)
            report["search_index_rows"] = copy_search_index(src, dst, present)
            target_counts = {t.name: dst.execute(text(f'SELECT COUNT(*) FROM "{t.name}"')).scalar() for t in tables}
            differences = {k: (source_counts[k], target_counts[k]) for k in source_counts if source_counts[k] != target_counts[k]}
            if differences:
                raise RuntimeError(f"Comptes différents après copie : {differences}")
        report["seconds"] = round(time.perf_counter() - t0, 2)
        report["status"] = "transfert terminé (à valider par scripts/verify_postgresql_migration.py)"
        return report
    except SystemExit:
        raise
    except Exception as exc:                                   # transaction annulée : cible inchangée
        report["status"] = f"échec, aucune donnée validée dans PostgreSQL : {exc.__class__.__name__}: {exc}"[:2000]
        return report
    finally:
        path = write_report(report, args.report_dir)
        shutil.rmtree(work, ignore_errors=True)
        print(json.dumps({k: report[k] for k in ("mode", "status")} | {"anomalies": len(report["anomalies"]),
                          "tables": len(report.get("tables", {})), "lignes": sum(report.get("tables", {}).values()), "rapport": str(path)},
                         ensure_ascii=False, indent=1))


if __name__ == "__main__":
    result = main()
    sys.exit(0 if result and not result["anomalies"] and not result["status"].startswith(("refusé", "échec")) else 2)
