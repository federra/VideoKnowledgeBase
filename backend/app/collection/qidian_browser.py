"""Explicit import of browser-assisted public captures, without scheduling a browser."""

from datetime import UTC, datetime

from app.collection.qidian_desktop import SavedQidian, run_saved, submit_local
from app.connectors.qidian_browser import CAPTURE, METHOD, discover, document, normalize
from app.intelligence.service import shanghai_date
from app.tasks.service import TaskError


class BrowserQidian(SavedQidian):
    method = METHOD
    capture_kind = CAPTURE
    board_prefix = "qidian:browser:female:"
    input_role = "novel_browser_ax"
    audit_action = "novel.browser_capture_imported"
    discover = staticmethod(discover)
    normalize = staticmethod(normalize)

    def validate_capture(self, body):
        value = document(body)["captured_at"]
        moment = datetime.fromisoformat(value)
        if shanghai_date(moment) != shanghai_date() or moment > datetime.now(UTC):
            raise TaskError("INVALID_INPUT")
        return value


def submit_browser(c, p, board, body, *, business="motion_comic"):
    return submit_local(c, p, board, body, BrowserQidian(), business=business)


def run_browser(engine, org, task_id):
    return run_saved(engine, org, task_id, handler=BrowserQidian())
