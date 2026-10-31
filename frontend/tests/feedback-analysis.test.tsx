import type { ComponentProps } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { expect, it, vi } from 'vitest';
import { ApiClient } from '../src/api/client';
import { ApiProvider } from '../src/api/provider';
import { FeedbackDrawer } from '../src/modules/intelligence/FeedbackDrawer';
const id='11111111-1111-4111-8111-111111111111', cid='22222222-2222-4222-8222-222222222222', other='33333333-3333-4333-8333-333333333333';
const sample='b'.repeat(64),stamp='2026-10-17T01:00:00Z';
const session={org_id:id,member_id:cid,display_name:'成员',actions:[],authz_version:'1',csrf_token:'a'.repeat(64),expires_at:'2030-01-01T00:00:00Z'};
const base={entry_id:id,snapshot_id:id,snapshot_version:1,business_code:'motion_comic',business_date:'2026-10-17',platform_code:'hongguo',status:'sampled',feedback_id:null,feedback_version:null,sampling_description:'第一页样本',coverage_note:'不代表整体观众',sample_count:1,classified_count:0,comments:[{id:cid,created_at:stamp,content_id:id,platform_comment_id:null,body_text:'这是原始评论',username:null,like_count:'1',posted_at:null,posted_at_raw:null,captured_at:stamp}],claims:[],sample_key:sample,analysis_model_ready:true,analysis:null,summary:null};
const task={id:other,entry_id:id,snapshot_id:id,business_code:'motion_comic',business_date:'2026-10-17',sample_key:sample,state:'queued',result_state:null,safe_error_code:null,feedback_id:null};
const envelope=(data:unknown,status=200)=>new Response(JSON.stringify({request_id:id,data}),{status,headers:{'Content-Type':'application/json'}});
async function setup(options:{initial?:unknown;post?:(init:RequestInit)=>Promise<Response>;poll?:()=>Promise<Response>}={}){
 const fetcher=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
  const path=String(input);if(path.endsWith('/session'))return envelope(init?.method==='DELETE'?{acknowledged:true}:session);
  if(init?.method==='POST')return options.post?options.post(init):envelope(task,202);
  if(path.includes('/feedback-analyses/'))return options.poll?options.poll():envelope({...task,state:'succeeded',result_state:'insufficient_evidence',feedback_id:id});
  return envelope(options.initial??base);
 });
 const client=new ApiClient({fetcher});await client.getSession();const queries=new QueryClient({defaultOptions:{queries:{retry:false}}});
 const props={entryId:id,business:'motion_comic' as const,date:'2026-10-17',title:'作品',url:null,close:vi.fn()};
 const tree=(p:ComponentProps<typeof FeedbackDrawer>=props)=><QueryClientProvider client={queries}><ApiProvider client={client}><FeedbackDrawer {...p}/></ApiProvider></QueryClientProvider>;
 const mounted=render(tree());await screen.findByText('这是原始评论');
 return {fetcher,client,mounted,tree,props};
}
it('POST走现有CSRF/幂等传输，同步双击只创建一次',async()=>{
 let finish!:(v:Response)=>void;const post=new Promise<Response>(r=>{finish=r;});
 const {fetcher}=await setup({post:()=>post});expect(fetcher.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(0);const button=screen.getByRole('button',{name:'评论分析'});expect(button.classList.contains('primary')).toBe(true);
 fireEvent.click(button);fireEvent.click(button);
 expect(fetcher.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(1);
 const [postUrl,init]=fetcher.mock.calls.find(([,init])=>init?.method==='POST')!;
 expect(postUrl).toBe(`/api/v1/intelligence/entries/${id}/feedback/analyze`);
 expect(new Headers(init?.headers).get('X-CSRF-Token')).toBe(session.csrf_token);
 expect(new Headers(init?.headers).get('Idempotency-Key')).toMatch(/^[a-f0-9-]{36}$/);
 expect(JSON.parse(String(init?.body))).toEqual({business_code:'motion_comic',business_date:'2026-10-17',expected_sample_key:sample,retry_of:null});
 await act(async()=>finish(envelope(task,202)));expect(screen.getByRole('button',{name:'评论分析'}).hasAttribute('disabled')).toBe(true);
});
it('无CSRF的分析请求在本地拒绝，0POST',async()=>{
 const fetcher=vi.fn();const client=new ApiClient({fetcher});
 await expect(client.analyzeFeedback(id,'motion_comic','2026-10-17',sample,null,id)).rejects.toMatchObject({code:'AUTH_REQUIRED'});
 expect(fetcher).not.toHaveBeenCalled();
});
it('没有模型配置仅指向现有控制台，不POST',async()=>{
 const {fetcher}=await setup({initial:{...base,analysis_model_ready:false}});
 expect(screen.getByRole('link',{name:'请到控制台配置用户评论分析'}).getAttribute('href')).toBe('#/3/5');
 fireEvent.click(screen.getByRole('button',{name:'评论分析'}));expect(fetcher.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false);
});
it('已有活跃分析直接GET轮询，完成刷新证据，不POST',async()=>{
 const {fetcher}=await setup({initial:{...base,analysis:task}});
 await screen.findByText('评论分析已完成',{}, {timeout:2500});
 await waitFor(()=>expect(fetcher.mock.calls.filter(([url])=>String(url).includes('/feedback?')).length).toBeGreaterThanOrEqual(2));
 expect(fetcher.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(0);
 expect(fetcher.mock.calls.filter(([url])=>String(url).includes('/feedback-analyses/')).every(([url])=>new URL(String(url),'http://local').searchParams.get('entry_id')===id)).toBe(true);
 expect(screen.getAllByText('样本不足，无法形成可靠归纳').length).toBeGreaterThan(0);
});
it('失败必须用户显式重试并绑定旧任务，已有成功不得再POST',async()=>{
 const {fetcher}=await setup({initial:{...base,analysis:{...task,state:'failed',safe_error_code:'MODEL_FAILED'}}});
 expect(fetcher.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false);
 fireEvent.click(screen.getByRole('button',{name:'评论分析'}));
 await screen.findByText('正在分析当前日期的评论样本');
 const [,init]=fetcher.mock.calls.find(([,init])=>init?.method==='POST')!;expect(JSON.parse(String(init?.body)).retry_of).toBe(other);
});
it('未知响应不自动重发，显式核验保留原body与幂等键',async()=>{
 let attempts=0;const {fetcher}=await setup({post:async()=>{if(++attempts===1)throw new TypeError('network');return envelope(task,202);}});
 fireEvent.click(screen.getByRole('button',{name:'评论分析'}));await screen.findByText(/提交结果待核验/);
 expect(attempts).toBe(1);fireEvent.click(screen.getByRole('button',{name:'评论分析'}));await screen.findByText('正在分析当前日期的评论样本');
 const calls=fetcher.mock.calls.filter(([,init])=>init?.method==='POST');expect(calls).toHaveLength(2);
 expect(calls[0][1]?.body).toEqual(calls[1][1]?.body);expect(new Headers(calls[0][1]?.headers).get('Idempotency-Key')).toBe(new Headers(calls[1][1]?.headers).get('Idempotency-Key'));
});
it('关闭抽屉取消GET与POST，迟到返回不能刷新证据',async()=>{
 let finish!:(v:Response)=>void;const p=new Promise<Response>(r=>{finish=r;});
 const {fetcher,mounted}=await setup({post:()=>p});fireEvent.click(screen.getByRole('button',{name:'评论分析'}));
 const signal=fetcher.mock.calls.find(([,init])=>init?.method==='POST')![1]?.signal;
 mounted.unmount();expect(signal?.aborted).toBe(true);const before=fetcher.mock.calls.length;
 await act(async()=>finish(envelope({...task,state:'succeeded',result_state:'completed',feedback_id:id},202)));
 expect(fetcher).toHaveBeenCalledTimes(before);
});
it('切日期卸载旧状态与轮询，迟到POST不串页',async()=>{
 let finish!:(v:Response)=>void;const p=new Promise<Response>(r=>{finish=r;});
 const {fetcher,mounted,tree,props}=await setup({post:()=>p});fireEvent.click(screen.getByRole('button',{name:'评论分析'}));
 const signal=fetcher.mock.calls.find(([,init])=>init?.method==='POST')![1]?.signal;
 mounted.rerender(tree({...props,date:'2026-10-18'}));expect(signal?.aborted).toBe(true);
 await act(async()=>finish(envelope({...task,state:'succeeded',result_state:'completed',feedback_id:id},202)));
 expect(screen.queryByText('评论分析已完成')).toBeNull();
});
it('已成功任务只读复用',async()=>{
 const {fetcher}=await setup({initial:{...base,analysis:{...task,state:'succeeded',result_state:'completed',feedback_id:id}}});
 expect(screen.getByRole('button',{name:'评论分析'}).hasAttribute('disabled')).toBe(true);expect(screen.getByText('评论分析已完成')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'评论分析'}));expect(fetcher.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false);
});
it.each([{entryId:other},{business:'story_short' as const}])('切换作品或业务清理旧POST与结果：%j',async change=>{
 let finish!:(v:Response)=>void;const p=new Promise<Response>(r=>{finish=r;});
 const {fetcher,mounted,tree,props}=await setup({post:()=>p});fireEvent.click(screen.getByRole('button',{name:'评论分析'}));
 const signal=fetcher.mock.calls.find(([,init])=>init?.method==='POST')![1]?.signal;
 mounted.rerender(tree({...props,...change}));expect(signal?.aborted).toBe(true);
 await act(async()=>finish(envelope({...task,state:'succeeded',result_state:'completed',feedback_id:id},202)));
 expect(screen.queryByText('评论分析已完成')).toBeNull();
});
it('身份边界立即取消运行并清空旧证据',async()=>{
 let finish!:(v:Response)=>void;const p=new Promise<Response>(r=>{finish=r;});
 const {fetcher,client}=await setup({post:()=>p});fireEvent.click(screen.getByRole('button',{name:'评论分析'}));
 const signal=fetcher.mock.calls.find(([,init])=>init?.method==='POST')![1]?.signal;
 await act(async()=>{await client.logout();});expect(signal?.aborted).toBe(true);
 expect(screen.queryByText('这是原始评论')).toBeNull();
 await act(async()=>finish(envelope(task,202)));expect(screen.queryByText('正在分析当前日期的评论样本')).toBeNull();
});
it('关闭后重开未知提交继续使用原幂等键，不自动POST',async()=>{
 const {fetcher,mounted,tree}=await setup({post:async()=>{throw new TypeError('network');}});
 fireEvent.click(screen.getByRole('button',{name:'评论分析'}));await screen.findByText(/提交结果待核验/);mounted.unmount();
 render(tree());await screen.findByText(/提交结果待核验/);
 expect(fetcher.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(1);
 fireEvent.click(screen.getByRole('button',{name:'评论分析'}));await screen.findByText(/提交结果待核验/);
 const calls=fetcher.mock.calls.filter(([,init])=>init?.method==='POST');expect(calls).toHaveLength(2);
 expect(new Headers(calls[0][1]?.headers).get('Idempotency-Key')).toBe(new Headers(calls[1][1]?.headers).get('Idempotency-Key'));
});

it('轮询错误只显式恢复GET，不创建新POST',async()=>{
 let reads=0;const {fetcher}=await setup({initial:{...base,analysis:task},poll:async()=>{if(++reads===1)throw new TypeError('offline');return envelope({...task,state:'succeeded',result_state:'completed',feedback_id:id});}});
 await screen.findByRole('button',{name:'重新读取状态'},{timeout:2500});
 fireEvent.click(screen.getByRole('button',{name:'重新读取状态'}));await screen.findByText('评论分析已完成',{}, {timeout:2500});
 expect(fetcher.mock.calls.filter(([,init])=>init?.method==='POST')).toHaveLength(0);expect(reads).toBe(2);
});
it('成功响应指向其他快照按未知处理，不能串入结果',async()=>{
 await setup({post:async()=>envelope({...task,snapshot_id:cid,state:'succeeded',result_state:'completed',feedback_id:id},202)});
 fireEvent.click(screen.getByRole('button',{name:'评论分析'}));await screen.findByText(/提交结果待核验/);
 expect(screen.queryByText('评论分析已完成')).toBeNull();
});

it('共享批次任务GET明确指定第二部作品，拒绝首部回执，保留旧无entry调用',async()=>{
 const fetcher=vi.fn(async(input:RequestInfo|URL)=>envelope({...task,entry_id:new URL(String(input),'http://local').searchParams.get('entry_id')??id}));
 const client=new ApiClient({fetcher});
 expect((await client.feedbackAnalysis(other,undefined,cid)).entry_id).toBe(cid);
 expect(String(fetcher.mock.calls[0][0])).toContain('entry_id='+cid);
 expect((await client.feedbackAnalysis(other)).entry_id).toBe(id);expect(String(fetcher.mock.calls[1][0])).not.toContain('?');
 const wrong=new ApiClient({fetcher:vi.fn(async()=>envelope(task))});
 await expect(wrong.feedbackAnalysis(other,undefined,cid)).rejects.toMatchObject({code:'INVALID_RESPONSE'});
});
it('共享任务GET非法entry_id本地拒绝，不发送请求',async()=>{
 const fetcher=vi.fn();const client=new ApiClient({fetcher});
 await expect(client.feedbackAnalysis(other,undefined,'invalid')).rejects.toMatchObject({code:'INVALID_REQUEST'});expect(fetcher).not.toHaveBeenCalled();
});
