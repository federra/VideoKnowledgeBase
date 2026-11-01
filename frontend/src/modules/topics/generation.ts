import {useEffect,useRef,useState} from 'react';
import {feedback,useApi} from '../../api/provider';
import {registerTopicCleanup} from './scope';
import {ApiError} from '../../api/client';
import {parseGeneration} from './contracts';
import type {Business,Generation} from './contracts';
export const terminal=(g:Generation)=>['succeeded','failed','cancelled'].includes(g.state);
type Request={business_code:Business;mode:'batch'|'brainstorm';spark_ids:string[];instructions:string};
type Operation={signature:string;key:string;body:Request};
const pending=new Map<string,Operation>();
const known=new Map<string,Generation>();
const pendingSlot=(slot:string)=>slot.replace('cip-topic-task:','cip-topic-pending:');
const uuid=(v:unknown):v is string=>typeof v==='string'&&/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(v);
function readPending(slot:string,business:Business,mode:Request['mode']):{operation?:Operation;error?:string}{
 const cached=pending.get(slot);if(cached)return {operation:cached};
 try{const raw=sessionStorage.getItem(pendingSlot(slot));if(!raw)return {};const v=JSON.parse(raw);const body=v?.body;
  if(v?.v!==1||!uuid(v.key)||!body||body.business_code!==business||body.mode!==mode||!Array.isArray(body.spark_ids)||body.spark_ids.length>12||!body.spark_ids.every(uuid)||new Set(body.spark_ids).size!==body.spark_ids.length||(mode==='batch'?body.spark_ids.length!==0:body.spark_ids.length===0)||typeof body.instructions!=='string'||body.instructions.length>4000||v.signature!==JSON.stringify(body))throw Error('shape');
  const operation={key:v.key,signature:v.signature,body} as Operation;pending.set(slot,operation);return {operation};
 }catch{return {error:'本地待核验提交记录不可读取，请先核验原任务；不会另建付费请求。'};}
}
function forgetPending(slot:string){pending.delete(slot);try{sessionStorage.removeItem(pendingSlot(slot));}catch{/* retained disk key is safer than a new paid request */}}

registerTopicCleanup(scope=>{if(scope===null){pending.clear();known.clear();return;}for(const key of pending.keys())if(key.startsWith('cip-topic-task:'+scope+':'))pending.delete(key);for(const key of known.keys())if(key.startsWith('cip-topic-task:'+scope+':'))known.delete(key);});
/** Pending requests persist before POST under the same private scope as drafts; recovery never automatically posts. */
export function useGeneration(scope:string,business:Business,mode:Request['mode'],onSuccess:()=>void){
 const api=useApi();const slot=`cip-topic-task:${scope}:${business}:${mode}`;const persisted=readPending(slot,business,mode);
 const [restored,setRestored]=useState(false);const [generation,setGeneration]=useState<Generation|undefined>(()=>known.get(slot));const [error,setError]=useState(persisted.error??(persisted.operation?'存在生成提交结果待核验，请恢复原提交；不会自动调用模型。':''));const [submitting,setSubmitting]=useState(false);const [readAttempt,setReadAttempt]=useState(0);
 const epoch=useRef(0);const [restoring,setRestoring]=useState(()=>{try{return !!sessionStorage.getItem(slot);}catch{return false;}});const gate=useRef(false),alive=useRef(true),success=useRef(onSuccess);
 useEffect(()=>{success.current=onSuccess;},[onSuccess]);useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
 function accept(g:Generation){if(g.business_code!==business||g.mode!==mode)throw Error('生成任务业务不匹配');known.set(slot,g);let persisted=true;try{sessionStorage.setItem(slot,g.id);}catch{persisted=false;}if(alive.current){setGeneration(g);setError(persisted?'':'任务已接收，浏览器未能保存任务编号；请保留原提交并恢复核验。');if(g.state==='succeeded')success.current();}return persisted;}
 useEffect(()=>{let active=true;const revision=epoch.current;const c=new AbortController();let task:string|null=null;try{task=sessionStorage.getItem(slot);}catch{/* optional storage */}if(task){setRestoring(true);void api.get('/api/v1/topics/generations/'+task,parseGeneration,c.signal).then(g=>{if(active&&revision===epoch.current){accept(g);setRestored(true);setRestoring(false);}}).catch(e=>{if(!active||revision!==epoch.current)return;if(e instanceof ApiError&&[400,404,410,422].includes(e.status)){known.delete(slot);forgetPending(slot);setGeneration(undefined);setRestored(false);setRestoring(false);try{sessionStorage.removeItem(slot);}catch{/* optional storage */}setError('原生成任务已不可读取，已清除本地引用；请重新连接工作区后再提交。');}else setError(feedback(e).message);});}else setRestoring(false);return()=>{active=false;c.abort();};},[api,slot,readAttempt]);
 useEffect(()=>{if(!generation||terminal(generation))return;let active=true;const c=new AbortController();const timer=setTimeout(()=>{api.get('/api/v1/topics/generations/'+generation.id,parseGeneration,c.signal).then(g=>{if(active)accept(g);}).catch(e=>{if(active)setError(feedback(e).message);});},1200);return()=>{active=false;clearTimeout(timer);c.abort();};},[api,generation,readAttempt]);
 async function submit(operation:Operation){if(gate.current||restoring||generation&&!terminal(generation))return;try{sessionStorage.setItem(pendingSlot(slot),JSON.stringify({v:1,...operation}));}catch{setError('浏览器无法保存提交标识，请恢复浏览器存储后再生成。');return;}epoch.current+=1;pending.set(slot,operation);known.delete(slot);try{sessionStorage.removeItem(slot);}catch{/* optional storage */}gate.current=true;setGeneration(undefined);setRestored(false);setSubmitting(true);setError('');try{const g=await api.json('/api/v1/topics/generate','POST',operation.body,operation.key,parseGeneration);if(accept(g))forgetPending(slot);}catch(e){if(e instanceof ApiError&&e.status>=400&&e.status<500&&e.code!=='EXTERNAL_RESULT_UNKNOWN')forgetPending(slot);if(alive.current)setError(feedback(e).message);}finally{gate.current=false;if(alive.current)setSubmitting(false);}}
 async function generate(spark_ids:string[],instructions:string){const body:Request={business_code:business,mode,spark_ids:[...new Set(spark_ids)],instructions};const signature=JSON.stringify(body);const restoredPending=readPending(slot,business,mode);if(restoredPending.error){setError(restoredPending.error);return;}const operation=restoredPending.operation;if(operation&&operation.signature!==signature){setError('上次提交结果待核验，请先恢复原提交；不会另建付费任务。');return;}await submit(operation??{signature,key:crypto.randomUUID(),body});}
 return {generation,error,submitting,restored,busy:restoring||submitting||!!generation&&!terminal(generation),generate,recover:()=>{const restoredPending=readPending(slot,business,mode);if(restoredPending.error)setError(restoredPending.error);else if(restoredPending.operation)void submit(restoredPending.operation);},hasPending:!!persisted.operation,check:()=>setReadAttempt(n=>n+1),clear:()=>{setGeneration(undefined);known.delete(slot);try{sessionStorage.removeItem(slot);}catch{/* optional storage */}}};
}
