import {useEffect,useRef} from 'react';
import type {ReactNode} from 'react';
import {Icon} from '../../components/Icon';
export function ResearchDialog({title,children,close,form,submit,drawer=false,busy=false}:{title:string;children:ReactNode;close:()=>void;form:string;submit:string;drawer?:boolean;busy?:boolean}){
 const ref=useRef<HTMLDialogElement>(null);
 useEffect(()=>{const d=ref.current!,opener=document.activeElement;d.showModal();return()=>{d.close();if(opener instanceof HTMLElement&&opener.isConnected)opener.focus();};},[]);
 return <dialog ref={ref} className={drawer?'drawer':''} aria-labelledby={form+'Title'} onCancel={e=>{e.preventDefault();if(!busy)close();}}><div className="dialog-head"><h2 id={form+'Title'}>{title}</h2><button type="button" className="icon-btn" aria-label="关闭" disabled={busy} onClick={close}><Icon name="close"/></button></div><div className="dialog-body">{children}</div><div className="dialog-foot"><button className="btn" disabled={busy} onClick={close}>取消</button><button className="btn primary" type="submit" form={form} disabled={busy}>{busy?'正在提交…':submit}</button></div></dialog>;
}
