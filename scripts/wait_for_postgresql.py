"""Attend que PostgreSQL accepte les connexions (DATABASE_URL + PGPASSWORD), sans rien modifier.

    python scripts/wait_for_postgresql.py --timeout 90
Code 0 : base joignable ; 1 : délai dépassé (message explicite, sans mot de passe).
"""
import argparse
import os
import sys
import time


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith(("postgresql", "postgres")):
        sys.exit("DATABASE_URL ne désigne pas PostgreSQL.")
    import psycopg
    conninfo = url.replace("postgresql+psycopg://", "postgresql://", 1)
    deadline, last = time.monotonic() + args.timeout, None
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(conninfo, connect_timeout=3) as conn:
                version = conn.execute("SHOW server_version").fetchone()[0]
            print(f"PostgreSQL {version} disponible.")
            return 0
        except psycopg.OperationalError as exc:
            last = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
            time.sleep(1)
    print(f"PostgreSQL injoignable après {args.timeout} s : {last}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
