import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {MemoryRouter} from 'react-router-dom';
import {describe,it,expect,vi} from 'vitest';
import {ApiClient} from '../src/api/client';
import {ApiProvider} from '../src/api/provider';
import {ResearchPage} from '../src/modules/research/ResearchPage';
const id='11111111-1111-4111-8111-111111111111';
const session={org_id:id,member_id:id,authz_version:'1',csrf_token:'a'.repeat(64),display_name:'南哥',actions:['content.read','content.write','research.submit'],expires_at:'2099-10-17T01:00:00Z'};
const empty={items:[],total:0,page:1,pages:1,genres:[],counts:{all:0,processing:0,attention:0,review:0,reported:0}};
function mount(load:(p:string,b?:RequestInit)=>unknown=()=>empty,route="/2/0"){
 const fetcher=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>new Response(JSON.stringify({request_id:id,data:String(input)==='/api/v1/session'?session:load(String(input),init)}),{headers:{'Content-Type':'application/json','X-Request-ID':id}}));
 render(<MemoryRouter initialEntries={[route]}><QueryClientProvider client={new QueryClient()}><ApiProvider client={new ApiClient({fetcher:fetcher as typeof fetch})}><ResearchPage business="AI漫剧"/></ApiProvider></QueryClientProvider></MemoryRouter>);return fetcher;
}
describe('真实研判导入',()=>{
 it('空工作区不回退演示作品，保留作品筛选和新建表单',async()=>{
  mount();await screen.findByText('没有匹配的作品');
  expect(screen.queryByText('逆风归城 · 多集演示')).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:/新建研判/}));
  expect(screen.getByRole('textbox',{name:'资料标题'})).toBeTruthy();
  expect(screen.getByRole('textbox',{name:'内容正文或来源链接'})).toBeTruthy();
 });
 it('文本提交使用真实接口和稳定请求键，保留未完成输入',async()=>{
  const fetcher=mount((p)=>p==='/api/v1/research/direct'?{work_id:id,artifact_id:id,artifact_version_id:id,task_id:id,submission_id:id,reused:false}:empty);
  await screen.findByText('没有匹配的作品');fireEvent.click(screen.getByRole('button',{name:/新建研判/}));
  fireEvent.change(screen.getByRole('textbox',{name:'资料标题'}),{target:{value:'授权文本'}});
  fireEvent.change(screen.getByRole('textbox',{name:'内容正文或来源链接'}),{target:{value:'第一段真实材料'}});
  fireEvent.click(screen.getByRole('button',{name:/^提交研判$/}));
  await waitFor(()=>expect(fetcher.mock.calls.some(([p])=>String(p)==='/api/v1/research/direct')).toBe(true));
  const call=fetcher.mock.calls.find(([p])=>String(p)==='/api/v1/research/direct')!;
  const body=JSON.parse(String(call[1]?.body));expect(body.origin).toBe('text');expect(body.body_text).toBe('第一段真实材料');
  expect(new Headers(call[1]?.headers).get('Idempotency-Key')).toMatch(/^[a-f0-9-]{36}$/);
 });
});

const work={id,org_id:id,business_code:'motion_comic',work_number:'W-real',name:'真实作品',genre_tags:[],total_episode_count:150,lock_version:'1',report_generation:'0',latest_report_id:null,collected_units:0,analyzed_units:0,material_count:1,processing_count:0,attention_count:0,author:null,author_id:null};
const version={id,version_no:1,title:'第二集资料',material_kind:'reference',body_text:'已有正文',file_id:null,content_sha256:'a'.repeat(64),episode_no:120,parsing:null,submissions:[]};
const material={id,lock_version:'1',material_number:'M-real',current_version_id:id,title:'第二集资料',versions:[version],parsing:null};
const detail={...work,units:[{id,episode_no:120,title:null}],materials:[material]};
it('作品列表支持翻页，超过20条仍可进入',async()=>{
 const fetcher=mount(p=>p.includes('page=2')?{...empty,items:[work],total:21,pages:2,page:2}:{...empty,items:[work],total:21,pages:2});
 await screen.findByRole('button',{name:'真实作品'});
 fireEvent.click(screen.getByRole('button',{name:'作品下一页'}));
 await waitFor(()=>expect(fetcher.mock.calls.some(([p])=>String(p).includes('page=2'))).toBe(true));
});
it('长剧深链接恢复120集导航分段，同集补充携带材料版本锁',async()=>{
 const fetcher=mount(p=>p.includes('/works/'+id)?detail:empty,'/2/0/work/'+id+'/episodes/ep%3A120/'+id);
 await screen.findByRole('heading',{name:'真实作品'});
 expect(screen.getByRole('button',{name:/120.*有资料/})).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'补充资料'}));
 fireEvent.change(screen.getByRole('textbox',{name:'资料名称'}),{target:{value:'修订资料'}});
 fireEvent.change(screen.getByRole('textbox',{name:'粘贴文本或来源链接'}),{target:{value:'修订后的正文'}});
 fireEvent.click(screen.getByRole('button',{name:'提交处理'}));
 await waitFor(()=>expect(fetcher.mock.calls.some(([p,b])=>String(p).endsWith('/materials')&&b?.method==='POST')).toBe(true));
 const call=fetcher.mock.calls.find(([p,b])=>String(p).endsWith('/materials')&&b?.method==='POST')!;
 expect(JSON.parse(String(call[1]?.body))).toMatchObject({artifact_id:id,expected_artifact_lock_version:'1',episode_no:120});
});

it('报告读取真实历史版本，质量与市场预测分别展示，不用评级补数值',async()=>{
 const report={id,created_at:'2026-10-17T01:00:00Z',work_id:id,input_set_id:id,version_no:1,coverage_kind:'partial',result_state:'completed',schema_version:1,content_sha256:'a'.repeat(64),missing_inputs:[],body:{claims:[{key:'goal',dimension:'人物设计',finding:'合成测试：主角发现线索'}],limitations:['仅当前材料']},evidence:[{claim_path:'claims.goal',evidence_id:id,artifact_version_id:id,raw_asset_id:null,paragraph_no:1,quoted_text:'已有正文'}]};
 const history={reports:[report],evaluations:[],prediction_drafts:[],frozen_predictions:[],prediction_assessments:[]};
 mount(p=>p.endsWith('/analysis-history')?history:p.includes('/works/'+id)?{...detail,latest_report_id:id}:empty,'/2/0/work/'+id+'/analysis');
 await screen.findByText('合成测试：主角发现线索');
 expect(screen.getByText(/暂不可可靠预测/)).toBeTruthy();
 expect(screen.queryByText('S级')).toBeNull();
 expect(screen.getByText('已有正文',{selector:'blockquote'})).toBeTruthy();
});

it.each(['material','parsed'])('报告%s引用携带父材料版本和原段落号，点击进入来源定位',async kind=>{
 const report={id,created_at:'2026-10-17T01:00:00Z',work_id:id,input_set_id:id,version_no:1,coverage_kind:'partial',result_state:'completed',schema_version:1,content_sha256:'a'.repeat(64),missing_inputs:[],body:{claims:[{key:'goal',dimension:'人物设计',finding:'合成引用定位'}],limitations:['局部']},evidence:[{claim_path:'claims.goal',evidence_id:id,artifact_version_id:kind==='material'?id:null,raw_asset_id:kind==='parsed'?id:null,target_artifact_version_id:id,target_episode_no:120,paragraph_no:2,quoted_text:'第二行'}]};
 const history={reports:[report],evaluations:[],prediction_drafts:[],frozen_predictions:[],prediction_assessments:[]};
 const parse={task_id:id,state:'succeeded',result_state:'completed',safe_error_code:null,raw_id:id,media_kind:'text',duration_ms:null,missing_inputs:[],paragraphs:[{number:2,text:'第二行',evidence_id:id}]};
 const v={...version,body_text:kind==='material'?'第一行\n第二行':null,parsing:parse};
 mount(p=>p.endsWith('/analysis-history')?history:p.includes('/works/'+id)?{...detail,materials:[{...material,versions:[v],parsing:parse}],latest_report_id:id}:empty,'/2/0/work/'+id+'/analysis');
 const link=await screen.findByRole('link',{name:'原文段落 2'});
 expect(link.getAttribute('href')).toContain('/episodes/ep%3A120/'+id+'?paragraph=2');
 fireEvent.click(link);
 await waitFor(()=>expect(document.activeElement?.id).toBe('source-paragraph-2'));
});
