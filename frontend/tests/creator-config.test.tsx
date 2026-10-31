import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {expect,it,vi} from 'vitest';
import {ApiClient} from '../src/api/client';
import {ApiProvider} from '../src/api/provider';
import {CreatorConfigButton} from '../src/modules/intelligence/CreatorConfig';
const id='11111111-1111-4111-8111-111111111111';
const reply=(data:unknown)=>new Response(JSON.stringify({request_id:id,data}),{status:200,headers:{'Content-Type':'application/json'}});
it('opens business config without collecting, submits batch, reports invalid lines, removes and restores focus',async()=>{
 const writes:string[]=[];let items:unknown[]=[];
 const fetcher=vi.fn(async(url:RequestInfo|URL,init?:RequestInit)=>{
  if(String(url).endsWith('/session'))return reply({org_id:id,member_id:id,authz_version:'1',csrf_token:'a'.repeat(64),display_name:'南哥',actions:['source.configure'],expires_at:'2099-10-17T01:00:00Z'});
  if(init?.method==='POST'){
   writes.push(String(url));
   const body=JSON.parse(String(init.body));expect(body.business_code).toBe('motion_comic');
   items=String(url).endsWith('/remove')?[]:[{id,url:'https://www.douyin.com/user/MS4wLjAB123',platform_uid:'123456',display_name:'容量夏然短剧'}];
   return reply({business_code:'motion_comic',items,results:items.length?[{line:1,state:'added',message:'已保存'},{line:2,state:'invalid',message:'仅支持完整主页链接'}]:[]});
  }
  return reply({business_code:'motion_comic',items,results:[]});
 });
 const api=new ApiClient({fetcher:fetcher as typeof fetch});await api.getSession();
 render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><ApiProvider client={api}><CreatorConfigButton business="motion_comic"/></ApiProvider></QueryClientProvider>);
 const trigger=screen.getByRole('button',{name:'配置博主'});trigger.focus();fireEvent.click(trigger);
 await screen.findByText('暂未配置博主');expect(writes).toHaveLength(0);
 fireEvent.change(screen.getByLabelText('博主主页链接，每行一个'),{target:{value:'https://www.douyin.com/user/MS4wLjAB123\nbad'}});
 fireEvent.click(screen.getByRole('button',{name:'保存配置'}));
 await screen.findByText('第2行：仅支持完整主页链接');const profile=screen.getByRole('link',{name:'打开博主容量夏然短剧的主页'});expect(profile.getAttribute('href')).toBe('https://www.douyin.com/user/MS4wLjAB123');expect(screen.queryByText('https://www.douyin.com/user/MS4wLjAB123')).toBeNull();expect(screen.queryByText('123456')).toBeNull();expect(screen.queryByText('抖音 ID')).toBeNull();expect(writes).toEqual(['/api/v1/intelligence/creators']);
 fireEvent.click(screen.getByRole('button',{name:'删除博主'}));await screen.findByText('暂未配置博主');
 expect(writes).toHaveLength(2);expect(writes.every(x=>!x.includes('refresh'))).toBe(true);
 fireEvent.click(screen.getByRole('button',{name:'关闭博主配置'}));await waitFor(()=>expect(document.activeElement).toBe(trigger));
});

it('feed and console share the same business homepage list and delete action',async()=>{
 const {ConsolePage}=await import('../src/modules/console/ConsolePage');
 let items:{id:string;url:string}[]=[];const writes:string[]=[];
 const fetcher=vi.fn(async(url:RequestInfo|URL,init?:RequestInit)=>{
  const path=String(url);
  if(path.endsWith('/session'))return reply({org_id:id,member_id:id,authz_version:'1',csrf_token:'a'.repeat(64),display_name:'南哥',actions:['source.configure'],expires_at:'2099-10-17T01:00:00Z'});
  if(path.includes('/sources?'))return reply({items:[],next_cursor:null,total:'0'});
  if(init?.method==='POST'){
   writes.push(path);items=path.endsWith('/remove')?[]:[{id,url:'https://www.douyin.com/user/MS4wLjAB123'}];
  }
  return reply({business_code:'motion_comic',items,results:[]});
 });
 const api=new ApiClient({fetcher:fetcher as typeof fetch});await api.getSession();
 const queries=new QueryClient({defaultOptions:{queries:{retry:false}}});
 const view=(consolePage:boolean)=><QueryClientProvider client={queries}><ApiProvider client={api}>{consolePage?<ConsolePage tab={0} business="AI漫剧"/>:<CreatorConfigButton business="motion_comic"/>}</ApiProvider></QueryClientProvider>;
 const mounted=render(view(false));
 fireEvent.click(screen.getByRole('button',{name:'配置博主'}));await screen.findByText('暂未配置博主');
 expect(screen.getByRole('region',{name:'批量填写博主主页'})).toBeTruthy();
 expect(screen.getByRole('region',{name:'已配置的监测博主'})).toBeTruthy();
 fireEvent.change(screen.getByLabelText('博主主页链接，每行一个'),{target:{value:'https://www.douyin.com/user/MS4wLjAB123'}});
 fireEvent.click(screen.getByRole('button',{name:'保存配置'}));await screen.findByRole('link',{name:'打开博主用户名未获取的主页'});
 fireEvent.click(screen.getByRole('button',{name:'关闭博主配置'}));mounted.rerender(view(true));
 const trigger=await screen.findByRole('button',{name:'管理监测博主'});fireEvent.click(trigger);
 await screen.findByRole('link',{name:'打开博主用户名未获取的主页'});
 expect(screen.queryByText('监测达人')).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'删除博主'}));await screen.findByText('暂未配置博主');
 expect(writes).toEqual(['/api/v1/intelligence/creators','/api/v1/intelligence/creators/remove']);
});
