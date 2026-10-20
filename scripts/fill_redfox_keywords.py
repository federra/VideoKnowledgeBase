"""Retired historical keyword fill. Strict playback ranking needs a verified source first."""

import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume-before-network", action="store_true")
    args = parser.parse_args()
    plan = {
        "keyword": "漫剧",
        "ranking_metric": "view_count",
        "order": "desc",
        "max_saved_works": 10,
        "paid_call": False,
        "blocked_by": "PLAYBACK_RANKING_UNVERIFIED",
        "reason": "RedFox playback field and ordering semantics have not been verified; historical search is not a playback board.",
    }
    if args.execute or args.resume_before_network:
        raise RuntimeError("PLAYBACK_RANKING_UNVERIFIED")
    print(json.dumps(plan, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except RuntimeError:
        print(
            "PLAYBACK_RANKING_UNVERIFIED: no request sent; see the ranking verification record.",
            file=sys.stderr,
        )
        sys.exit(2)
