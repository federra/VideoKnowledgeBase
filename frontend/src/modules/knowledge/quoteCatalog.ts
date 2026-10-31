import type {KnowledgeItem} from "../../api/client";
// K09原文分组；B线后两组女频映射经用户2026-10-22确认。
export const quoteCatalog = [
  {
    "source": "男频 · 仇恨/复仇主题（20条）",
    "line": "A",
    "gender": "男频",
    "label": "仇恨/复仇",
    "mapped": false
  },
  {
    "source": "男频 · 爽感/装逼主题（20条）",
    "line": "A",
    "gender": "男频",
    "label": "爽感/装逼",
    "mapped": false
  },
  {
    "source": "男频 · 怜悯/守护主题（20条）",
    "line": "A",
    "gender": "男频",
    "label": "怜悯/守护",
    "mapped": false
  },
  {
    "source": "男频 · 好奇/探索主题（20条）",
    "line": "A",
    "gender": "男频",
    "label": "好奇/探索",
    "mapped": false
  },
  {
    "source": "女频 · 虐恋/抛弃主题（20条）",
    "line": "A",
    "gender": "女频",
    "label": "虐恋/抛弃",
    "mapped": false
  },
  {
    "source": "女频 · 甜宠/总裁主题（20条）",
    "line": "A",
    "gender": "女频",
    "label": "甜宠/总裁",
    "mapped": false
  },
  {
    "source": "女频 · 爽感/反杀主题（20条）",
    "line": "A",
    "gender": "女频",
    "label": "爽感/反杀",
    "mapped": false
  },
  {
    "source": "女频 · 共情/守护主题（20条）",
    "line": "A",
    "gender": "女频",
    "label": "共情/守护",
    "mapped": false
  },
  {
    "source": "B线 · Female Heartbreak (10)",
    "line": "B",
    "gender": "女频",
    "label": "Female Heartbreak",
    "mapped": false
  },
  {
    "source": "B线 · Female Catharsis/Power (10)",
    "line": "B",
    "gender": "女频",
    "label": "Female Catharsis/Power",
    "mapped": false
  },
  {
    "source": "B线 · Werewolf/Supernatural (10)",
    "line": "B",
    "gender": "女频",
    "label": "Werewolf/Supernatural",
    "mapped": true
  },
  {
    "source": "B线 · Marriage of Convenience/Sweet (10)",
    "line": "B",
    "gender": "女频",
    "label": "Marriage of Convenience/Sweet",
    "mapped": true
  }
];
export function quoteGroups(item:Pick<KnowledgeItem,"tags">){return quoteCatalog.filter(g=>item.tags.some(t=>t.kind==="genre"&&t.code===g.source));}
export function quoteLines(item:Pick<KnowledgeItem,"tags">){return [...new Set([...quoteGroups(item).map(g=>g.line),...item.tags.filter(t=>t.kind==='task'&&['quote_line_A','quote_line_B'].includes(t.code)).map(t=>t.code.slice(-1))])];}
export function quoteSummary(item:Pick<KnowledgeItem,"tags">){const groups=quoteGroups(item);return [...quoteLines(item).map(l=>l+"线"),...new Set(groups.map(g=>g.gender)),...groups.map(g=>g.label),...item.tags.filter(t=>t.kind==='genre'&&!groups.some(g=>g.source===t.code)).map(t=>t.code)].join(" · ");}
