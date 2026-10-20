import {useCallback,useState} from 'react';
import {useApi,useApiQuery} from '../../api/provider';
import type {KnowledgeItem} from '../../api/client';
import {KnowledgeDetail,stateLabels} from './KnowledgeDetail';
import {KnowledgeForm} from './KnowledgeForm';
export function ReportKnowledge({reportId,business}:{reportId:string;business:string}){
 const api=useApi(),[selected,setSelected]=useState<KnowledgeItem>(),[editing,setEditing]=useState<KnowledgeItem>();
 const query=useApiQuery(['report-knowledge',reportId,business],async signal=>{const [formal,candidates]=await Promise.all([api.knowledgeItems(business,false,signal,reportId),api.knowledgeItems(business,true,signal,reportId)]);return [...formal.items,...candidates.items];},x=>x.length===0);
 const refresh=useCallback(()=>void query.refetch(),[query.refetch]);
 return <details className="report-appendix"><summary>作品级知识提炼与审核记录</summary>{query.error?<p role="alert">{query.message}<button className="btn" onClick={()=>void query.refetch()}>重试</button></p>:query.status==='loading'?<p role="status">正在读取候选知识…</p>:query.data?.length?query.data.map(x=><div className="knowledge-preview" key={x.revision_id}><h3>{x.title}</h3><span className="tag">{stateLabels[x.state]}</span><p>{x.revision.body_text}</p><button className="btn" onClick={()=>setSelected(x)}>查看审核记录</button></div>):<p className="muted">尚无作品级候选知识。分析完成也不会自动入库。</p>}{selected&&<KnowledgeDetail refreshed={refresh} item={selected} close={()=>setSelected(undefined)} edit={()=>{setEditing(selected);setSelected(undefined);}} saved={()=>void query.refetch()}/>} {editing&&<KnowledgeForm business="AI漫剧" category={editing.browse_category} item={editing} close={()=>setEditing(undefined)} saved={()=>void query.refetch()}/>}</details>;
}
