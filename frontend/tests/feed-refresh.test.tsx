import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {expect,it,vi} from 'vitest';
import {ApiClient} from '../src/api/client';
import {ApiProvider} from '../src/api/provider';
import {RefreshControl} from '../src/modules/intelligence/RefreshControl';
const id='11111111-1111-4111-8111-111111111111';
const idle={task_id:null,business_code:'motion_comic',business_date:'2026-10-22',state:'idle',channels:[]};
const reply=(data:unknown)=>new Response(JSON.stringify({request_id:id,data}),{status:200,headers:{'Content-Type':'application/json'}});
it('refresh reads never collect; one explicit click uses only business and caller idempotency key',async()=>{
 const posts:RequestInit[]=[];const date=vi.fn();let started=false;
 const running={...idle,task_id:id,state:'running',channels:[{code:'hongguo',name:'红果',state:'running',completed:1,total:4,message:'正在采集'}]};
 const fetcher=vi.fn(async(_url:RequestInfo|URL,init?:RequestInit)=>{
  if(init?.method==='POST'){posts.push(init);started=true;return reply(running);}
  return reply(started?running:idle);
 });
 const api=new ApiClient({fetcher:fetcher as typeof fetch});
 // Initialize the existing client session/CSRF boundary through its public API.
 fetcher.mockImplementationOnce(async()=>reply({org_id:id,member_id:id,authz_version:'1',csrf_token:'a'.repeat(64),display_name:'南哥',actions:['content.read','collection.run'],expires_at:'2099-10-17T01:00:00Z'}));
 await api.getSession();
 render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><ApiProvider client={api}><RefreshControl business="motion_comic" allowed onDateChange={date}/></ApiProvider></QueryClientProvider>);
 const button=await screen.findByRole('button',{name:'重新采集'});await waitFor(()=>expect(fetcher).toHaveBeenCalledTimes(2));expect(posts).toHaveLength(0);
 fireEvent.click(button);fireEvent.click(button);
 fireEvent.click(await screen.findByRole('button',{name:'正在重新采集'}));
 await screen.findByText('正在采集');expect(posts).toHaveLength(1);expect(JSON.parse(String(posts[0].body))).toEqual({business_code:'motion_comic'});
 expect(new Headers(posts[0].headers).get('Idempotency-Key')).toMatch(/^[\da-f-]{36}$/);expect(date).toHaveBeenCalledWith('2026-10-22');expect((screen.getByRole('button',{name:'采集中…'}) as HTMLButtonElement).disabled).toBe(true);
});
it('a transient status read failure keeps the active batch disabled and polling recoverable',async()=>{
 const queries=new QueryClient({defaultOptions:{queries:{retry:false}}});let failed=false,finished=false;let posts=0;
 const session={org_id:id,member_id:id,authz_version:'1',csrf_token:'a'.repeat(64),display_name:'南哥',actions:['content.read','collection.run'],expires_at:'2099-10-17T01:00:00Z'};
 const fetcher=vi.fn(async(url:RequestInfo|URL,init?:RequestInit)=>{
  if(String(url).endsWith('/session'))return reply(session);
  if(init?.method==='POST')posts++;
  if(failed&&init?.method!=='POST')return new Response(JSON.stringify({request_id:id,error:{code:'SERVICE_NOT_READY',message:'暂不可用',field_paths:[]}}),{status:503,headers:{'Content-Type':'application/json'}});
  return reply({...idle,task_id:id,state:finished?'completed':'running',channels:[]});
 });
 const api=new ApiClient({fetcher:fetcher as typeof fetch});await api.getSession();
 render(<QueryClientProvider client={queries}><ApiProvider client={api}><RefreshControl business="motion_comic" allowed onDateChange={()=>{}}/></ApiProvider></QueryClientProvider>);
 await screen.findByRole('button',{name:'采集中…'});
 fireEvent.click(screen.getByRole('button',{name:'正在重新采集'}));
 failed=true;await queries.invalidateQueries({queryKey:['api']});
 await screen.findByText(/将继续核验，不会重复采集/);
 expect((screen.getByRole('button',{name:'采集中…'}) as HTMLButtonElement).disabled).toBe(true);
 failed=false;finished=true;await queries.invalidateQueries({queryKey:['api']});
 await screen.findByRole('button',{name:'采集完成'});expect(posts).toBe(0);
});
it('story refresh displays all six runtime channels including microfilm without starting collection',async()=>{
 const codes=['hongguo','tikhub','fanqie','qidian','creators','microfilm'];
 const view={...idle,business_code:'story_short',task_id:id,state:'partial',channels:codes.map(code=>({code,name:code==='microfilm'?'抖音微电影':code,state:code==='microfilm'?'succeeded':'unavailable',completed:code==='microfilm'?1:0,total:code==='microfilm'?1:0,message:code==='microfilm'?'今日50条视频已保存':'当前不可采集'}))};
 const fetcher=vi.fn(async()=>reply(view));const api=new ApiClient({fetcher:fetcher as typeof fetch});
 render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><ApiProvider client={api}><RefreshControl business="story_short" allowed onDateChange={()=>{}}/></ApiProvider></QueryClientProvider>);
 const summary=await screen.findByRole('button',{name:'采集结果'});
 expect(summary.getAttribute('aria-expanded')).toBe('false');
 expect(screen.queryByText(/抖音微电影/)).toBeNull();
 expect(summary.compareDocumentPosition(screen.getByRole('button',{name:'重新采集'}))&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
 fireEvent.click(summary);
 await screen.findByText(/抖音微电影/);
 fireEvent.click(screen.getByRole('button',{name:'收起采集结果'}));
 expect(screen.queryByText(/抖音微电影/)).toBeNull();
 expect(document.activeElement).toBe(summary);
 fireEvent.click(summary);
 expect(screen.getByText('今日50条视频已保存')).toBeTruthy();
 expect(screen.queryByText(/服务响应格式异常/)).toBeNull();
 expect(fetcher.mock.calls.every(call=>(call as unknown as [unknown,RequestInit?])[1]?.method!=='POST')).toBe(true);
});
it.each(['unknown','oversized'])('refresh still rejects %s channel payloads',async kind=>{
 const channel={code:'microfilm',name:'抖音微电影',state:'succeeded',completed:1,total:1,message:'已保存'};
 const channels=kind==='unknown'?[{...channel,code:'arbitrary'}]:Array.from({length:8},()=>channel);
 const api=new ApiClient({fetcher:(async()=>reply({...idle,business_code:'story_short',channels})) as typeof fetch});
 await expect(api.intelligenceRefresh('story_short')).rejects.toMatchObject({code:'INVALID_RESPONSE'});
});

it('refresh accepts Qimao as a known seventh channel',async()=>{
 const channels=['hongguo','tikhub','fanqie','qidian','creators','microfilm','qimao'].map(code=>({code,name:code,state:'succeeded',completed:1,total:1,message:'已保存'}));
 const api=new ApiClient({fetcher:(async()=>reply({...idle,business_code:'motion_comic',channels})) as typeof fetch});
 expect((await api.intelligenceRefresh('motion_comic')).channels).toHaveLength(7);
});
