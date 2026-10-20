import {fireEvent,render,screen,waitFor} from '@testing-library/react';
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
 await screen.findByText('没有匹配的知识');
 expect(screen.queryByText('日常动作的重复与情绪递进')).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:/人工新增/}));
 fireEvent.change(screen.getByLabelText('知识标题'),{target:{value:'待审真实提交'}});
 fireEvent.change(screen.getByLabelText('知识内容'),{target:{value:'只提交候选'}});
 fireEvent.change(screen.getByLabelText('来源与适用限制'),{target:{value:'来源尚待核实'}});
 fireEvent.click(screen.getByRole('button',{name:'提交候选'}));
 expect(fetcher.mock.calls.filter(([,b])=>b?.method==='POST')).toHaveLength(0);
 fireEvent.change(screen.getByRole('combobox',{name:'知识分类'}),{target:{value:'genre'}});
 fireEvent.click(screen.getByRole('button',{name:'提交候选'}));
 await waitFor(()=>expect(fetcher.mock.calls.filter(([,b])=>b?.method==='POST')).toHaveLength(1));
 const call=fetcher.mock.calls.find(([,b])=>b?.method==='POST')!;
 expect(JSON.parse(String(call[1]?.body))).toMatchObject({business_codes:['motion_comic'],browse_category:'genre',body_text:'只提交候选'});
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
 await screen.findByText('没有匹配的知识');fireEvent.click(screen.getByRole('button',{name:/人工新增/}));
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
 const fetcher=mount(0,p=>p.includes('q=')||p.includes('browse_category=')?empty:{items:[formal],total:'1',next_cursor:null});
 await screen.findByRole('button',{name:/查看知识/});
 fireEvent.change(screen.getByRole('textbox',{name:'搜索当前工作区'}),{target:{value:'授权片段'}});
 await waitFor(()=>expect(fetcher.mock.calls.some(([p])=>String(p).includes('q='))).toBe(true));
 await screen.findByText('没有匹配的知识');
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
