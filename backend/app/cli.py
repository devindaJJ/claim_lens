"""Operational commands.

python -m app.cli ingest-policies /data/policies
python -m app.cli seed-claims /data/claims [--sync]
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from app.config import get_settings
from app.db import session_scope


def ingest_policies(directory: Path) -> None:
    from app.services.rag.ingest import ingest_policy

    paths = sorted(directory.glob("*.pdf"))
    if not paths:
        raise SystemExit(f"No PDFs found in {directory}")
    with session_scope() as session:
        for path in paths:
            policy = ingest_policy(session, path)
            print(f"  {policy.policy_number:<20} {len(policy.chunks):>3} chunks  ({path.name})")
    print(f"Ingested {len(paths)} policies.")


def seed_claims(directory: Path, sync: bool) -> None:
    from app.services.claims import create_claim

    settings = get_settings()
    paths = sorted(directory.glob("*.pdf"))
    ids = []
    with session_scope() as session:
        for path in paths:
            ids.append(create_claim(session, settings, path.name, path.read_bytes()).id)
    if sync:
        from app.worker import process_claim

        for claim_id, path in zip(ids, paths, strict=True):
            print(f"  {path.name}: {process_claim.run(str(claim_id))}")
    else:
        from app.api.claims import enqueue

        for claim_id in ids:
            enqueue(claim_id)
        print(f"Queued {len(ids)} claims for processing.")


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser(prog="claimlens")
    sub = parser.add_subparsers(dest="command", required=True)
    p_ingest = sub.add_parser("ingest-policies", help="Chunk, embed and store policy PDFs")
    p_ingest.add_argument("directory", type=Path)
    p_seed = sub.add_parser("seed-claims", help="Upload every claim PDF in a directory")
    p_seed.add_argument("directory", type=Path)
    p_seed.add_argument("--sync", action="store_true", help="Process in this process instead of the worker")
    args = parser.parse_args()

    if args.command == "ingest-policies":
        ingest_policies(args.directory)
    else:
        seed_claims(args.directory, args.sync)


if __name__ == "__main__":
    main()
