import { readFileSync } from 'node:fs';
import { afterEach, expect, it, vi } from 'vitest';
import { ApiClient } from '../src/api/client';
const rid='11111111-1111-4111-8111-111111111111',wid='22222222-2222-4222-8222-222222222222',fid='33333333-3333-4333-8333-333333333333';
const session={org_id:wid,member_id:fid,display_name:'成员',actions:[],authz_version:'1',csrf_token:'a'.repeat(64),expires_at:'2030-01-01T00:00:00Z'};
const file={id:fid,byte_size:'4',original_name:'test.txt',media_type:'text/plain',sha256:'b'.repeat(64),validation_state:'accepted',created_at:'2026-10-17T00:00:00Z'};
const envelope=(data:unknown,status=200)=>new Response(JSON.stringify({request_id:rid,data}),{status,headers:{'Content-Type':'application/json'}});
afterEach(()=>vi.unstubAllEnvs());
it.each([['/','/api'],['/vkb/','/vkb/api'],['/vkb','/vkb/api'],['/apps/vkb/','/apps/vkb/api']])('BASE_URL %s统一代理会话读写及文件上传下载',async(base,prefix)=>{
 vi.stubEnv('BASE_URL',base);
 const fetcher=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
  const url=String(input);
  if(url.startsWith(prefix+'/v1/files?')&&init?.method==='POST')return envelope(file,201);
  if(url.startsWith(prefix+'/v1/files/'+fid))return new Response('data',{headers:{'Content-Type':'application/octet-stream'}});
  if(init?.method==='DELETE')return envelope({acknowledged:true});
  return envelope(session);
 });
 const client=new ApiClient({fetcher});
 await client.getSession();expect(fetcher.mock.calls[0][0]).toBe(prefix+'/v1/session');
 await client.login({org_id:wid,login_name:'test',password:'test password'});expect(fetcher.mock.calls[1][0]).toBe(prefix+'/v1/session');
 const bytes=new Blob(['data']);await client.uploadFile(bytes,{work_id:wid,expected_work_lock_version:'1',original_name:'test.txt',media_type:'text/plain'},rid);
 expect(String(fetcher.mock.calls[2][0])).toContain(prefix+'/v1/files?');expect(fetcher.mock.calls[2][1]?.body).toBe(bytes);
 expect(new Headers(fetcher.mock.calls[2][1]?.headers).get('X-CSRF-Token')).toBe(session.csrf_token);expect(new Headers(fetcher.mock.calls[2][1]?.headers).get('Idempotency-Key')).toBe(rid);
 expect(await (await client.downloadFile(fid)).text()).toBe('data');expect(new URL(String(fetcher.mock.calls[3][0]),'http://local').pathname).toBe(prefix+'/v1/files/'+fid+'/content');
 await client.logout();expect(fetcher.mock.calls[4][0]).toBe(prefix+'/v1/session');
 expect(fetcher.mock.calls.every(([,init])=>init?.credentials==='same-origin'&&init.redirect==='error')).toBe(true);
});
it.each(['','./','vkb/','https://example.com/vkb/','//example.com/vkb/','/vkb//','/vkb/../','/vkb/./','/vkb%2f/','/vkb?x/','/vkb#x/','/vkb\\x/','/vkb\n/'])('异常BASE_URL %j不创建可发送凭据的客户端',base=>{
 vi.stubEnv('BASE_URL',base);const fetcher=vi.fn();expect(()=>new ApiClient({fetcher})).toThrow();expect(fetcher).not.toHaveBeenCalled();
});
it.each(['/','/vkb/'])('BASE_URL %s身份变更隔离迟到响应，前缀不扩张API路径权限',async base=>{
 vi.stubEnv('BASE_URL',base);let resolve!:(response:Response)=>void;const delayed=new Promise<Response>(done=>{resolve=done;});
 const fetcher=vi.fn(async(input:RequestInfo|URL)=>String(input).endsWith('/private')?delayed:envelope(session));
 const client=new ApiClient({fetcher});const first=client.snapshot();
 const read=client.get('/api/v1/private',value=>value).catch(e=>e);
 await client.login({org_id:wid,login_name:'test',password:'test password'});expect(client.snapshot()).not.toBe(first);
 resolve(envelope({private:'old identity'}));expect(await read).toMatchObject({code:'REQUEST_CANCELLED'});
 const count=fetcher.mock.calls.length;
 await expect(client.get('/vkb/api/v1/session',value=>value)).rejects.toMatchObject({code:'INVALID_REQUEST'});
 await expect(client.get('//external/api/session',value=>value)).rejects.toMatchObject({code:'INVALID_REQUEST'});expect(fetcher).toHaveBeenCalledTimes(count);
});

it('创建客户端后固定部署前缀，不在现有身份会话中切换路径',async()=>{
 vi.stubEnv('BASE_URL','/vkb/');const fetcher=vi.fn(async(input:RequestInfo|URL)=>{void input;return envelope(session);});const client=new ApiClient({fetcher});
 vi.stubEnv('BASE_URL','/other/');await client.getSession();expect(fetcher.mock.calls[0][0]).toBe('/vkb/api/v1/session');
});

it('Demo公开封面保持相对资源，根路径及子路径的Hash详情路由均不越出部署目录',()=>{
 const runtime=readFileSync('src/demo/runtime.js','utf8');
 const assets=[...runtime.matchAll(/['"](assets\/[^'"]+)['"]/g)].map(match=>match[1]);expect(assets.length).toBeGreaterThan(0);
 for(const base of ['/','/vkb/'])for(const asset of assets){const url=new URL(asset,'https://example.test'+base+'#/2/0/work/demo');expect(url.origin).toBe('https://example.test');expect(url.pathname).toBe(base+asset);}
});
