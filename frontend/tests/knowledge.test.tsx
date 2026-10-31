import {fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {MemoryRouter,useLocation} from 'react-router-dom';
import {it,expect,vi} from 'vitest';
import {ApiClient} from '../src/api/client';
import {ApiProvider} from '../src/api/provider';
import {KnowledgePage} from '../src/modules/knowledge/KnowledgePage';
const id='11111111-1111-4111-8111-111111111111';
const session={org_id:id,member_id:id,authz_version:'1',csrf_token:'a'.repeat(64),display_name:'南哥',actions:['content.read','knowledge.edit','knowledge.candidate.read','knowledge.review','knowledge.publish'],expires_at:'2099-10-17T01:00:00Z'};
const empty={items:[],total:'0',next_cursor:null};
function RoutePosition(){return <output data-testid="route">{useLocation().pathname}</output>;}
function mount(tab=0,load:(p:string,b?:RequestInit)=>unknown=()=>empty){
 const fetcher=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>new Response(JSON.stringify({request_id:id,data:String(input)==='/api/v1/session'?session:load(String(input),init)}),{headers:{'Content-Type':'application/json'}}));
 render(<MemoryRouter initialEntries={[tab===0?'/1/0':'/1/2']}><RoutePosition/><QueryClientProvider client={new QueryClient()}><ApiProvider client={new ApiClient({fetcher:fetcher as typeof fetch})}><KnowledgePage business="AI漫剧" tab={tab}/></ApiProvider></QueryClientProvider></MemoryRouter>);return fetcher;
}
it('正式空态不读取Demo知识，新增必须选分类且不假批准',async()=>{
 const fetcher=mount(0,(_p,b)=>b?.method==='POST'?item:empty);
 await screen.findByText('题材库暂无匹配的正式知识');
 expect(screen.queryByText('日常动作的重复与情绪递进')).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:/人工新增/}));
 fireEvent.change(screen.getByLabelText('知识标题'),{target:{value:'待审真实提交'}});
 fireEvent.change(screen.getByLabelText('知识内容'),{target:{value:'只提交候选'}});
 fireEvent.change(screen.getByLabelText('来源',{exact:true}),{target:{value:'测试影片'}});
 fireEvent.change(screen.getByLabelText('解释',{exact:true}),{target:{value:'测试角色'}});
 fireEvent.change(screen.getByLabelText('来源与适用限制'),{target:{value:'来源尚待核实'}});
 fireEvent.change(screen.getByRole('combobox',{name:'知识分类'}),{target:{value:''}});
 fireEvent.click(screen.getByRole('button',{name:'提交候选'}));
 expect(fetcher.mock.calls.filter(([,b])=>b?.method==='POST')).toHaveLength(0);
 fireEvent.change(screen.getByRole('combobox',{name:'知识分类'}),{target:{value:'genre'}});
 fireEvent.click(screen.getByRole('button',{name:'提交候选'}));
 await waitFor(()=>expect(fetcher.mock.calls.filter(([,b])=>b?.method==='POST')).toHaveLength(1));
 const call=fetcher.mock.calls.find(([,b])=>b?.method==='POST')!;
 expect(JSON.parse(String(call[1]?.body))).toMatchObject({business_codes:['motion_comic'],browse_category:'genre',body_text:'只提交候选',source_text:'测试影片',explanation:'测试角色'});
 expect(JSON.parse(String(call[1]?.body))).not.toHaveProperty('approved');
 await waitFor(()=>expect(screen.getByTestId('route').textContent).toBe('/1/2'));
});
const revision={id,knowledge_id:id,created_at:'2026-10-17T01:00:00Z',version_no:1,title:'待审真实提交',body_text:'只提交候选',knowledge_type:'method_rule',browse_category:'genre',business_codes:['motion_comic'],tags:[{kind:'stage',code:'script'}],evidence_ids:[],source_report_id:null,limitations:'来源待核实',content_sha256:'a'.repeat(64),sealed_at:'2026-10-17T01:00:00Z'};
const item={id,created_at:revision.created_at,updated_at:revision.created_at,lock_version:'2',title:revision.title,revision_id:id,publication_id:null,browse_category:'genre',business_codes:['motion_comic'],tags:revision.tags,state:'pending_ai',review_request_id:id,revision};
it('待AI审核不能人工发布，修订携带当前版本锁',async()=>{
 const review={id,created_at:revision.created_at,purpose:'knowledge_release',target_id:id,input_sha256:'a'.repeat(64),ai_head_id:null,human_head_id:null,ai_head_lock_version:null,human_head_lock_version:null,task:null,decisions:[]};
 const fetcher=mount(2,(p,b)=>p.includes('/reviews')?review:b?.method==='POST'?revision:p.endsWith('/knowledge/candidates/'+id)?item:{items:[item],total:'1',next_cursor:null});
 fireEvent.click(await screen.findByRole('button',{name:/审核详情/}));
 expect((await screen.findByRole('button',{name:'人工通过并入库'}) as HTMLButtonElement).disabled).toBe(true);
 fireEvent.click(screen.getByRole('button',{name:'修订候选'}));
 fireEvent.change(screen.getByLabelText('知识内容'),{target:{value:'修订后正文'}});
 fireEvent.click(screen.getByRole('button',{name:'提交候选'}));
 await waitFor(()=>expect(fetcher.mock.calls.some(([p,b])=>String(p).includes('/revisions')&&b?.method==='POST')).toBe(true));
 const call=fetcher.mock.calls.find(([p,b])=>String(p).includes('/revisions')&&b?.method==='POST')!;
 expect(JSON.parse(String(call[1]?.body))).toMatchObject({expected_lock_version:'2',body_text:'修订后正文'});
});

const aiId='22222222-2222-4222-8222-222222222222';
const approvedReview={id,created_at:revision.created_at,purpose:'knowledge_release',target_id:id,input_sha256:'a'.repeat(64),ai_head_id:aiId,human_head_id:null,ai_head_lock_version:'1',human_head_lock_version:null,task:{id,kind:'task',state:'succeeded'},decisions:[{id:aiId,created_at:revision.created_at,request_id:id,reviewer_kind:'ai',verdict:'approved',reason:'有引用支持的审核',reviewed_ai_decision_id:null,supersedes_decision_id:null}]};
it('审核抽屉轮询完成后刷新同版本状态及锁，人工确认后回正式浏览',async()=>{
 let finished=false;
 const fetcher=mount(2,(p,b)=>{
  if(b?.method==='POST')return {id,revision_id:id};
  if(p.endsWith('/reviews/'+id))return finished?approvedReview:{...approvedReview,ai_head_id:null,ai_head_lock_version:null,decisions:[],task:{id,kind:'task',state:'queued'}};
  const current=finished?{...item,lock_version:'4',state:'pending_human'}:item;
  if(p.endsWith('/knowledge/candidates/'+id))return current;
  return {items:[current],total:'1',next_cursor:null};
 });
 fireEvent.click(await screen.findByRole('button',{name:/审核详情/}));
 expect((await screen.findByRole('button',{name:'人工通过并入库'}) as HTMLButtonElement).disabled).toBe(true);
 finished=true;
 await waitFor(()=>expect((screen.getByRole('button',{name:'人工通过并入库'}) as HTMLButtonElement).disabled).toBe(false),{timeout:5000});
 fireEvent.click(screen.getByRole('checkbox',{name:/已人工核实/}));
 fireEvent.click(screen.getByRole('button',{name:'人工通过并入库'}));
 await waitFor(()=>expect(screen.getByTestId('route').textContent).toBe('/1/0'));
 const call=fetcher.mock.calls.find(([p,b])=>String(p).endsWith('/approve-publication')&&b?.method==='POST')!;
 expect(JSON.parse(String(call[1]?.body))).toMatchObject({expected_lock_version:'4',reviewed_ai_decision_id:aiId});
},8000);
it('打开的候选已被修订时不悄悄改审新版本，也不允许用旧审核发布',async()=>{
 mount(2,p=>p.endsWith('/reviews/'+id)?approvedReview:p.endsWith('/knowledge/candidates/'+id)?{...item,revision_id:aiId,revision:{...revision,id:aiId,version_no:2},lock_version:'3'}:{items:[item],total:'1',next_cursor:null});
 fireEvent.click(await screen.findByRole('button',{name:/审核详情/}));
 await screen.findByText(/候选已更新.*重新打开/);
 expect((screen.getByRole('button',{name:'人工通过并入库'}) as HTMLButtonElement).disabled).toBe(true);
 expect(screen.getAllByText('只提交候选').length).toBeGreaterThan(0);
});
it('来源框中的明确原文与出处作为人工提交资料，普通来源说明不伪装证据',async()=>{
 const fetcher=mount(0,(_p,b)=>b?.method==='POST'?item:empty);
 await screen.findByText('题材库暂无匹配的正式知识');fireEvent.click(screen.getByRole('button',{name:/人工新增/}));
 fireEvent.change(screen.getByLabelText('知识标题'),{target:{value:'手动知识'}});
 fireEvent.change(screen.getByLabelText('知识内容'),{target:{value:'观察：角色改变行动'}});
 fireEvent.change(screen.getByRole('combobox',{name:'知识分类'}),{target:{value:'dna_case'}});
 fireEvent.change(screen.getByLabelText('来源与适用限制'),{target:{value:'原文：主角发现线索后，转身调查门外动静。\n出处：本人提供的授权剧本文字\n限制：仅此片段，不证明效果'}});
 fireEvent.click(screen.getByRole('button',{name:'提交候选'}));
 await waitFor(()=>expect(fetcher.mock.calls.some(([,b])=>b?.method==='POST')).toBe(true));
 const call=fetcher.mock.calls.find(([,b])=>b?.method==='POST')!;
 expect(JSON.parse(String(call[1]?.body)).manual_source).toEqual({body_text:'主角发现线索后，转身调查门外动静。',attribution:'本人提供的授权剧本文字'});
});

it('关键词及分类发送服务端，分类计数仍取业务正式全集',async()=>{
 const formal={...item,state:'published',publication_id:id};
 const fetcher=mount(0,p=>p.includes('q=')?empty:{items:[formal],total:'1',next_cursor:null});
 await screen.findByRole('button',{name:/查看知识/});
 fireEvent.change(screen.getByRole('textbox',{name:'搜索当前工作区'}),{target:{value:'授权片段'}});
 await waitFor(()=>expect(fetcher.mock.calls.some(([p])=>String(p).includes('q='))).toBe(true));
 await screen.findByText('题材库暂无匹配的正式知识');
 expect(screen.getByRole('button',{name:'题材库1'})).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'题材库1'}));
 await waitFor(()=>expect(fetcher.mock.calls.some(([p])=>String(p).includes('browse_category=genre'))).toBe(true));
});
it('知识详情读取当前确切版本的真实来源摘录',async()=>{
 const formal={...item,state:'published',publication_id:id};
 mount(0,p=>p.endsWith('/sources')?{revision_id:id,knowledge_id:id,source_report_id:null,items:[{id,raw_asset_id:id,artifact_version_id:null,locator_kind:'whole',paragraph_no:null,page_no:null,start_ms:null,end_ms:null,quoted_text:'真实绑定的人工原文',origin:'manual',independently_verified:false,attribution:'已授权文字',target_artifact_version_id:null,work_id:null,episode_no:null,material_version_no:null,business_code:null}]}:p.includes('/reviews/')?approvedReview:p.endsWith('/knowledge/'+id)?formal:{items:[formal],total:'1',next_cursor:null});
 fireEvent.click(await screen.findByRole('button',{name:/查看知识/}));
 await screen.findByText('真实绑定的人工原文');
 expect(screen.getByText(/人工提供.*未独立核验/)).toBeTruthy();
});

it.each([null,2])('作品原文定位保留确切版本并携带来源业务，集号=%s',async episode=>{
 const formal={...item,state:'published',publication_id:id};
 mount(0,p=>p.endsWith('/sources')?{revision_id:id,knowledge_id:id,source_report_id:null,items:[{id,raw_asset_id:id,artifact_version_id:null,locator_kind:'paragraph',paragraph_no:3,page_no:null,start_ms:null,end_ms:null,quoted_text:'原文定位片段',origin:'parsed_document',independently_verified:false,attribution:null,target_artifact_version_id:aiId,work_id:id,episode_no:episode,material_version_no:1,business_code:'motion_comic'}]}:p.includes('/reviews/')?approvedReview:p.endsWith('/knowledge/'+id)?formal:{items:[formal],total:'1',next_cursor:null});
 fireEvent.click(await screen.findByRole('button',{name:/查看知识/}));
 const link=await screen.findByRole('link',{name:'原文段落 3'});
 const href=link.getAttribute('href')!;
 expect(href).toContain('/episodes/'+(episode?'ep:2':'unknown')+'/'+aiId);
 expect(href).toContain('source_business=motion_comic');expect(href).toContain('paragraph=3');
});

it('存量导入详情明确未执行AI审核，不伪装双审通过',async()=>{
 const imported={...item,state:'published',publication_id:aiId,release_mode:'legacy_import'};
 mount(0,p=>p.endsWith('/reviews/'+id)?{...approvedReview,ai_head_id:null,decisions:[],task:null}:p.endsWith('/knowledge/'+id)?imported:p.includes('/sources')?{revision_id:id,knowledge_id:id,source_report_id:null,items:[]}:{items:[imported],total:'1',next_cursor:null});
 fireEvent.click(await screen.findByRole('button',{name:/查看知识/}));
 await screen.findByText('AI审核：未执行');
 expect(screen.getByText('入库依据：用户确认存量导入')).toBeTruthy();
 expect(screen.queryByText('人工审核：通过')).toBeNull();
});

it('紧凑知识行不预览正文，题材三个筛选联动且切分类清空',async()=>{
 const groups=['都市男频（15个）','古风女频（10个）','B线女频Romance（25个）','3.2 Male/Mixed B线（15个）'];
 const rows=groups.map((group,i)=>({...item,id:`11111111-1111-4111-8111-11111111111${i}`,title:`题材${i}`,state:'published',publication_id:id,tags:[{kind:'genre',code:group}]}));
 mount(0,()=>({items:rows,total:'4',next_cursor:null}));
 await screen.findByRole('button',{name:'查看知识：题材0'});
 expect(screen.queryByText('只提交候选')).toBeNull();
 expect(screen.getByRole('group',{name:'A/B线'})).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'题材库4'}));
 await waitFor(()=>expect(screen.getAllByRole('button',{name:/查看知识：/})).toHaveLength(4));
 fireEvent.click(within(screen.getByRole('group',{name:'A/B线'})).getByRole('button',{name:'A线 · 国内'}));
 expect(screen.getAllByRole('button',{name:/查看知识：/})).toHaveLength(2);
 fireEvent.click(within(screen.getByRole('group',{name:'男女频'})).getByRole('button',{name:'男频'}));
 expect(screen.getAllByRole('button',{name:/查看知识：/})).toHaveLength(1);
 fireEvent.click(within(screen.getByRole('group',{name:'题材大类'})).getByRole('button',{name:'都市男频'}));
 fireEvent.click(within(screen.getByRole('group',{name:'A/B线'})).getByRole('button',{name:'B线 · 海外'}));
 expect(within(screen.getByRole('group',{name:'男女频'})).getByRole('button',{name:'全部'}).getAttribute('aria-pressed')).toBe('true');
 expect(within(screen.getByRole('group',{name:'题材大类'})).getByRole('button',{name:'全部'}).getAttribute('aria-pressed')).toBe('true');
 expect(screen.getAllByRole('button',{name:/查看知识：/})).toHaveLength(2);
 fireEvent.click(within(screen.getByRole('group',{name:'男女频'})).getByRole('button',{name:'男频／混合'}));
 expect(screen.getByRole('button',{name:'查看知识：题材3'})).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'爽点库0'}));
 await waitFor(()=>expect(screen.getAllByRole('button',{name:/查看知识：/})).toHaveLength(4));
 expect(screen.queryByRole('group',{name:'A/B线'})).toBeNull();
});

it('切换知识分类不重新获取分类计数全集',async()=>{
 const formal={...item,state:'published',publication_id:id};
 const fetcher=mount(0,()=>({items:[formal],total:'1',next_cursor:null}));
 await screen.findByRole('button',{name:/查看知识/});
 const fullCalls=()=>fetcher.mock.calls.filter(([p])=>String(p).includes('/knowledge?')&&!String(p).includes('browse_category=')).length;
 const before=fullCalls();
 fireEvent.click(screen.getByRole('button',{name:'题材库1'}));
 await screen.findByRole('button',{name:/查看知识/});
 expect(fullCalls()).toBe(before);
});

it('金句按AB线筛选，行与详情保留两个主题和女频映射依据',async()=>{
 const rows=[{...item,id, title:'守护金句',state:'published',browse_category:'quote',tags:[{kind:'genre',code:'男频 · 仇恨/复仇主题（20条）'},{kind:'genre',code:'男频 · 怜悯/守护主题（20条）'}]}, {...item,id:aiId,title:'狼人金句',state:'published',browse_category:'quote',tags:[{kind:'genre',code:'B线 · Werewolf/Supernatural (10)'}]}];
 mount(0,p=>p.includes('/sources')?{revision_id:id,knowledge_id:id,items:[]}:p.endsWith('/reviews/'+id)?approvedReview:p.endsWith('/knowledge/'+aiId)?rows[1]:{items:rows,total:'2',next_cursor:null});
 await screen.findByRole('button',{name:'查看知识：守护金句'});
 fireEvent.click(screen.getByRole('button',{name:'金句库2'}));
 await waitFor(()=>expect(screen.getAllByRole('button',{name:/查看知识：/})).toHaveLength(2));
 expect(screen.getByText('A线 · 男频 · 仇恨/复仇 · 怜悯/守护')).toBeTruthy();
 fireEvent.click(within(screen.getByRole('group',{name:'A/B线'})).getByRole('button',{name:'B线 · 海外'}));
 expect(screen.queryByRole('button',{name:'查看知识：守护金句'})).toBeNull();
 expect(screen.getByText('B线 · 女频 · Werewolf/Supernatural')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'查看知识：狼人金句'}));
 await screen.findByText(/女频归类为用户确认映射/);
});

it('知识浏览只保留五个单类且默认请求题材',async()=>{
 const fetcher=mount();
 await screen.findByRole('button',{name:'题材库0'});
 const tabs=within(screen.getByRole('group',{name:'知识分类'}));
 expect(tabs.queryByRole('button',{name:/全部/})).toBeNull();
 expect(tabs.getAllByRole('button')).toHaveLength(5);
 expect(tabs.getByRole('button',{name:'题材库0'}).getAttribute('aria-pressed')).toBe('true');
 await waitFor(()=>expect(fetcher.mock.calls.some(([p])=>String(p).includes('browse_category=genre'))).toBe(true));
});

it('知识行单条取消零写、两条选择后批量确认并刷新正式列表',async()=>{
 const second='33333333-3333-4333-8333-333333333333';
 let values=[{...item,state:'published',publication_id:id},{...item,id:second,title:'第二条知识',state:'published',publication_id:second}];
 const fetcher=mount(0,(_p,b)=>{if(b?.method==='POST'){values=[];return {ids:[id,second]};}return {items:values,total:String(values.length),next_cursor:null};});
 const firstRemove=await screen.findByRole('button',{name:'移入回收站：待审真实提交'});
 expect(screen.queryByText('显示双审通过或用户确认导入的版本')).toBeNull();
 expect(screen.queryByRole('button',{name:'批量移入回收站'})).toBeNull();
 fireEvent.click(firstRemove);expect(screen.getByRole('dialog',{name:'确认移入回收站？'})).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'取消'}));expect(fetcher.mock.calls.filter(([,b])=>b?.method==='POST')).toHaveLength(0);
 fireEvent.click(screen.getByRole('checkbox',{name:'选择知识：待审真实提交'}));expect(screen.queryByRole('button',{name:'批量移入回收站'})).toBeNull();
 fireEvent.click(screen.getByRole('checkbox',{name:'选择知识：第二条知识'}));fireEvent.click(screen.getByRole('button',{name:'批量移入回收站'}));
 fireEvent.click(screen.getByRole('button',{name:/^确认$/}));
 await screen.findByText('题材库暂无匹配的正式知识');
 const calls=fetcher.mock.calls.filter(([,b])=>b?.method==='POST');expect(calls).toHaveLength(1);
 expect(String(calls[0][0])).toBe('/api/v1/knowledge/recycle');
 expect(JSON.parse(String(calls[0][1]?.body))).toEqual({items:[{id,expected_lock_version:'2'},{id:second,expected_lock_version:'2'}]});
});

it('切换筛选清理当前选择',async()=>{
 const second='33333333-3333-4333-8333-333333333333';
 const values=[{...item,state:'published',publication_id:id},{...item,id:second,title:'第二条知识',state:'published',publication_id:second}];
 mount(0,p=>p.includes('browse_category=quote')?empty:{items:values,total:'2',next_cursor:null});
 fireEvent.click(await screen.findByRole('checkbox',{name:'选择知识：待审真实提交'}));fireEvent.click(screen.getByRole('checkbox',{name:'选择知识：第二条知识'}));
 expect(screen.getByRole('button',{name:'批量移入回收站'})).toBeTruthy();
 fireEvent.change(screen.getByRole('textbox',{name:'搜索当前工作区'}),{target:{value:'新条件'}});
 expect(screen.queryByRole('button',{name:'批量移入回收站'})).toBeNull();
 fireEvent.change(screen.getByRole('textbox',{name:'搜索当前工作区'}),{target:{value:''}});
 expect(screen.queryByRole('button',{name:'批量移入回收站'})).toBeNull();
});

it('真实回收站恢复确认后刷新列表，取消不写入',async()=>{
 let values=[{...item,state:'published',publication_id:id,recycled_at:'2026-10-23T01:00:00Z'}];
 const fetcher=mount(3,(_p,b)=>{if(b?.method==='POST'){values=[];return {ids:[id]};}return {items:values,total:String(values.length),next_cursor:null};});
 fireEvent.click(await screen.findByRole('button',{name:'恢复知识：待审真实提交'}));
 expect(screen.getByRole('dialog',{name:'确认恢复知识？'})).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:/^确认$/}));
 await screen.findByText('回收站为空');
 expect(fetcher.mock.calls.some(([p,b])=>String(p)==='/api/v1/knowledge/restore'&&b?.method==='POST')).toBe(true);
 expect(fetcher.mock.calls.some(([p])=>String(p).includes('/knowledge/candidates'))).toBe(false);
});

it('知识按20条分页，可调整条数且筛选回首页',async()=>{
 const rows=Array.from({length:55},(_,i)=>({...item,id:`11111111-1111-4111-8111-${String(i).padStart(12,'0')}`,title:`分页知识${i+1}`,state:'published'}));
 mount(0,()=>({items:rows,total:'55',next_cursor:null}));
 await screen.findByRole('button',{name:'查看知识：分页知识1'});
 expect(screen.getAllByRole('button',{name:/查看知识：/})).toHaveLength(20);
 fireEvent.click(screen.getByRole('button',{name:'下一页'}));
 expect(screen.queryByRole('button',{name:'查看知识：分页知识1'})).toBeNull();
 expect(screen.getByRole('button',{name:'查看知识：分页知识21'})).toBeTruthy();
 fireEvent.change(screen.getByLabelText('每页条数'),{target:{value:'50'}});
 expect(screen.getAllByRole('button',{name:/查看知识：/})).toHaveLength(50);
 fireEvent.click(screen.getByRole('button',{name:'下一页'}));
 expect(screen.getAllByRole('button',{name:/查看知识：/})).toHaveLength(5);
 fireEvent.change(screen.getByRole('textbox',{name:'搜索当前工作区'}),{target:{value:'分页'}});
 await screen.findByRole('button',{name:'查看知识：分页知识1'});
 fireEvent.change(screen.getByRole('textbox',{name:'搜索当前工作区'}),{target:{value:''}});
 await screen.findByRole('button',{name:'查看知识：分页知识1'});
});
it('知识详情展示来源和解释',async()=>{
 const enriched={...item,revision:{...revision,source_text:'测试影片',explanation:'说话角色：测试角色'}};
 mount(2,p=>p.includes('/reviews/')?approvedReview:p.endsWith('/'+id)?enriched:{items:[enriched],total:'1',next_cursor:null});
 fireEvent.click(await screen.findByRole('button',{name:/审核详情/}));
 expect(screen.getByText('测试影片')).toBeTruthy();
 expect(within(screen.getByRole('dialog')).getByText('说话角色：测试角色')).toBeTruthy();
});

const aiExplanation={text:'围绕主角身份秘密与关系转变展开冲突，适合通过选择逐步揭示动机。',revision_id:id,task_id:aiId,execution_id:aiId,created_at:'2026-10-31T01:00:00Z'};
it('题材标题下显示AI附加解释，详情沿用解释位置且不改变存量审核状态',async()=>{
 const enriched={...item,state:'published',release_mode:'legacy_import',ai_explanation:aiExplanation};
 mount(0,p=>p.includes('/sources')?{revision_id:id,knowledge_id:id,items:[]}:p.includes('/reviews/')?{...approvedReview,ai_head_id:null,decisions:[],task:null}:p.endsWith('/'+id)?enriched:{items:[enriched],total:'1',next_cursor:null});
 const row=await screen.findByRole('button',{name:'查看知识：待审真实提交'});
 expect(row.querySelector('.knowledge-row-copy')?.textContent).toContain(aiExplanation.text+' · AI生成');
 fireEvent.click(row);
 const detail=screen.getByRole('dialog',{name:'知识详情'});
 expect(within(detail).getByText(aiExplanation.text)).toBeTruthy();
 expect(within(detail).getByText('· AI生成')).toBeTruthy();
 await within(detail).findByText('AI审核：未执行');
 expect(within(detail).getByText('入库依据：用户确认存量导入')).toBeTruthy();
});
it('原解释优先于AI附加解释，缺解释时标题下不占位',async()=>{
 const enriched={...item,state:'published',revision:{...revision,explanation:'人工原解释'},ai_explanation:aiExplanation};
 const plain={...item,id:aiId,title:'无解释题材',state:'published',ai_explanation:null};
 mount(0,p=>p.includes('/reviews/')?approvedReview:p.endsWith('/'+id)?enriched:{items:[enriched,plain],total:'2',next_cursor:null});
 const row=await screen.findByRole('button',{name:'查看知识：待审真实提交'});
 expect(within(row).getByText('人工原解释')).toBeTruthy();expect(row.textContent).not.toContain('AI生成');
 expect(screen.getByRole('button',{name:'查看知识：无解释题材'}).querySelector('.knowledge-row-explanation')).toBeNull();
 fireEvent.click(row);
 expect(within(screen.getByRole('dialog')).getByText('人工原解释')).toBeTruthy();
 expect(within(screen.getByRole('dialog')).queryByText(aiExplanation.text)).toBeNull();
});
it('修订表单不自动带入AI附加说明，提交仍仅写原解释字段',async()=>{
 const enriched={...item,ai_explanation:aiExplanation};
 const fetcher=mount(2,(p,b)=>p.includes('/reviews/')?approvedReview:b?.method==='POST'?revision:p.endsWith('/'+id)?enriched:{items:[enriched],total:'1',next_cursor:null});
 fireEvent.click(await screen.findByRole('button',{name:/审核详情/}));
 fireEvent.click(screen.getByRole('button',{name:'修订候选'}));
 expect(screen.getByLabelText('解释',{exact:true})).toHaveProperty('value','');
 fireEvent.click(screen.getByRole('button',{name:'提交候选'}));
 await waitFor(()=>expect(fetcher.mock.calls.some(([,b])=>b?.method==='POST')).toBe(true));
 const body=JSON.parse(String(fetcher.mock.calls.find(([,b])=>b?.method==='POST')![1]?.body));
 expect(body.explanation).toBeNull();expect(body).not.toHaveProperty('ai_explanation');
 expect(JSON.stringify(body)).not.toContain(aiExplanation.text);
});
it.each([
 {},{text:''},{text:' '.repeat(2)},{text:'字'.repeat(181)},{revision_id:aiId},{task_id:'bad'},{execution_id:'bad'},{created_at:'yesterday'},{created_at:'2026-10-31'},{extra:'unexpected'},
])('客户端拒绝非法或跨版本AI附加说明 %j',async patch=>{
 const explanation=Object.keys(patch).length?{...aiExplanation,...patch}:{};
 const client=new ApiClient({fetcher:async()=>new Response(JSON.stringify({request_id:id,data:{...item,ai_explanation:explanation}}),{headers:{'Content-Type':'application/json'}})});
 await expect(client.knowledgeItem(id,true)).rejects.toMatchObject({code:'INVALID_RESPONSE'});
});
it.each([undefined,null,aiExplanation,{...aiExplanation,text:'😀'.repeat(180),created_at:'2026-10-31T09:00:00+08:00'}])('客户端兼容缺失、可空与合法版本附加说明',async explanation=>{
 const client=new ApiClient({fetcher:async()=>new Response(JSON.stringify({request_id:id,data:{...item,ai_explanation:explanation}}),{headers:{'Content-Type':'application/json'}})});
 expect((await client.knowledgeItem(id,true)).ai_explanation).toEqual(explanation);
});
