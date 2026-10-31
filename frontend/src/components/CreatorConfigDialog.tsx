import {useEffect,useRef,useState} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import type {CreatorConfig} from '../api/client';
import {feedback,useApi,useApiQuery} from '../api/provider';
import {Icon} from './Icon';
const businesses:Record<string,string>={motion_comic:'AI漫剧',story_short:'故事短片',ecommerce_video:'电商短视频'};
export function CreatorConfigDialog({business,close}:{business:string;close:()=>void}){
 const [selected,setSelected]=useState(business);
 return <CreatorConfigContent key={selected} business={selected} close={close} onBusiness={setSelected}/>;
}
function creatorName(item:CreatorConfig['items'][number]){return item.display_name?.trim()||'用户名未获取';}
function CreatorConfigContent({business,close,onBusiness}:{business:string;close:()=>void;onBusiness:(code:string)=>void}){
 const api=useApi(),queries=useQueryClient(),dialog=useRef<HTMLDialogElement>(null),busyRef=useRef(false),intent=useRef<{payload:string;key:string}|null>(null);
 const query=useApiQuery(['creator-config',business],signal=>api.creatorLinks(business,signal),()=>false);
 const [links,setLinks]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[result,setResult]=useState<CreatorConfig|null>(null);
 const request=useRef<AbortController|null>(null);
 useEffect(()=>{const element=dialog.current!,opener=document.activeElement;element.showModal();return()=>{request.current?.abort();element.close();if(opener instanceof HTMLElement&&opener.isConnected)opener.focus();};},[]);
 const data=query.data;
 async function write(remove?:string){
  if(busyRef.current||!data)return;
  busyRef.current=true;setBusy(true);setError('');
  const payload=JSON.stringify([business,remove??links]);if(intent.current?.payload!==payload)intent.current={payload,key:crypto.randomUUID()};
  request.current=new AbortController();
  try{
   const saved=remove?await api.removeCreatorLink(business,remove,intent.current.key,request.current.signal):await api.saveCreatorLinks(business,links,intent.current.key,request.current.signal);
   if(request.current.signal.aborted)return;
   setResult(saved);queries.setQueryData(['api',api.snapshot(),'creator-config',business],saved);intent.current=null;
   if(!remove&&!saved.results.some(x=>x.state==='invalid'||x.state==='limit'))setLinks('');
  }catch(e){if(!request.current.signal.aborted)setError(feedback(e).message);}
  finally{busyRef.current=false;setBusy(false);}
 }
 return <dialog ref={dialog} className="creator-config-dialog" aria-labelledby="creatorConfigTitle" onCancel={e=>{e.preventDefault();close();}}>
 <div className="dialog-head"><h2 id="creatorConfigTitle">配置博主</h2><button className="iconbtn" aria-label="关闭博主配置" onClick={close}><Icon name="close"/></button></div>
 <div className="dialog-body"><div className="field creator-config-business"><label htmlFor="creatorBiz">业务线</label><select id="creatorBiz" aria-label="配置的业务线" value={business} disabled={busy} onChange={e=>onBusiness(e.target.value)}>{Object.entries(businesses).map(([code,name])=><option key={code} value={code}>{name}</option>)}</select></div><p className="muted small">仅支持抖音完整主页链接，每行一个，每个业务线最多50位。保存不会采集；{business==='story_short'?'点击“重新采集”时读取北京时间T-7日00:00至采集时刻发布的视频，按点赞数值降序，展示赞、评、藏、转；不采评论正文。':'点击“重新采集”时完整读取短剧目录，按整剧播放量取每位TOP10、每部第1集评论最多15条。'}博主渠道使用免费接口及独立采集会话，不调用付费API。暂不启用定时采集。</p>
 {query.error?<p role="alert">{query.message}<button className="btn" onClick={()=>void query.refetch()}>重试</button></p>:!data?<p role="status">正在读取配置…</p>:<>
 <div className="creator-config-columns"><section className="creator-config-input" aria-label="批量填写博主主页"><div className="field"><label htmlFor="creatorLinks">博主主页链接，每行一个</label><textarea id="creatorLinks" rows={5} maxLength={16000} placeholder="https://www.douyin.com/user/…" value={links} onChange={e=>setLinks(e.target.value)}/></div></section>
 <section className="creator-config-monitored" aria-label="已配置的监测博主"><h3 className="small">已配置 {data.items.length} 位博主 · 手动采集</h3><div className="creator-config-list">{data.items.map(item=><article className="creator-monitor-card" key={item.id}><a className="creator-monitor-identity" href={item.url} target="_blank" rel="noopener noreferrer" aria-label={`打开博主${creatorName(item)}的主页`}><strong title={creatorName(item)}>{creatorName(item)}</strong></a><button className="btn small" disabled={busy} aria-label="删除博主" onClick={()=>void write(item.id)}>删除</button></article>)}{!data.items.length&&<p className="muted small">暂未配置博主</p>}</div></section></div>
 </>}
 {error&&<p className="form-error" role="alert">{error}；可再次提交核验同一请求。</p>}
 {result&&<div role="status" className="small creator-config-results">{result.results.length?result.results.map(x=><p key={x.line} className={x.state==='invalid'||x.state==='limit'?'form-error':'muted'}>第{x.line}行：{x.message}</p>):<p>已删除配置，后续采集不再包含该博主；历史数据保留。</p>}</div>}
 </div><div className="dialog-foot"><button className="btn" onClick={close}>关闭</button><button className="btn primary" disabled={busy||!data||!links.trim()} onClick={()=>void write()}>{busy?'正在保存…':'保存配置'}</button></div>
 </dialog>;
}
