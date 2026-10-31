import type {ApiClient} from '../../api/client';
export type ModelSource={id:string;name:string;provider:'deepseek'|'openai'|'other';capability:'text'|'vision';endpoint:string;model:string;secret_ref:'DEEPSEEK_KEY'|'OPENAI_API_KEY';timeout:number;retries:0;max_tokens:number|null;enabled:boolean;version:number;lock_version:string;credential_ready:boolean};
export type ModelConfig={sources:ModelSource[];bindings:Record<string,string>;lock_version:string};
export type SourceWrite=Omit<ModelSource,'id'|'version'|'lock_version'|'credential_ready'> & {id?:string;expected_lock_version?:string};
function record(v:unknown):v is Record<string,unknown>{return typeof v==='object'&&v!==null&&!Array.isArray(v);}
export function parseSource(v:unknown):ModelSource{
 if(!record(v)||!['id','name','endpoint','model','secret_ref','lock_version'].every(k=>typeof v[k]==='string')||!['text','vision'].includes(String(v.capability))||!['deepseek','openai','other'].includes(String(v.provider))||!['timeout','retries','version'].every(k=>typeof v[k]==='number'&&Number.isSafeInteger(v[k]))||!(v.max_tokens===null||typeof v.max_tokens==='number'&&Number.isSafeInteger(v.max_tokens)&&v.max_tokens>=1&&v.max_tokens<=131072)||typeof v.enabled!=='boolean'||typeof v.credential_ready!=='boolean')throw new Error('shape');
 return v as ModelSource;
}
export function parseConfig(v:unknown):ModelConfig{
 if(!record(v)||!Array.isArray(v.sources)||!record(v.bindings)||typeof v.lock_version!=='string'||!Object.values(v.bindings).every(x=>typeof x==='string'))throw new Error('shape');
 return {sources:v.sources.map(parseSource),bindings:v.bindings as Record<string,string>,lock_version:v.lock_version};
}
export const loadConfig=(api:ApiClient,business:string,signal?:AbortSignal)=>api.get('/api/v1/model-config?business_code='+encodeURIComponent(business),parseConfig,signal);
export const saveSource=(api:ApiClient,body:SourceWrite,key:string)=>api.json('/api/v1/model-config/sources','POST',body,key,parseSource);
export const saveBindings=(api:ApiClient,business:string,bindings:Record<string,string>,version:string,key:string)=>api.json('/api/v1/model-config/bindings','POST',{business_code:business,bindings,expected_lock_version:version},key,parseConfig);
