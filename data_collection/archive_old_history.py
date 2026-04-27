"""
archive_old_history.py
──────────────────────
Identifiserer daglige historikkfiler i ``data_collection/history/`` som er
eldre enn retensjonsgrensen, og kopierer dem til en arkivmappe der workflowen
sjekker ut ``gh-pages``-branchen.

Skriver også en oppdatert ``archive_index.json`` som lister alle datoer som
finnes i arkivet etter operasjonen.

Brukes av GitHub Actions: workflowen kaller skriptet med stier til lokal
historikk og arkivmappen, og håndterer selv git-commit/push på begge brancher.
"""

import argparse
import json
import os
import re
import shutil
from datetime import date, timedelta

DEFAULT_RETENTION_DAYS = 30
HISTORY_FILENAME_RE = re.compile(r"^forsinkelser_(\d{4}-\d{2}-\d{2})\.csv$")
ARCHIVE_INDEX_FILENAME = "archive_index.json"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--history-dir",
        required=True,
        help="Lokal historikkmappe (data_collection/history/)",
    )
    parser.add_argument(
        "--archive-dir",
        required=True,
        help="Mappe der gh-pages-branchen er sjekket ut",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=DEFAULT_RETENTION_DAYS,
        help=f"Antall dager som beholdes lokalt (default: {DEFAULT_RETENTION_DAYS})",
    )
    parser.add_argument(
        "--today",
        default=None,
        help="Overstyr dagens dato (kun for testing, format YYYY-MM-DD)",
    )
    return parser.parse_args()


def list_history_files(history_dir):
    """Returnerer liste av (dato, filsti) for hver gyldig historikkfil."""
    if not os.path.isdir(history_dir):
        return []

    entries = []
    for name in os.listdir(history_dir):
        match = HISTORY_FILENAME_RE.match(name)
        if not match:
            continue
        try:
            day = date.fromisoformat(match.group(1))
        except ValueError:
            continue
        entries.append((day, os.path.join(history_dir, name)))
    return sorted(entries)


def list_archive_days(archive_dir):
    """Returnerer settet av datoer (YYYY-MM-DD) som allerede finnes i arkivet."""
    if not os.path.isdir(archive_dir):
        return set()

    days = set()
    for name in os.listdir(archive_dir):
        match = HISTORY_FILENAME_RE.match(name)
        if match:
            days.add(match.group(1))
    return days


def write_archive_index(archive_dir, day_keys):
    """Skriver arkivindeksen. Bruker stabil sortering for deterministisk diff."""
    sorted_keys = sorted(day_keys)
    index = {
        "days": sorted_keys,
        "earliest": sorted_keys[0] if sorted_keys else None,
        "latest": sorted_keys[-1] if sorted_keys else None,
        "count": len(sorted_keys),
    }
    target = os.path.join(archive_dir, ARCHIVE_INDEX_FILENAME)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return target


def main():
    args = parse_args()

    today = (
        date.fromisoformat(args.today) if args.today else date.today()
    )
    cutoff = today - timedelta(days=args.retention_days)

    os.makedirs(args.archive_dir, exist_ok=True)

    history_files = list_history_files(args.history_dir)
    existing_archive = list_archive_days(args.archive_dir)

    moved = []
    for day, file_path in history_files:
        if day >= cutoff:
            continue

        target_path = os.path.join(args.archive_dir, os.path.basename(file_path))
        if not os.path.exists(target_path):
            shutil.copy2(file_path, target_path)
        os.remove(file_path)
        moved.append(day.isoformat())

    final_archive_days = existing_archive | set(moved)
    index_path = write_archive_index(args.archive_dir, final_archive_days)

    print(f"Retensjonsgrense: {cutoff.isoformat()} (i dag: {today.isoformat()})")
    print(f"Arkiverte dager denne kjøringen: {len(moved)}")
    for day_key in moved:
        print(f"  → {day_key}")
    print(f"Totalt antall dager i arkivet: {len(final_archive_days)}")
    print(f"Indeks oppdatert: {index_path}")


if __name__ == "__main__":
    main()
