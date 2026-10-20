import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../src/app/App';

beforeEach(() => { localStorage.clear(); window.location.hash = '#0/0'; });

describe('Demo 基线与工程导航', () => {
  it('导出后立即卸载也会释放下载用Blob URL', async () => {
    Object.defineProperty(URL, 'createObjectURL', {configurable: true, value: vi.fn(() => 'blob:demo-export')});
    const revoke = vi.fn();
    Object.defineProperty(URL, 'revokeObjectURL', {configurable: true, value: revoke});
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const mounted = render(<App />);
    await screen.findByRole('heading', {name: '情报流'});
    fireEvent.click(screen.getByRole('button', {name: '电商短视频'}));
    fireEvent.click(screen.getByRole('button', {name: '待生产'}));
    fireEvent.click(document.querySelector('[data-action="topic-detail"]')!);
    fireEvent.click(screen.getByRole('button', {name: '导出 Markdown'}));
    expect(URL.createObjectURL).toHaveBeenCalledOnce();
    mounted.unmount();
    expect(revoke).toHaveBeenCalledWith('blob:demo-export');
  });
  it('React日期控件每次只处理一次变更，不重复进入原生事件层', async () => {
    render(<App />);
    await screen.findByRole('heading', {name: '情报流'});
    const save = vi.spyOn(Storage.prototype, 'setItem');
    fireEvent.change(screen.getByLabelText('情报流日期'), {target: {value: '2026-10-03'}});
    expect(save.mock.calls.filter(([key]) => key === 'cip-feed-date')).toHaveLength(1);
    expect((screen.getByLabelText('情报流日期') as HTMLInputElement).value).toBe('2026-10-03');
  });
  it('兼容带斜杠的路由，并将无效模块回退到情报流', async () => {
    window.location.hash = '#/3/4';
    render(<App />);
    await screen.findByRole('heading', {name: '运行状态'});
    window.location.hash = '#/99/99';
    await screen.findByRole('heading', {name: '情报流'});
  });
  it('提供四入口、16个工作区，保留跨模块业务选择', async () => {
    render(<App />);
    await screen.findByRole('heading', {name: '情报流'});
    fireEvent.click(screen.getByRole('button', {name: 'AI漫剧'}));
    const groups = [
      ['情报局', ['情报流', '选题卡', '待生产']],
      ['研判室', ['内容研判', '发布复盘', '规律验证']],
      ['藏经阁', ['知识浏览', '入库处理', '审核队列', '回收站']],
      ['控制台', ['采集配置', '处理配置', '评价标准', '权限管理', '运行状态', '模型配置']],
    ] as const;
    for (const [name, tabs] of groups) {
      fireEvent.click(screen.getByRole('button', {name}));
      for (const tab of tabs) {
        fireEvent.click(screen.getByRole('button', {name: tab}));
        await screen.findByRole('heading', {name: tab});
        expect(screen.getByRole('button', {name: 'AI漫剧'}).getAttribute('aria-pressed')).toBe('true');
      }
    }
  });
  it('真实页切换主题和业务可保留，存储与原 Demo 隔离', async () => {
    localStorage.setItem('content-ui-v1', 'original-untouched');
    render(<App />);
    await screen.findByRole('heading', {name: '情报流'});
    fireEvent.click(screen.getByRole('button', {name: '切换深色主题'}));
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(localStorage.getItem('content-ui-v1')).toBe('original-untouched');
    expect(localStorage.getItem('cip-demo-theme')).toBe('dark');
  });
  it('卸载再挂载不累积全局监听器，闪念每次只新增一条', async () => {
    const first = render(<App />);
    await screen.findByRole('heading', {name: '情报流'});
    first.unmount();
    render(<App />);
    await screen.findByRole('heading', {name: '情报流'});
    fireEvent.click(screen.getByRole('button', {name: '打开闪念胶囊'}));
    fireEvent.input(screen.getByRole('textbox', {name: '记录灵感，输入后自动保存'}), {target: {value: '测试灵感'}});
    const db = JSON.parse(localStorage.getItem('cip-demo-v1')!);
    expect(db.sparks).toHaveLength(1);
    expect(db.topics.filter((topic: {origin: string}) => topic.origin === '闪念胶囊')).toHaveLength(0);
  });
});

it('正式研判入口不渲染旧演示作品和报告',async()=>{
 localStorage.setItem('cip-demo-v1-workspace','AI漫剧');window.location.hash='#2/0';
 render(<App/>);await screen.findByText(/正在连接本地工作区|连接失败|无法连接|请求失败/);
 expect(screen.queryByRole('button',{name:'逆风归城 · 多集演示'})).toBeNull();
 expect(document.querySelector('[data-action="work-unit"]')).toBeNull();
});

it('旧来源表单不再进入任何Demo业务写入分支',async()=>{
 render(<App/>);await screen.findByRole('heading',{name:'情报流'});
 const before=JSON.parse(localStorage.getItem('cip-demo-v1')!);
 const form=document.createElement('form');form.id='simpleForm';form.dataset.kind='source';
 form.innerHTML='<input name="title" value="obsolete-source"><input name="value" value="https://example.com"><input name="biz" value="AI漫剧">';document.body.append(form);
 fireEvent.submit(form);form.remove();
 const after=JSON.parse(localStorage.getItem('cip-demo-v1')!);
 for(const key of ['sources','research','works'])expect(after[key]).toEqual(before[key]);
});

it('知识来源深链接切换顶部业务同时保留材料与段落路由',async()=>{
 localStorage.setItem('cip-demo-v1-workspace','故事短片');
 const path='2/0/work/11111111-1111-4111-8111-111111111111/episodes/unknown/22222222-2222-4222-8222-222222222222?source_business=motion_comic&paragraph=3';
 window.location.hash='#/'+path;
 render(<App/>);
 await vi.waitFor(()=>expect(screen.getByRole('button',{name:'AI漫剧'}).getAttribute('aria-pressed')).toBe('true'));
 expect(window.location.hash.replace(/^#\//,'')).toBe(path);
});
