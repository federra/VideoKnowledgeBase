import type {RefreshView} from '../../api/client';
import {useEffect,useRef,useState} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {feedback,useApi,useApiQuery} from '../../api/provider';

const states:Record<string,string>={queued:'等待中',running:'采集中',succeeded:'已更新',partial:'部分更新',failed:'未完成',unavailable:'不可自动采集'};
export function RefreshControl({business,allowed,onDateChange}:{business:string;allowed:boolean;onDateChange:(date:string)=>void}){
 const api=useApi(),queries=useQueryClient();
 const query=useApiQuery(['feed-refresh',business],signal=>api.intelligenceRefresh(business,signal),()=>false,{enabled:allowed});
 const cached=queries.getQueryData<RefreshView>(['api',api.snapshot(),'feed-refresh',business]);
 const data=query.data??(!api.accessBlocked?cached:undefined),active=data?.state==='queued'||data?.state==='running';
 const readError=query.error?feedback(query.error).message:'';
 const [submitting,setSubmitting]=useState(false),[error,setError]=useState(''),[dismissed,setDismissed]=useState('');
 const intent=useRef(''),busy=useRef(false),done=useRef('');
 const controller=useRef<AbortController|null>(null);
 useEffect(()=>()=>controller.current?.abort(),[]);
 useEffect(()=>{if(!active)return;const id=setInterval(()=>void query.refetch(),3000);return()=>clearInterval(id);},[active,query.refetch]);
 useEffect(()=>{if(!data?.task_id||active||data.state==='idle'||done.current===data.task_id)return;done.current=data.task_id;void queries.invalidateQueries({queryKey:['api']});},[data,active,queries]);
 async function collect(){
  if(busy.current||active||!allowed)return;
  busy.current=true;setSubmitting(true);setError('');setDismissed('');
  intent.current ||= crypto.randomUUID();controller.current=new AbortController();
  try{
   const result=await api.refreshIntelligence(business,intent.current,controller.current.signal);
   if(controller.current.signal.aborted)return;
   queries.setQueryData(['api',api.snapshot(),'feed-refresh',business],result);
   onDateChange(result.business_date);intent.current='';
  }catch(e){if(!controller.current?.signal.aborted)setError(feedback(e).message);}
  finally{busy.current=false;setSubmitting(false);}
 }
 const visible=data?.task_id&&data.task_id!==dismissed;
 return <div className="feed-refresh"><button className="btn" type="button" disabled={!allowed||api.accessBlocked||submitting||active} onClick={()=>void collect()} title="重新采集当前业务线所有现用渠道；更新北京时间当天数据，TikHub可能产生调用费用；博主监测使用免费接口及独立采集会话">{submitting||active?'采集中…':'重新采集'}</button>
 {(error||readError||visible)&&<section className="feed-refresh-status" aria-label="渠道采集状态" aria-live="polite"><div className="feed-refresh-heading"><strong>{error?'请求未完成':active?'正在重新采集':data?.state==='completed'?'采集完成':'采集结果'}</strong><button className="btn" type="button" aria-label="关闭采集结果" onClick={()=>{setError('');setDismissed(data?.task_id??'');}}>×</button></div>
 {readError&&<p role="alert">进度读取暂未完成：{readError}{active?'；将继续核验，不会重复采集':'；请刷新页面核验'}</p>}
 {error?<p role="alert">{error}；可再次点击核验同一请求。</p>:<><p className="small muted">{data?.business_date} · 新快照成功后替换展示，历史保留</p>{data?.channels.map(c=><div className="feed-refresh-channel" key={c.code}><strong>{c.name} · {states[c.state]}{c.total?` ${c.completed}/${c.total}`:''}</strong><span>{c.message}</span></div>)}</>}
 </section>}
 </div>;
}
