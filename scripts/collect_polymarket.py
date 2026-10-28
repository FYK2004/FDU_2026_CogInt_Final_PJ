"""Compatibility entry point for dated historical collection.

python scripts/collect_polymarket.py --as-of 2026-10-14

Does not overwrite the original Gamma snapshot or mix current order books into
historical information sets. Token metadata is read from the 10/07 archive.
"""
from backfill_market import main

if __name__ == "__main__":
    main()
