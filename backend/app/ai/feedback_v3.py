"""One structured invocation, exact independent per-work evidence validation."""

from uuid import UUID

from pydantic import Field

from app.ai.feedback_v2 import PROMPT as SINGLE_PROMPT
from app.ai.feedback_v2 import Output, inspect_output
from app.contracts.models import Contract


class Item(Contract):
    entry_id: UUID
    result: Output


class BatchOutput(Contract):
    items: list[Item] = Field(min_length=1, max_length=3)


PROMPT = (
    SINGLE_PROMPT
    + """\n本次输入items为1至3部不同作品，各部评论独立。一次返回items数组，entry_id精确逐部对应，不遗漏、不新增、不重复。每部result使用同一单部schema。严禁跨作品引用comment_id或混用结论。逐条检查每部全部评论均在emotion中覆盖；同一comment_id出现多次时sentiment必须完全相同。可将同一倾向评论合并在一个emotion中，具体情绪/触发原因仍必须有依据；语义不明填unclassifiable，不得为了覆盖捏造倾向。完成JSON前逐部核对输入ID集合与情绪引用并集完全相等。"""
)


def inspect_batch(samples, value):
    parsed = BatchOutput.model_validate(value).model_dump(mode="json")["items"]
    wanted = [str(x["entry_id"]) for x in samples]
    actual = [x["entry_id"] for x in parsed]
    if (
        len(set(wanted)) != len(wanted)
        or len(set(actual)) != len(actual)
        or set(wanted) != set(actual)
    ):
        raise ValueError("Invalid exact batch members")
    lookup = {x["entry_id"]: x["result"] for x in parsed}
    return {
        "items": [
            {
                "entry_id": str(s["entry_id"]),
                "checked": inspect_output(s, lookup[str(s["entry_id"])]),
            }
            for s in samples
        ]
    }
