"""Story-short monitoring: explicit configured creators, ordinary videos, likes order."""

from contextlib import contextmanager

from app.connectors.douyin_posts import VERSION, parse_identity
from app.connectors.redfox import AdapterError
from app.intelligence.creator_resolution import Resolve, run_resolution
from app.intelligence.creator_series import checkpoint, run_creator
from app.intelligence.creators import active, known_account
from app.tasks.service import TaskError


def connector_factory():
    from app.connectors.douyin_posts_http import SessionPosts

    return SessionPosts()


@contextmanager
def opened_connector():
    try:
        with connector_factory() as connector:
            yield connector
    except AdapterError as exc:
        raise TaskError(str(exc)) from None


def collect_creators(channels):
    checkpoint(channels)
    entries = channels.ticket.payload.get("creators", [])
    if not entries:
        return "unavailable", "当前业务线未配置博主主页"
    channels.begin(len(entries))
    done = 0
    with opened_connector() as connector:
        connector.before_request = lambda: checkpoint(channels)
        for entry in entries:
            connector.before_request = lambda: checkpoint(channels)
            checkpoint(channels)
            with channels.runner.engine.connect() as c:
                if not active(c, channels.p.org_id, "story_short", entry):
                    raise TaskError("ACCESS_REVOKED")
                uid, evidence = known_account(c, channels.p, entry["url"])
            try:
                if not uid:
                    run_resolution(
                        channels, entry, Resolve(connector.resolve, parse_identity, VERSION)
                    )
                    with channels.runner.engine.connect() as c:
                        uid, evidence = known_account(c, channels.p, entry["url"])
                if not uid:
                    raise TaskError("INVALID_RESPONSE")
                run_creator(channels, entry, uid, evidence, posts_connector=connector)
                done += 1
                channels.completed = done
                channels.progress(
                    "creators",
                    "running",
                    done,
                    len(entries),
                    "已保存时间窗内视频及赞、评、藏、转，按点赞降序",
                )
            except TaskError as exc:
                if exc.code in ("ACCESS_REVOKED", "DATE_WINDOW_MISMATCH"):
                    raise
                # A restricted/unknown response stops the session; never rotate identity.
                break
    return (
        "succeeded" if done == len(entries) else "partial" if done else "failed",
        f"已更新{done}/{len(entries)}位博主：北京时间T-7日00:00至本次采集时刻，点赞数值降序；赞评藏转为视频级指标，未采评论正文；免费接口，未启用定时采集",
    )
