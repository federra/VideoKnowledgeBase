import type {KnowledgeItem} from "../../api/client";
// K10 模块16的原始分组；仅匹配明确来源，不从标题猜测。
export const genreCatalog = [
  {
    "line": "A",
    "gender": "男频",
    "label": "都市男频",
    "source": "都市男频（15个）"
  },
  {
    "line": "A",
    "gender": "男频",
    "label": "玄幻/古风男频",
    "source": "玄幻/古风男频（10个）"
  },
  {
    "line": "A",
    "gender": "男频",
    "label": "特殊题材男频",
    "source": "特殊题材男频（10个）"
  },
  {
    "line": "A",
    "gender": "女频",
    "label": "都市女频",
    "source": "都市女频（15个）"
  },
  {
    "line": "A",
    "gender": "女频",
    "label": "古风女频",
    "source": "古风女频（10个）"
  },
  {
    "line": "A",
    "gender": "女频",
    "label": "特殊题材女频",
    "source": "特殊题材女频（10个）"
  },
  {
    "line": "A",
    "gender": "男女通用",
    "label": "特别题材",
    "source": "2.3 特别题材（10个，男女通用）"
  },
  {
    "line": "B",
    "gender": "女频",
    "label": "Romance",
    "source": "B线女频Romance（25个）"
  },
  {
    "line": "B",
    "gender": "女频",
    "label": "Supernatural",
    "source": "B线女频Supernatural（15个）"
  },
  {
    "line": "B",
    "gender": "女频",
    "label": "Drama",
    "source": "B线女频Drama（5个）"
  },
  {
    "line": "B",
    "gender": "男频／混合",
    "label": "Male/Mixed",
    "source": "3.2 Male/Mixed B线（15个）"
  }
];
export function genreGroup(item:Pick<KnowledgeItem,"tags">){
 const matches=genreCatalog.filter(g=>item.tags.some(t=>t.kind==="genre"&&t.code===g.source));
 return matches.length===1?matches[0]:undefined;
}
