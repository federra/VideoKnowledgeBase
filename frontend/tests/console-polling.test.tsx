import {act,fireEvent,render,screen} from '@testing-library/react';
import {QueryClient,QueryClientProvider,focusManager} from '@tanstack/react-query';
import {afterEach,expect,it,vi} from 'vitest';
import {ApiClient} from '../src/api/client';
import {ApiProvider} from '../src/api/provider';
import {ConsolePage} from '../src/modules/console/ConsolePage';
const id='11111111-1111-4111-8111-111111111111',at='2026-11-01T01:00:00Z';
const session={org_id:id,member_id:id,authz_version:'1',csrf_token:'a'.repeat(64),display_name:'管理员',actions:['task.read'],expires_at:'2099-11-01T01:00:00Z'};
const task=(state:string)=>({id,created_at:at,updated_at:at,lock_version:'1',kind:'collect.redfox',business_code:'motion_comic',state,business_outcome:null,requested_by:id,execution_authorized_by:id,max_attempts:1,max_external_calls:1,available_at:at,started_at:null,finished_at:null,safe_error_code:null,outputs:[]});
const response=(data:unknown)=>new Response(JSON.stringify({request_id:id,data}),{headers:{'Content-Type':'application/json'}});
async function tick(ms=0){await act(async()=>{await vi.advanceTimersByTimeAsync(ms);});}
async function mount(initial:string|null,tab=4){
 vi.useFakeTimers();let state=initial,reads=0,fail=false,hold=false,release:((r:Response)=>void)|undefined;
 const queries=new QueryClient({defaultOptions:{queries:{retry:false}}});
 const client=new ApiClient({fetcher:async path=>{
  if(String(path).endsWith('/session'))return response(session);
  reads++;
  if(hold)return new Promise<Response>(r=>{release=r;});
  if(fail)throw Error('temporary failure');
  return response({items:state?[task(state)]:[],next_cursor:null,total:state?'1':'0'});
 }});
 const tree=render(<QueryClientProvider client={queries}><ApiProvider client={client}><ConsolePage tab={tab} business="AI漫剧"/></ApiProvider></QueryClientProvider>);
 await tick();await tick();
 return {reads:()=>reads,state:(s:string|null)=>{state=s;},fail:(v:boolean)=>{fail=v;},hold:()=>{hold=true;},release:async()=>{await act(async()=>release!(response({items:[task('succeeded')],next_cursor:null,total:'1'})));await tick();},unmount:()=>{tree.unmount();queries.clear();}};
}
afterEach(()=>{focusManager.setFocused(undefined);vi.useRealTimers();vi.restoreAllMocks();});
it.each(['succeeded','failed','cancelled',null])('无活动任务（%s）不定时查询',async state=>{const f=await mount(state);expect(f.reads()).toBe(1);await tick(35000);expect(f.reads()).toBe(1);f.unmount();});
it('采集配置页没有周期查询',async()=>{const f=await mount(null,0);expect(f.reads()).toBe(1);await tick(35000);expect(f.reads()).toBe(1);f.unmount();});
it.each(['queued','running','cancel_requested'])('活动状态%s每10秒更新，结束立即停止',async state=>{const f=await mount(state);await tick(10000);expect(f.reads()).toBe(2);f.state('succeeded');await tick(10000);expect(f.reads()).toBe(3);await tick(35000);expect(f.reads()).toBe(3);f.unmount();});
it('后台标签页不轮询，回到前台先读取一次以发现新任务',async()=>{
 let visibility='visible';vi.spyOn(document,'visibilityState','get').mockImplementation(()=>visibility as DocumentVisibilityState);
 const f=await mount('running');visibility='hidden';await act(async()=>fireEvent(window,new Event('visibilitychange')));await tick(35000);expect(f.reads()).toBe(1);
 visibility='visible';await act(async()=>fireEvent(window,new Event('visibilitychange')));await tick();expect(f.reads()).toBe(2);
 f.state('succeeded');await tick(10000);expect(f.reads()).toBe(3);await tick(20000);expect(f.reads()).toBe(3);f.unmount();
});
it('请求失败停止轮询，用户重试成功后恢复活动任务更新',async()=>{const f=await mount('running');f.fail(true);await tick(10000);expect(f.reads()).toBe(2);await tick(30000);expect(f.reads()).toBe(2);f.fail(false);await act(async()=>fireEvent.click(screen.getByRole('button',{name:'重试'})));await tick();expect(f.reads()).toBe(3);await tick(10000);expect(f.reads()).toBe(4);f.unmount();});
it('慢请求不重叠或反复取消，离开运行状态页停止查询',async()=>{const f=await mount('running');f.hold();await tick(10000);expect(f.reads()).toBe(2);await tick(10000);expect(f.reads()).toBe(2);await f.release();await tick(20000);expect(f.reads()).toBe(2);f.unmount();await tick(20000);expect(f.reads()).toBe(2);});
it('离开页面再进入仍主动读取，不依赖上次任务状态',async()=>{const f=await mount('succeeded');f.unmount();const next=await mount('running');expect(next.reads()).toBe(1);await tick(10000);expect(next.reads()).toBe(2);next.unmount();});
it('停止后回到前台仍检查一次并发现新排队任务',async()=>{const f=await mount('succeeded');await act(async()=>focusManager.setFocused(false));f.state('queued');await tick(20000);expect(f.reads()).toBe(1);await act(async()=>focusManager.setFocused(true));await tick();expect(f.reads()).toBe(2);await tick(10000);expect(f.reads()).toBe(3);f.unmount();});
it('有运行任务时离开页面也立即停止定时查询',async()=>{const f=await mount('running');f.unmount();await tick(35000);expect(f.reads()).toBe(1);});
