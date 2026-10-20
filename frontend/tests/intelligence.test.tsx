import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import { ApiClient } from '../src/api/client';
import { ApiProvider } from '../src/api/provider';
import { IntelligencePage } from '../src/modules/intelligence/IntelligencePage';
const id='11111111-1111-4111-8111-111111111111';
const session={org_id:id,member_id:id,authz_version:'1',csrf_token:'a'.repeat(64),display_name:'南哥',actions:['content.read'],expires_at:'2099-10-17T01:00:00Z'};
const empty={business_code:'motion_comic',business_date:'2026-10-17',has_snapshot:false,metrics:{videos:null,creators:null,comments:null,likes:null},boards:[],creators:[],page:1,page_size:10,total:'0',items:[],insight:null};
const novelEmpty={business_code:'motion_comic',business_date:'2026-10-17',novel_count:null,page:1,page_size:10,total:'0',items:[],rank_types:[],genders:[],genres:[],statuses:[]};
function mount(load:(path:string)=>unknown=path=>path.includes('/novels?')?novelEmpty:empty){
 const fetcher=vi.fn(async(input:RequestInfo|URL)=>new Response(JSON.stringify({request_id:id,data:String(input)==='/api/v1/session'?session:load(String(input))}),{headers:{'Content-Type':'application/json','X-Request-ID':id}}));
 render(<QueryClientProvider client={new QueryClient()}><ApiProvider client={new ApiClient({fetcher:fetcher as typeof fetch})}><IntelligencePage business="AI漫剧" date="2026-10-17" /></ApiProvider></QueryClientProvider>);
 return fetcher;
}
describe('真实情报流',()=>{
 it('打开即获取本地上下文，历史缺失不显示演示样例或零',async()=>{
  mount();await screen.findByText(/暂无历史数据：该日期未保存/);
  expect(screen.queryByRole('link',{name:'本地接口登录'})).toBeNull();
  expect(document.querySelectorAll('.metric-card strong')).toHaveLength(3);
  expect(Array.from(document.querySelectorAll('.metric-card span')).map(x=>x.textContent)).toEqual(['视频','博主','小说']);
  expect(Array.from(document.querySelectorAll('.metric-card strong')).map(x=>x.textContent)).toEqual(['未获取','未获取','未获取']);
  expect(screen.queryByText('开学那天，我被当成传说')).toBeNull();
 });
 it('保留榜单达人互斥、搜索与洞察收展，查询带精确业务日期',async()=>{
  const fetcher=mount();await screen.findByText(/暂无历史数据：该日期未保存/);
  fireEvent.click(screen.getByRole('button',{name:'博主'}));
  await screen.findByRole('button',{name:'全部达人'});
  fireEvent.change(screen.getByRole('textbox',{name:'搜索当前工作区'}),{target:{value:'漫剧'}});
  await waitFor(()=>expect(fetcher.mock.calls.some(([p])=>String(p).includes('lane=creator')&&String(p).includes('q=%E6%BC%AB%E5%89%A7')&&String(p).includes('business_date=2026-10-17'))).toBe(true));
  fireEvent.click(screen.getByRole('button',{name:'收起洞察报告'}));
  expect(screen.getByRole('button',{name:'展开洞察报告'})).toBeTruthy();
 });
 it('原始描述按文本渲染，未知值不记零，危险原链接不可点击',async()=>{
  mount(()=>({...empty,has_snapshot:true,metrics:{videos:null,creators:'1',comments:null,likes:'0'},total:'1',items:[{source_id:id,source_name:'真实来源',snapshot_version:1,account_id:id,author:'UID:123',entry:{id,lock_version:'1',created_at:'2026-10-17T01:00:00Z',updated_at:'2026-10-17T01:00:00Z',snapshot_id:id,position:0,provider_rank:null,feedback_id:null,observation:{id,kind:'content',platform_code:'douyin',platform_id:'123',display_name:null,description:'<img src=x onerror=alert(1)>原始文案',original_url:'javascript:alert(1)',observed_at:'2026-10-17T01:00:00Z',published_at:null,published_at_raw:null,follower_count:null,work_count:null,like_count:'0',comment_count:null,share_count:null,collect_count:null,repost_count:null,view_count:null}}}]}));
  await screen.findByText('<img src=x onerror=alert(1)>原始文案');
  expect(document.querySelector('.rank-card img')).toBeNull();
  expect(document.querySelector('.rank-card a')).toBeNull();
  expect(document.querySelector('.rank-stats')?.textContent).toContain('赞0');
 });
});

it('切换日期清除已失效达人选择，避免隐藏筛选造成假空态',async()=>{
 const old='11111111-1111-4111-8111-111111111111',next='22222222-2222-4222-8222-222222222222';
 const fetcher=vi.fn(async(input:RequestInfo|URL)=>{
  const path=String(input);const day=path.includes('business_date=2026-10-16')?'2026-10-16':'2026-10-17';
  const data=path==='/api/v1/session'?session:{...empty,business_date:day,has_snapshot:true,creators:[{id:day==='2026-10-16'?old:next,name:day==='2026-10-16'?'昨天达人':'今天达人'}]};
  return new Response(JSON.stringify({request_id:id,data}),{headers:{'Content-Type':'application/json','X-Request-ID':id}});
 });
 const api=new ApiClient({fetcher:fetcher as typeof fetch}),queries=new QueryClient();
 function Page({day}:{day:string}){return <QueryClientProvider client={queries}><ApiProvider client={api}><IntelligencePage business="AI漫剧" date={day}/></ApiProvider></QueryClientProvider>;}
 const mounted=render(<Page day="2026-10-16"/>);
 fireEvent.click(await screen.findByRole('button',{name:'博主'}));
 fireEvent.click(await screen.findByRole('button',{name:'全部达人'}));
 fireEvent.click(await screen.findByRole('button',{name:'昨天达人'}));
 await screen.findByRole('button',{name:/1 位达人/});
 mounted.rerender(<Page day="2026-10-17"/>);
 await waitFor(()=>expect(screen.queryByRole('button',{name:/1 位达人/})).toBeNull());
 await waitFor(()=>expect(fetcher.mock.calls.some(([p])=>String(p).includes('business_date=2026-10-17')&&!String(p).includes('accounts='))).toBe(true));
});

it('同日洞察显示封存样本口径，未知母题不伪造，切换筛选不重算',async()=>{
 const fetcher=mount(()=>({...empty,has_snapshot:true,insight:{id,created_at:'2026-10-17T05:00:00Z',business_code:'motion_comic',business_date:'2026-10-17',feedback_id:id,version_no:1,sample_count:20,classified_count:6,emotions:[{name:'期待',count:6,percent:100}],motif:null,genre:null,suggestions:['保留悬念，验证下一集反应'],coverage_note:'仅一条作品样本，不代表市场整体。'}}));
 await screen.findByText('期待 100%（6条）');
 expect(screen.getByText(/20 条评论 · 情绪分类 6 条/)).toBeTruthy();
 expect(screen.getAllByText('证据不足').length).toBe(2);
 expect(screen.getByText('保留悬念，验证下一集反应')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'博主'}));
 await waitFor(()=>expect(fetcher.mock.calls.some(([x])=>String(x).includes('lane=creator'))).toBe(true));
 expect(await screen.findByText('期待 100%（6条）')).toBeTruthy();
});

it('关键词缺播放量时明确拒绝成榜，不引导当作达人更新',async()=>{
 mount(()=>({...empty,has_snapshot:true,keyword_works_count:'10',keyword_ranking_status:'insufficient_metrics'}));
 await screen.findByText(/缺少播放量及可核验默认顺序批次/);
 expect(screen.getByText(/关键词候选不计作达人监测更新/)).toBeTruthy();
 expect(document.querySelectorAll('.rank-card')).toHaveLength(0);
});

it('默认顺序批次明确说明相关性与时效性，不再因未知播放量挡住列表',async()=>{
 mount(()=>({...empty,has_snapshot:true,keyword_works_count:'10',keyword_ranking_status:'default_order'}));
 expect(await screen.findByText(/默认相关性排序（红狐接口）/)).toBeTruthy();
 expect(screen.getByText(/相关性、时效性等因素/)).toBeTruthy();
 expect(screen.queryByText(/当前尚无可用默认排序批次/)).toBeNull();
});

it('每日热门榜采用平台分类来源，不显示旧关键词搜索口径',async()=>{
 mount(()=>({...empty,has_snapshot:true,keyword_works_count:'20',keyword_ranking_status:'provider_order',boards:[{id,name:'小剧场 · 红狐每日热门作品榜 · 数据日期 2026-10-16'}]}));
 expect(await screen.findByText(/保留接口返回顺序展示前10条/)).toBeTruthy();
 expect(screen.queryByText(/已保存.*关键词候选/)).toBeNull();
 expect(document.querySelector('.notice')?.textContent).toContain('数据日期 2026-10-16');
});

it('小剧场榜单空返回不套用关键词或播放量要求',async()=>{
 mount(()=>({...empty,has_snapshot:true,keyword_ranking_status:'provider_order'}));
 expect(await screen.findByText('该请求日期未返回可展示的小剧场视频。')).toBeTruthy();
 expect(screen.queryByText('尚无符合关键词和播放量排序要求的数据。')).toBeNull();
});

it('TikHub短剧热榜说明整剧统计及简介来源，不混旧榜单口径',async()=>{
 mount(()=>({...empty,has_snapshot:true,keyword_works_count:'20',keyword_ranking_status:'series_order'}));
 expect(await screen.findByText(/当前暂用TikHub短剧热榜/)).toBeTruthy();
 expect(screen.getByText(/简介来自series.desc/)).toBeTruthy();
 expect(screen.queryByText(/当前采用.*小剧场/)).toBeNull();
 expect(screen.queryByText(/已保存.*关键词候选/)).toBeNull();
});

it('小说入口不使用视频接口或演示数据，不显示视频互动指标',async()=>{
 const fetcher=mount();await screen.findByText(/暂无历史数据：该日期未保存/);
 fireEvent.click(screen.getByRole('button',{name:'小说'}));await screen.findByText('暂无小说数据');
 const calls=fetcher.mock.calls.length;
 expect(screen.getByRole('button',{name:'视频'})).toBeTruthy();expect(screen.getByRole('button',{name:'博主'})).toBeTruthy();
 expect(document.querySelectorAll('.metric-card')).toHaveLength(3);expect(document.querySelector('.rank-stats:not(.novel-stats)')).toBeNull();
 expect(screen.getByText(/在读人数 · 未获取/)).toBeTruthy();
 await Promise.resolve();expect(fetcher.mock.calls).toHaveLength(calls);
 fireEvent.click(screen.getByRole('button',{name:'视频'}));await screen.findByText(/暂无历史数据：该日期未保存/);
});

it('小说平台与三类真实标签筛选请求保持独立，起点受限不冒充空榜',async()=>{
 const novel={...novelEmpty,novel_count:'12',rank_types:[{value:'read',label:'阅读榜'}],genders:[{value:'male',label:'男频'}],genres:[{value:'科幻',label:'科幻'}],statuses:[{platform:'qidian',board:'qidian:catalog',state:'failed',http_status:202}]};
 const fetcher=mount(path=>path.includes('/novels?')?novel:empty);await screen.findByText(/暂无历史数据：该日期未保存/);
 fireEvent.click(screen.getByRole('button',{name:'小说'}));await screen.findByText('阅读榜');
 expect(screen.getByText(/起点中文网.*202.*受限/)).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'科幻'}));
 await waitFor(()=>expect(fetcher.mock.calls.some(([p])=>String(p).includes('genre=%E7%A7%91%E5%B9%BB'))).toBe(true));
 fireEvent.change(screen.getByRole('combobox',{name:'小说平台'}),{target:{value:'qidian'}});
 await waitFor(()=>expect(fetcher.mock.calls.some(([p])=>String(p).includes('platform=qidian')&&!String(p).includes('genre='))).toBe(true));
 expect(document.querySelector('.rank-stats:not(.novel-stats)')).toBeNull();
});

it('小说三项条件累加，不在请求切换后丢失已选榜型',async()=>{
 const novel={...novelEmpty,novel_count:'30',rank_types:[{value:'read',label:'阅读榜'}],genders:[{value:'male',label:'男频'}],genres:[{value:'科幻',label:'科幻'}]};
 const fetcher=mount(path=>path.includes('/novels?')?novel:empty);await screen.findByText(/暂无历史数据：该日期未保存/);
 fireEvent.click(screen.getByRole('button',{name:'小说'}));await screen.findByText('阅读榜');
 fireEvent.click(screen.getByRole('button',{name:'阅读榜'}));await waitFor(()=>expect(screen.getByRole('button',{name:'阅读榜'}).getAttribute('aria-pressed')).toBe('true'));
 fireEvent.click(screen.getByRole('button',{name:'男频'}));await waitFor(()=>expect(screen.getByRole('button',{name:'男频'}).getAttribute('aria-pressed')).toBe('true'));
 fireEvent.click(screen.getByRole('button',{name:'科幻'}));await waitFor(()=>expect(fetcher.mock.calls.some(([p])=>{const u=new URL(String(p),'http://local');return u.searchParams.get('rank_type')==='read'&&u.searchParams.get('gender')==='male'&&u.searchParams.get('genre')==='科幻';})).toBe(true));
});

it.each([
 {platform:'fanqie',url:'https://fanqienovel.com/page/123',gender:null,genre:null,expected:['女频','女频衍生']},
 {platform:'fanqie',url:'https://fanqienovel.com/page/123',gender:'male',genre:'科幻',expected:['男频','女频衍生']},
 {platform:'qidian',url:'https://www.qdmm.com/book/123/',gender:null,genre:'玄幻言情',categoryId:'all',categoryName:'全站',expected:['女频','玄幻言情'],method:'qidian-desktop-html-v1'},
 {platform:'qidian',url:'https://www.qdmm.com/book/123/',gender:null,genre:'玄幻言情',categoryId:'all',categoryName:'全站',expected:['女频','玄幻言情'],method:'qidian-browser-ax-v1'},
 {platform:'fanqie',url:'https://fanqienovel.com/page/123',gender:null,genre:null,boardGender:'male',categoryName:'传统玄幻',expected:['男频','传统玄幻']},
 {platform:'qidian',url:'https://www.qdmm.com/book/123/',gender:null,genre:null,categoryId:'all',categoryName:'全站',expected:['女频','题材：—']},
 {platform:'qidian',url:'https://www.qdmm.com/book/123/',gender:null,genre:null,boardGender:'all',categoryId:'all',categoryName:'全站',expected:['男女频：—','题材：—']},
 {platform:'fanqie',url:'https://fanqienovel.com/page/123',gender:null,genre:'科幻',categoryId:'8',categoryName:'目录外题材',expected:['女频','题材：—']},
 {platform:'fanqie',url:'https://fanqienovel.com/page/123',gender:null,genre:null,categoryId:'0',categoryName:'全部',expected:['女频','题材：—']},
])('小说题材使用筛选目录名称、子榜优先且全站不充题材 $gender $genre $platform $categoryName',async({platform,url,gender,genre,expected,method,boardGender,categoryId,categoryName})=>{
 const novel={...novelEmpty,novel_count:'1',total:'1',genres:[{value:'传统玄幻',label:'传统玄幻'},{value:'科幻',label:'科幻'},{value:'女频衍生',label:'女频衍生'},{value:'玄幻言情',label:'玄幻言情'}],items:[{reader_count:platform==='qidian'?null:'0',rank:13,work_gender:gender,work_genre:genre,board:{platform,method,rank_type:'new',gender:boardGender??'female',category_id:categoryId??'8',category_name:categoryName??'女频衍生',code:'fanqie:new:female:8'},item:{source_id:id,source_name:'新书榜 · 女频衍生',snapshot_version:1,account_id:null,author:'真实作者',entry:{id,created_at:'2026-10-17T01:00:00Z',snapshot_id:id,position:0,provider_rank:1,feedback_id:null,observation:{id,kind:'content',platform_code:platform,platform_id:'123',display_name:'真实小说标签样本',description:'不得从简介猜题材',original_url:url,observed_at:'2026-10-17T01:00:00Z',published_at:null,published_at_raw:null,follower_count:null,work_count:null,like_count:null,comment_count:null,share_count:null,collect_count:null,repost_count:null,view_count:null}}}}]};
 mount(path=>path.includes('/novels?')?novel:empty);await screen.findByRole('button',{name:'小说'});fireEvent.click(screen.getByRole('button',{name:'小说'}));await screen.findByText('真实小说标签样本');
 expect(document.querySelector('.novel-card .rank-number')?.textContent).toBe(platform==='fanqie'?'01':'13');
 expect(document.querySelector('.novel-card .rank-number')?.getAttribute('title')).toContain('来源原名次：13');
 expect(Array.from(document.querySelectorAll('.novel-card .feed-card-tags .genre-tag')).map(e=>e.textContent)).toEqual(expected);
 const tags=document.querySelectorAll('.novel-card .feed-card-tags .genre-tag');
 if(gender==='male')expect(tags[0]?.getAttribute('title')).toContain('作品原始标签');
 if(gender===null&&expected[0]==='女频')expect(tags[0]?.getAttribute('title')).toContain('来源榜单');
 if(genre==='科幻')expect(tags[1]?.getAttribute('title')).toContain(categoryName==='目录外题材'?'未获取':'来源榜单');
 expect(screen.getByRole('link',{name:/真实小说标签样本/}).getAttribute('href')).toBe(url);
 if(platform==='qidian'){if(method)expect(screen.getByText(method==='qidian-browser-ax-v1'?/浏览器辅助采集/:/人工保存网页/)).toBeTruthy();expect(document.querySelector('.novel-stats strong')?.textContent).toBe('-');}
});

it('起点男频已采集而女频受限时保留榜型筛选并提示部分成功',async()=>{
 const novel={...novelEmpty,novel_count:'118',rank_types:[{value:'yuepiao',label:'月票榜'}],genders:[{value:'male',label:'男频'},{value:'female',label:'女频',disabled:true,reason:'女频目录访问受限（HTTP 202）'}],statuses:[{platform:'qidian',board:'qidian:mobile:male:yuepiao',state:'succeeded',http_status:200},{platform:'qidian',board:'qidian:mobile:female:catalog',state:'failed',http_status:202}]};
 const fetcher=mount(path=>path.includes('/novels?')?novel:empty);await screen.findByRole('button',{name:'小说'});fireEvent.click(screen.getByRole('button',{name:'小说'}));
 expect(await screen.findByText(/起点部分来源受限，已展示可访问榜单/)).toBeTruthy();
 expect(screen.queryByText(/尚未取得真实榜单/)).toBeNull();
 expect((screen.getByRole('button',{name:'女频'}) as HTMLButtonElement).disabled).toBe(true);
 expect(screen.getByRole('button',{name:'女频'}).getAttribute('title')).toContain('202');
 fireEvent.click(screen.getByRole('button',{name:'月票榜'}));
 await waitFor(()=>expect(fetcher.mock.calls.some(([p])=>String(p).includes('rank_type=yuepiao'))).toBe(true));
});

it('小说默认番茄且只有两个平台，三级筛选均默认全部',async()=>{
 const fetcher=mount();await screen.findByRole('button',{name:'小说'});fireEvent.click(screen.getByRole('button',{name:'小说'}));await screen.findByText('暂无小说数据');
 const select=screen.getByRole('combobox',{name:'小说平台'}) as HTMLSelectElement;
 expect(select.value).toBe('fanqie');expect(Array.from(select.options).map(x=>x.value)).toEqual(['fanqie','qidian']);
 for(const name of ['男女频','榜单类型','题材'])expect(within(screen.getByRole('group',{name})).getByRole('button',{name:'全部'}).getAttribute('aria-pressed')).toBe('true');
 expect(fetcher.mock.calls.some(([p])=>String(p).includes('/novels?')&&String(p).includes('platform=fanqie'))).toBe(true);
});

it('男女频联动禁用题材，切换男女频清除旧题材并保留榜型',async()=>{
 const fetcher=mount(path=>{if(!path.includes('/novels?'))return empty;const male=new URL(path,'http://local').searchParams.get('gender')==='male';return {...novelEmpty,rank_types:[{value:'read',label:'阅读榜'}],genders:[{value:'male',label:'男频'},{value:'female',label:'女频'}],genres:[{value:'科幻末世',label:'科幻末世',disabled:false},{value:'女频衍生',label:'女频衍生',disabled:male,reason:male?'不属于男频题材':null}]};});
 await screen.findByRole('button',{name:'小说'});fireEvent.click(screen.getByRole('button',{name:'小说'}));await screen.findByText('阅读榜');
 fireEvent.click(screen.getByRole('button',{name:'阅读榜'}));await waitFor(()=>expect(screen.getByRole('button',{name:'阅读榜'}).getAttribute('aria-pressed')).toBe('true'));
 fireEvent.click(screen.getByRole('button',{name:'女频衍生'}));await waitFor(()=>expect(screen.getByRole('button',{name:'女频衍生'}).getAttribute('aria-pressed')).toBe('true'));
 fireEvent.click(screen.getByRole('button',{name:'男频'}));
 await waitFor(()=>expect((screen.getByRole('button',{name:'女频衍生'}) as HTMLButtonElement).disabled).toBe(true));
 expect((screen.getByRole('button',{name:'科幻末世'}) as HTMLButtonElement).disabled).toBe(false);
 expect(screen.getByRole('button',{name:'女频衍生'}).getAttribute('aria-pressed')).toBe('false');
 expect(fetcher.mock.calls.some(([p])=>{const u=new URL(String(p),'http://local');return u.searchParams.get('gender')==='male'&&u.searchParams.get('rank_type')==='read'&&!u.searchParams.has('genre');})).toBe(true);
 fireEvent.click(screen.getByRole('button',{name:'女频'}));await waitFor(()=>expect((screen.getByRole('button',{name:'女频衍生'}) as HTMLButtonElement).disabled).toBe(false));
});

it('所有小说平台均按男女频、榜单类型、题材排序，改名不改变筛选含义',async()=>{
 const fetcher=mount(path=>path.includes('/novels?')?{...novelEmpty,rank_types:[{value:'read',label:'阅读榜'}],genders:[{value:'male',label:'男频'}],genres:[{value:'科幻',label:'科幻'}]}:empty);
 await screen.findByRole('button',{name:'小说'});fireEvent.click(screen.getByRole('button',{name:'小说'}));await screen.findByRole('button',{name:'阅读榜'});
 for(const platform of ['fanqie','qidian']){
  fireEvent.change(screen.getByRole('combobox',{name:'小说平台'}),{target:{value:platform}});
  await screen.findByRole('button',{name:'阅读榜'});
  expect(Array.from(document.querySelectorAll('.novel-filter-row')).map(e=>e.getAttribute('aria-label'))).toEqual(['男女频','榜单类型','题材']);
  fireEvent.click(screen.getByRole('button',{name:'男频'}));await screen.findByRole('button',{name:'阅读榜'});
  fireEvent.click(screen.getByRole('button',{name:'阅读榜'}));
  await waitFor(()=>expect(fetcher.mock.calls.some(([p])=>{const u=new URL(String(p),'http://local');return u.searchParams.get('platform')===platform&&u.searchParams.get('gender')==='male'&&u.searchParams.get('rank_type')==='read';})).toBe(true));
 }
});
