import {useEffect,useRef,useState} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {feedback,useApi,useApiQuery} from '../../api/provider';
import {Icon} from '../../components/Icon';
import {parseSpark,parseSparks,sparkColors,topicTime} from './contracts';
import type {Spark,SparkColor} from './contracts';
import {TopicDialog,useTopicSession} from './shared';
export function SparkEntry(){const {session,error,retry}=useTopicSession();const [open,setOpen]=useState(false);return session?<PersonalSparks key={session.org_id+session.member_id+session.authz_version} open={open} setOpen={setOpen}/>:<><button id="sparkFloat" className="spark-float" aria-label="打开闪念胶囊" onClick={()=>setOpen(true)}><Icon name="spark"/><span>闪念胶囊</span><span className="spark-count">0</span></button>{open&&<TopicDialog title="闪念胶囊" close={()=>setOpen(false)}><p role="alert">{error||'正在连接本地工作区…'}</p><button className="btn" onClick={retry}>重试</button></TopicDialog>}</>;}
function PersonalSparks({open,setOpen}:{open:boolean;setOpen:(v:boolean)=>void}){const api=useApi();const notes=useApiQuery(['sparks'],s=>api.get('/api/v1/sparks',parseSparks,s),v=>!v.items.length);return <><button id="sparkFloat" className="spark-float" aria-label="打开闪念胶囊" onClick={()=>setOpen(true)}><Icon name="spark"/><span>闪念胶囊</span><span className="spark-count">{notes.data?.items.length??0}</span></button>{open&&<SparkEditor notes={notes.data?.items??[]} loadError={notes.error?notes.message:''} close={()=>setOpen(false)}/>}</>;}
function SparkEditor({notes,loadError,close}:{notes:Spark[];loadError:string;close:()=>void}){const api=useApi(),queries=useQueryClient();const [selected,setSelected]=useState<Spark>();const [text,setText]=useState('');const [error,setError]=useState('');const [busy,setBusy]=useState(false);const [saved,setSaved]=useState(false);
 const [color,setColor]=useState<SparkColor>('violet');
 const [removing,setRemoving]=useState<Spark>();
 const [removeError,setRemoveError]=useState('');
 const removeKey=useRef('');
 const [removedIds,setRemovedIds]=useState<string[]>([]);
 const visibleNotes=notes.filter(note=>!removedIds.includes(note.id));const current=useRef({selected:undefined as Spark|undefined,text:'',color});current.current={selected,text,color};const gate=useRef(false);const operations=useRef(new Map<string,string>());const pending=useRef<{body:{text:string;color?:SparkColor;id?:string;expected_version?:number};key:string}|undefined>(undefined);const alive=useRef(true);useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
 async function flush(){if(gate.current)return false;const draft=current.current;if(!pending.current&&draft.selected&&!draft.text.trim()){setError('闪念内容不能为空，请补充内容后保存。');return false;}if(!pending.current&&(!draft.text.trim()||(draft.text.trim()===(draft.selected?.text??'')&&draft.color===(draft.selected?.color??'violet'))))return true;gate.current=true;setBusy(true);setError('');const body=pending.current?.body??{text:draft.text.trim(),...(draft.color!==(draft.selected?.color??'violet')?{color:draft.color}:{}),...(draft.selected?{id:draft.selected.id,expected_version:draft.selected.version}:{})};const sig=JSON.stringify(body);let key=pending.current?.key??operations.current.get(sig);if(!key){key=crypto.randomUUID();operations.current.set(sig,key);}pending.current={body,key};try{const note=await api.json('/api/v1/sparks','POST',body,key,parseSpark);operations.current.delete(sig);pending.current=undefined;if(alive.current){setSelected(note);current.current.selected=note;setSaved(current.current.text===draft.text);if(current.current.text===draft.text&&draft.text.trim()===note.text){setText(note.text);current.current.text=note.text;}void queries.invalidateQueries({queryKey:['api']});}return true;}catch(e){if(alive.current)setError(feedback(e).message);return false;}finally{gate.current=false;if(alive.current)setBusy(false);}}
 // Commit on an editor pause or exit, serially. Inputs arriving during a write stay dirty.
 useEffect(()=>{if(busy||!text.trim()||(text.trim()===(selected?.text??'')&&color===(selected?.color??'violet'))||error)return;const timer=setTimeout(()=>void flush(),900);return()=>clearTimeout(timer);
 },[text,selected,color,busy,error]);
 async function switchNote(note?:Spark){if(await flushLatest()){setSelected(note);setColor(note?.color??'violet');setText(note?.text??'');setError('');setSaved(false);}}
 async function flushLatest(){if(gate.current)return false;for(;;){if(!await flush())return false;const draft=current.current;if(!pending.current&&(!draft.text.trim()&&!draft.selected||(draft.text.trim()===(draft.selected?.text??'')&&draft.color===(draft.selected?.color??'violet'))))return true;}}
 async function finish(){if(await flushLatest())close();}
 async function removeNote(){
   if(!removing||gate.current)return;
   gate.current=true;setBusy(true);setRemoveError('');
   try {
     await api.json('/api/v1/sparks/remove','POST',
       {id:removing.id,expected_version:removing.version},removeKey.current,value=>{
         if(!value||typeof value!=='object'||!('id' in value)||value.id!==removing.id)throw Error('shape');
         return value;
       });
     if(!alive.current)return;
     if(current.current.selected?.id===removing.id){
       setSelected(undefined);setText('');setColor('violet');setSaved(false);setError('');
       current.current={selected:undefined,text:'',color:'violet'};
     }
     setRemovedIds(ids=>[...ids,removing.id]);setRemoving(undefined);
     void queries.invalidateQueries({queryKey:['api']});
   } catch(e){if(alive.current)setRemoveError(feedback(e).message);}
   finally{gate.current=false;if(alive.current)setBusy(false);}
 }
 async function confirmRemove(note:Spark){
   if(!await flushLatest())return;
   removeKey.current=crypto.randomUUID();setRemoveError('');
   setRemoving(current.current.selected?.id===note.id?current.current.selected:note);
 }
 return <TopicDialog title="闪念胶囊" className="spark-dialog" close={()=>{void finish();}}><div className="spark-layout"><section><div className="idea-heading"><h3>随手记录</h3><button className="btn" disabled={busy} onClick={()=>void switchNote()}>新记录</button></div><textarea className="spark-capture" aria-label="记录灵感，输入后自动保存" placeholder="任何想法，都可以先放在这里…" value={text} maxLength={20000} onChange={e=>{setText(e.target.value);setSaved(false);setError('');}}/><label className="spark-color-control">胶囊颜色 <select aria-label="胶囊颜色" value={color} disabled={busy} onChange={e=>{setColor(e.target.value as SparkColor);setSaved(false);setError('');}}>{Object.entries(sparkColors).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><p className="small muted" role="status">{busy?'正在保存…':saved?'已保存':'输入后自动保存'}</p>{(error||loadError)&&<><p role="alert" className="form-error">{error||loadError}</p><button className="btn" disabled={busy} onClick={()=>void flush()}>重试保存</button></>}</section><aside><h3>之前的闪念</h3><div className="idea-capsules">{visibleNotes.map(n=><div className="spark-history-item" data-color={n.color??'violet'} key={n.id}
 onPointerEnter={e=>{const text=e.currentTarget.querySelector<HTMLElement>('.spark-text');if(text)scrollSpark(text);}}
 onPointerLeave={e=>e.currentTarget.querySelector('.spark-text span')?.getAnimations().forEach(animation=>animation.cancel())}>
 <button className={'idea-capsule spark-compact '+(selected?.id===n.id?'selected':'')} disabled={busy} onClick={()=>void switchNote(n)} title={topicTime(n.updated_at)} aria-pressed={selected?.id===n.id}>
 <span className="spark-text"><span>{n.text.replace(/\s+/g,' ')}</span></span>
 </button><button className="spark-remove" disabled={busy} aria-label={`删除闪念：${n.title}`} onClick={()=>void confirmRemove(n)}>×</button>
 </div>)}{!visibleNotes.length&&<p className="small muted">还没有闪念，随手记下第一条。</p>}</div></aside></div>{removing&&<TopicDialog title="确认删除这条闪念？" close={()=>{if(!busy)setRemoving(undefined);}} foot={<><button className="btn" disabled={busy} onClick={()=>setRemoving(undefined)}>取消</button><button className="btn primary" disabled={busy} onClick={()=>void removeNote()}>确认删除</button></>}><p>{removing.title}</p>{removeError&&<p role="alert">{removeError}</p>}</TopicDialog>}</TopicDialog>;
}

function scrollSpark(text:HTMLElement){
 const distance=text.scrollWidth-text.clientWidth;
 if(distance<=0||window.matchMedia('(prefers-reduced-motion: reduce)').matches)return;
 text.firstElementChild?.animate([{transform:'translateX(0)'},{transform:`translateX(-${distance}px)`}],
   {duration:Math.max(1000,distance*22),delay:350,fill:'forwards',id:'spark-scroll'});
}
