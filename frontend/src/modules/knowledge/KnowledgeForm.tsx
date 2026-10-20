import {useRef,useState} from 'react';
import type {FormEvent} from 'react';
import {feedback,useApi} from '../../api/provider';
import type {KnowledgeItem,KnowledgeInput} from '../../api/client';
import {businessCodes} from '../research/MaterialForm';
import {ResearchDialog} from '../research/ResearchDialog';
export const categories={genre:'题材库',quote:'金句库',payoff:'爽点库',failure:'翻车点',dna_case:'DNA经典案例'} as const;
export const stages={topic:'选题',script:'脚本',asset:'资产',final:'成片'} as const;
export const types={fact:'事实情报',content_atom:'内容原子',method_rule:'方法规则',case_experience:'案例经验',project_related:'项目相关知识'} as const;
export function KnowledgeForm({business,category,item,close,saved}:{business:string;category:string;item?:KnowledgeItem;close:()=>void;saved:()=>void}){
 const api=useApi(),[title,setTitle]=useState(item?.title??''),[biz,setBiz]=useState(item?.business_codes[0]??businessCodes[business]),[stage,setStage]=useState(item?.tags.find(t=>t.kind==='stage')?.code??'topic'),[cat,setCat]=useState(item?.browse_category??category),[body,setBody]=useState(item?.revision.body_text??''),[evidence,setEvidence]=useState(item?.revision.limitations??''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const intent=useRef<{payload:string;key:string}|undefined>(undefined),form='knowledgeForm';
 const dismiss=()=>{if(!title&&!body&&!evidence||window.confirm('存在未保存的输入，确认关闭？'))close();};
 async function submit(e:FormEvent){e.preventDefault();if(busy)return;
  if(!(cat in categories)){setError('请选择知识分类。');return;}
  if(!title.trim()||!body.trim()||!evidence.trim()){setError('请填写知识标题、内容和来源与适用限制。');return;}
  const source=evidence.match(/^原文[：:]\s*([\s\S]+?)\n出处[：:]\s*([^\n]+)\n(?:适用)?限制[：:]\s*([\s\S]+)$/);
  const manual=source?{body_text:source[1].trim(),attribution:source[2].trim()}:undefined;
  if(manual&&(!manual.body_text||/^https?:\/\/\S+$/.test(manual.body_text)||!manual.attribution)){setError('请提供可核对的原文，链接或来源名称不能代替原文。');return;}
  const value:KnowledgeInput={title:title.trim(),body_text:body,knowledge_type:item?.revision.knowledge_type??'method_rule',browse_category:cat as KnowledgeInput['browse_category'],business_codes:[biz],tags:[...(item?.tags.filter(t=>t.kind!=='stage')??[]),{kind:'stage',code:stage}],evidence_ids:item?.revision.evidence_ids??[],source_report_id:item?.revision.source_report_id??null,limitations:evidence,...(manual?{manual_source:manual}:{})};
  const payload=JSON.stringify(value);if(intent.current?.payload!==payload)intent.current={payload,key:crypto.randomUUID()};
  setBusy(true);setError('');try{if(item)await api.reviseKnowledge(item.id,{...value,expected_lock_version:item.lock_version,revision_reason:'人工修订候选：正文、来源、分类或适用范围更新，重新双审'},intent.current.key);else await api.createKnowledge(value,intent.current.key);saved();close();}catch(ex){setError(feedback(ex).message);}finally{setBusy(false);}
 }
 return <ResearchDialog title={item?'修订候选知识':'人工新增知识'} form={form} submit="提交候选" busy={busy} close={dismiss}><form id={form} onSubmit={submit}><div className="field"><label htmlFor="kt">知识标题</label><input id="kt" required maxLength={90} value={title} onChange={e=>setTitle(e.target.value)}/></div><div className="field"><label htmlFor="kb">业务线</label><select id="kb" value={biz} onChange={e=>setBiz(e.target.value as typeof biz)}>{Object.entries(businessCodes).map(([label,code])=><option key={code} value={code}>{label}</option>)}</select></div><div className="field"><label htmlFor="ks">适用环节</label><select id="ks" value={stage} onChange={e=>setStage(e.target.value)}>{Object.entries(stages).map(([code,label])=><option key={code} value={code}>{label}</option>)}</select></div><div className="field"><label htmlFor="knowledgeCategory">知识分类</label><select id="knowledgeCategory" required value={cat} onChange={e=>setCat(e.target.value)}><option value="">请选择知识分类</option>{Object.entries(categories).map(([code,label])=><option key={code} value={code}>{label}</option>)}</select></div><div className="field"><label htmlFor="kc">知识内容</label><textarea id="kc" required value={body} onChange={e=>setBody(e.target.value)}/></div><div className="field"><label htmlFor="ke">来源与适用限制</label><textarea id="ke" placeholder={'原文：粘贴可核对的原文\n出处：注明来源\n限制：说明适用范围与局限'} required maxLength={1000} value={evidence} onChange={e=>setEvidence(e.target.value)}/></div><div className="notice">提交后进入待AI审核，人工新增同样不能跳过双审。可在来源框按“原文／出处／限制”分行补充资料；仅来源名称或链接仍待补原文。人工提供资料不代表独立核验；审核须批准配置及明确预算，不会自动标记通过。</div>{error&&<p className="form-error" role="alert">{error}</p>}</form></ResearchDialog>;
}
