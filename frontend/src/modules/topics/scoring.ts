import {useEffect,useRef,useState} from 'react';
import {feedback,useApi} from '../../api/provider';
import {ApiError} from '../../api/client';
import {parseScoreTask} from './contracts';
import type {ScoreTask,Topic} from './contracts';
const terminal=(t:ScoreTask)=>['succeeded','failed','cancelled'].includes(t.state);
type Pending={key:string;version:number};
function read(slot:string):Pending|null{const raw=sessionStorage.getItem(slot);if(!raw)return null;const v=JSON.parse(raw);if(!v||typeof v.key!=='string'||!/^[0-9a-f-]{36}$/i.test(v.key)||!Number.isSafeInteger(v.version)||v.version<1)throw Error('待核验评分记录损坏，请先核验原任务。');return v;}
export function useScoring(topic:Topic|undefined,scope:string,onResult:(task:ScoreTask)=>void){
 const api=useApi(),slot=`cip-topic-score:${scope}:${topic?.id??'new'}`;
 const [task,setTask]=useState(topic?.evaluation_task??null),[error,setError]=useState(''),[submitting,setSubmitting]=useState(false),[unknown,setUnknown]=useState(()=>{try{return !!read(slot);}catch{return true;}}),[attempt,setAttempt]=useState(0);
 const gate=useRef(false),alive=useRef(true),callback=useRef(onResult);
 useEffect(()=>{callback.current=onResult;},[onResult]);useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
 function accept(t:ScoreTask){if(t.topic_id!==topic?.id)throw Error('评分对象不匹配');if(alive.current){setTask(t);callback.current(t);}}
 useEffect(()=>{const current=task??topic?.evaluation_task;if(!current||terminal(current))return;let active=true;const controller=new AbortController();const timer=setTimeout(()=>{void api.get('/api/v1/topics/evaluations/'+current.id,parseScoreTask,controller.signal).then(t=>{if(t.id!==current.id||t.topic_id!==current.topic_id||t.topic_version!==current.topic_version)throw Error('评分版本不匹配');if(active)accept(t);}).catch(e=>{if(active)setError(feedback(e).message);});},1200);return()=>{active=false;clearTimeout(timer);controller.abort();};},[api,task,topic?.evaluation_task,attempt]);
 async function submit(target:Topic,recover=false){if(gate.current||task&&!terminal(task))return;let pending:Pending|null;try{pending=read(slot);if(pending&&!recover){setUnknown(true);setError('上次评分结果待核验，请恢复原评分提交。');return;}if(recover&&!pending)return;pending??={key:crypto.randomUUID(),version:target.version};sessionStorage.setItem(slot,JSON.stringify(pending));}catch{setUnknown(true);setError('无法保存或读取评分提交标识，请先核验原任务；不会另建付费请求。');return;}gate.current=true;setSubmitting(true);setUnknown(true);setError('');try{const result=await api.json('/api/v1/topics/'+target.id+'/evaluate','POST',{expected_version:pending.version},pending.key,parseScoreTask);if(result.topic_version!==pending.version)throw Error('评分版本不匹配');accept(result);sessionStorage.removeItem(slot);if(alive.current)setUnknown(false);}catch(e){if(e instanceof ApiError&&e.status>=400&&e.status<500&&!['EXTERNAL_RESULT_UNKNOWN','INVALID_RESPONSE'].includes(e.code)){sessionStorage.removeItem(slot);if(alive.current)setUnknown(false);}if(alive.current)setError(feedback(e).message);}finally{gate.current=false;if(alive.current)setSubmitting(false);}}
 return {task,error,unknown,busy:submitting||!!task&&!terminal(task),submit,recover:()=>{if(topic)void submit(topic,true);},check:()=>setAttempt(n=>n+1)};
}
