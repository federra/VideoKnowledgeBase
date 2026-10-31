"""Local text overlap heuristics against frozen sources, never a copyright verdict."""

import unicodedata
from difflib import SequenceMatcher

from app.tasks.service import TaskError

LIMITATIONS = (
    "仅比对本次冻结来源的文字，以连续片段及字符n元组筛查；不覆盖全网、语义换写或完整情节，"
    "不能证明原创或版权安全。用户私有闪念作为创作意图保留，不作为抄写比对来源。"
)


def normalized(text):
    return "".join(x for x in unicodedata.normalize("NFKC", text or "").casefold() if x.isalnum())


def sources(refs):
    """Stable source identities; only externally sourced prose enters comparison."""
    result = []
    for kind, key in (("intelligence", "entry_id"), ("knowledge", "revision_id")):
        for ref in refs.get(kind, []):
            body = "\n".join(str(ref.get(k) or "") for k in ("title", "description", "text"))
            result.append((kind + ":" + str(ref.get(key, "")), body, ref))
    return result


def screen(fields, refs):
    values = fields.model_dump() if hasattr(fields, "model_dump") else fields
    texts = [normalized(v) for v in values.values() if isinstance(v, str)]
    matches = []
    comparable = False
    for identity, body, ref in sources(refs):
        original = normalized(body)
        if not original:
            continue
        comparable = True
        grams = {original[i : i + 6] for i in range(max(0, len(original) - 5))}
        for candidate in texts:
            if not candidate:
                continue
            longest = (
                SequenceMatcher(None, original, candidate, autojunk=False).find_longest_match().size
            )
            candidate_grams = {candidate[i : i + 6] for i in range(max(0, len(candidate) - 5))}
            common = len(grams & candidate_grams)
            ratio = common / max(1, len(candidate_grams))
            title = normalized(ref.get("title"))
            # Knowledge labels are reusable genre/method names, not work titles.
            title_reuse = (
                identity.startswith("intelligence:") and len(title) >= 4 and title in candidate
            )
            if longest >= 12 or (common >= 6 and ratio >= 0.35) or title_reuse:
                matches.append(
                    {
                        "source_id": identity,
                        "reason": "source_title" if title_reuse else "text_overlap",
                        "longest_fragment": longest,
                        "shared_ngrams": common,
                    }
                )
                break
    status = (
        "risk"
        if matches
        else "no_obvious_overlap"
        if comparable or refs.get("sparks")
        else "unchecked"
    )
    return {"status": status, "matches": matches, "limitations": LIMITATIONS}


def guard(fields, refs):
    value = screen(fields, refs)
    if value["status"] != "no_obvious_overlap":
        raise TaskError(
            "ORIGINALITY_RISK" if value["status"] == "risk" else "INSUFFICIENT_MATERIAL"
        )
    return value
