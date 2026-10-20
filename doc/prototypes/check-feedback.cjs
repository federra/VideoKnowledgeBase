// 无浏览器、无依赖的原型行为检查；不代替实屏布局与可访问性验证。
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function boot(saved = {}, hash = '#0/0') {
  const storage = new Map(Object.entries(saved)), nodes = new Map(), events = {}, timers = new Map();let timerId=0;
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, {
      id, innerHTML: '', textContent: '', open: false, isConnected: true,
      classList: {add() {}, remove() {}}, attributes: {}, style: {}, hidden: true,
      setAttribute(name,value) {this.attributes[name]=String(value);},
      getAttribute(name) {return this.attributes[name]??null;},
      removeAttribute(name) {delete this.attributes[name];}, contains(target) {return target===this;}, focus() {},
      scrollIntoView() {}, addEventListener(name,fn) {events[id+':'+name] = fn;},
      showModal() {this.open = true;}, close() {this.open = false;}
    });
    return nodes.get(id);
  };
  class DemoFormData {
    constructor(form) {this.values = form.values;}
    *[Symbol.iterator]() {for (const [k,v] of Object.entries(this.values)) for (const x of [].concat(v)) yield [k,x];}
    getAll(key) {return this.values[key] === undefined ? [] : [].concat(this.values[key]);}
  }
  const context = vm.createContext({
    console, structuredClone, URL, URLSearchParams, FormData: DemoFormData,
    location: {search: '?qa=1', hash},
    localStorage: {getItem: k => storage.get(k) ?? null, setItem: (k,v) => storage.set(k,v)},
    document: {documentElement: {dataset: {}}, activeElement: node('focus'), getElementById: node, querySelectorAll: () => [],
      addEventListener: (name,fn) => events[name] = fn},
    window: {addEventListener(name,fn) {events['window:'+name]=fn;}},
    setTimeout: fn => {timers.set(++timerId,fn);return timerId;}, clearTimeout: id => timers.delete(id), confirm: () => true
  });
  vm.runInContext(script, context);
  return {nodes, storage, run: expression => vm.runInContext(expression, context), dispatch: (name,event) => events[name](event),
    flushTimers() {const pending=[...timers.values()];timers.clear();pending.forEach(fn=>fn());}, input(id,value) {
    const target = node(id);target.value = value;
    events['dialog:input']({target});
  }, submit(values, formId='researchIntakeForm', kind='') {
    events.submit({preventDefault() {}, target: {values, dataset:{kind}, getAttribute: () => formId, querySelectorAll: () => []}});
  }};
}

if(require.main===module)(async () => {
  const app = boot();
  // 浮框只揭示被截断的全文；尺寸为隔离输入，不能代替浏览器布局检查。
  assert.equal(app.run('typeof showFeedFullText'), 'function', '截断标题和剧情应支持全文浮框');
  app.run(`window.innerWidth=375;window.innerHeight=700;
    const longText='<img onerror=alert(1)>\\n'+ '长剧情'.repeat(1000);
    const textSource={isConnected:true,dataset:{feedFullText:longText},clientWidth:200,scrollWidth:200,clientHeight:22,scrollHeight:22,attributes:{},
      getBoundingClientRect:()=>({left:320,top:640,bottom:662}),
      getAttribute(name){return this.attributes[name]??null;},setAttribute(name,value){this.attributes[name]=value;},removeAttribute(name){delete this.attributes[name];},contains(target){return target===this;}};
    const textPopover=document.getElementById('feedTextPopover');textPopover.offsetWidth=351;textPopover.offsetHeight=300;`);
  app.run('showFeedFullText(textSource)');
  assert.equal(app.nodes.get('feedTextPopover').hidden,true, '完整显示时不弹框');
  app.run('textSource.scrollWidth=201;showFeedFullText(textSource)');
  const popover=app.nodes.get('feedTextPopover');
  assert.equal(popover.hidden,false);
  assert.equal(popover.textContent,app.run('longText'), '全文按纯文本呈现，不能插入第三方HTML');
  assert.equal(app.run('textSource.getAttribute("aria-describedby")'),'feedTextPopover');
  assert.ok(parseFloat(popover.style.left)>=12 && parseFloat(popover.style.left)+351<=363,'窄屏浮框不得越过右边缘');
  assert.ok(parseFloat(popover.style.top)>=12 && parseFloat(popover.style.top)+300<=688,'底部浮框应向上避让');
  app.run('hideFeedFullText()');
  assert.equal(popover.hidden,true);
  assert.equal(app.run('textSource.getAttribute("aria-describedby")'),null);
  app.run('textSource.scrollWidth=200;textSource.scrollHeight=44;showFeedFullText(textSource)');
  assert.equal(popover.hidden,false, '纵向截断也能显示全文');
  app.run('render()');
  assert.equal(popover.hidden,true, '切换筛选或页面不残留旧浮框');
  const source=app.run('textSource');source.closest=()=>source;
  app.dispatch('pointerover',{target:source,relatedTarget:null,pointerType:'mouse'});
  assert.equal(popover.hidden,false, '鼠标悬停触发全文框');
  app.dispatch('pointerout',{target:source,relatedTarget:popover});app.flushTimers();
  assert.equal(popover.hidden,false,'移入全文框不能关闭它');
  app.dispatch('pointerout',{target:popover,relatedTarget:null});app.flushTimers();
  assert.equal(popover.hidden,true,'离开正文和浮框后关闭');
  app.dispatch('focusin',{target:source});
  assert.equal(popover.hidden,false,'键盘聚焦也能阅读');
  app.dispatch('keydown',{key:'Escape',preventDefault(){}});
  assert.equal(popover.hidden,true,'Escape关闭浮框');
  app.dispatch('pointerover',{target:source,relatedTarget:null,pointerType:'touch'});
  assert.equal(popover.hidden,true,'触摸移动不触发悬停');
  app.dispatch('pointerover',{target:source,relatedTarget:null,pointerType:'mouse'});
  app.dispatch('window:scroll',{target:popover});
  assert.equal(popover.hidden,false,'浮框内滚动保留全文');
  app.dispatch('window:resize',{});
  assert.equal(popover.hidden,true,'改变窗口后清除旧位置');
  const latest = app.run('feedSource("S-2401", latestFeedDate).audienceFeedback');
  assert.ok(latest, '历史快照应包含观众反馈，而非仅有总评论数');
  assert.equal(latest.sourceDate, '2026-10-04');
  assert.equal(latest.comments.length, 8);
  assert.equal(app.run('feedbackEmotions(feedSource("S-2401").audienceFeedback).find(e=>e.name==="爽感").percent'), 25);
  assert.equal(app.run('feedbackEmotions({comments:[{id:"x",text:"有趣",emotions:["好奇","好奇"],likes:0},{id:"x",text:"重复",emotions:["好奇"],likes:1}]}).find(e=>e.name==="好奇").count'), 1);
  const older = app.run('feedSource("S-2401", "2026-10-02").audienceFeedback');
  assert.equal(older.sourceDate, '2026-10-02');
  assert.notEqual(older.id, latest.id);
  assert.notEqual(older.comments.length, latest.comments.length);
  assert.ok(app.run('getFeedSnapshot("2026-10-01")') === null, '无历史日不能回退最新数据');
  assert.ok(app.run('feedbackPreview({id:"unknown"})').includes('评论未获取'));
  assert.ok(app.run('feedbackReport({status:"empty",comments:[]})').includes('确认无评论'));
  assert.ok(app.run('feedbackReport({status:"failed",comments:[]})').includes('采集失败'));
  assert.ok(!app.run('feedbackReport({status:"empty",comments:[]})').includes('%'));
  for (const date of ['2026-10-02','2026-10-03','2026-10-04']) {
    for (const video of app.run(`getFeedSnapshot(${JSON.stringify(date)}).intel`)) {
      if(video.displaySample){assert.ok(!video.audienceFeedback,'展示样例不伪造评论分析');assert.ok(app.run(`feedbackPreview(feedSource(${JSON.stringify(video.id)},${JSON.stringify(date)}))`).includes('评论未获取'));continue;}
      assert.equal(video.audienceFeedback.sourceDate, date);
      assert.equal(video.audienceFeedback.sourceId, video.id);
      app.run(`feedbackReport(feedSource(${JSON.stringify(video.id)},${JSON.stringify(date)}).audienceFeedback)`);
    }
  }

  app.run('state.biz=["AI漫剧"]; changeFeedDate("2026-10-02")');
  const originalHash = app.run('location.hash');
  const feed = app.nodes.get('page').innerHTML;
  assert.ok(feed.includes('观众反馈'));
  assert.ok(feed.includes('genre-tag') && feed.includes('emotion-tag'));
  assert.ok(!feed.includes('feed-biz-tag'), '列表不重复展示业务标签');
  assert.ok(!feed.includes('更新时间') && !/\d{2}:\d{2} 更新/.test(feed), '列表不展示更新时间');
  assert.ok(!feed.includes(older.summary), '关键反馈不能出现在列表正文或提示中');
  const unsafeCard=app.run('feedCard({id:"unsafe",title:"<img onerror=alert(1)>",plot:"<script>alert(1)</script>",url:"https://example.com"},1,{platform:"样例",blogger:"样例",genre:"样例"})');
  assert.ok(!unsafeCard.includes('<img onerror')&&!unsafeCard.includes('<script>'),'爬取标题与剧情不能成为HTML');
  assert.ok(unsafeCard.includes('&lt;img')&&unsafeCard.includes('&lt;script&gt;'),'全文属性和正文均安全转义');
  const sampleCard=app.run('feedCard({id:"display-test",title:"虚构展示样例",plot:"用于检查截断",biz:["AI漫剧"]},1,{platform:"展示测试样例",blogger:"演示作者"})');
  assert.ok(!sampleCard.includes('href=""')&&!sampleCard.includes('打开原视频：'),'虚构样例无链接时不产生假的原视频入口');
  await app.run('action("feedback-open", "S-2401")');
  const body = app.nodes.get('dialog').innerHTML;
  for (const text of ['情绪分布', '受欢迎点与问题点', '观众期待', '创作建议', 'TOP评论', '虚构', '2026-10-02']) assert.ok(body.includes(text), text);
  assert.ok(!body.includes(older.summary) && !body.includes('关键反馈：'), '选择研判前不展示关键反馈');
  assert.equal(app.run('state.module'), 0);
  assert.equal(app.run('location.hash'), originalHash);
  assert.equal(app.nodes.get('dialog').className, 'drawer');
  await app.run('action("feedback-evidence", "0")');
  assert.equal(app.nodes.get('feedbackComments').open, true);
  await app.run('action("feedback-evidence", "0,4")');
  assert.ok(app.nodes.get('feedbackEvidenceNote').textContent.includes('2 条'));
  await app.run('action("feedback-research", "S-2401")');
  assert.ok(app.nodes.get('dialog').innerHTML.includes('researchIntakeForm'));
  assert.ok(app.nodes.get('dialog').innerHTML.includes('观众反馈'));
  assert.ok(app.nodes.get('dialog').innerHTML.includes(older.summary));
  assert.ok(app.nodes.get('dialog').innerHTML.includes('关键反馈：'));
  app.submit({workName:'开学那天，我被当成传说',workId:'WORK-A-001',sourceId:'S-2401', sourceDate:'2026-10-02', grade:'A', biz:'AI漫剧', genre:'都市奇幻', learningTag:['剧情反转'], learningText:'验证人物动机铺垫'});
  const submitted = app.run('structuredClone(db.research[0])');
  assert.equal(submitted.status, '待分析');
  assert.equal(submitted.sourceSnapshot.audienceFeedback.id, older.id);
  app.run('feedSource("S-2401", "2026-10-02").audienceFeedback.comments[0].text="后续变更"');
  assert.equal(app.run('db.research[0].sourceSnapshot.audienceFeedback.comments[0].text'), submitted.sourceSnapshot.audienceFeedback.comments[0].text, '研判证据不得随源数据变更');
  await app.run('action("research-detail", db.research[0].id)');
  assert.ok(app.nodes.get('dialog').innerHTML.includes('观众反馈'));
  assert.ok(app.nodes.get('dialog').innerHTML.includes(older.summary), '研判详情保留提交时的关键反馈');
  assert.ok(!app.nodes.get('dialog').innerHTML.includes('后续变更'));

  await app.run('action("work-detail", db.research[0].workId)');
  for(const text of ['人工初评','A 级','剧情反转','验证人物动机铺垫','2026-10-02']) assert.ok(app.nodes.get('page').innerHTML.includes(text),'作品详情应直接展示初评：'+text);
  const reviewTaskId=app.run('db.research[0].id');
  app.run('db.research[0].status="已完成"');
  await app.run('action("research-detail", db.research[0].id)');
  assert.ok(app.nodes.get('dialog').innerHTML.includes('验证人物动机铺垫'),'已完成报告仍保留人工初评');
  app.run('db.research[0].status="待分析"');
  app.submit({workName:'开学那天，我被当成传说',workId:'WORK-A-001',sourceId:'S-2401',sourceDate:'2026-10-02',grade:'S',biz:'AI漫剧',genre:'校园',learningTag:['人物塑造'],learningText:'新的判断\n<不要作为HTML>'});
  assert.equal(app.run('db.research[0].id'),reviewTaskId,'重复提交更新原待分析任务');
  await app.run('action("work-detail", db.research[0].workId)');
  const revisedReview=app.nodes.get('page').innerHTML;
  assert.ok(revisedReview.includes('S 级')&&revisedReview.includes('验证人物动机铺垫'),'新旧初评均可查看');
  assert.ok(revisedReview.includes('&lt;不要作为HTML&gt;')&&!revisedReview.includes('<不要作为HTML>'),'人工文字必须安全转义');
  app.run('save()');
  const reviewReload=boot(Object.fromEntries(app.storage));
  reviewReload.run('state.biz=["AI漫剧"];workDetail(db.research[0].workId)');
  assert.ok(reviewReload.nodes.get('page').innerHTML.includes('新的判断'),'刷新后初评保持可见');
  app.run('db.research.push({id:"C-OTHER-REVIEW",workId:"WORK-A-002",title:"其他作品",biz:["AI漫剧"],status:"待分析",version:1,rating:"C",learningText:"其他作品的判断"})');
  app.run('workDetail(db.research[0].workId)');
  assert.ok(!app.nodes.get('page').innerHTML.includes('其他作品的判断'),'按作品ID隔离人工初评');
  app.run('researchDetail("C-088")');
  assert.ok(app.nodes.get('dialog').innerHTML.includes('尚无人工初评记录'),'无初评不能补造等级');

  app.run('db.research.push({id:"C-WORK-REPORT",workId:db.research[0].workId,title:"同作品阶段报告",biz:["AI漫剧"],status:"已完成",version:2,sourceId:"人工提交"});researchDetail("C-WORK-REPORT")');
  assert.ok(app.nodes.get('dialog').innerHTML.includes('作品关联人工初评')&&app.nodes.get('dialog').innerHTML.includes('新的判断'),'同作品报告关联原提交初评');
  assert.ok(app.nodes.get('dialog').innerHTML.includes('不代表该历史报告的输入或结论'),'后续关联初评与历史报告结论区分');
  assert.ok(app.run('humanReviewBlock({id:"legacy-review",title:"旧记录",version:1,learningText:"没有评级的旧学习点"})').includes('没有评级的旧学习点'),'旧记录无评级也展示已存文字');

  // 缺失及空样本不显示虚构百分比，第三方正文不能成为HTML。
  assert.ok(app.run('feedbackReport(null)').includes('评论未获取'));
  assert.ok(!app.run('feedbackReport({status:"empty",comments:[]})').includes('NaN'));
  const safe = app.run('feedbackReport({...feedSource("S-2401").audienceFeedback, comments:[{id:"x",text:"<img onerror=alert(1)>",user:"<script>",likes:null,emotions:[]}]})');
  assert.ok(!safe.includes('<img onerror'));
  assert.ok(safe.includes('&lt;img'));
  assert.ok(safe.includes('未获取'));

  const frozenFeedback = JSON.stringify(app.run('feedSource("S-2401").audienceFeedback'));
  app.run('save()');
  const restored = boot(Object.fromEntries(app.storage));
  assert.equal(restored.run('state.feedDate'), '2026-10-02');
  assert.equal(JSON.stringify(restored.run('feedSource("S-2401").audienceFeedback')), frozenFeedback);
  assert.equal(restored.run('db.research[0].sourceSnapshot.audienceFeedback.id'), older.id);
  // 旧存储中只有最新反馈时，补充虚构历史档案不能携带最新反馈日期。
  const legacy = app.run('JSON.parse(JSON.stringify(db))');
  delete legacy.feedArchive['2026-10-02'];delete legacy.feedArchive['2026-10-03'];
  legacy.intel[0].audienceFeedback.summary = '保留已有反馈修改';
  const migrated = boot({'content-ui-qa-v1':JSON.stringify(legacy)});
  assert.equal(migrated.run('feedSource("S-2401", "2026-10-02").audienceFeedback.sourceDate'), '2026-10-02');
  assert.equal(migrated.run('feedSource("S-2401", latestFeedDate).audienceFeedback.summary'), '保留已有反馈修改');
  // 快速捕捉灵感：单一文本框自动保存；选题操作集中在列表之前。
  const capture = boot();
  capture.run('state.biz=["AI漫剧"];navigate(0,1)');
  const topics = capture.nodes.get('page').innerHTML;
  const actions = topics.slice(0,topics.indexOf('cards-grid'));
  assert.ok(actions.includes('新增选题') && actions.includes('AI再来5个'));
  assert.ok(actions.indexOf('new-topic') < actions.indexOf('topic-more'));
  assert.equal((topics.match(/data-action="topic-more"/g)||[]).length,1);
  assert.ok(!topics.includes('topic-more-row'));
  const before = capture.run('db.topics.length');
  await capture.run('action("spark")');
  assert.ok(capture.nodes.get('dialog').innerHTML.includes('sparkHistory'));
  capture.input('sparkBody','  ');
  assert.equal(capture.run('db.sparks.length'),0);
  const idea = '电梯里的影子先走了\n主角停在原地，看见另一个自己。';
  capture.input('sparkBody',idea);
  const note = capture.run('structuredClone(db.sparks[0])');
  assert.equal(note.text,idea);
  assert.equal(capture.run('db.topics.length'),before);
  capture.input('sparkBody',idea+'\n<反转>');
  await capture.run('action("close")');
  const savedCapture = boot(Object.fromEntries(capture.storage));
  assert.equal(savedCapture.run('db.sparks[0].text'),idea+'\n<反转>');
  capture.run('sparkDialog('+JSON.stringify(note.id)+')');
  assert.ok(capture.nodes.get('dialog').innerHTML.includes('&lt;反转&gt;'));
  capture.input('sparkBody',idea+'\n新的结尾');capture.input('sparkBody',idea+'\n再次改写');
  assert.equal(capture.run('db.sparks[0].version'),2);
  assert.equal(capture.run('db.sparks[0].versions.at(-1).text'),idea+'\n<反转>');
  await capture.run('action("close")');
  await capture.run('action("spark")');capture.input('sparkBody','第二条独立灵感');
  assert.equal(capture.run('db.sparks.length'),2);
  await capture.run('action("close")');
  capture.run('navigate(0,1)');
  const batchBefore = capture.run('db.topics.length');
  await capture.run('action("topic-more","AI漫剧")');
  assert.equal(capture.run('db.topics.length'),batchBefore+5);
  capture.run('state.biz=["电商短视频"];navigate(0,1)');
  assert.ok(!capture.nodes.get('page').innerHTML.includes('data-action="topic-more"'));
  const unavailable = boot();
  await unavailable.run('action("spark")');
  unavailable.run('const workingSetItem=localStorage.setItem;localStorage.setItem=()=>{throw new Error("quota")};');
  unavailable.input('sparkBody','存储失败时仍保留文本');
  assert.ok(unavailable.nodes.get('toast').textContent.includes('存储不可用'));
  assert.equal(unavailable.run('draftDirty'),true);
  unavailable.run('localStorage.setItem=workingSetItem');
  unavailable.input('sparkBody','存储失败时仍保留文本');
  assert.equal(unavailable.run('draftDirty'),false,'存储恢复后相同文本可重试');
  for (const business of ['AI漫剧','故事短片','电商短视频']) for(const theme of ['light','dark']) {
    app.run(`state.biz=[${JSON.stringify(business)}];theme=${JSON.stringify(theme)}`);
    for (let m=0;m<4;m++) for(let t=0;t<[3,4,3,5][m];t++) app.run(`navigate(${m},${t})`);
  }
  const workPicker=boot();workPicker.run('state.biz=["AI漫剧"];researchIntake("S-2401")');
  let pickerHtml=workPicker.nodes.get('dialog').innerHTML;
  assert.ok(pickerHtml.includes('id="reviewWorkName"')&&pickerHtml.includes('role="combobox"'),'作品名称支持可输入的下拉选择');
  assert.ok(!pickerHtml.includes('总集数（选填）')&&pickerHtml.includes('当前第几集'),'旧单框替换为总集数和当前集数');
  assert.equal(workPicker.nodes.get('reviewWorkName').value,'开学那天，我被当成传说','自动预填已有来源关联作品');
  const pickerInput=workPicker.nodes.get('reviewWorkName');pickerInput.value='告白';
  workPicker.dispatch('input',{target:pickerInput});
  assert.ok(workPicker.nodes.get('reviewWorkOptions').innerHTML.includes('她与剑的告白'),'输入实时匹配');
  assert.ok(!workPicker.nodes.get('reviewWorkOptions').innerHTML.includes('收纳演示'),'候选只来自漫剧作品');
  assert.equal(workPicker.nodes.get('reviewWorkId').value,'','修改名称清除旧关联');
  workPicker.dispatch('keydown',{target:pickerInput,key:'ArrowDown',preventDefault(){}});
  workPicker.dispatch('keydown',{target:pickerInput,key:'Enter',preventDefault(){}});
  assert.equal(workPicker.nodes.get('reviewWorkId').value,'WORK-A-002','键盘选中稳定作品ID');
  assert.equal(workPicker.nodes.get('reviewWorkName').value,'她与剑的告白');
  const pickerForm={sourceId:'S-2401',sourceDate:'2026-10-04',grade:'A',biz:'AI漫剧',genre:'奇幻',learningTag:['人物塑造'],learningText:'学习人物冲突',workName:'她与剑的告白',workId:'WORK-A-002',totalEpisodes:'80',episodeNumber:'10'};
  workPicker.submit(pickerForm);
  assert.equal(workPicker.run('db.research[0].workId'),'WORK-A-002','人工选择优先于来源预匹配');
  assert.equal(workPicker.run('db.research[0].episodeNumber'),10);
  assert.equal(workPicker.run('db.research[0].humanReviews.at(-1).workName'),'她与剑的告白');
  const workCount=workPicker.run('db.works.length');
  workPicker.submit({...pickerForm,workId:'',workName:'全新的漫剧作品',episodeNumber:'20'});
  assert.equal(workPicker.run('db.works.length'),workCount+1,'输入新作品名称创建作品');
  assert.equal(workPicker.run('db.works.find(work=>work.id===db.research[0].workId).title'),'全新的漫剧作品');
  const beforeInvalid=workPicker.run('db.research[0].humanReviews.length');
  for(const bad of [{episodeNumber:'81'},{episodeNumber:'0'},{episodeNumber:'1.5'},{workName:'',workId:''},{workId:'WORK-S-001'}]){
    workPicker.submit({...pickerForm,...bad});assert.equal(workPicker.run('db.research[0].humanReviews.length'),beforeInvalid,'无效作品或集数不提交');
  }
  workPicker.run('db.works.push({id:"WORK-DUP-1",title:"同名",biz:["AI漫剧"]},{id:"WORK-DUP-2",title:"同名",biz:["AI漫剧"]})');
  workPicker.submit({...pickerForm,workId:'',workName:'同名'});
  assert.ok(workPicker.nodes.get('formError').textContent.includes('下拉菜单'),'同名作品需要按ID选择');
  workPicker.submit({...pickerForm,workId:'',workName:'全新的漫剧作品',episodeNumber:''});
  assert.ok(workPicker.nodes.get('formError').textContent.includes('下拉菜单'),'输入已有名称不能悄悄新增同名作品');
  workPicker.run('save()');const pickerReload=boot(Object.fromEntries(workPicker.storage));
  pickerReload.run('researchIntake("S-2401")');
  assert.equal(pickerReload.nodes.get('reviewWorkName').value,'全新的漫剧作品','刷新后保留人工选定作品');
  assert.equal(pickerReload.nodes.get('reviewEpisodeNumber').value,20);

  const uncertain=boot();
  uncertain.run('db.works.push({id:"WORK-TITLE-DUP",title:"开学那天，我被当成传说",biz:["AI漫剧"]})');
  assert.equal(uncertain.run('suggestedIntakeWork({id:"unknown",title:"开学那天，我被当成传说"},null,"AI漫剧")'),null,'同名线索有歧义不自动选定');
  assert.equal(uncertain.run('suggestedIntakeWork({id:"unknown",title:"开学那天，我被当成传说 第二集"},null,"AI漫剧")'),null,'相似视频标题不自动合并作品');
  assert.equal(uncertain.run('suggestedIntakeWork({id:"unknown",workTitle:"她与剑的告白"},null,"AI漫剧").id'),'WORK-A-002','唯一明确名称线索可演示预匹配');
  uncertain.run('db.works.push({id:"WORK-UNSAFE",title:"<img onerror=alert(1)>",biz:["AI漫剧"]});researchIntake("S-2401");renderIntakeWorkOptions("<img")');
  assert.ok(uncertain.nodes.get('reviewWorkOptions').innerHTML.includes('&lt;img')&&!uncertain.nodes.get('reviewWorkOptions').innerHTML.includes('<img onerror'),'候选作品名称安全转义');
  uncertain.dispatch('keydown',{target:uncertain.nodes.get('reviewWorkName'),key:'Escape',preventDefault(){}});
  assert.equal(uncertain.nodes.get('reviewWorkOptions').hidden,true,'Escape关闭匹配菜单');
  pickerReload.run('db.research[0].status="已完成";researchIntake("S-2401")');
  assert.equal(pickerReload.nodes.get('reviewWorkName').value,'全新的漫剧作品','已有完成报告时仍使用最近人工归属');

  const episodes=boot();episodes.run('state.biz=["AI漫剧"];researchIntake("S-2401")');
  assert.ok(episodes.nodes.get('dialog').innerHTML.includes('id="reviewTotalEpisodes"'),'漫剧研判应包含总集数输入');
  const episodeForm={workName:'开学那天，我被当成传说',workId:'WORK-A-001',sourceId:'S-2401',sourceDate:'2026-10-04',grade:'A',biz:'AI漫剧',genre:'校园',learningTag:['剧情反转'],learningText:''};
  episodes.submit({...episodeForm,totalEpisodes:'80'});
  assert.equal(episodes.run('db.works.find(work=>work.id===db.research[0].workId).totalEpisodes'),80,'总集数保存到作品');
  assert.equal(episodes.run('db.research[0].humanReviews.at(-1).totalEpisodes'),80,'初评保留提交时的总集数');
  episodes.run('researchIntake("S-2401")');
  assert.ok(episodes.nodes.get('dialog').innerHTML.includes('value="80"'),'再次打开回填总集数');
  const episodesSaved=boot(Object.fromEntries(episodes.storage));
  episodesSaved.run('state.biz=["AI漫剧"];workDetail(db.research[0].workId)');
  assert.ok(episodesSaved.nodes.get('page').innerHTML.includes('<span>总集数</span><strong>80'),'刷新后作品仍显示总集数');
  for(const totalEpisodes of ['0','-1','1.5','abc','9007199254740992']){
    const prior=episodes.run('db.research[0].humanReviews.length');episodes.submit({...episodeForm,totalEpisodes});
    assert.equal(episodes.run('db.research[0].humanReviews.length'),prior,'非法总集数不得提交：'+totalEpisodes);
    assert.ok(episodes.nodes.get('formError').textContent.includes('正整数'));
  }
  episodes.submit({...episodeForm,totalEpisodes:''});
  assert.equal(episodes.run('db.works.find(work=>work.id===db.research[0].workId).totalEpisodes'),null,'留空表示未知，不能为0');
  episodes.run('workDetail(db.research[0].workId)');
  assert.ok(episodes.nodes.get('page').innerHTML.includes('80 集'),'旧初评总集数不被清空操作改写');
  episodes.dispatch('change',{target:{id:'reviewBiz',value:'故事短片'}});
  assert.equal(episodes.nodes.get('reviewEpisodeFields').hidden,true);
  assert.equal(episodes.nodes.get('reviewWorkField').hidden,true);
  assert.equal(episodes.nodes.get('reviewTotalEpisodes').disabled,true,'非漫剧不提交总集数字段');
  episodes.dispatch('change',{target:{id:'reviewBiz',value:'AI漫剧'}});
  assert.equal(episodes.nodes.get('reviewEpisodeFields').hidden,false);
  const shortEpisodes=boot();shortEpisodes.run('researchIntake("S-2402")');
  assert.ok(shortEpisodes.nodes.get('dialog').innerHTML.includes('id="reviewEpisodeFields" hidden'),'短片默认隐藏集数');
  shortEpisodes.submit({...episodeForm,sourceId:'S-2402',biz:'故事短片',totalEpisodes:'80'});
  assert.equal(shortEpisodes.run('db.research[0].totalEpisodes'),null,'其他业务不保存漫剧集数');

  const load=boot();load.run('state.biz=["AI漫剧"];navigate(0,1)');
  assert.ok(load.nodes.get('page').innerHTML.includes('题材承重力'),'AI漫剧卡片显示总分');
  const generated=load.run('db.topics.find(topic=>topic.id==="T-DEMO-A-1-1")');
  assert.equal(generated.genreLoadAssessment.dimensions.length,10);
  assert.ok(generated.genreLoadAssessment.dimensions.every(d=>Number.isInteger(d.score)&&d.score>=0&&d.score<=5));
  const total=generated.genreLoadAssessment.dimensions.reduce((sum,d)=>sum+d.score,0);
  assert.ok(load.nodes.get('page').innerHTML.includes(total+' / 50'));
  const scoredCards=load.nodes.get('page').innerHTML.match(/<article class="card topic-card"[\s\S]*?<\/article>/g)||[];
  for(const card of scoredCards.filter(card=>card.includes('genre-load-badge'))){assert.ok(card.indexOf('genre-load-badge')>card.indexOf('class="card-top"')&&card.indexOf('genre-load-badge')<card.indexOf('class="title-button"'),'评分位于卡片左上元信息区');assert.ok(!card.includes('class="tag">AI漫剧</span>'),'删除卡片漫剧业务标签');assert.equal((card.match(/class="genre-load-badge"/g)||[]).length,1,'每卡只显示一次评分');assert.ok(!card.slice(card.indexOf('class="card-foot')).includes('genre-load-badge'),'底栏不再显示评分');}
  assert.ok(!load.nodes.get('page').innerHTML.includes('点击查看十维评分与分析'),'删除评分入口解释文案');

  load.dispatch('keydown',{target:{dataset:{topicId:'T-DEMO-A-1-1'}},key:'Enter',preventDefault(){}});
  for(const text of ['内容承重维度','市场承重维度','情绪承重力','冲突厚度','反差容量','反派承重','反转空间','用户基数','平台调性','投流潜力','复购预期','竞品差异','80集','Logline'])assert.ok(load.nodes.get('dialog').innerHTML.includes(text),'详情展示五维解释：'+text);
  for(const dimension of generated.genreLoadAssessment.dimensions)assert.ok(!load.nodes.get('dialog').innerHTML.includes(dimension.analysis),'紧凑评估不展示逐维分析长段落');
  assert.equal((load.nodes.get('dialog').innerHTML.match(/class="genre-load-row"/g)||[]).length,10,'十维紧凑行保留');
  assert.ok(!load.nodes.get('dialog').innerHTML.includes('内容、市场各五维，每维5分。'),'移除总说明长段落');
  assert.ok(load.nodes.get('dialog').innerHTML.includes('class="genre-load-question"'),'问题置于标题右侧的小字区域');
  assert.ok(!load.nodes.get('dialog').innerHTML.includes('class="genre-load-total"'),'移除独立总分行');
  assert.ok(load.nodes.get('dialog').innerHTML.includes('id="topicAssessmentTotal">'+total+' / 50'),'总分并入评估标题');
  assert.equal((load.nodes.get('dialog').innerHTML.match(/role="meter"/g)||[]).length,10,'十维均有分值条');
  assert.ok(load.run('genreLoadRow(genreLoadDimensions[0],4)').includes('width:80%'),'4分对应80%条长');
  assert.ok(load.run('genreLoadRow(genreLoadDimensions[0],0)').includes('aria-valuenow="0"'),'真实零分可表示');
  assert.ok(!load.run('genreLoadRow(genreLoadDimensions[0])').includes('aria-valuenow'),'未知不能伪装成零分');
  const openedCard=load.nodes.get('dialog').innerHTML;
  await load.run('action("edit-topic","T-DEMO-A-1-1")');
  assert.equal(load.nodes.get('dialog').innerHTML,openedCard,'编辑和点击卡片打开同一详情编辑页');
  for(const name of ['logline','characterSettings','globalRhythm'])assert.ok(openedCard.includes('name="'+name+'"'),'详情有可编辑字段：'+name);
  assert.ok(!openedCard.includes('id="topicProtagonist"')&&!openedCard.includes('id="topicAntagonist"'),'角色设定只有一个自由文本框');
  assert.ok(openedCard.includes('保存并重新评分'),'保存按钮文案');
  assert.equal(load.nodes.get('topicSaveButton').disabled,true,'未编辑时按钮禁用');
  assert.ok(!openedCard.includes('五维各10分')&&!openedCard.includes(' / 10'),'移除旧五维十分制');
  load.input('topicLogline','新的核心情绪与故事冲突');
  assert.equal(load.nodes.get('topicAssessmentResults').hidden,true,'未保存的改动不能继续显示旧评分为有效');
  assert.equal(load.nodes.get('topicAssessmentNotice').hidden,false);
  assert.equal(load.nodes.get('topicAssessmentTotal').textContent,'待重评','编辑后标题不残留旧总分');
  assert.equal(load.nodes.get('topicSaveButton').disabled,false,'编辑后可保存');
  load.input('topicLogline',generated.logline);
  assert.equal(load.nodes.get('topicSaveButton').disabled,true,'改回原文重新禁用');
  assert.equal(load.nodes.get('topicAssessmentResults').hidden,false,'撤销全部编辑恢复有效评分');
  assert.equal(load.run('draftDirty'),false,'撤销全部编辑不提示放弃');

  load.run('navigate(0,1)');await load.run('action("topic-more","AI漫剧")');
  assert.ok(load.run('db.topics.slice(0,5).every(topic=>!!topic.genreLoadAssessment)'),'再生成5个同时提供十维样例评估');
  load.run('state.biz=["故事短片"];navigate(0,1)');
  assert.ok(!load.nodes.get('page').innerHTML.includes('题材承重力'),'80集量表只用于漫剧');
  const loadSnapshot=Object.fromEntries(load.storage);const loadRefresh=boot(loadSnapshot);
  assert.equal(loadRefresh.run('db.topics.find(topic=>topic.id==="T-DEMO-A-1-1").genreLoadAssessment.dimensions[0].score'),generated.genreLoadAssessment.dimensions[0].score,'刷新评分不变');
  load.submit({id:generated.id,title:'修改后的故事',logline:'修改后的核心情绪与冲突',characterSettings:'新主角及目标\n新反派与阵营\n配角可自由增加',globalRhythm:'开局建立冲突，中段升级，末段回收',biz:'AI漫剧',audience:'新观众',sourceId:''},'topicForm');
  assert.equal(load.run('currentGenreLoadAssessment(db.topics.find(topic=>topic.id==="T-DEMO-A-1-1"))'),null,'编辑后旧评分不能作为新版本评分');
  load.run('topicDetail("T-DEMO-A-1-1")');
  assert.ok(load.nodes.get('dialog').innerHTML.includes('新主角及目标')&&load.nodes.get('dialog').innerHTML.includes('新反派与阵营')&&load.nodes.get('dialog').innerHTML.includes('末段回收'),'保存后三部分回填');
  assert.ok(load.nodes.get('dialog').innerHTML.includes('待评分')&&load.nodes.get('dialog').innerHTML.includes('历史内容'));
  assert.equal(load.run('db.topics.find(topic=>topic.id==="T-DEMO-A-1-1").scoreRequests[0].status'),'待评分','修改保存记录评分请求');
  assert.ok(load.run('db.topics.find(topic=>topic.id==="T-DEMO-A-1-1").versions[0].genreLoadAssessment.dimensions.length===10'),'历史版本保存十维分析');
  const oldLoadDb=boot().run('structuredClone(db)');
  oldLoadDb.topics.forEach(topic=>delete topic.genreLoadAssessment);
  oldLoadDb.topics.find(topic=>topic.id==='T-DEMO-A-1-2').summary='用户已有修改';
  const legacyLoad=boot({'content-ui-qa-v1':JSON.stringify(oldLoadDb)});
  assert.ok(legacyLoad.run('!!db.topics.find(topic=>topic.id==="T-DEMO-A-1-1").genreLoadAssessment'),'未改动旧样例补入评分');
  assert.ok(legacyLoad.run('!db.topics.find(topic=>topic.id==="T-DEMO-A-1-2").genreLoadAssessment'),'用户修改内容不套原样例评分');
  const handTopic={id:'T-HAND',title:'手工灵感',summary:'手工正文',biz:['AI漫剧'],version:1,origin:'闪念胶囊',evaluation:'未评价'};
  assert.equal(load.run('genreLoadBadge('+JSON.stringify(handTopic)+')'),'','手工灵感不虚构AI评分');
  load.run('db.topics.find(topic=>topic.id==="T-DEMO-A-2-1").genreLoadAssessment.dimensions[0].score=99');
  assert.equal(load.run('currentGenreLoadAssessment(db.topics.find(topic=>topic.id==="T-DEMO-A-2-1"))'),null,'超出5分不能显示有效总分');

  const editor=boot();const originalTopic=editor.run('structuredClone(db.topics.find(topic=>topic.id==="T-DEMO-A-1-2"))');
  const unchanged={id:originalTopic.id,title:originalTopic.title,logline:originalTopic.logline,characterSettings:editor.run('topicCharactersText(db.topics.find(topic=>topic.id==="T-DEMO-A-1-2"))'),globalRhythm:originalTopic.globalRhythm,biz:'AI漫剧',audience:originalTopic.audience,sourceId:''};
  editor.submit(unchanged,'topicForm');
  assert.equal(editor.run('db.topics.find(topic=>topic.id==="T-DEMO-A-1-2").version'),1,'未修改保存不新增版本或废弃评分');
  assert.ok(editor.run('!!currentGenreLoadAssessment(db.topics.find(topic=>topic.id==="T-DEMO-A-1-2"))'));
  editor.submit({...unchanged,characterSettings:'修改主角 <script>测试</script>\n自由写入配角'},'topicForm');
  assert.equal(editor.run('currentGenreLoadAssessment(db.topics.find(topic=>topic.id==="T-DEMO-A-1-2"))'),null,'仅修改角色也触发待重评');
  editor.run('topicDetail("T-DEMO-A-1-2")');
  assert.ok(editor.nodes.get('dialog').innerHTML.includes('&lt;script&gt;测试&lt;/script&gt;'),'可编辑角色按文本转义');
  assert.equal(editor.run('db.topics.find(topic=>topic.id==="T-DEMO-A-1-2").versions[0].characters.protagonist'),originalTopic.characters.protagonist,'旧角色与节奏快照保留');
  const savedEdit=editor.run('structuredClone(db.topics.find(topic=>topic.id==="T-DEMO-A-1-2"))');
  assert.equal(savedEdit.scoreRequests.length,1,'一次修改只创建一个评分请求');
  assert.equal(savedEdit.scoreRequests[0].input.characterSettings,savedEdit.characterSettings,'评分请求绑定自由角色文本');
  editor.submit({...unchanged,characterSettings:savedEdit.characterSettings},'topicForm');
  assert.equal(editor.run('db.topics.find(topic=>topic.id==="T-DEMO-A-1-2").scoreRequests.length'),1,'相同内容重复提交不重建评分请求');
  const editorReload=boot(Object.fromEntries(editor.storage));editorReload.run('topicDetail("T-DEMO-A-1-2")');
  assert.equal(editorReload.run('db.topics.find(topic=>topic.id==="T-DEMO-A-1-2").scoreRequests[0].topicVersion'),savedEdit.version,'刷新保留评分请求与输入版本');
  assert.equal(editorReload.nodes.get('topicSaveButton').disabled,true,'保存后重新打开默认禁用');
  editorReload.input('topicCharacterSettings','');
  assert.equal(editorReload.nodes.get('topicSaveButton').disabled,false,'清空角色也是有效编辑');
  editorReload.input('topicCharacterSettings',savedEdit.characterSettings);
  assert.equal(editorReload.nodes.get('topicSaveButton').disabled,true,'自由角色全文恢复后禁用');
  editorReload.input('bizInput','故事短片');
  assert.equal(editorReload.nodes.get('topicSaveButton').disabled,false,'业务修改也启用按钮');
  assert.equal(editorReload.nodes.get('topicAssessmentScope').hidden,true,'其他业务不显示漫剧量表');
  editorReload.input('bizInput','AI漫剧');
  assert.equal(editorReload.nodes.get('topicSaveButton').disabled,true,'业务改回基线后禁用');
  assert.ok(editorReload.nodes.get('dialog').innerHTML.includes('修改主角'),'刷新保留角色编辑');
  assert.ok(editor.run('topicText(db.topics.find(topic=>topic.id==="T-DEMO-A-1-2"))').includes('## 全局节奏'),'复制导出包含三个详情部分');
  const oldCharactersDb=boot().run('structuredClone(db)');const oldCharactersTopic=oldCharactersDb.topics.find(topic=>topic.id==='T-DEMO-A-1-1');
  const oldInput=oldCharactersTopic.genreLoadAssessment.input;
  delete oldInput.characterSettings;oldInput.protagonist=oldCharactersTopic.characters.protagonist;oldInput.antagonist=oldCharactersTopic.characters.antagonist;
  const oldCharacters=boot({'content-ui-qa-v1':JSON.stringify(oldCharactersDb)});oldCharacters.run('topicDetail("T-DEMO-A-1-1")');
  assert.ok(oldCharacters.run('!!currentGenreLoadAssessment(db.topics.find(topic=>topic.id==="T-DEMO-A-1-1"))'),'合并旧角色字段不废弃内容相同的有效评分');
  const mergedCharacters=oldCharacters.nodes.get('topicCharacterSettings').value;
  assert.ok(mergedCharacters.includes('主角：')&&mergedCharacters.includes('反派：'),'旧角色完整合并回填');
  oldCharacters.submit({id:oldCharactersTopic.id,title:oldCharactersTopic.title,logline:oldCharactersTopic.logline,characterSettings:'',globalRhythm:oldCharactersTopic.globalRhythm,biz:'AI漫剧',audience:oldCharactersTopic.audience},'topicForm');
  assert.equal(oldCharacters.run('topicCharactersText(db.topics.find(topic=>topic.id==="T-DEMO-A-1-1"))'),'','清空自由角色不会被旧角色自动填回');
  assert.ok(!oldCharacters.run('topicText(db.topics.find(topic=>topic.id==="T-DEMO-A-1-1"))').includes(oldCharactersTopic.characters.protagonist),'导出读取编辑后的自由文本');
  const obsolete=boot().run('structuredClone(db)');const obsoleteTopic=obsolete.topics.find(topic=>topic.id==='T-DEMO-A-1-1');
  delete obsoleteTopic.logline;delete obsoleteTopic.characters;delete obsoleteTopic.globalRhythm;
  obsoleteTopic.genreLoadAssessment={schemaVersion:'genre-load-v1',dimensions:[{score:10}],input:{summary:obsoleteTopic.summary}};
  const upgraded=boot({'content-ui-qa-v1':JSON.stringify(obsolete)});upgraded.run('topicDetail("T-DEMO-A-1-1")');
  assert.equal(upgraded.run('db.topics.find(topic=>topic.id==="T-DEMO-A-1-1").genreLoadAssessment.schemaVersion'),'genre-load-v2','旧未改动样例重建新量表，不直接换算旧分数');
  assert.ok(!upgraded.nodes.get('dialog').innerHTML.includes(' / 10'),'旧十分制不混入新页面');
  capture.run('sparkDialog('+JSON.stringify(note.id)+')');capture.input('sparkBody','新版独立闪念');
  assert.equal(capture.run('db.sparks.find(n=>n.id==='+JSON.stringify(note.id)+').text'),'新版独立闪念');

  const library=boot();library.run('state.biz=["AI漫剧"];navigate(1,0);state.stage="成片";render()');
  const libraryPage=library.nodes.get('page').innerHTML;
  assert.ok(libraryPage.includes('page-actions actions-left'),'人工新增在左侧');
  assert.ok(!libraryPage.includes('class="filter-line"'),'不展示适用环节筛选');
  assert.ok(libraryPage.includes('K-031'),'隐藏的旧环节状态不影响结果');
  for(const category of ['题材库','金句库','爽点库','翻车点','DNA经典案例'])assert.ok(libraryPage.includes(category),'知识分类：'+category);
  library.run('knowledgeCategories.forEach((category,i)=>db.knowledge.push({id:"CATEGORY-"+i,title:category+"样例",summary:"分类内容",category,biz:["AI漫剧"],stage:"脚本",status:"已入库",type:"内容原子",version:1}));db.knowledge.push({id:"PRIVATE-K",title:"不能公开的候选",category:"金句库",biz:["AI漫剧"],stage:"脚本",status:"待AI审核",version:1});render()');
  await library.run('action("knowledge-category","金句库")');
  assert.ok(library.nodes.get('page').innerHTML.includes('CATEGORY-1')&&!library.nodes.get('page').innerHTML.includes('CATEGORY-2'),'知识分类筛选生效');
  assert.ok(!library.nodes.get('page').innerHTML.includes('不能公开的候选'),'分类不放出未审核候选');
  library.run('knowledgeForm()');assert.ok(library.nodes.get('dialog').innerHTML.includes('value="金句库" selected'),'当前分类带入新增');
  library.submit({id:'',title:'一句新的金句',category:'金句库',biz:'AI漫剧',stage:'脚本',summary:'测试文字',evidence:'用户输入，需核验'},'knowledgeForm');
  const createdKnowledge=library.run('structuredClone(db.knowledge[0])');
  assert.equal(createdKnowledge.category,'金句库');assert.equal(createdKnowledge.status,'待AI审核','人工新增仍走双审');
  library.run('knowledgeForm(db.knowledge[0].id)');
  library.submit({id:createdKnowledge.id,title:'修订的金句',category:'爽点库',biz:'AI漫剧',stage:'脚本',summary:'修订内容',evidence:'新证据'},'knowledgeForm');
  assert.equal(library.run('db.knowledge[0].versions[0].category'),'金句库','修订保留旧分类');
  const libraryReload=boot(Object.fromEntries(library.storage));
  assert.equal(libraryReload.run('db.knowledge[0].category'),'爽点库','刷新保留修改后的分类');
  assert.equal(libraryReload.run('db.knowledge.find(item=>item.id==="K-031").category'),undefined,'旧知识不被猜测归类');
  const beforeBadCategory=library.run('db.knowledge.length');
  library.submit({id:'',title:'未知分类',category:'随便造的分类',biz:'AI漫剧',stage:'脚本',summary:'内容',evidence:'证据'},'knowledgeForm');
  assert.equal(library.run('db.knowledge.length'),beforeBadCategory,'仅允许五个暂定分类');

  await library.run('action("biz","故事短片")');assert.equal(library.run('state.knowledgeCategory'),'全部','切换业务清除局部分类');

  const works = boot();
  works.run('state.biz=["AI漫剧"];navigate(2,0)');
  const workPage = works.nodes.get('page').innerHTML;
  assert.equal((workPage.match(/class="work-card"/g)||[]).length,7,'漫剧应以七部作品呈现，而非逐任务列出');
  assert.ok(!workPage.includes('<table')&&!workPage.includes('适用环节'),'内容研判不使用表格或环节筛选');
  assert.ok(workPage.includes('处理中 <span>')&&workPage.includes('需处理 <span>')&&workPage.includes('已有报告 <span>'),'多种状态按作品独立汇总');
  assert.ok(workPage.includes('id="workGenreFilter"'),'搜索行包含题材筛选');
  works.dispatch('change',{target:{id:'workGenreFilter',value:'悬疑'}});
  assert.equal((works.nodes.get('page').innerHTML.match(/class="work-card"/g)||[]).length,3,'复合题材可按单个标签筛选');
  works.run('state.query="DEMO_CREATOR_003";render()');
  assert.equal((works.nodes.get('page').innerHTML.match(/class="work-card"/g)||[]).length,1,'博主 ID 搜索不区分大小写并与题材组合');
  await works.run('action("work-status","已有报告")');
  assert.ok(works.nodes.get('page').innerHTML.includes('没有匹配的作品'),'状态、题材和关键词共同筛选');
  await works.run('action("biz","故事短片")');
  assert.equal(works.run('state.workGenre'),'全部题材','切换业务清除旧题材');
  assert.ok(!works.nodes.get('page').innerHTML.includes('value="科幻"'),'筛选选项仅来自当前业务');
  works.run('state.biz=["AI漫剧"];navigate(2,0);db.research.find(task=>task.workId==="WORK-A-004").sourceSnapshot={creatorId:"frozen_author_44",creator:"夜行人"};state.query="frozen_author_44";render()');
  assert.ok(works.nodes.get('page').innerHTML.includes('长夜无名'),'可按已冻结的来源博主 ID 搜索');
  works.run('state.query="夜行人";render()');
  assert.ok(works.nodes.get('page').innerHTML.includes('长夜无名'),'支持博主名称搜索');
  works.run('state.query="";render()');
  const sampleAssets=works.run('seed.works.flatMap(work=>[work.coverUrl,work.frameUrl].filter(Boolean))');
  assert.equal(sampleAssets.length,4,'原三张演示图片及新作品复用封面');
  for(const asset of sampleAssets){const bytes=fs.readFileSync(require('path').join(__dirname,asset));assert.equal(bytes.subarray(1,4).toString(),'PNG','图片文件存在且为 PNG');}
  works.run('db.research.unshift({id:"C-EXTRA",workId:"WORK-A-001",title:"开学那天 · 第2集",biz:["AI漫剧"],status:"待分析",version:1});render()');
  assert.equal((works.nodes.get('page').innerHTML.match(/class="work-card"/g)||[]).length,7,'同一作品新增单集任务不能增加作品卡');
  await works.run('action("work-detail","WORK-A-001")');
  assert.ok(works.nodes.get('page').innerHTML.includes('C-EXTRA'),'作品详情应列出关联任务');
  const legacyData=boot().run('structuredClone(db)');delete legacyData.works;delete legacyData.researchWorkSamplesVersion;
  legacyData.research=legacyData.research.slice(0,3).map(({workId,...task})=>task);
  const legacyWorks=boot({'content-ui-qa-v1':JSON.stringify(legacyData)});
  assert.ok(legacyWorks.run('db.works.find(work=>work.id==="WORK-A-001").coverUrl'),'旧存储自动补入样例封面');
  assert.equal(legacyWorks.run('db.research.find(task=>task.id==="C-083").workId'),'WORK-A-001','旧任务按来源 ID 关联作品');
  assert.equal(legacyWorks.run('db.research.filter(task=>task.id.startsWith("C-08")).length'),8,'旧存储只补一次演示任务');
  assert.ok(works.run('workCard(db.works.find(work=>work.id==="WORK-A-006"))').includes('btn primary'),'可查看报告应有强调样式');
  const thumbs=boot();
  thumbs.run(`state.module=2;state.tab=0;
    const thumbClasses=new Set();
    const thumbBox={dataset:{workThumbnail:'WORK-A-001'},isConnected:true,classList:{add(name){thumbClasses.add(name)},remove(name){thumbClasses.delete(name)}},append(image){this.image=image}};
    document.querySelectorAll=()=>[thumbBox];
    document.createElement=tag=>({tag,remove(){this.removed=true},removeAttribute(){},load(){}});
    const thumbWork=db.works.find(work=>work.id==='WORK-A-001');
    thumbWork.coverUrl='https://example.com/cover.jpg';thumbWork.frameUrl='https://example.com/frame.jpg';
    hydrateWorkThumbnails();`);
  assert.equal(thumbs.run('thumbBox.image.src'),'https://example.com/cover.jpg');
  thumbs.run('thumbBox.image.onerror()');
  assert.equal(thumbs.run('thumbBox.image.src'),'https://example.com/frame.jpg','封面失败应回退视频帧');
  thumbs.run('thumbBox.image.onload()');thumbs.flushTimers();
  assert.equal(thumbs.run('thumbClasses.has("has-image")'),true,'成功图片不能被旧超时回退');
  thumbs.run('clearWorkThumbnails();workThumbnailCache.clear();thumbClasses.clear();hydrateWorkThumbnails();thumbBox.image.onerror();thumbBox.image.onerror()');
  assert.equal(thumbs.run('thumbClasses.has("is-loading")'),false,'全部图片失败后应显示文字');
  assert.equal(thumbs.run('thumbBox.image.removed'),true,'失败图片不保留破图图标');
  assert.equal(thumbs.run('workMediaUrl("javascript:alert(1)")'),'');
  thumbs.run(`clearWorkThumbnails();thumbClasses.clear();delete thumbWork.coverUrl;delete thumbWork.frameUrl;thumbWork.mediaUrl='https://example.com/work.mp4';
    let testVideo;
    document.createElement=tag=>tag==='canvas'?{getContext:()=>({drawImage(){}}),toDataURL:()=> 'data:image/jpeg;base64,frame'}:tag==='video'?(testVideo={videoWidth:1280,videoHeight:720,duration:3,removeAttribute(){},load(){}}):{remove(){this.removed=true}};
    hydrateWorkThumbnails();testVideo.onloadeddata();testVideo.onseeked();`);
  assert.equal(thumbs.run('thumbBox.image.src'),'data:image/jpeg;base64,frame','无封面时可从直接视频文件截帧');
  thumbs.run('clearWorkThumbnails()');
  console.log('PASS: unified editable topic detail, ten-dimension scores/migration/version history, work combobox/pre-match/manual links/new works/episode validation, human reviews in work/report, revision history/persistence/isolation, work cards/status/grouping/legacy links, cover/frame/text fallbacks, report emphasis, overflow hover, feedback snapshots, spark autosave, and 15 workspaces in three businesses/two themes.');
})().catch(error => {console.error(error);process.exitCode = 1;});

module.exports={boot};
