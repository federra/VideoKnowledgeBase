const assert=require('node:assert/strict');const {boot}=require('./check-feedback.cjs');
(async()=>{const app=boot();assert.equal(app.run('state.rankBoard'),'hongguo');app.run('state.biz=["AI漫剧"];navigate(0,0)');assert.ok(!app.run('rankBoardFilter()').includes('全部榜单'));
let html=app.nodes.get('page').innerHTML;for(const text of ['红果榜单','红果热播榜','真人剧热播榜','AI剧热播榜','漫剧热播榜','暂无已采集题材','二级题材','暂无已采集二级题材'])assert.ok(html.includes(text),text);
assert.ok(html.includes('novel-filter-row'));assert.ok(!html.includes('开学那天，我被当成传说'));
await app.run('action("hongguo-board","hot-ai-drama")');app.run('state.hongguoGenre="都市";state.hongguoSubgenre="重生"');await app.run('action("hongguo-board","hot-comic-drama")');assert.equal(app.run('state.hongguoGenre'),'');assert.equal(app.run('state.rankPage'),1);assert.equal(app.run('state.hongguoSubgenre'),'');
// Explicit captured tags only: never infer labels from a title or synopsis.
assert.ok(app.run('hongguoFilters([{genreTags:["玄幻","逆袭"]}])').includes('玄幻'));
assert.ok(!app.run('hongguoFilters([{title:"都市复仇",plot:"爱情"}])').includes('都市复仇'));
const metrics=app.run('engagementStats({heatDisplay:"8070万",scoreDisplay:"9.1",likes:2212000,saves:685000},true)');assert.deepEqual([...metrics.matchAll(/<b>(.*?)<\/b>/g)].map(x=>x[1]),['热','分','赞','藏']);assert.ok(metrics.includes('8070万')&&metrics.includes('9.1'));
const missing=app.run('engagementStats({views:999999},true)');assert.ok(!missing.includes('999999'));
console.log('PASS 红果入口、三级紧凑筛选、真实标签空态与联动重置');})().catch(e=>{console.error(e);process.exitCode=1});
