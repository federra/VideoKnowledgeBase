const assert=require('node:assert/strict');
const {boot}=require('./check-feedback.cjs');
(async()=>{
 const app=boot();
 app.run(`state.biz=['AI漫剧'];db.knowledge=[{id:'K-1',title:'测试甲',category:'题材库',biz:['AI漫剧'],status:'已入库',version:1,tags:[]},{id:'K-2',title:'测试乙',category:'题材库',biz:['AI漫剧'],status:'已入库',version:1,tags:[]}];navigate(1,0)`);
 let html=app.run('knowledgePage()');assert.doesNotMatch(html,/显示双审通过|条正式知识|knowledge-bulk-recycle/);assert.match(html,/选择知识：测试甲/);assert.match(html,/移入回收站：测试甲/);
 await app.run('action("delete-knowledge","K-1")');assert.match(app.nodes.get('dialog').innerHTML,/确认移入回收站？/);await app.run('action("close")');assert.equal(app.run('db.knowledge[0].status'),'已入库');
 await app.run('action("knowledge-select","K-1")');assert.doesNotMatch(app.run('knowledgePage()'),/knowledge-bulk-recycle/);
 await app.run('action("knowledge-select","K-2")');assert.match(app.run('knowledgePage()'),/knowledge-bulk-recycle/);
 await app.run('action("knowledge-bulk-recycle")');assert.match(app.nodes.get('dialog').innerHTML,/已选择 2 条知识/);await app.run('action("knowledge-recycle-confirm")');assert.equal(app.run('db.knowledge.filter(x=>x.status==="回收站").length'),2);
 await app.run('navigate(1,3)');assert.match(app.run('knowledgePage()'),/data-action="restore-knowledge"/);await app.run('action("restore-knowledge","K-1")');await app.run('action("knowledge-recycle-confirm")');assert.equal(app.run('db.knowledge[0].status'),'已入库');
 await app.run('action("delete-knowledge","K-1")');await app.run('action("knowledge-recycle-confirm")');
 await app.run('navigate(1,3)');assert.match(app.run('knowledgePage()'),/永久删除知识：测试甲/);assert.match(app.run('knowledgePage()'),/选择知识：测试甲/);
 await app.run('action("knowledge-select","K-1")');await app.run('action("knowledge-select","K-2")');assert.match(app.run('knowledgePage()'),/批量永久删除/);assert.match(app.run('knowledgePage()'),/批量恢复/);
 await app.run('action("knowledge-bulk-purge")');assert.match(app.nodes.get('dialog').innerHTML,/确认永久删除？/);await app.run('action("close")');assert.equal(app.run('db.knowledge.length'),2);
 await app.run('action("knowledge-bulk-purge")');await app.run('action("knowledge-recycle-confirm")');assert.equal(app.run('db.knowledge.length'),0);
 app.run(`db.knowledge=[{id:'expired',title:'到期演示',category:'题材库',biz:['AI漫剧'],status:'回收站',recycledAt:new Date(Date.now()-30*86400000).toISOString(),version:1,tags:[]}];knowledgePage()`);assert.equal(app.run('db.knowledge.length'),0);
 console.log('PASS 回收站单条/批量永久删除确认取消、恢复与30天过期清理（Demo本地）');
})().catch(e=>{console.error(e);process.exitCode=1});
