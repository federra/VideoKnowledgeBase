import type {KnowledgeItem} from '../../api/client';

export function knowledgeExplanation(item:KnowledgeItem){
 const original=item.revision.explanation?.trim();
 if(original)return {text:original,ai:false};
 if(item.browse_category==='genre'&&item.ai_explanation)return {text:item.ai_explanation.text,ai:true};
 return undefined;
}
