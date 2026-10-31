import httpx
import pytest

from app.connectors.redfox import AdapterError


def page(*, channel="boy", kind="hot", heat="9.6", unit="万", marker="热度", count=2):
    labels = {
        "hot": "大热榜",
        "new": "新书榜",
        "over": "完结榜",
        "collect": "收藏榜",
        "update": "更新榜",
    }
    cards = "".join(
        f"""<li class="rank-list-item"><span class="rank-number">{i}</span>
      <a class="s-book-title" href="https://www.qimao.com/shuku/{i}/">书{i}</a>
      <span class="s-book-info"><a href="https://www.qimao.com/zuozhe/a/">作者</a>
      <a href="https://www.qimao.com/shuku/a-203-a-a-a-a-a-click-1/">都市</a>
      <a href="https://www.qimao.com/shuku/a-203-219-a-a-a-a-click-1/">都市高武</a><em>连载中</em><em>123万字</em></span>
      <span class="s-book-intro">简介{i} &lt;文本&gt;</span>
      <span class="rank-change-num"><em class="rank-num">{heat}</em><em class="rank-unit">{unit}</em><em>{marker}</em></span></li>"""
        for i in range(1, count + 1)
    )
    return f"""<title>七猫免费小说排行榜-{labels[kind]}-七猫中文网</title>
      <span class="item init active">{"男生榜" if channel == "boy" else "女生榜"}</span>
      <div class="child-tabs-item active"><a href="/paihang/{channel}/{kind}/date/">{labels[kind]}</a></div>
      <div class="date-type-tabs"><a class="tab active" href="/paihang/{channel}/{kind}/date/">日榜</a><a class="tab month" href="/paihang/{channel}/{kind}/month/">月榜</a></div>{cards}<div class="rank-page"><span class="num active">1</span></div>"""


def test_fixed_ten_boards_and_strict_request():
    from app.connectors.qimao import boards, validate_board

    values = boards()
    assert len(values) == 10 and len({b["code"] for b in values}) == 10
    assert {b["gender"] for b in values} == {"male", "female"}
    assert {b["rank_name"] for b in values} == {"大热榜", "新书榜", "完结榜", "收藏榜", "更新榜"}
    for bad in (
        {"gender": "all"},
        {"rank_type": "../../"},
        {"code": "qimao:wrong"},
        {"method": "other"},
    ):
        with pytest.raises(AdapterError):
            validate_board({**values[0], **bad})


@pytest.mark.parametrize(
    "heat,unit,expected",
    [("9.6", "万", 96000), ("32.6", "万", 326000), ("1.2", "亿", 120000000), ("0", "", 0)],
)
def test_fields_heat_and_taxonomy(heat, unit, expected):
    from app.connectors.qimao import boards, normalize

    batch = normalize(boards()[0], page(heat=heat, unit=unit))
    assert len(batch.records) == 2
    record = batch.records[0]
    meta = record["content"]["source_tags"][0]
    assert meta["reader_count"] is None
    assert meta["heat_value"] == expected and meta["heat_display"] == heat + unit
    assert meta["work_fields"] == {"gender": None, "genres": ["都市", "都市高武"]}
    assert meta["taxonomy"] == ["都市"] and meta["rank"] == 1
    assert record["content"]["description"] == "简介1 <文本>"
    assert record["content"]["view_count"] is None


def test_rank_movement_and_missing_heat_are_not_heat_or_readers():
    from app.connectors.qimao import boards, normalize

    b = next(b for b in boards() if b["rank_type"] == "collect" and b["gender"] == "male")
    for html in (
        page(kind="collect", marker="名", unit=""),
        page(kind="collect").replace("rank-change-num", "other"),
    ):
        meta = normalize(b, html).records[0]["content"]["source_tags"][0]
        assert (
            meta["heat_value"] is None
            and meta["heat_display"] is None
            and meta["reader_count"] is None
        )


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.replace("男生榜", "女生榜"),
        lambda s: s.replace("/boy/hot/date/", "/boy/new/date/"),
        lambda s: s.replace('num active">1', 'num active">2'),
        lambda s: s.replace("/shuku/2/", "/shuku/1/"),
        lambda s: s.replace("https://www.qimao.com/shuku/1/", "https://evil.test/shuku/1/"),
        lambda s: s.replace("rank-list-item", "other"),
    ],
)
def test_bad_context_or_content_rejected(change):
    from app.connectors.qimao import boards, normalize

    with pytest.raises(AdapterError):
        normalize(boards()[0], change(page()))


def test_truncate_to_20_but_retain_provider_order():
    from app.connectors.qimao import boards, normalize

    batch = normalize(boards()[0], page(count=35))
    assert len(batch.records) == 20 and batch.returned_items == 35
    assert [r["provider_rank"] for r in batch.records] == list(range(1, 21))


@pytest.mark.parametrize("status", [200, 302, 403, 429])
def test_one_public_request_without_redirect_or_retry(status):
    from app.connectors.qimao import Qimao, boards

    requests = []

    def transport(req):
        requests.append(req)
        assert str(req.url) == "https://www.qimao.com/paihang/boy/hot/date/"
        assert "cookie" not in req.headers
        return httpx.Response(status, text=page(), headers={"location": "http://127.0.0.1/"})

    client = httpx.Client(transport=httpx.MockTransport(transport), follow_redirects=False)
    result = Qimao(client).fetch("novel.qimao.board", boards()[0], maximum=20)
    assert len(requests) == 1 and result.http_status == status
    assert (result.batch is not None) == (status == 200)
    assert result.raw_text == page()


def test_monthly_hot_page_cannot_be_sealed_as_daily():
    from app.connectors.qimao import boards, normalize

    html = (
        page()
        .replace('class="tab active"', 'class="tab"')
        .replace('class="tab month"', 'class="tab active"')
    )
    with pytest.raises(AdapterError):
        normalize(boards()[0], html)


@pytest.mark.parametrize("status", ["blocked", "running", "stopped"])
def test_resume_never_continues_a_batch_with_refusal(status):
    from scripts.collect_qimao import validate_resume

    with pytest.raises(RuntimeError):
        validate_resume(
            {"date": "2026-10-31", "status": status, "jobs": [{"calls": [{"http_status": 403}]}]},
            "2026-10-31",
        )


def test_refresh_waits_before_first_qimao_call_after_other_novel_channels():
    from app.connectors.qimao import boards
    from app.intelligence.refresh_channels import Channels
    class Fake:
        def __init__(self):self.events=[]
        def configured(self,cap):return [{'safe_request':b} for b in boards()]
        def begin(self,total):self.events.append(('begin',total))
        def wait(self,seconds):self.events.append(('wait',seconds))
        def one(self,*args):self.events.append(('request',1))
    fake=Fake()
    assert Channels.qimao(fake)[0]=='succeeded'
    assert fake.events[1]==('wait',10)
    assert fake.events.count(('request',1))==10
