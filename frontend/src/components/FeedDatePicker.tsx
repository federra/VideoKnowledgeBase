import {useEffect, useId, useRef, useState} from 'react';
import type {KeyboardEvent} from 'react';
import {useApi, useApiQuery} from '../api/provider';

type Props = {business:'motion_comic'|'story_short'|'ecommerce_video';value:string;today:string;onChange:(day:string)=>void};
const labels={future:'未来日期','has-data':'已采集','no-data':'无采集数据',unknown:'状态待确认'};
const iso=(d:Date)=>d.toISOString().slice(0,10);
const date=(s:string)=>new Date(s+'T12:00:00Z');
function nextMonth(month:string,step:number){const d=date(month+'-01');d.setUTCMonth(d.getUTCMonth()+step);return iso(d).slice(0,7);}

export function FeedDatePicker(props:Props){
 const [open,setOpen]=useState(false);
 const root=useRef<HTMLDivElement>(null),trigger=useRef<HTMLButtonElement>(null);
 const dialogId=useId();
 function close(restore=true){setOpen(false);if(restore)trigger.current?.focus();}
 useEffect(()=>{
  if(!open)return;
  function outside(e:PointerEvent){if(e.target instanceof Node&&!root.current?.contains(e.target))setOpen(false);}
  document.addEventListener('pointerdown',outside);
  return()=>document.removeEventListener('pointerdown',outside);
 },[open]);
 return <div className="feed-date-picker" ref={root} onBlur={e=>{if(e.relatedTarget instanceof Node&&!e.currentTarget.contains(e.relatedTarget))setOpen(false);}} onKeyDown={e=>{if(e.key==='Escape'&&open){e.preventDefault();e.stopPropagation();close();}}}>
  <button id="feedDate" ref={trigger} className="feed-date-trigger" type="button" aria-label="情报流日期" aria-haspopup="dialog" aria-expanded={open} aria-controls={open?dialogId:undefined} title="按北京时间查看指定日期的真实快照" onClick={()=>setOpen(!open)}>
   <span>{props.value.replaceAll('-','/')}</span><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 11h18"/></svg>
  </button>
  {open&&<Calendar key={props.business} {...props} id={dialogId} close={close}/>}
 </div>;
}
function Calendar({business,value,today,onChange,id,close}:Props&{id:string;close:()=>void}){
 const [month,setMonth]=useState(value.slice(0,7));
 const [focusDay,setFocusDay]=useState(value);
 const grid=useRef<HTMLDivElement>(null);
 const api=useApi();
 const query=useApiQuery(['feed-calendar',business,month],signal=>api.feedCalendar(business,month,signal),()=>false);
 const cutoff=query.data?.today??today;
 const days=new Set(query.data?.dates??[]);
 const first=date(month+'-01'),next=date(month+'-01');next.setUTCMonth(next.getUTCMonth()+1);next.setUTCDate(0);
 const count=next.getUTCDate(),offset=(first.getUTCDay()+6)%7;
 const state=(day:string)=>day>cutoff?'future':query.data?days.has(day)?'has-data':'no-data':'unknown';
 useEffect(()=>{grid.current?.querySelector<HTMLButtonElement>(`[data-day="${focusDay}"]`)?.focus();},[focusDay]);
 function moveMonth(step:number){if(step<0&&month==='0001-01'||step>0&&month==='9999-12')return;const target=nextMonth(month,step);setMonth(target);setFocusDay(target+'-01');}
 function keyboard(e:KeyboardEvent<HTMLButtonElement>,day:string){
  const d=date(day);let delta:number;
  if(e.key==='ArrowLeft')delta=-1;else if(e.key==='ArrowRight')delta=1;else if(e.key==='ArrowUp')delta=-7;else if(e.key==='ArrowDown')delta=7;
  else if(e.key==='Home')delta=-(d.getUTCDay()+6)%7;else if(e.key==='End')delta=6-(d.getUTCDay()+6)%7;
  else if(e.key==='PageUp'||e.key==='PageDown'){e.preventDefault();moveMonth(e.key==='PageUp'?-1:1);return;}else return;
  e.preventDefault();d.setUTCDate(d.getUTCDate()+delta);const target=iso(d);
  if(target>cutoff||target<'0001-01-01'||target>'9999-12-31')return;
  setMonth(target.slice(0,7));setFocusDay(target);
 }
 return <section className="feed-calendar" id={id} role="dialog" aria-labelledby={id+'-title'} aria-describedby={id+'-scope'}>
  <div className="feed-calendar-heading"><strong id={id+'-title'} aria-live="polite">{Number(month.slice(0,4))}年{Number(month.slice(5))}月</strong><button type="button" aria-label="上个月" disabled={month==='0001-01'} onClick={()=>moveMonth(-1)}>‹</button><button type="button" aria-label="下个月" disabled={month==='9999-12'} onClick={()=>moveMonth(1)}>›</button></div>
  <p id={id+'-scope'} className="feed-calendar-scope">当前业务线 · 北京时间</p>
  <div className="feed-calendar-week" aria-hidden="true">{['一','二','三','四','五','六','日'].map(w=><span key={w}>{w}</span>)}</div>
  <div className="feed-calendar-days" ref={grid} role="group" aria-label="选择日期">
   {Array.from({length:offset},(_,i)=><span key={'blank'+i}/>)}
   {Array.from({length:count},(_,i)=>{const day=month+'-'+String(i+1).padStart(2,'0'),status=state(day);return <button key={day} data-day={day} type="button" className={`feed-calendar-day ${status}${day===value?' selected':''}${day===cutoff?' today':''}`} disabled={status==='future'} aria-label={`${day}，${labels[status]}${day===cutoff?'，今天':''}`} aria-pressed={day===value} aria-current={day===cutoff?'date':undefined} tabIndex={day===focusDay?0:-1} title={`${day} · ${labels[status]}`} onKeyDown={e=>keyboard(e,day)} onClick={()=>{onChange(day);close();}}><span>{i+1}</span><i aria-hidden="true"/></button>;})}
  </div>
  <div className="feed-calendar-footer"><div className="feed-calendar-legend" aria-label="采集状态图例"><span className="no-data">未采集／未来</span><span className="has-data">已采集</span></div><button type="button" onClick={()=>{onChange(cutoff);close();}}>今天</button></div>
  {!query.data&&<div className="feed-calendar-status"><span role="status">{query.status==='loading'?'正在查询采集状态…':'采集状态暂不可用'}</span>{query.status!=='loading'&&<button type="button" onClick={()=>void query.refetch()}>重试</button>}</div>}

 </section>;
}
