import { useEffect, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ApiError } from '../../api/client';
import type { ConsoleCreate, ConsolePageData, ConsoleSource, ConsoleTask, Session } from '../../api/client';
import { feedback, useApi, useApiQuery } from '../../api/provider';
import { Icon } from '../../components/Icon';

const codes: Record<string, ConsoleCreate['business_code']> = { AI漫剧:'motion_comic', 故事短片:'story_short', 电商短视频:'ecommerce_video' };
const frequencies = {daily_0900:'每日 09:00',every_2h:'每 2 小时',every_4h:'每 4 小时'};
const states = {queued:'排队中',running:'处理中',succeeded:'成功',failed:'失败',cancel_requested:'取消待确认',cancelled:'已取消'};
const errorText:Record<string,string>={SOURCE_UNAVAILABLE:'来源或密钥未就绪',INVALID_RESPONSE:'来源响应不完整',EXTERNAL_RESULT_UNKNOWN:'外部请求已发生，结果待核实，请勿重复采集',INSUFFICIENT_MATERIAL:'资料不足，尚不能提炼知识',ACCESS_DENIED:'当前权限已失效',VALIDATION_FAILED:'输入或配置需要检查',RATE_LIMITED:'请求限流，请稍后检查',SERVICE_NOT_READY:'处理器或服务暂未就绪',DATE_WINDOW_MISMATCH:'响应跨日，未发布为当日数据'};
const date=(value:string|null)=>value?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'short',timeStyle:'medium'}).format(new Date(value)):'未记录';
function message(error:unknown){return error instanceof ApiError?(errorText[error.code]??error.message):'操作未完成，请重试';}
function Table({headers,children}:{headers:string[];children:ReactNode}){return <div className="table-wrap"><table><thead><tr>{headers.map(h=><th key={h} scope="col">{h}</th>)}</tr></thead><tbody>{children}</tbody></table></div>;}
function Notice({children}:{children:ReactNode}){return <div className="notice"><Icon name="info" /><p>{children}</p></div>;}
function Modal({title,close,drawer=false,children,foot}:{title:string;close:()=>void;drawer?:boolean;children:ReactNode;foot?:ReactNode}){
 const ref=useRef<HTMLDialogElement>(null);
 useEffect(()=>{const dialog=ref.current!,opener=document.activeElement;dialog.showModal();return()=>{dialog.close();if(opener instanceof HTMLElement&&opener.isConnected)opener.focus();};},[]);
 return <dialog ref={ref} className={drawer?'drawer':''} aria-labelledby="consoleDialogTitle" onCancel={e=>{e.preventDefault();close();}}>
  <div className="dialog-head"><h2 id="consoleDialogTitle">{title}</h2><button className="iconbtn" aria-label="关闭" onClick={close}><Icon name="close" /></button></div>
  <div className="dialog-body">{children}</div>{foot&&<div className="dialog-foot">{foot}</div>}
 </dialog>;
}
export function ConsolePage({tab,business,onSession}:{tab:number;business:string;onSession?:(s:Session|undefined)=>void}){
 const api=useApi();const [session,setSession]=useState<Session>();const [error,setError]=useState<unknown>();const [attempt,setAttempt]=useState(0);
 useEffect(()=>{const controller=new AbortController();let active=true;
  api.getSession(controller.signal).then(s=>{if(active){setSession(s);setError(undefined);onSession?.(s);}}).catch(e=>{if(active){setError(e);setSession(undefined);onSession?.(undefined);}});
  return()=>{active=false;controller.abort();};
 },[api,attempt,onSession]);
 useEffect(()=>api.onBoundary(()=>{setSession(undefined);setError(api.accessError);onSession?.(undefined);}),[api,onSession]);
 const title=tab===0?'采集配置':'运行状态';
 return <><h1 className="sr-only">{title}</h1>{session?<ConsoleBody key={`${business}:${tab}`} tab={tab} business={business} />:
  <>{tab===0&&<div className="page-heading page-actions"><button className="btn" disabled><Icon name="plus" /> 新增来源</button></div>}
  <div className="empty" role={error?'alert':'status'}><Icon name="info" /><h2>{error?feedback(error).message:'正在连接本地工作区…'}</h2>{Boolean(error)&&<><p>本地服务尚未就绪，请检查后端运行状态。</p><button className="btn" onClick={()=>setAttempt(n=>n+1)}>重试</button></>}</div></>}
 </>;
}
function ConsoleBody({tab,business}:{tab:number;business:string}){
 const api=useApi(),queries=useQueryClient();
 const code=codes[business];
 const [modal,setModal]=useState<'source'|'boards'|'creators'|'task'|null>(null);
 const [task,setTask]=useState<ConsoleTask>();const [error,setError]=useState('');const [busy,setBusy]=useState(false);
 const operation=useRef<{intent:string;key:string} | undefined>(undefined);
 const query=useApiQuery<ConsolePageData<ConsoleSource | ConsoleTask>>(['console',tab,code],signal=>tab===0?api.listAllSources(code,signal):api.listAllTasks(code,signal),data=>data.items.length===0);
 useEffect(()=>{const timer=setInterval(()=>{void query.refetch();},10000);return()=>clearInterval(timer);},[query.refetch]);
 const refresh=()=>{void queries.invalidateQueries({queryKey:['api']});};
 const close=()=>{if(!busy){setModal(null);setError('');operation.current=undefined;}};
 const key=(intent:string)=>{if(operation.current?.intent!==intent)operation.current={intent,key:crypto.randomUUID()};return operation.current.key;};
 async function write(intent:string,perform:(key:string)=>Promise<unknown>,keepOpen=false){if(busy)return;setBusy(true);setError('');try{await perform(key(intent));operation.current=undefined;if(!keepOpen)setModal(null);refresh();}catch(e){setError(message(e));}finally{setBusy(false);}}
 function saveSource(e:FormEvent<HTMLFormElement>){e.preventDefault();e.stopPropagation();const data=new FormData(e.currentTarget);
  const body:ConsoleCreate={name:String(data.get('title')).trim(),address:String(data.get('value')).trim(),business_code:codes[String(data.get('biz'))],frequency:String(data.get('freq')) as ConsoleCreate['frequency']};
  void write(JSON.stringify(body),k=>api.createSource(body,k));
 }
 async function showTask(id:string){setError('');try{const result=await api.getTask(id);setTask(result);setModal('task');}catch(e){setError(message(e));}}
 const sources=tab===0?(query.data?.items??[]) as ConsoleSource[]:[];
 const tasks=tab===4?(query.data?.items??[]) as ConsoleTask[]:[];
 const listedTask=task&&tasks.find(item=>item.id===task.id);
 const visibleTask=task&&listedTask&&!query.error?(BigInt(task.lock_version)>BigInt(listedTask.lock_version)?task:listedTask):undefined;
 return <>
 {tab===0&&<><div className="page-heading page-actions"><button className="btn" onClick={()=>setModal('source')}><Icon name="plus" /> 新增来源</button></div>
 <Notice>来源由服务端保存；启用后按计划调用红狐（可能计费），每次最多1个请求、1条记录。新来源默认暂停。</Notice>
 <div className="console-config-grid"><section className="console-config-card"><div><h2>榜单类型</h2><p>按业务线维护情报流的榜单筛选项</p></div><button className="btn" onClick={()=>setModal('boards')}>管理榜单类型</button></section><section className="console-config-card"><div><h2>监测达人</h2><p>按业务线维护达人更新的监测名单</p></div><button className="btn" onClick={()=>setModal('creators')}>管理监测达人</button></section></div></>}
 {error&&modal===null&&<p className="form-error" role="alert">{error}</p>}
 {['error','unauthenticated','forbidden','not-found','cancelled'].includes(query.status)?<div className="empty" role="alert"><h2>{query.message}</h2><button className="btn" onClick={()=>void query.refetch()}>重试</button></div>:
 query.status==='loading'?<div className="card state-panel" role="status"><p>正在获取内容…</p><div className="skeleton" /></div>:
 tab===0?<Table headers={['监测来源','采集计划','用途','状态','操作']}>
 {sources.map(source=><tr key={source.id}><td><strong>{source.name}</strong><p>{source.target.kind==='account'?'达人作品':source.target.kind==='board'?'平台榜单':source.target.kind==='content'?'作品评论':'关键词来源'} · {source.last_state?states[source.last_state]:'未运行'}{source.last_at?' · '+date(source.last_at):''}</p></td><td>{source.plan?frequencies[source.plan.frequency]:'未配置计划'}</td><td>{source.plan?.purpose==='both'?'情报与知识':source.plan?.purpose==='knowledge'?'知识':'情报'}</td><td><span className="tag">{source.enabled&&source.plan?.enabled?'启用':'暂停'}</span></td><td><button className="btn" disabled={busy||!source.plan} onClick={()=>void write(`toggle:${source.id}:${source.lock_version}`,k=>api.updateSource(source.id,{expected_lock_version:source.lock_version,enabled:!source.enabled},k))}>{source.enabled?'暂停':'启用'}</button></td></tr>)}
 {!sources.length&&<tr><td colSpan={5}><div className="empty">暂无监测来源</div></td></tr>}
 </Table>:<Table headers={['任务','输入与版本','运行状态','操作']}>
 {tasks.map(item=><tr key={item.id}><td><strong>{item.kind==='collect.redfox'?'来源采集':item.kind==='collection.knowledge-intake'?'知识资料交接':item.kind==='file.verify'?'文件校验':item.kind}</strong><p>{item.id}</p></td><td>输入已封存 · 状态 v{item.lock_version}<p>{date(item.created_at)}</p></td><td><span className="tag">{states[item.state]}</span>{item.safe_error_code&&<p>{errorText[item.safe_error_code]??'处理未完成，请查看记录'}</p>}</td><td><button className="btn" onClick={()=>void showTask(item.id)}>查看记录</button>{item.state==='failed'&&<button className="btn" disabled={busy} onClick={()=>void write(`retry:${item.id}:${item.lock_version}`,k=>api.controlTask(item.id,'retry',{expected_lock_version:item.lock_version,reason:'控制台人工重试'},k))}>重试</button>}</td></tr>)}
 {!tasks.length&&<tr><td colSpan={4}><div className="empty">暂无运行任务</div></td></tr>}
 </Table>}
 {query.data?.next_cursor&&<p className="small muted">当前显示最近100条，后续记录可通过接口分页检查。</p>}
 {modal==='source'&&<Modal title="新增采集来源" close={close} foot={<><button className="btn" disabled={busy} onClick={close}>取消</button><button className="btn primary" type="submit" form="consoleSourceForm" disabled={busy}>{busy?'正在保存…':'保存来源'}</button></>}>
 <form id="consoleSourceForm" onSubmit={saveSource}><div className="field"><label htmlFor="st">来源名称</label><input id="st" name="title" required maxLength={90} /></div><div className="field"><label htmlFor="sv">来源地址</label><textarea id="sv" name="value" required maxLength={256} /></div><div className="field"><label htmlFor="sb">业务线</label><select id="sb" name="biz" defaultValue={business}>{Object.keys(codes).map(b=><option key={b}>{b}</option>)}</select></div><div className="field"><label htmlFor="sf">采集频率</label><select id="sf" name="freq" defaultValue="daily_0900">{Object.entries(frequencies).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></div><Notice>当前支持AI漫剧／抖音。来源地址填写关键词（如“漫剧”）或 uid:账号UID；暂不解析任意链接。保存不会采集，启用后按计划执行。</Notice>{error&&<p className="form-error" role="alert">{error}</p>}</form>
 </Modal>}
 {modal==='boards'&&<BoardManager business={business} close={close} />}
 {modal==='creators'&&<CreatorManager business={business} close={close} write={write} error={error} busy={busy} />}

 {modal==='task'&&visibleTask&&<Modal title="任务运行记录" drawer close={close} foot={<button className="btn" onClick={close}>关闭</button>}><h3>{visibleTask.id}</h3><div className="timeline"><div>{date(visibleTask.created_at)} · 已排队<p>输入版本已保存</p></div>{visibleTask.started_at&&<div>{date(visibleTask.started_at)} · 处理中<p>实际处理器：{visibleTask.kind}</p></div>}<div>{date(visibleTask.finished_at??visibleTask.started_at??visibleTask.created_at)} · {states[visibleTask.state]}<p>{visibleTask.safe_error_code?errorText[visibleTask.safe_error_code]??'任务尚未完成':visibleTask.state==='succeeded'?'结果已保存，仍受当前权限约束':'尚无正式结果'}</p></div></div>{visibleTask.outputs.map(o=><p key={o.id} className="small">结果引用：{o.kind} · {o.id}</p>)}</Modal>}
 </>;
}

function CreatorManager({business,close,write,error,busy}:{business:string;close:()=>void;write:(intent:string,perform:(key:string)=>Promise<unknown>,keepOpen?:boolean)=>Promise<void>;error:string;busy:boolean}) {
 const api=useApi();const [selected,setSelected]=useState(business);const code=codes[selected];
 const query=useApiQuery(['console-creators',code],signal=>api.listAllSources(code,signal),data=>data.items.length===0);
 const sources=(query.data?.items??[]).filter(s=>s.target.kind==='account');
 return <Modal title="管理监测达人" close={close} foot={<button className="btn primary" type="submit" form="consoleCreatorForm" disabled={busy||query.status==='loading'}>添加达人</button>}>
 <p className="muted small">按业务线维护监测名单。新增达人默认暂停；移除监测不删除历史作品与研判资料。</p>
 <div className="field" style={{marginTop:18}}><label htmlFor="creatorBiz">业务线</label><select id="creatorBiz" aria-label="配置的业务线" value={selected} onChange={e=>setSelected(e.target.value)} disabled={busy}>{Object.keys(codes).map(b=><option key={b}>{b}</option>)}</select></div>
 <div className="board-config-list">{query.status==='loading'?<p role="status">正在获取监测名单…</p>:query.error?<p role="alert">{query.message}</p>:sources.map(s=><div className="board-config-item" key={s.id}><span>{s.name}</span><button className="btn small" disabled={busy} aria-label={`移除${s.name}`} onClick={()=>void write(`archive:${s.id}:${s.lock_version}`,k=>api.updateSource(s.id,{expected_lock_version:s.lock_version,archived:true},k),true)}>移除</button></div>)}{!query.error&&query.status!=='loading'&&!sources.length&&<p className="muted small">此业务线尚未配置达人。</p>}</div>
 <form id="consoleCreatorForm" onSubmit={e=>{e.preventDefault();e.stopPropagation();const data=new FormData(e.currentTarget);const value=String(data.get('name')).trim();void write(`creator:${code}:${value}`,k=>api.createSource({name:value,address:`uid:${value}`,business_code:code,frequency:'daily_0900'},k),true);}}><div className="field"><label htmlFor="creatorName">新增监测达人</label><input id="creatorName" name="name" maxLength={40} required placeholder="填写稳定账号UID" disabled={busy} /></div><p className="small muted">当前仅按抖音账号UID配置，昵称与分享链接尚未支持。</p>{error&&<p className="form-error" role="alert">{error}</p>}</form></Modal>;
}

function BoardManager({business,close}:{business:string;close:()=>void}) {
 const [selected,setSelected]=useState(business);
 return <Modal title="管理榜单类型" close={close} foot={<button className="btn primary" disabled>添加榜单</button>}>
 <p className="muted small">按业务线维护筛选项。新增榜单暂无采集数据；删除类型不删除历史情报。</p>
 <div className="field" style={{marginTop:18}}><label htmlFor="rankBoardBiz">业务线</label><select id="rankBoardBiz" aria-label="配置的业务线" value={selected} onChange={e=>setSelected(e.target.value)}>{Object.keys(codes).map(b=><option key={b}>{b}</option>)}</select></div>
 <div className="board-config-list"><p className="muted small">此业务线尚未配置榜单类型。</p></div><form><div className="field"><label htmlFor="rankBoardName">新增榜单类型</label><input id="rankBoardName" maxLength={40} disabled /></div><p className="form-error" role="status">红狐“小剧场”每日热门榜已支持固定采样；本页暂未开放新增榜单或自动采集计划。</p></form>
 </Modal>;
}
