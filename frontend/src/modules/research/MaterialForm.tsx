import {useRef,useState} from 'react';
import type {FormEvent} from 'react';
import {feedback,useApi} from '../../api/provider';
import type {DirectResearch,ResearchWork} from '../../api/client';
import {ResearchDialog} from './ResearchDialog';
export const businessCodes:Record<string,'motion_comic'|'story_short'|'ecommerce_video'>={AI漫剧:'motion_comic',故事短片:'story_short',电商短视频:'ecommerce_video'};
export function MaterialForm({business,work,material,initialEpisode,close,saved}:{business:string;work?:ResearchWork;material?:ResearchWork['materials'][number];initialEpisode?:number;close:()=>void;saved:()=>void}){
 const [selectedBusiness,setSelectedBusiness]=useState(business);
 const api=useApi(),[title,setTitle]=useState(''),[body,setBody]=useState(''),[scope,setScope]=useState(initialEpisode?'episode':'work'),[episode,setEpisode]=useState(initialEpisode?.toString()??''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const intent=useRef<{body:string;key:string}|undefined>(undefined);
 const form='realMaterialForm';
 const dismiss=()=>{if(!title&&!body||window.confirm('存在未保存的输入，确认关闭？'))close();};
 async function submit(e:FormEvent){e.preventDefault();if(busy)return;setError('');
  if(!title.trim()||!body.trim()){setError('请填写资料标题和内容');return;}
  const number=scope==='episode'?Number(episode):undefined;
  if(scope==='episode'&&(!Number.isSafeInteger(number)||!number||number<1||work?.total_episode_count&&number>work.total_episode_count)){setError('请填写有效集号，不能超过总集数');return;}
  const source=/^https?:\/\/\S+$/i.test(body.trim())?{origin:'link' as const,url:body.trim()}:{origin:'text' as const,body_text:body};
  const sameUnit=material?.versions.find(v=>v.id===material.current_version_id)?.episode_no===(number??null);
  const input={title:title.trim(),material_kind:'reference' as const,...source,episode_no:number,...(material&&sameUnit?{artifact_id:material.id,expected_artifact_lock_version:material.lock_version}:{})};
  const payload=work?input:{...input,target:{kind:'new' as const,business_code:businessCodes[selectedBusiness],name:title.trim(),genre_tags:[]}};
  const canonical=JSON.stringify(payload);if(intent.current?.body!==canonical)intent.current={body:canonical,key:crypto.randomUUID()};
  setBusy(true);try{if(work)await api.addResearchMaterial(work.id,input,intent.current.key);else await api.submitResearch(payload as DirectResearch,intent.current.key);saved();close();}catch(ex){setError(feedback(ex).message);}finally{setBusy(false);}
 }
 return <ResearchDialog title={work?'提交资料':'新建研判'} form={form} submit={work?'提交处理':'提交研判'} busy={busy} close={dismiss}><form id={form} onSubmit={submit}><div className="field"><label htmlFor="realMaterialTitle">{work?'资料名称':'资料标题'}</label><input id="realMaterialTitle" value={title} onChange={e=>setTitle(e.target.value)} maxLength={100} required/></div><div className="field"><label htmlFor="realMaterialBody">{work?'粘贴文本或来源链接':'内容正文或来源链接'}</label><textarea id="realMaterialBody" value={body} onChange={e=>setBody(e.target.value)} maxLength={200000} required/></div>{work?.business_code==='motion_comic'?<div className="field"><label htmlFor="materialScope">资料归属</label><select id="materialScope" value={scope} onChange={e=>setScope(e.target.value)}><option value="work">作品级资料</option><option value="episode">单集资料</option></select>{scope==='episode'&&<><label htmlFor="materialEpisode">集号</label><input id="materialEpisode" type="number" min={1} step={1} value={episode} onChange={e=>setEpisode(e.target.value)} required/></>}</div>:null}{work?<p className="small muted">关联作品：{work.name} · {work.work_number}</p>:<div className="field"><label htmlFor="directBusiness">业务线</label><select id="directBusiness" value={selectedBusiness} onChange={e=>setSelectedBusiness(e.target.value)}>{Object.keys(businessCodes).map(b=><option key={b}>{b}</option>)}</select></div>}<p className="small muted">提交后保存真实资料并进行文本解析；链接仅支持已采集来源，不自动追加外部采集。音视频转写尚待配置。</p>{error&&<p className="form-error" role="alert">{error}</p>}</form></ResearchDialog>;
}
