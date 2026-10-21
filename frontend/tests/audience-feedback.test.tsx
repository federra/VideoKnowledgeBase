import { fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { expect, it, vi } from 'vitest';
import { ApiClient } from '../src/api/client';
import { ApiProvider } from '../src/api/provider';
import { FeedbackDrawer } from '../src/modules/intelligence/FeedbackDrawer';

const id='11111111-1111-4111-8111-111111111111';
const c1='22222222-2222-4222-8222-222222222222',c2='33333333-3333-4333-8333-333333333333';
const stamp='2026-10-17T01:00:00Z';
const absent={entry_id:id,snapshot_id:id,snapshot_version:1,business_code:'motion_comic',business_date:'2026-10-17',platform_code:'douyin',status:'not_acquired',feedback_id:null,feedback_version:null,sampling_description:null,coverage_note:null,sample_count:null,classified_count:null,comments:[],claims:[]};
function mount(data:unknown=absent){
 const fetcher=vi.fn(async(input:RequestInfo|URL)=>{String(input);return new Response(JSON.stringify({request_id:id,data}),{headers:{'Content-Type':'application/json','X-Request-ID':id}});});
 const close=vi.fn();
 render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><ApiProvider client={new ApiClient({fetcher:fetcher as typeof fetch})}><FeedbackDrawer entryId={id} business="motion_comic" date="2026-10-17" title="真实作品" url="javascript:alert(1)" close={close}/></ApiProvider></QueryClientProvider>);
 return {close,fetcher};
}
it('评论未取得仍打开Demo抽屉，不显示百分比或伪造零样本',async()=>{
 const {close,fetcher}=mount();
 await screen.findByText('该日期评论未获取');
 expect(screen.getByRole('dialog',{name:'观众反馈'})).toBeTruthy();
 expect(document.querySelector('.feedback-meter')).toBeNull();
 expect(screen.getByRole('button',{name:'查看TOP评论'}).hasAttribute('disabled')).toBe(true);
 expect(screen.queryByRole('link',{name:/打开原视频/})).toBeNull();
 expect(String(fetcher.mock.calls[0]?.[0])).toContain('business_date=2026-10-17');
 fireEvent.click(screen.getByRole('button',{name:'关闭'}));expect(close).toHaveBeenCalledOnce();
});
it('单作品情绪比例、证据高亮、原文转义，普通抽屉不显示关键反馈',async()=>{
 mount({...absent,status:'ready',feedback_id:id,feedback_version:1,sample_count:2,classified_count:1,sampling_description:'授权样本',coverage_note:'不代表整体观众',comments:[
  {id:c1,created_at:stamp,content_id:id,platform_comment_id:'1',body_text:'<img src=x onerror=alert(1)>',username:null,like_count:'0',posted_at_raw:null,posted_at:null,captured_at:stamp},
  {id:c2,created_at:stamp,content_id:id,platform_comment_id:'2',body_text:'期待下一集',username:null,like_count:null,posted_at_raw:null,posted_at:null,captured_at:stamp}],
 claims:[{id,kind:'emotion',text:'期待',support_count:1,comment_ids:[c1],details:{trigger:'后续发展'}}]});
 await screen.findByText('1 条 · 100%');
 expect(screen.queryByText(/关键反馈/)).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'查看1条证据 ›'}));
 expect(document.querySelectorAll('.is-evidence')).toHaveLength(1);
 expect(document.querySelector('.feedback-comment img')).toBeNull();
 expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeTruthy();
 expect(screen.getByText(/非全站排名/)).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'研判该内容'}));
 expect(await screen.findByText(/当前未创建研判任务/)).toBeTruthy();
});

it('关闭抽屉后将键盘焦点还给原入口',async()=>{
 const opener=document.createElement('button');document.body.append(opener);opener.focus();
 const client=new ApiClient({fetcher:vi.fn(async()=>new Response(JSON.stringify({request_id:id,data:absent}),{headers:{'Content-Type':'application/json','X-Request-ID':id}})) as typeof fetch});
 const mounted=render(<QueryClientProvider client={new QueryClient()}><ApiProvider client={client}><FeedbackDrawer entryId={id} business="motion_comic" date="2026-10-17" title="作品" url={null} close={()=>{}}/></ApiProvider></QueryClientProvider>);
 await screen.findByText('该日期评论未获取');screen.getByRole('button',{name:'关闭'}).focus();
 mounted.unmount();expect(document.activeElement).toBe(opener);opener.remove();
});

it('红果原始评论可独立展示，不伪造分析版本和情绪',async()=>{
 mount({...absent,platform_code:'hongguo',status:'sampled',sample_count:1,classified_count:0,sampling_description:'第一页预载',coverage_note:'未分析，跨集归属未验证',comments:[
 {id:c1,created_at:stamp,content_id:id,platform_comment_id:null,body_text:'红果原始评论',username:'观众',like_count:'116',posted_at_raw:'1792339200',posted_at:stamp,captured_at:stamp}]});
 await screen.findByText('已采集的评论原文（未分析）');
 expect(screen.getByText('红果原始评论')).toBeTruthy();
 expect(document.querySelectorAll('.feedback-meter')).toHaveLength(0);
 expect(screen.getByText(/未分析，跨集归属未验证/)).toBeTruthy();
});
