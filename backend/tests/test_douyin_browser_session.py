from app.connectors.douyin_browser_session import sample_bundle
from tests.test_douyin_series import series


def test_browser_json_only_binds_first_episode_and_caps_fifteen():
    s = series(999, 100)
    episode = {
        "status_code": 0,
        "aweme_list": [
            {
                "aweme_id": "111",
                "series_info": {"series_id": s["series_id"]},
                "author": s["author"],
                "series_play_info": {"series_aweme_index": 1},
            }
        ],
    }
    rows = [
        {"cid": str(i), "aweme_id": "111", "text": f"原文{i}", "digg_count": i} for i in range(20)
    ]
    responses = [
        {
            "path": "/aweme/v1/web/series/aweme/",
            "parameters": {"series_id": "999", "cursor": "0"},
            "status": 200,
            "body": episode,
        },
        {
            "path": "/aweme/v1/web/comment/list/",
            "parameters": {"aweme_id": "111", "cursor": "0"},
            "status": 200,
            "body": {"status_code": 0, "comments": rows},
        },
    ]
    result = sample_bundle(responses, "999", "123456")
    assert result["aweme_id"] == "111" and len(result["comments"]) == 15
    # A recommendation's comments never enter this series' evidence.
    responses[-1]["parameters"]["aweme_id"] = "222"
    assert sample_bundle(responses, "999", "123456")["comments"] == []


def response_pages():
    s = series(999, 100)
    episode = {
        "path": "/aweme/v1/web/series/aweme/",
        "parameters": {"series_id": "999", "cursor": "0"},
        "status": 200,
        "body": {
            "status_code": 0,
            "aweme_list": [
                {
                    "aweme_id": "111",
                    "series_info": {"series_id": "999"},
                    "author": s["author"],
                    "series_play_info": {"series_aweme_index": 1},
                }
            ],
        },
    }

    def page(cursor, next_cursor, start, end, more):
        return {
            "path": "/aweme/v1/web/comment/list/",
            "parameters": {"aweme_id": "111", "cursor": str(cursor)},
            "status": 200,
            "body": {
                "status_code": 0,
                "cursor": next_cursor,
                "has_more": more,
                "comments": [
                    {"cid": str(i), "aweme_id": "111", "text": str(i)} for i in range(start, end)
                ],
            },
        }

    return episode, page(0, 5, 0, 5, 1), page(5, 15, 5, 15, 1), page(10, 20, 10, 20, 1)


def test_out_of_order_network_completion_still_follows_cursor_chain():
    ep, first, second, _ = response_pages()
    result = sample_bundle([ep, second, first], "999", "123456")
    assert result["sample_complete"] and len(result["comments"]) == 15


def test_gap_in_comment_cursor_never_claims_complete():
    ep, first, _, gap = response_pages()
    result = sample_bundle([ep, first, gap], "999", "123456")
    assert not result["sample_complete"] and len(result["comments"]) == 5


def test_terminal_page_can_confirm_zero_without_inventing_it():
    ep, first, _, _ = response_pages()
    first["body"] = {"status_code": 0, "comments": [], "total": 0, "has_more": 0, "cursor": 0}
    result = sample_bundle([ep, first], "999", "123456")
    assert result["sample_complete"] and result["comments"] == []


class NavigationPage:
    url = "https://www.douyin.com/collection/999/1"

    def __init__(self, status=403, revoke=None):
        self.status, self.revoke, self.aborted, self.closed = status, revoke, False, False

    async def route(self, pattern, callback):
        self.route_callback = callback

    def on(self, event, callback):
        self.response_callback = callback

    def remove_listener(self, *args):
        pass

    async def close(self):
        self.closed = True

    async def goto(self, url, **kwargs):
        from types import SimpleNamespace

        if self.revoke:
            self.revoke()
            owner = self

            class Request:
                request = SimpleNamespace(
                    url="https://www.douyin.com/aweme/v1/web/comment/list/?aweme_id=111&cursor=0",
                    resource_type="xhr",
                )

                async def abort(self):
                    owner.aborted = True

                async def continue_(self):
                    pass

            await self.route_callback(Request())
        return SimpleNamespace(status=self.status, url=self.url)


def test_main_document_rate_limit_is_recorded_and_persisted(monkeypatch, tmp_path):
    import asyncio
    import json
    import time

    from app.connectors import douyin_browser_session as browser

    page = NavigationPage()

    class Context:
        async def new_page(self):
            return page

    monkeypatch.setattr(browser, "ROOT", tmp_path)
    result = asyncio.run(browser.guarded_capture(Context(), "999", "123456", timeout=0.001))
    assert any(r["status"] == 403 for r in result["diagnostics"])
    gate = json.loads((tmp_path / "public-series/request-gate.json").read_text())
    assert gate["blocked_until"] > time.time() and page.closed


def test_revocation_during_page_load_aborts_the_next_api_request():
    import asyncio

    from app.connectors.douyin_browser_session import capture_page
    from app.tasks.service import TaskError

    current = [True]
    page = NavigationPage(200, revoke=lambda: current.__setitem__(0, False))

    class Context:
        async def new_page(self):
            return page

    def fence():
        if not current[0]:
            raise TaskError("ACCESS_REVOKED")

    result = asyncio.run(
        capture_page(Context(), "999", "123456", timeout=0.001, before_request=fence)
    )
    assert page.aborted and page.closed and result["safe_error"] == "ACCESS_REVOKED"


def test_fifteen_source_slots_with_one_duplicate_is_a_valid_fourteen_comment_sample():
    ep, first, second, _ = response_pages()
    second["body"]["comments"][0]["cid"] = first["body"]["comments"][-1]["cid"]
    result = sample_bundle([ep, first, second], "999", "123456")
    assert result["sample_complete"] and len(result["comments"]) == 14


def test_provider_cursor_can_advance_faster_than_actual_comment_count():
    ep, first, second, _ = response_pages()
    first["body"]["cursor"] = 10
    second["parameters"]["cursor"] = "10"
    second["body"]["cursor"] = 20
    second["body"]["comments"] = second["body"]["comments"][:9]
    result = sample_bundle([ep, first, second], "999", "123456")
    assert result["sample_complete"] and len(result["comments"]) == 14


def test_a_positive_partial_sample_is_valid_without_claiming_fifteen_or_total_coverage():
    from app.collection.creator_browser_comments import bundle_from_capture

    ep, first, _, _ = response_pages()
    data = sample_bundle([ep, first], "999", "123456")
    data.update(
        series_id="999", uid="123456", status="sampled", method="dedicated_browser_network_json"
    )
    result = bundle_from_capture(data)
    assert len(result["comments"]) == 5 and not result["sample_complete"]
