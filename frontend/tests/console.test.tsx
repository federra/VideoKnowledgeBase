import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import { ApiClient } from '../src/api/client';
import { ApiProvider } from '../src/api/provider';
import { ConsolePage } from '../src/modules/console/ConsolePage';
const uuid='11111111-1111-4111-8111-111111111111';
const session={org_id:uuid,member_id:uuid,authz_version:'1',csrf_token:'a'.repeat(64),display_name:'本地检查',actions:['source.configure','task.read'],expires_at:'2099-10-17T01:00:00Z'};
function mount(tab=0,failed=false){
 const fetcher=vi.fn(async(input:RequestInfo|URL)=>{
  const path=String(input);
  const data=path==='/api/v1/session'?session:{items:[],next_cursor:null,total:'0'};
  return new Response(JSON.stringify(failed?{request_id:uuid,error:{code:'ACCESS_DENIED',message:'拒绝',field_paths:[]}}:{request_id:uuid,data}),{status:failed?403:200,headers:{'Content-Type':'application/json','X-Request-ID':uuid}});
 });
 const client=new ApiClient({fetcher:fetcher as typeof fetch});
 render(<QueryClientProvider client={new QueryClient()}><ApiProvider client={client}><ConsolePage tab={tab} business="AI漫剧" /></ApiProvider></QueryClientProvider>);
 return fetcher;
}
describe('真实控制台',()=>{
 it('空来源显示真实空态，不呈现Demo来源',async()=>{
  mount();await screen.findByText('暂无监测来源');
  expect(screen.queryByText('短剧观察 · 样本来源')).toBeNull();
  const opener=screen.getByRole('button',{name:'新增来源'});opener.focus();fireEvent.click(opener);
  expect(screen.getByRole('heading',{name:'新增采集来源'})).toBeTruthy();
  expect(screen.getByLabelText('来源地址')).toBeTruthy();
  expect(screen.getByLabelText('采集频率')).toBeTruthy();
  screen.getByRole('button',{name:'取消'}).focus();fireEvent.click(screen.getByRole('button',{name:'取消'}));
  await waitFor(()=>expect(document.querySelector('dialog')?.open).toBeFalsy());
  expect(document.activeElement).toBe(opener);
 });
 it('读取失败明确反馈，不回退演示成功',async()=>{
  mount(4,true);expect((await screen.findByRole('alert')).textContent).toMatch(/无权/);
  expect(screen.queryByText('演示成功')).toBeNull();
 });
 it('运行状态只读取本业务任务',async()=>{
  const fetcher=mount(4);await screen.findByText('暂无运行任务');
  expect(fetcher.mock.calls.some(([p])=>String(p).includes('/api/v1/tasks?business_code=motion_comic'))).toBe(true);
  expect(screen.queryByText('JOB-091')).toBeNull();
 });
});

it('来源保存失败保留同一幂等键，成功后显示服务端暂停状态',async()=>{
 let saved=false;let writes=0;const keys:string[]=[];
 const source={id:uuid,created_at:'2026-10-17T01:00:00Z',updated_at:'2026-10-17T01:00:00Z',lock_version:'9007199254740993',name:'漫剧监测',business_code:'motion_comic',platform_code:'douyin',target:{kind:'keyword',keyword:'漫剧'},enabled:false,archived:false,last_state:null,last_at:null,plan:{id:uuid,created_at:'2026-10-17T01:00:00Z',lock_version:'1',enabled:false,frequency:'daily_0900',purpose:'intelligence',max_requests:1,max_items:1,connection_id:uuid}};
 const fetcher=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
  const path=String(input);let data:unknown;
  if(path==='/api/v1/session')data=session;
  else if(init?.method==='POST'){
   writes++;keys.push(new Headers(init.headers).get('Idempotency-Key')!);
   expect(JSON.parse(String(init.body))).toMatchObject({name:'漫剧监测',address:'漫剧',business_code:'motion_comic',frequency:'daily_0900'});
   if(writes===1)return new Response(JSON.stringify({request_id:uuid,error:{code:'SERVICE_NOT_READY',message:'unavailable',field_paths:[]}}),{status:503,headers:{'Content-Type':'application/json','X-Request-ID':uuid}});
   saved=true;data=source;
  }else data={items:saved?[source]:[],next_cursor:null,total:saved?'1':'0'};
  return new Response(JSON.stringify({request_id:uuid,data}),{headers:{'Content-Type':'application/json','X-Request-ID':uuid}});
 });
 render(<QueryClientProvider client={new QueryClient()}><ApiProvider client={new ApiClient({fetcher:fetcher as typeof fetch})}><ConsolePage tab={0} business="AI漫剧" /></ApiProvider></QueryClientProvider>);
 await screen.findByText('暂无监测来源');fireEvent.click(screen.getByRole('button',{name:'新增来源'}));
 fireEvent.change(screen.getByLabelText('来源名称'),{target:{value:'漫剧监测'}});fireEvent.change(screen.getByLabelText('来源地址'),{target:{value:'漫剧'}});
 fireEvent.submit(document.querySelector('#consoleSourceForm')!);await screen.findByRole('alert');
 fireEvent.submit(document.querySelector('#consoleSourceForm')!);await screen.findByText('漫剧监测');
 expect(screen.getByText(/关键词来源/)).toBeTruthy();
 expect(keys).toHaveLength(2);expect(keys[0]).toBe(keys[1]);expect(screen.getByRole('button',{name:'启用'})).toBeTruthy();
});

it('超过100个来源仍可在原表格找到并暂停旧来源',async()=>{
 const source=(index:number)=>({id:`11111111-1111-4111-8111-${String(index).padStart(12,'0')}`,created_at:'2026-10-17T01:00:00Z',updated_at:'2026-10-17T01:00:00Z',lock_version:'1',name:`来源-${index}`,business_code:'motion_comic',platform_code:'douyin',target:{kind:'keyword',keyword:'漫剧'},enabled:index===101,archived:false,last_state:null,last_at:null,plan:{id:uuid,created_at:'2026-10-17T01:00:00Z',lock_version:'1',enabled:index===101,frequency:'daily_0900',purpose:'intelligence',max_requests:1,max_items:1,connection_id:uuid}});
 let paused=false;
 const fetcher=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
  const path=String(input);let data:unknown;
  if(path==='/api/v1/session')data=session;
  else if(init?.method==='PATCH'){expect(JSON.parse(String(init.body))).toMatchObject({enabled:false,expected_lock_version:'1'});paused=true;data={...source(101),enabled:false,lock_version:'2'};}
  else if(path.includes('cursor='))data={items:[{...source(101),enabled:!paused}],next_cursor:null,total:'101'};
  else data={items:Array.from({length:100},(_,i)=>source(i+1)),next_cursor:'page-two',total:'101'};
  return new Response(JSON.stringify({request_id:uuid,data}),{headers:{'Content-Type':'application/json','X-Request-ID':uuid}});
 });
 render(<QueryClientProvider client={new QueryClient()}><ApiProvider client={new ApiClient({fetcher:fetcher as typeof fetch})}><ConsolePage tab={0} business="AI漫剧" /></ApiProvider></QueryClientProvider>);
 await screen.findByText('来源-101');fireEvent.click(screen.getByRole('button',{name:'暂停'}));
 await waitFor(()=>expect(paused).toBe(true));
});

it('任务记录随服务端状态刷新，不停留在打开时的处理中',async()=>{
 const at='2026-10-17T01:00:00Z';let done=false;
 const running={id:uuid,created_at:at,updated_at:at,lock_version:'1',kind:'collect.redfox',business_code:'motion_comic',state:'running',business_outcome:null,requested_by:uuid,execution_authorized_by:uuid,max_attempts:1,max_external_calls:1,available_at:at,started_at:at,finished_at:null,safe_error_code:null,outputs:[]};
 const fetcher=vi.fn(async(input:RequestInfo|URL)=>{
  const path=String(input);const task=done?{...running,state:'succeeded',business_outcome:'completed',finished_at:at,lock_version:'2'}:running;
  const data=path==='/api/v1/session'?session:path.includes('/tasks?')?{items:[task],next_cursor:null,total:'1'}:task;
  return new Response(JSON.stringify({request_id:uuid,data}),{headers:{'Content-Type':'application/json','X-Request-ID':uuid}});
 });
 const queries=new QueryClient();
 render(<QueryClientProvider client={queries}><ApiProvider client={new ApiClient({fetcher:fetcher as typeof fetch})}><ConsolePage tab={4} business="AI漫剧" /></ApiProvider></QueryClientProvider>);
 fireEvent.click(await screen.findByRole('button',{name:'查看记录'}));await screen.findByRole('heading',{name:'任务运行记录'});
 done=true;await queries.invalidateQueries({queryKey:['api']});
 await waitFor(()=>expect(document.querySelector('dialog')?.textContent).toContain('成功'));
});
