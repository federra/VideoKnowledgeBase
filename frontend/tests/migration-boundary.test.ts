import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { Linter } from 'eslint';
import globals from 'globals';
const runtime = readFileSync('src/demo/runtime.js', 'utf8');
describe('已迁移页面的旧入口隔离', () => {
  it('不再保留情报流渲染器及另一套日期、分页和筛选状态', () => {
    for (const name of ['feed', 'feedPage', 'feedPager', 'feedDateFilter', 'changeFeedDate', 'audienceFeedbackDialog']) {
      expect(runtime).not.toMatch(new RegExp(`function ${name}\\(`));
    }
    for (const key of ['feedDate','rankPage','creatorPage','feedView','insightOpen','creatorMenuOpen','rankBoard','creators']) {
      expect(runtime).not.toContain(`state.${key}`);
    }
    expect(runtime).not.toContain('changeDate:');
  });
  it('不再接收旧控制台表单对本地来源或名单的写入', () => {
    expect(runtime).not.toContain("f.getAttribute('id')==='rankBoardForm'");
    expect(runtime).not.toContain("f.getAttribute('id')==='creatorForm'");
    expect(runtime).not.toContain("db.sources.unshift(");
  });
  it('不再分发已迁移的反馈、来源、重试及名单模拟操作', () => {
    for (const action of ['feedback-open','feedback-research','toggle-source','retry-job','rank-board-manage','creator-manage']) {
      expect(runtime).not.toContain(`case '${action}':`);
    }
  });
});

it('生成脚本没有悬空的旧日期或事件标识', () => {
  const errors=new Linter().verify(runtime,{languageOptions:{sourceType:'module',globals:globals.browser},rules:{'no-undef':'error'}});
  expect(errors).toEqual([]);
});
