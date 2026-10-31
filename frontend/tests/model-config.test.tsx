import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {expect,it,vi} from 'vitest';
import {ApiClient} from '../src/api/client';
import {ApiProvider} from '../src/api/provider';
import {ModelConfigPage} from '../src/modules/console/ModelConfigPage';
const id='11111111-1111-4111-8111-111111111111';
it('模型源空态与环节表来自服务端，保存配置不调用生成',async()=>{
 const writes:unknown[]=[];
 const source={id,name:'测试DeepSeek',provider:'deepseek',capability:'text',endpoint:'https://api.deepseek.com',model:'deepseek-chat',secret_ref:'DEEPSEEK_KEY',timeout:45,retries:0,max_tokens:2048,enabled:true,version:1,lock_version:'1',credential_ready:true};
 const fetcher=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
  const path=String(input);let data:unknown;
  if(path.endsWith('/session'))data={org_id:id,member_id:id,authz_version:'1',csrf_token:'a'.repeat(64),display_name:'本地检查',actions:['model.configure'],expires_at:'2099-10-17T01:00:00Z'};
  else if(init?.method==='POST'){writes.push(JSON.parse(String(init.body)));data=source;}
  else data={sources:writes.length?[source]:[],bindings:{},lock_version:'0'};
  return new Response(JSON.stringify({request_id:id,data}),{headers:{'Content-Type':'application/json','X-Request-ID':id}});
 });
 render(<QueryClientProvider client={new QueryClient()}><ApiProvider client={new ApiClient({fetcher:fetcher as typeof fetch})}><ModelConfigPage business="AI漫剧" /></ApiProvider></QueryClientProvider>);
 await screen.findByText('尚未配置单文本模型源');
 fireEvent.click(screen.getByRole('button',{name:'新增单文本模型源'}));
 expect(screen.getByRole('spinbutton',{name:'最大输出长度（Token）'})).toHaveProperty('value','');
 fireEvent.change(screen.getByLabelText('模型源名称'),{target:{value:'测试DeepSeek'}});
 fireEvent.submit(screen.getByRole('form',{name:'模型源配置'}));
 await screen.findByText('测试DeepSeek');
 expect(writes).toHaveLength(1);
 expect(writes[0]).toMatchObject({secret_ref:'DEEPSEEK_KEY',retries:0,max_tokens:null});
 expect(fetcher.mock.calls.some(([url])=>String(url).includes('/topics/generate'))).toBe(false);
 await waitFor(()=>expect(document.querySelector('dialog')).toBeNull());
});

it('真实环节分配按类型筛选并冻结业务版本，其他适配器不可执行',async()=>{
 const sources=[{id,name:'文本源',provider:'deepseek',capability:'text',endpoint:'https://api.deepseek.com',model:'deepseek-chat',secret_ref:'DEEPSEEK_KEY',timeout:45,retries:0,max_tokens:2048,enabled:true,version:1,lock_version:'1',credential_ready:true},{id:'22222222-2222-4222-8222-222222222222',name:'视觉源',provider:'other',capability:'vision',endpoint:'https://example.com/v1',model:'vision',secret_ref:'OPENAI_API_KEY',timeout:45,retries:0,max_tokens:2048,enabled:true,version:1,lock_version:'1',credential_ready:false}];
 let body:Record<string,unknown>|undefined;
 const fetcher=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
  let data:unknown={sources,bindings:body?.bindings??{},lock_version:body?'8':'7'};
  if(String(input).endsWith('/session'))data={org_id:id,member_id:id,authz_version:'1',csrf_token:'a'.repeat(64),display_name:'本地检查',actions:['model.configure'],expires_at:'2099-10-17T01:00:00Z'};
  else if(init?.method==='POST'){body=JSON.parse(String(init.body));data={sources,bindings:body!.bindings,lock_version:'8'};}
  return new Response(JSON.stringify({request_id:id,data}),{headers:{'Content-Type':'application/json','X-Request-ID':id}});
 });
 render(<QueryClientProvider client={new QueryClient()}><ApiProvider client={new ApiClient({fetcher:fetcher as typeof fetch})}><ModelConfigPage business="AI漫剧" /></ApiProvider></QueryClientProvider>);
 const topic=await screen.findByLabelText('选题生成');
 expect(topic.textContent).toContain('文本源');expect(topic.textContent).not.toContain('视觉源');
 expect(screen.getAllByRole('option',{name:/视觉源/}).every(x=>(x as HTMLOptionElement).disabled)).toBe(true);
 fireEvent.change(topic,{target:{value:id}});fireEvent.click(screen.getByRole('button',{name:'保存环节分配'}));
 await waitFor(()=>expect(body).toEqual({business_code:'motion_comic',expected_lock_version:'7',bindings:{topic:id}}));
});
import {parseSource} from '../src/modules/console/modelConfigApi';
it.each([2048,null])('真实模型源接受最大输出长度%s，保留现值并允许清空保存null',async tokens=>{let source={id,name:'配置源',provider:'deepseek',capability:'text',endpoint:'https://api.deepseek.com',model:'deepseek-chat',secret_ref:'DEEPSEEK_KEY',timeout:45,retries:0,max_tokens:tokens as number|null,enabled:true,version:1,lock_version:'1',credential_ready:true};const writes:Record<string,unknown>[]=[];const client=new ApiClient({fetcher:async(path,init)=>{let data:unknown={sources:[source],bindings:{},lock_version:'1'};if(String(path).endsWith('/session'))data={org_id:id,member_id:id,authz_version:'1',csrf_token:'a'.repeat(64),display_name:'本地检查',actions:['model.configure'],expires_at:'2099-10-17T01:00:00Z'};else if(init?.method==='POST'){const body=JSON.parse(String(init.body));writes.push(body);source={...source,max_tokens:body.max_tokens,version:source.version+1,lock_version:String(source.version+1)};data=source;}return new Response(JSON.stringify({request_id:id,data}),{headers:{'Content-Type':'application/json'}});}});render(<QueryClientProvider client={new QueryClient()}><ApiProvider client={client}><ModelConfigPage business="AI漫剧"/></ApiProvider></QueryClientProvider>);fireEvent.click(await screen.findByRole('button',{name:'编辑'}));const field=screen.getByRole('spinbutton',{name:'最大输出长度（Token）'});expect(field).toHaveProperty('value',tokens===null?'':String(tokens));expect(screen.getByText('留空：由供应商默认值／上限决定')).toBeTruthy();fireEvent.submit(screen.getByRole('form',{name:'模型源配置'}));await waitFor(()=>expect(writes).toHaveLength(1));expect(writes[0].max_tokens).toBe(tokens);await waitFor(()=>expect(document.querySelector('dialog')).toBeNull());fireEvent.click(screen.getByRole('button',{name:'编辑'}));fireEvent.change(screen.getByRole('spinbutton',{name:'最大输出长度（Token）'}),{target:{value:''}});fireEvent.submit(screen.getByRole('form',{name:'模型源配置'}));await waitFor(()=>expect(writes).toHaveLength(2));expect(writes[1].max_tokens).toBeNull();});
it('模型输出上限解析只接受null或有效正整数，不把空字符串当零',()=>{const source={id,name:'源',provider:'deepseek',capability:'text',endpoint:'https://api.deepseek.com',model:'deepseek-chat',secret_ref:'DEEPSEEK_KEY',timeout:45,retries:0,max_tokens:null,enabled:true,version:1,lock_version:'1',credential_ready:true};expect(parseSource(source).max_tokens).toBeNull();for(const value of [0,-1,1.5,'',false])expect(()=>parseSource({...source,max_tokens:value})).toThrow();});
import {App} from '../src/app/App';
it('独立Demo最大输出长度留空保存null，保留旧数值直至人工清空',async()=>{localStorage.clear();localStorage.setItem('cip-demo-v1-workspace','AI漫剧');window.location.hash='#/3/5';render(<App realTopics={false}/>);fireEvent.click(await screen.findByRole('button',{name:'新增单文本模型源'}));const input=screen.getByRole('spinbutton',{name:'最大输出长度（Token）'});expect(input).toHaveProperty('value','');expect(screen.getByText('留空：由供应商默认值／上限决定')).toBeTruthy();fireEvent.change(screen.getByLabelText('模型源名称'),{target:{value:'Demo配置'}});fireEvent.change(screen.getByLabelText('API地址'),{target:{value:'https://api.deepseek.com'}});fireEvent.change(screen.getByLabelText('模型名称'),{target:{value:'deepseek-chat'}});fireEvent.change(screen.getByLabelText('服务端密钥引用'),{target:{value:'DEEPSEEK_KEY'}});fireEvent.click(screen.getByRole('button',{name:'保存配置草稿'}));const read=()=>JSON.parse(localStorage.getItem('cip-demo-v1')!).modelConnections[0];await waitFor(()=>expect(read().maxTokens).toBeNull());fireEvent.click(screen.getByRole('button',{name:'编辑'}));fireEvent.change(screen.getByRole('spinbutton',{name:'最大输出长度（Token）'}),{target:{value:'2048'}});fireEvent.click(screen.getByRole('button',{name:'保存配置草稿'}));await waitFor(()=>expect(read().maxTokens).toBe(2048));fireEvent.click(screen.getByRole('button',{name:'编辑'}));expect(screen.getByRole('spinbutton',{name:'最大输出长度（Token）'})).toHaveProperty('value','2048');fireEvent.change(screen.getByRole('spinbutton',{name:'最大输出长度（Token）'}),{target:{value:''}});fireEvent.click(screen.getByRole('button',{name:'保存配置草稿'}));await waitFor(()=>expect(read().maxTokens).toBeNull());});
