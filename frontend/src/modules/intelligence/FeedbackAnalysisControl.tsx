import { useEffect, useRef, useState } from 'react';
import { ApiClient, ApiError, type EntryFeedback, type FeedbackAnalysisView } from '../../api/client';
import { useApi } from '../../api/provider';

// Keep an unresolved write's exact body and key across drawer reopenings, within this
// client identity only. Nothing is persisted to browser storage.
const unresolved=new WeakMap<ApiClient,Map<string,{key:string;sample:string;retry:string|null}>>();
const active=(a:FeedbackAnalysisView|null|undefined)=>!!a&&['queued','running','cancel_requested'].includes(a.state);
export function FeedbackAnalysisControl({data,refresh,onResult}:{data:EntryFeedback;refresh:()=>Promise<unknown>;onResult:(a:FeedbackAnalysisView)=>void}){
 const api=useApi(),scope=[api.snapshot(),data.entry_id,data.business_code,data.business_date,data.sample_key].join(':');
 const registry=useRef(unresolved.get(api)??new Map<string,{key:string;sample:string;retry:string|null}>()).current;
 unresolved.set(api,registry);
 const [task,setTask]=useState<FeedbackAnalysisView|null>(null),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[unknown,setUnknown]=useState(registry.has(scope)),[pollVersion,setPollVersion]=useState(0);
 const controller=useRef<AbortController|null>(null),locked=useRef(false);
 const current=task??data.analysis;
 useEffect(()=>()=>{controller.current?.abort();},[]);
 useEffect(()=>{
  if(!active(current))return;
  const abort=new AbortController();let timer:ReturnType<typeof setTimeout>|undefined;
  async function poll(){
   try{
    const a=await api.feedbackAnalysis(current!.id,abort.signal,data.entry_id);
    if(abort.signal.aborted)return;
    if(a.entry_id!==data.entry_id||a.snapshot_id!==data.snapshot_id||a.business_code!==data.business_code||a.business_date!==data.business_date||a.sample_key!==data.sample_key)throw new ApiError(502,'INVALID_RESPONSE');
    if(active(a)){timer=setTimeout(()=>void poll(),1500);return;}
    setTask(a);onResult(a);if(a.state==='succeeded')await refresh();
   }catch(e){if(!abort.signal.aborted)setMessage(e instanceof ApiError?e.message:'读取分析状态失败');}
  }
  timer=setTimeout(()=>void poll(),1000);
  return()=>{abort.abort();clearTimeout(timer);};
 },[api,current,data.entry_id,data.snapshot_id,data.business_code,data.business_date,data.sample_key,refresh,onResult,pollVersion]);
 async function start(){
  if(locked.current||active(current)||current?.state==='succeeded'||!data.analysis_model_ready||!data.comments.length||!data.sample_key)return;
  locked.current=true;setBusy(true);setMessage('');
  const pending=registry.get(scope)??{key:crypto.randomUUID(),sample:data.sample_key,retry:current&&['failed','cancelled'].includes(current.state)?current.id:null};
  registry.set(scope,pending);const abort=new AbortController();controller.current=abort;
  try{
   const a=await api.analyzeFeedback(data.entry_id,data.business_code,data.business_date,pending.sample,pending.retry,pending.key,abort.signal);
   if(abort.signal.aborted)return;
   if(a.snapshot_id!==data.snapshot_id)throw new ApiError(502,'INVALID_RESPONSE',undefined,[],true);
   registry.delete(scope);setUnknown(false);setTask(a);onResult(a);if(a.state==='succeeded')await refresh();
  }catch(e){
   const uncertain=e instanceof ApiError&&(e.status>=500||['TIMEOUT','NETWORK_ERROR','INVALID_RESPONSE','REQUEST_CANCELLED'].includes(e.code));
   if(!uncertain)registry.delete(scope);
   if(!abort.signal.aborted){setUnknown(uncertain);setMessage(e instanceof ApiError?e.message:'分析请求未完成');}
  }finally{if(!abort.signal.aborted){locked.current=false;setBusy(false);}}
 }
 const failed=current&&['failed','cancelled'].includes(current.state);
 return <div className="feedback-analysis"><button className="btn primary" disabled={busy||active(current)||current?.state==='succeeded'||!data.analysis_model_ready||!data.sample_key||!data.comments.length} onClick={()=>void start()}>评论分析</button>
 {!data.analysis_model_ready&&data.comments.length>0&&<a href="#/3/5">请到控制台配置用户评论分析</a>}
 <span className="small muted" role="status">{unknown?'提交结果待核验；点击评论分析核验原请求。':''}{message||(failed?'分析未完成，保留原评论与已有报告；点击评论分析可显式重试':current?.state==='succeeded'?'评论分析已完成':active(current)||busy?'正在分析当前日期的评论样本':'')}</span>
 {message&&active(current)&&<button className="btn" onClick={()=>{setMessage('');setPollVersion(v=>v+1);}}>重新读取状态</button>}
 </div>;
}
