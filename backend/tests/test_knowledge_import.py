"""Import parsing must preserve original wording and distinct source classifications."""

import pytest


def test_quotes_merge_exact_duplicates_keep_all_locations_and_stage_note():
    from app.knowledge.legacy_import import parse_quotes

    rows = parse_quotes("""## 二、共鸣金句库（200+条）
### 2.1 男频金句库
#### 男频 · 复仇
1. "守护。"
#### 男频 · 守护
2. "守护。"
3. "I accept." (Cold, no tears)
## 三、18爽点内核库
1. "不导入"
""")
    assert len(rows) == 2
    assert rows[0]["text"] == "守护。"
    assert [x["number"] for x in rows[0]["locations"]] == ["1", "2"]
    assert rows[1]["note"] == "(Cold, no tears)"


def test_genres_preserve_same_name_in_distinct_codes_and_ignore_mapping():
    from app.knowledge.legacy_import import parse_genres

    rows = parse_genres("""# 模块16 · 海外本土化 + 140+题材库
## 二、A线题材库
### 2.2 女频题材库
#### 特殊题材女频
F27 · 民国情仇
### 2.3 特别题材（男女通用）
S08 · 民国情仇
## 三、B线题材库
### 3.1 Female B线
#### B线女频Romance
BF25 · Forbidden Romance（成年人间）
## 四、A↔B对应速查表
M99 · 不导入
""")
    assert [r["code"] for r in rows] == ["F27", "S08", "BF25"]
    assert rows[2]["text"] == "Forbidden Romance（成年人间）"


def test_parser_rejects_missing_section_and_duplicate_code():
    from app.knowledge.legacy_import import parse_genres, parse_quotes

    with pytest.raises(ValueError):
        parse_quotes("无金句清单")
    with pytest.raises(ValueError):
        parse_genres("# 模块16 · 海外本土化 + 140+题材库\nM01 · A\nM01 · B\n## 四、A↔B对应速查表")


def test_failures_preserve_full_blocks_and_reject_missing_fields_or_codes():
    from app.knowledge.legacy_import import parse_failures

    text = """# 模块10 · 41翻车点反模式手册
## 二、41翻车点完整清单
### 2.1 入口阶段翻车点（5条）
#### TP01 · 跳过分流直接立项
**描述**：原始描述。
**后果**：原始后果。
**修复**：原始修复。
#### TP02 · 第二条
**描述**：描述2。
**后果**：后果2。
**修复**：修复2。
## 三、`/anti_pattern` 命令规范
#### TP03 · 不导入
"""
    rows = parse_failures(text)
    assert len(rows) == 2
    assert rows[0]["text"] == "跳过分流直接立项"
    assert "**后果**：原始后果。" in rows[0]["body"]
    assert rows[0]["body"] == rows[0]["locations"][0]["original"]
    for broken in [
        text.replace("**修复**：原始修复。", ""),
        text.replace("TP02", "TP01"),
        text.replace("TP02", "TP03"),
    ]:
        with pytest.raises(ValueError):
            parse_failures(broken)


def test_payoffs_preserve_descriptions_and_reject_broken_numbering():
    from app.knowledge.legacy_import import parse_payoffs

    text = "### 3.1 18爽点完整清单\n1. 反杀爽：被欺压后强势反击\n2. 装逼爽：低调中突然亮真实身份\n### 3.2 v3.0四大案例爽点配置"
    rows = parse_payoffs(text)
    assert [r["text"] for r in rows] == ["反杀爽", "装逼爽"]
    assert rows[0]["body"] == "反杀爽：被欺压后强势反击"
    assert rows[0]["locations"][0]["original"] == "1. 反杀爽：被欺压后强势反击"
    for broken in [
        text.replace("2. 装", "1. 装"),
        text.replace("2. 装", "3. 装"),
        text.replace("：低调中突然亮真实身份", "："),
    ]:
        with pytest.raises(ValueError):
            parse_payoffs(broken)
