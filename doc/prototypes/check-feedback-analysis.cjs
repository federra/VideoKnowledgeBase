const assert=require('node:assert/strict');
const {boot}=require('./check-feedback.cjs');
(async()=>{
 const app=boot();
 const business=app.nodes.get('businessWorkspace').innerHTML;assert.match(business,/data-id="电商短视频"[^>]*disabled[^>]*>电商（建设中）/);
 const preview=app.run('feedbackPreview({id:"analyzed",title:"样例",comment_sample_count:15,entry:{feedback_id:"saved"},feedback_emotions:["正面","期待","好奇"]})');assert.ok(!preview.includes('已采集 15'));assert.equal((preview.match(/class="emotion-tag"/g)||[]).length,2);assert.ok(preview.includes('title="正面"'));
 assert.ok(app.run('feedbackPreview({id:"analyzed",entry:{feedback_id:"saved"},comment_sample_count:15,feedback_emotions:[]})').includes('AI分析已完成'));
 const originalBiz=app.run('state.biz[0]');await app.run('action("biz","电商短视频")');assert.equal(app.run('state.biz[0]'),originalBiz);
 for(const sourceType of ['video','novel']){const card=app.run(`feedCard({id:'sample',sourceType:${JSON.stringify(sourceType)},title:'演示',biz:['AI漫剧'],plot:'示例',url:null},1,{platform:'样例',blogger:'样例',genre:'样例'})`);assert.equal((card.match(/data-action="feedback-open"/g)||[]).length,1);assert.ok(!card.includes('data-action="research-send"'));}
app.run('audienceFeedbackDialog("S-2401","2026-10-04")');
 const html=app.nodes.get('dialog').innerHTML;
 assert.match(html,/<span hidden style="display:none"><button[^>]*data-action="feedback-research"/);
 assert.match(html,/<button class="btn primary" data-action="feedback-analyze-demo"[^>]*>评论分析<\/button>/);assert.ok(html.includes('仅展示固定虚构结果，未调用AI'));
 assert.ok(html.includes('情绪分布')&&html.includes('受欢迎点与问题点')&&html.includes('TOP评论'));
 await app.run('action("feedback-analyze-demo")');
 assert.ok(app.nodes.get('toast').textContent.includes('未提交分析或调用AI'));
 app.run('audienceFeedbackDialog(getFeedSnapshot("2026-10-04").intel.find(v=>v.displaySample).id,"2026-10-04")');
 assert.match(app.nodes.get("dialog").innerHTML,/data-action="feedback-analyze-demo" disabled/);
 console.log('观众反馈AI演示入口与只读报告检查通过；未调用网络或模型。');
})().catch(e=>{console.error(e);process.exitCode=1;});
