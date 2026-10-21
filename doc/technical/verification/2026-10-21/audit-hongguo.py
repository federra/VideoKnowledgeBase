"""Read-only local acceptance. No source requests, task creation or comment text export."""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
from app.connectors.hongguo import BOARDS, response_html
from app.core.database import application_engine
from app.intelligence.feedback import entry_feedback
from app.intelligence.service import feed, shanghai_date
from app.security.sessions import MemberPrincipal


def main():
    engine = application_engine()
    day = shanghai_date()
    with engine.begin() as c:
        member = (
            c.exec_driver_sql(
                "SELECT m.org_id,m.id FROM members m JOIN organizations o ON o.id=m.org_id WHERE o.name='本地单人工作区' AND m.login_name='__local_owner__'"
            )
            .mappings()
            .one()
        )
        p = MemberPrincipal(member["org_id"], member["id"])
        first = feed(c, p, "motion_comic", day, video_catalog="hongguo")
        items = first["items"][:]
        for page in range(2, (int(first["total"]) + 9) // 10 + 1):
            items.extend(
                feed(c, p, "motion_comic", day, page=page, video_catalog="hongguo")[
                    "items"
                ]
            )
        heat = [int(v["heat_value"]) for v in items]
        assert heat == sorted(heat, reverse=True)
        ids = [v["entry"]["observation"]["platform_id"] for v in items]
        assert len(ids) == len(set(ids)) == int(first["total"])
        boards = {}
        for board in BOARDS:
            result = feed(
                c, p, "motion_comic", day, video_catalog="hongguo", video_board=board
            )
            assert result["total"] == "20"
            assert all(
                v["entry"]["provider_rank"] == i + 1
                for i, v in enumerate(result["items"])
            )
            boards[board] = {"name": BOARDS[board], "count": int(result["total"])}
        assert all(
            len(v["genre_tags"]) <= 1
            and len(v["genre_hierarchy"]) <= 1
            and all(len(g["subgenres"]) <= 1 for g in v["genre_hierarchy"])
            for v in items
        )
        samples = []
        for item in items:
            data = entry_feedback(c, p, item["entry"]["id"], "motion_comic", day)
            assert (
                data["status"] == "sampled"
                and data["feedback_id"] is None
                and data["classified_count"] == 0
                and data["claims"] == []
            )
            assert len(data["comments"]) == data["sample_count"] <= 15
            assert all(
                v["platform_comment_id"] is None and v["body_text"].strip()
                for v in data["comments"]
            )
            samples.append(data["sample_count"])
        paused = c.exec_driver_sql(
            "SELECT count(*) FROM sources WHERE org_id=%s AND platform_code='hongguo' AND enabled",
            (p.org_id,),
        ).scalar_one()
        assert paused == 0
        novel_counts = dict(
            c.exec_driver_sql(
                "SELECT platform_code,count(*) FROM external_contents WHERE org_id=%s AND platform_code IN ('fanqie','qidian') GROUP BY platform_code",
                (p.org_id,),
            ).all()
        )
        assert novel_counts == {"fanqie": 2213, "qidian": 274}
        latest = first["video_latest_dates"]["tikhub"]
        tikhub = feed(c, p, "motion_comic", latest, video_catalog="tikhub")
        assert tikhub["total"] == "10"
        captures = []
        for raw in c.exec_driver_sql(
            "SELECT r.id,r.sha256,r.body_text,cc.http_status,cc.outcome,j.capability_code FROM raw_assets r JOIN collection_jobs j ON j.org_id=r.org_id AND j.id=r.collection_job_id JOIN sources s ON s.org_id=j.org_id AND s.id=j.source_id JOIN collection_calls cc ON cc.org_id=r.org_id AND cc.id=r.collection_call_id WHERE r.org_id=%s AND j.business_date=%s AND s.platform_code='hongguo' ORDER BY r.captured_at",
            (p.org_id, day),
        ).mappings():
            assert (
                hashlib.sha256(raw["body_text"].encode()).hexdigest() == raw["sha256"]
            )
            html = response_html(raw["body_text"])
            captures.append(
                {
                    "raw_id": str(raw["id"]),
                    "stored_sha256": raw["sha256"],
                    "response_sha256": hashlib.sha256(html.encode()).hexdigest(),
                    "http_status": raw["http_status"],
                    "outcome": raw["outcome"],
                    "capability": raw["capability_code"],
                }
            )
        result = {
            "date": str(day),
            "schema": c.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one(),
            "boards": boards,
            "board_members": 80,
            "unique_series": len(items),
            "comments": sum(samples),
            "minimum_sample": min(samples),
            "maximum_sample": max(samples),
            "all_series_sampled": True,
            "all_order_numeric_descending": True,
            "source_enabled_count": paused,
            "novels_unchanged": novel_counts,
            "tikhub_date": str(latest),
            "tikhub_count": int(tikhub["total"]),
            "captures": captures,
            "external_requests_by_audit": 0,
            "model_calls_by_audit": 0,
        }
    engine.dispose()
    Path(__file__).with_name("hongguo-live-audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "captures"}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
