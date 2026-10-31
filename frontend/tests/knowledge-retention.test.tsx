import {fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {MemoryRouter} from 'react-router-dom';
import {expect,it,vi} from 'vitest';
import {ApiClient} from '../src/api/client';
import {ApiProvider} from '../src/api/provider';
import {KnowledgePage} from '../src/modules/knowledge/KnowledgePage';
const a='11111111-1111-4111-8111-111111111111',b='22222222-2222-4222-8222-222222222222';
const session={org_id:a,member_id:a,authz_version:'1',csrf_token:'a'.repeat(64),display_name:'南哥',actions:['content.read','knowledge.edit'],expires_at:'2099-10-17T01:00:00Z'};
function row(id:string,title:string){const now=new Date().toISOString();return {id,title,created_at:now,updated_at:now,lock_version:'3',revision_id:id,publication_id:id,browse_category:'quote',business_codes:['motion_comic'],tags:[],state:'published',review_request_id:id,recycled_at:now,recycle_expires_at:new Date(Date.now()+30*86400000).toISOString(),revision:{id,knowledge_id:id,created_at:now,version_no:1,title,body_text:'隔离测试正文',knowledge_type:'method_rule',browse_category:'quote',business_codes:['motion_comic'],tags:[],evidence_ids:[],source_report_id:null,limitations:null,content_sha256:'a'.repeat(64),sealed_at:now}};}
const response=(data:unknown)=>new Response(JSON.stringify({request_id:a,data}),{headers:{'Content-Type':'application/json'}});
function mount(){
 let items=[row(a,'回收甲'),row(b,'回收乙')];
 const fetcher=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{const path=String(input);if(path==='/api/v1/session')return response(session);if(init?.method==='POST'){const body=JSON.parse(String(init.body));items=items.filter(x=>!body.items.some((v:{id:string})=>v.id===x.id));return response({ids:body.items.map((v:{id:string})=>v.id)});}return response({items,total:String(items.length),next_cursor:null});});
 render(<MemoryRouter><QueryClientProvider client={new QueryClient()}><ApiProvider client={new ApiClient({fetcher:fetcher as typeof fetch})}><KnowledgePage business="AI漫剧" tab={3}/></ApiProvider></QueryClientProvider></MemoryRouter>);return fetcher;
}
it('回收站单条叉号先确认，取消零写入，确认使用永久删除契约',async()=>{
 const fetcher=mount();await screen.findByText(/移入回收站后保留30天/);
 fireEvent.click(await screen.findByRole('button',{name:'永久删除知识：回收甲'}));
 const dialog=screen.getByRole('dialog',{name:'确认永久删除？'});expect(within(dialog).getByText(/不可恢复/)).toBeTruthy();
 fireEvent.click(within(dialog).getByRole('button',{name:'取消'}));expect(fetcher.mock.calls.filter(([,i])=>i?.method==='POST')).toHaveLength(0);
 fireEvent.click(screen.getByRole('button',{name:'永久删除知识：回收甲'}));fireEvent.click(within(screen.getByRole('dialog')).getByRole('button',{name:'永久删除'}));
 await waitFor(()=>expect(screen.queryByRole('button',{name:'永久删除知识：回收甲'})).toBeNull());
 const call=fetcher.mock.calls.find(([,i])=>i?.method==='POST')!;expect(call[0]).toBe('/api/v1/knowledge/purge');expect(JSON.parse(String(call[1]?.body))).toEqual({items:[{id:a,expected_lock_version:'3'}],confirmation:'PERMANENTLY_DELETE'});
});
it('回收站至少选择两条才出现批量叉号与恢复，批量恢复发送两条版本锁',async()=>{
 const fetcher=mount();fireEvent.click(await screen.findByRole('checkbox',{name:'选择知识：回收甲'}));expect(screen.queryByRole('button',{name:'批量永久删除'})).toBeNull();
 fireEvent.click(screen.getByRole('checkbox',{name:'选择知识：回收乙'}));expect(screen.getByRole('button',{name:'批量永久删除'})).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'批量恢复'}));fireEvent.click(within(screen.getByRole('dialog',{name:'确认恢复知识？'})).getByRole('button',{name:'确认'}));
 await screen.findByText('回收站为空');const call=fetcher.mock.calls.find(([,i])=>i?.method==='POST')!;expect(call[0]).toBe('/api/v1/knowledge/restore');expect(JSON.parse(String(call[1]?.body)).items).toHaveLength(2);
});
it('批量永久删除仍经确认，搜索清空多选避免处理隐藏知识',async()=>{
 const fetcher=mount();fireEvent.click(await screen.findByRole('checkbox',{name:'选择知识：回收甲'}));fireEvent.click(screen.getByRole('checkbox',{name:'选择知识：回收乙'}));
 fireEvent.change(screen.getByRole('textbox',{name:'搜索当前工作区'}),{target:{value:'回收'}});expect(screen.queryByRole('button',{name:'批量永久删除'})).toBeNull();
 fireEvent.click(await screen.findByRole('checkbox',{name:'选择知识：回收甲'}));fireEvent.click(screen.getByRole('checkbox',{name:'选择知识：回收乙'}));fireEvent.click(screen.getByRole('button',{name:'批量永久删除'}));
 expect(within(screen.getByRole('dialog')).getByText('已选择 2 条知识')).toBeTruthy();fireEvent.click(within(screen.getByRole('dialog')).getByRole('button',{name:'永久删除'}));
 await screen.findByText('回收站为空');const call=fetcher.mock.calls.find(([,i])=>i?.method==='POST')!;expect(JSON.parse(String(call[1]?.body)).items).toHaveLength(2);
});
