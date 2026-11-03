import {act,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {expect,it} from 'vitest';
import {ApiClient} from '../src/api/client';
import {ApiProvider} from '../src/api/provider';
import {IntelligencePage} from '../src/modules/intelligence/IntelligencePage';
const id='11111111-1111-4111-8111-111111111111';
const session={org_id:id,member_id:id,authz_version:'1',csrf_token:'a'.repeat(64),display_name:'南哥',actions:['content.read'],expires_at:'2099-10-17T01:00:00Z'};
const empty={business_code:'motion_comic',business_date:'2026-10-17',has_snapshot:false,metrics:{videos:null,creators:null,comments:null,likes:null},boards:[],creators:[],page:1,page_size:10,total:'0',items:[],insight:null};
const novelEmpty={business_code:'motion_comic',business_date:'2026-10-17',novel_count:null,page:1,page_size:10,total:'0',items:[],rank_types:[],genders:[],genres:[],statuses:[]};
// Keep the real API/query/components; control only network completion.
function pendingOverview(business='AI漫剧'){
 const pending:{url:URL;resolve:(response:Response)=>void}[]=[];
 const response=(data:unknown,status=200)=>new Response(JSON.stringify(status===200?{request_id:id,data}:{request_id:id,error:{code:'UPSTREAM_TIMEOUT',message:'读取超时'}}),{status,headers:{'Content-Type':'application/json'}});
 const api=new ApiClient({fetcher:(async(input:RequestInfo|URL)=>String(input)==='/api/v1/session'?response(session):new Promise<Response>(resolve=>pending.push({url:new URL(String(input),'http://local'),resolve}))) as typeof fetch});
 const qc=new QueryClient();
 const app=(biz:string,day:string)=><QueryClientProvider client={qc}><ApiProvider client={api}><IntelligencePage business={biz} date={day}/></ApiProvider></QueryClientProvider>;
 const view=render(app(business,'2026-10-17'));
 return {qc,counts:()=>Array.from(document.querySelectorAll('.feed-overview strong')).map(x=>x.textContent),change:(biz:string,day:string)=>view.rerender(app(biz,day)),async finish(novel:boolean,data:unknown,status=200){await waitFor(()=>expect(pending.some(x=>x.url.pathname.endsWith(novel?'/novels':'/feed'))).toBe(true));const index=pending.findIndex(x=>x.url.pathname.endsWith(novel?'/novels':'/feed'));const [request]=pending.splice(index,1);await act(async()=>request.resolve(response(status===200?{...(data as object),business_code:request.url.searchParams.get('business_code'),business_date:request.url.searchParams.get('business_date')}:data,status)));}};
}
it.each(['AI漫剧','故事短片','电商短视频'])('%s初次请求待返回时三个指标加载中，独立完成才确认缺失',async business=>{
 const app=pendingOverview(business);
 await waitFor(()=>expect(app.counts()).toEqual(['加载中','加载中','加载中']));
 await app.finish(false,{...empty,metrics:{...empty.metrics,videos:'0'}});
 await waitFor(()=>expect(app.counts()).toEqual(['0','未获取','加载中']));
 await app.finish(true,novelEmpty);await waitFor(()=>expect(app.counts()).toEqual(['0','未获取','未获取']));
});
it('小说先完成不提前把未完成的视频和博主显示未获取',async()=>{
 const app=pendingOverview();await screen.findByRole('button',{name:'视频'});
 await app.finish(true,{...novelEmpty,novel_count:'200'});await waitFor(()=>expect(app.counts()).toEqual(['加载中','加载中','200']));
 await app.finish(false,empty);await waitFor(()=>expect(app.counts()).toEqual(['未获取','未获取','200']));
});
it('视频失败显示加载失败，显式重试恢复加载中，成功空响应才显示未获取',async()=>{
 const app=pendingOverview();await screen.findByRole('button',{name:'视频'});
 await app.finish(false,null,500);await app.finish(true,{...novelEmpty,novel_count:'200'});
 await waitFor(()=>expect(app.counts()).toEqual(['加载失败','加载失败','200']));
 fireEvent.click(within(screen.getByRole('alert')).getByRole('button',{name:'重试'}));
 await waitFor(()=>expect(app.counts()).toEqual(['加载中','加载中','200']));
 await app.finish(false,empty);await waitFor(()=>expect(app.counts()).toEqual(['未获取','未获取','200']));
});
it('小说失败独立显示失败，重新读取期间不显示无数据',async()=>{
 const app=pendingOverview();await screen.findByRole('button',{name:'视频'});
 await app.finish(false,{...empty,metrics:{...empty.metrics,videos:'60',creators:'3'}});await app.finish(true,null,500);
 await waitFor(()=>expect(app.counts()).toEqual(['60','3','加载失败']));
 let retry:Promise<unknown>|undefined;act(()=>{retry=app.qc.refetchQueries({predicate:q=>q.queryKey.includes('novels')});});
 await waitFor(()=>expect(app.counts()).toEqual(['60','3','加载中']));
 await app.finish(true,novelEmpty);await act(async()=>{await retry;});await waitFor(()=>expect(app.counts()).toEqual(['60','3','未获取']));
});
it('切日期和业务立即隐藏旧范围数值，独立加载新范围',async()=>{
 const app=pendingOverview();await screen.findByRole('button',{name:'视频'});
 await app.finish(false,{...empty,metrics:{...empty.metrics,videos:'60',creators:'3'}});await app.finish(true,{...novelEmpty,novel_count:'200'});
 await waitFor(()=>expect(app.counts()).toEqual(['60','3','200']));
 app.change('AI漫剧','2026-10-18');await waitFor(()=>expect(app.counts()).toEqual(['加载中','加载中','加载中']));
 await app.finish(false,empty);await app.finish(true,novelEmpty);await waitFor(()=>expect(app.counts()).toEqual(['未获取','未获取','未获取']));
 app.change('故事短片','2026-10-18');await waitFor(()=>expect(app.counts()).toEqual(['加载中','加载中','加载中']));
 await app.finish(false,{...empty,metrics:{...empty.metrics,videos:'5'}});await app.finish(true,{...novelEmpty,novel_count:'0'});await waitFor(()=>expect(app.counts()).toEqual(['5','未获取','0']));
});
it('同日切榜重新读取或失败保留已确认数量，未确认的指标仍独立加载',async()=>{
 const app=pendingOverview();await screen.findByRole('button',{name:'视频'});
 await app.finish(false,{...empty,metrics:{...empty.metrics,videos:'60',creators:'3'}});
 await waitFor(()=>expect(app.counts()).toEqual(['60','3','加载中']));
 fireEvent.change(screen.getByRole('combobox',{name:'榜单类型'}),{target:{value:'tikhub'}});
 expect(app.counts()).toEqual(['60','3','加载中']);await app.finish(false,null,500);
 await screen.findByRole('alert');expect(app.counts()).toEqual(['60','3','加载中']);
 await app.finish(true,{...novelEmpty,novel_count:'200'});await waitFor(()=>expect(app.counts()).toEqual(['60','3','200']));
});
it('切日期后旧请求迟到不能解除新范围加载或显示旧数值',async()=>{
 const app=pendingOverview();await screen.findByRole('button',{name:'视频'});
 app.change('AI漫剧','2026-10-18');
 await app.finish(false,{...empty,metrics:{...empty.metrics,videos:'60',creators:'3'}});await app.finish(true,{...novelEmpty,novel_count:'200'});
 expect(app.counts()).toEqual(['加载中','加载中','加载中']);
 await app.finish(false,empty);await app.finish(true,novelEmpty);await waitFor(()=>expect(app.counts()).toEqual(['未获取','未获取','未获取']));
});
