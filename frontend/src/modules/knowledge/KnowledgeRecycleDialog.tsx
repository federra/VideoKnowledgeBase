import {useEffect,useRef,useState} from 'react';
import type {KnowledgeItem} from '../../api/client';
import {feedback,useApi} from '../../api/provider';
export function KnowledgeRecycleDialog({items,restore=false,purge=false,close,saved}:{items:KnowledgeItem[];restore?:boolean;purge?:boolean;close:()=>void;saved:()=>void}){
 const api=useApi(),dialog=useRef<HTMLDialogElement>(null),key=useRef(crypto.randomUUID()),inflight=useRef(false),request=useRef<AbortController|null>(null);
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 const title=purge?'确认永久删除？':restore?'确认恢复知识？':'确认移入回收站？';
 useEffect(()=>{const d=dialog.current!,opener=document.activeElement;d.showModal();return()=>{request.current?.abort();d.close();if(opener instanceof HTMLElement&&opener.isConnected)opener.focus();};},[]);
 async function confirm(){
  if(inflight.current)return;
  inflight.current=true;setBusy(true);setError('');request.current=new AbortController();
  try{const targets=items.map(item=>({id:item.id,expected_lock_version:item.lock_version}));if(purge)await api.purgeKnowledge(targets,key.current,request.current.signal);else await api.recycleKnowledge(targets,key.current,restore,request.current.signal);if(!request.current.signal.aborted)saved();}
  catch(e){if(!request.current.signal.aborted)setError(feedback(e).message+'；请核对后重试，或取消并刷新列表。');}
  finally{inflight.current=false;setBusy(false);}
 }
 return <dialog ref={dialog} className="knowledge-recycle-dialog" aria-labelledby="knowledgeRecycleTitle" onCancel={e=>{e.preventDefault();if(!busy)close();}}><div className="dialog-head"><h2 id="knowledgeRecycleTitle">{title}</h2></div><div className="dialog-body"><p>{items.length===1?items[0].title:`已选择 ${items.length} 条知识`}</p><p className="small muted">{purge?'永久删除后不可恢复，知识内容及检索索引将清除；历史报告和独立来源资料保留。':restore?'恢复原正式版本及适用业务。':'移入后保留30天，可在回收站恢复；到期自动清理，共享知识将从所有适用业务中隐藏。'}</p>{error&&<p className="form-error" role="alert">{error}</p>}</div><div className="dialog-foot"><button className="btn" autoFocus disabled={busy} onClick={close}>取消</button><button className={`btn ${purge?'danger':'primary'}`} disabled={busy} onClick={()=>void confirm()}>{busy?'正在提交…':purge?'永久删除':'确认'}</button></div></dialog>;
}
