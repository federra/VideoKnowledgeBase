import {Link} from 'react-router-dom';
import {useApi,useApiQuery} from '../../api/provider';
export function KnowledgeSources({revision}:{revision:string}){
 const api=useApi(),query=useApiQuery(['knowledge-sources',revision],signal=>api.knowledgeSources(revision,signal),v=>v.items.length===0);
 if(query.error)return <p role="alert">来源读取失败：{query.message}<button className="btn" onClick={()=>void query.refetch()}>重试</button></p>;
 if(query.status==='loading')return <p role="status">正在读取当前版本来源…</p>;
 return <>{query.data?.items.map(e=><div className="unit-evidence-item" key={e.id}><p className="small muted">{e.origin==='manual'?'人工提供，未独立核验':'已绑定来源，未独立核验'}{e.attribution?' · '+e.attribution:''} · {e.id}{e.material_version_no?' · 材料 v'+e.material_version_no:''}</p>{e.quoted_text?<blockquote className="human-review-text">{e.quoted_text}</blockquote>:<p className="muted">该引用未保存摘录。</p>}{e.work_id&&e.target_artifact_version_id&&<Link to={'/2/0/work/'+e.work_id+'/episodes/'+(e.episode_no?'ep:'+e.episode_no:'unknown')+'/'+e.target_artifact_version_id+'?'+new URLSearchParams({...e.business_code?{source_business:e.business_code}:{},...e.paragraph_no?{paragraph:String(e.paragraph_no)}:{}}).toString()}>原文{e.paragraph_no?'段落 '+e.paragraph_no:'材料'}</Link>}{e.page_no&&<p>原文第 {e.page_no} 页</p>}{e.start_ms!==null&&<p>原文时间 {e.start_ms}—{e.end_ms} 毫秒</p>}</div>)}{!query.data?.items.length&&<p className="muted">当前版本尚未绑定原文证据。</p>}</>;
}
