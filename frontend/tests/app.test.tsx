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
    const initial=render(<App realTopics={false}/>);await screen.findByRole('heading',{name:'情报流'});initial.unmount();
    const saved=JSON.parse(localStorage.getItem('cip-demo-v1')!);saved.topics.find((t:{id:string})=>t.id==='T-102').status='待生产';localStorage.setItem('cip-demo-v1',JSON.stringify(saved));
    const mounted = render(<App realTopics={false} />);
    await screen.findByRole('heading', {name: '情报流'});
    fireEvent.click(screen.getByRole('button', {name: '故事短片'}));
    fireEvent.click(screen.getByRole('button', {name: '待生产'}));
    fireEvent.click(document.querySelector('[data-action="topic-detail"]')!);
    fireEvent.click(screen.getByRole('button', {name: '导出 Markdown'}));
    expect(URL.createObjectURL).toHaveBeenCalledOnce();
    mounted.unmount();
    expect(revoke).toHaveBeenCalledWith('blob:demo-export');
  });
  it('切换业务后日期栏仍只有一份采集操作和日历',async()=>{
    render(<App realTopics={false}/>);
    await screen.findByRole('heading',{name:'情报流'});
    for(const business of ['AI漫剧','故事短片','AI漫剧']){
      fireEvent.click(screen.getByRole('button',{name:business}));
      expect(screen.getAllByRole('button',{name:'重新采集'})).toHaveLength(1);
      expect(screen.getAllByRole('button',{name:'情报流日期'})).toHaveLength(1);
    }
  });
  it('React日期控件每次只处理一次变更，不重复进入原生事件层', async () => {
    localStorage.setItem('cip-feed-date','2026-10-30');
    render(<App realTopics={false} />);
    await screen.findByRole('heading', {name: '情报流'});
    const save = vi.spyOn(Storage.prototype, 'setItem');
    fireEvent.click(screen.getByRole('button',{name:'情报流日期'}));
    fireEvent.click(await screen.findByRole('button',{name:/2026-10-03，/}));
    expect(save.mock.calls.filter(([key]) => key === 'cip-feed-date')).toHaveLength(1);
    expect(screen.getByRole('button',{name:'情报流日期'}).textContent).toBe('2026/10/03');
  });
  it('兼容带斜杠的路由，并将无效模块回退到情报流', async () => {
    window.location.hash = '#/3/4';
    render(<App realTopics={false} />);
    await screen.findByRole('heading', {name: '运行状态'});
    window.location.hash = '#/99/99';
    await screen.findByRole('heading', {name: '情报流'});
  });
  it('暂隐藏研判室和知识处理入口，保留可见工作区的业务选择', async () => {
    render(<App realTopics={false} />);
    await screen.findByRole('heading', {name: '情报流'});
    fireEvent.click(screen.getByRole('button', {name: 'AI漫剧'}));
    expect(screen.queryByRole('button', {name: '研判室'})).toBeNull();
    const commerce=screen.getByRole('button',{name:'电商（建设中）'});expect(commerce.hasAttribute('disabled')).toBe(true);fireEvent.click(commerce);expect(screen.getByRole('button',{name:'AI漫剧'}).getAttribute('aria-pressed')).toBe('true');
    const groups = [
      ['情报局', ['情报流', '选题卡', '待生产']],
      ['藏经阁', ['知识浏览', '回收站']],
      ['控制台', ['采集配置', '处理配置', '评价标准', '权限管理', '运行状态', '模型配置']],
    ] as const;
    for (const [name, tabs] of groups) {
      fireEvent.click(screen.getByRole('button', {name}));
      if (name === '藏经阁') {
        expect(screen.queryByRole('button', {name: '入库处理'})).toBeNull();
        expect(screen.queryByRole('button', {name: '审核队列'})).toBeNull();
      }
      for (const tab of tabs) {
        fireEvent.click(screen.getByRole('button', {name: tab}));
        await screen.findByRole('heading', {name: tab});
        if (tab === '回收站') expect(window.location.hash).toMatch(/1\/3$/);
        if (tab === '模型配置') expect(window.location.hash).toMatch(/3\/5$/);
        expect(screen.getByRole('button', {name: 'AI漫剧'}).getAttribute('aria-pressed')).toBe('true');
      }
    }
  });
  it('真实页切换主题和业务可保留，存储与原 Demo 隔离', async () => {
    localStorage.setItem('content-ui-v1', 'original-untouched');
    render(<App realTopics={false} />);
    await screen.findByRole('heading', {name: '情报流'});
    fireEvent.click(screen.getByRole('button', {name: '切换深色主题'}));
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(localStorage.getItem('content-ui-v1')).toBe('original-untouched');
    expect(localStorage.getItem('cip-demo-theme')).toBe('dark');
  });
  it('卸载再挂载不累积全局监听器，闪念每次只新增一条', async () => {
    const first = render(<App realTopics={false} />);
    await screen.findByRole('heading', {name: '情报流'});
    first.unmount();
    render(<App realTopics={false} />);
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
 render(<App realTopics={false}/>);await screen.findByText(/正在连接本地工作区|连接失败|无法连接|请求失败/);
 expect(screen.queryByRole('button',{name:'逆风归城 · 多集演示'})).toBeNull();
 expect(document.querySelector('[data-action="work-unit"]')).toBeNull();
});

it('旧来源表单不再进入任何Demo业务写入分支',async()=>{
 render(<App realTopics={false}/>);await screen.findByRole('heading',{name:'情报流'});
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
 render(<App realTopics={false}/>);
 await vi.waitFor(()=>expect(screen.getByRole('button',{name:'AI漫剧'}).getAttribute('aria-pressed')).toBe('true'));
 expect(window.location.hash.replace(/^#\//,'')).toBe(path);
});

it('切换TikHub或红果只更换榜单，不自动改写所选日期和日期偏好',async()=>{
 const id='11111111-1111-4111-8111-111111111111';
 const calls:string[]=[];
 vi.spyOn(globalThis,'fetch').mockImplementation(async(input:RequestInfo|URL)=>{
  const u=new URL(String(input),'http://local');calls.push(u.pathname+u.search);
  const business=u.searchParams.get('business_code')??'motion_comic',date=u.searchParams.get('business_date')??'2026-10-30';
  const data=u.pathname.endsWith('/session')?{org_id:id,member_id:id,authz_version:'1',csrf_token:'a'.repeat(64),display_name:'南哥',actions:['content.read'],expires_at:'2099-10-17T01:00:00Z'}:u.pathname.endsWith('/novels')?{business_code:business,business_date:date,novel_count:null,page:1,page_size:10,total:'0',items:[],rank_types:[],genders:[],genres:[],statuses:[]}:{business_code:business,business_date:date,has_snapshot:true,metrics:{videos:'60',creators:'3',comments:null,likes:null},video_latest_dates:{hongguo:'2026-10-30',tikhub:'2026-10-27'},boards:[],creators:[],page:1,page_size:10,total:'0',items:[],insight:null};
  return new Response(JSON.stringify({request_id:id,data}),{headers:{'Content-Type':'application/json'}});
 });
 localStorage.setItem('cip-feed-date','2026-10-30');localStorage.setItem('cip-demo-v1-workspace','AI漫剧');
 render(<App realTopics={false}/>);
 await vi.waitFor(()=>expect(document.querySelector('.feed-overview strong')?.textContent).toBe('60'));
 fireEvent.change(screen.getByRole('combobox',{name:'榜单类型'}),{target:{value:'tikhub'}});
 await vi.waitFor(()=>expect(calls.some(path=>path.includes('video_catalog=tikhub'))).toBe(true));
 expect(screen.getByRole('button',{name:'情报流日期'}).textContent).toBe('2026/10/30');
 expect(localStorage.getItem('cip-feed-date')).toBe('2026-10-30');
 await screen.findByText(/最近已保存日期为 2026-10-27/);
 fireEvent.change(screen.getByRole('combobox',{name:'榜单类型'}),{target:{value:'hongguo'}});
 expect((screen.getByRole('combobox',{name:'榜单类型'}) as HTMLSelectElement).value).toBe('hongguo');
 expect(screen.getByRole('button',{name:'情报流日期'}).textContent).toBe('2026/10/30');
 expect(calls.filter(path=>path.includes('/intelligence/')).every(path=>!path.includes('business_date=2026-10-27'))).toBe(true);
});
