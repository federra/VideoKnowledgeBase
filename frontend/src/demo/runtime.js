// Generated from approved Demo. SHA-256: 2fce76c1547e11dfbbadb4cdcaba0bab94732c33ca18a367f1e80df9dec6cf0d
// Transitional DOM renderer: no real API, authentication or server-side writes.
// Run pnpm demo:sync after explicitly approving a changed Demo baseline.
export function createDemoRuntime({onChange, renderWorkspace}) {
 const controller = new AbortController();
 const pendingTimers = new Set();
 const downloadUrls = new Set();
 function createDownloadUrl(blob){const url=URL.createObjectURL(blob);downloadUrls.add(url);return url}
 function revokeDownloadUrl(url){downloadUrls.delete(url);URL.revokeObjectURL(url)}
 const nativeTimeout = window.setTimeout.bind(window);
 const nativeClearTimeout = window.clearTimeout.bind(window);
 const setTimeout = (callback, delay) => {
   const id = nativeTimeout(() => { pendingTimers.delete(id); callback(); }, delay);
   pendingTimers.add(id);return id;
 };
 const clearTimeout = id => {pendingTimers.delete(id);nativeClearTimeout(id)};
 function listen(target,type,listener,options){
   const isolatedListener = event => {
     if (target === document && event.target?.closest?.('[data-real-workspace]')) return;
     listener(event);
   };
   target.addEventListener(type,isolatedListener,{...(typeof options==='boolean'?{capture:options}:options),signal:controller.signal});
 }
 function publish(){onChange({
   module:state.module,tab:state.tab,business:state.biz[0],theme,
   workTitle:selectedWork()?.title||'',workId:state.workId,
   sparkCount:db.sparks.length
 })}

'use strict';
const icons={radar:'<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><path d="m12 12 7-7M12 3v2M3 12h2M12 19v2M19 12h2"/>',book:'<path d="M3 4h6a4 4 0 0 1 3 2 4 4 0 0 1 3-2h6v15h-6a4 4 0 0 0-3 2 4 4 0 0 0-3-2H3zM12 6v15"/>',research:'<path d="M9 3h6M10 3v6l-6 10a1 1 0 0 0 1 2h14a1 1 0 0 0 1-2L14 9V3M8 14h8"/>',settings:'<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="8" cy="6" r="2" fill="var(--canvas)"/><circle cx="16" cy="12" r="2" fill="var(--canvas)"/><circle cx="10" cy="18" r="2" fill="var(--canvas)"/>',search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',plus:'<path d="M12 5v14M5 12h14"/>',arrow:'<path d="M5 12h14m-5-5 5 5-5 5"/>',out:'<path d="M14 3h7v7m0-7-11 11M10 5H4v15h15v-6"/>',close:'<path d="m6 6 12 12M6 18 18 6"/>',info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7v1"/>',check:'<path d="m5 12 4 4L19 6"/>',download:'<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',clock:'<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',moon:'<path d="M20.5 15.2A8.6 8.6 0 0 1 8.8 3.5 8.8 8.8 0 1 0 20.5 15.2Z"/>',sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/>',spark:'<path d="M8 3h8a5 5 0 0 1 0 10H8A5 5 0 0 1 8 3Zm0 10h8a5 5 0 0 1 0 10H8a5 5 0 0 1 0-10Z"/><path d="M8 13h8M12 6v4m-2-2h4"/>',file:'<path d="M13 3H5v18h14V9zm0 0v6h6M8 13h8M8 17h6"/>'};
const icon=n=>`<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${icons[n]||icons.file}</svg>`;
const navSolidIcons={
  radar:'<path fill-rule="evenodd" d="M12 3a9 9 0 1 0 9 9 9 9 0 0 0-9-9Zm0 6a3 3 0 1 0 3 3 3 3 0 0 0-3-3Z"/><circle cx="12" cy="12" r="1.5"/><path d="m11 12 8-9 2 2-9 8Z"/>',
  book:'<path d="M3 3h5a6 6 0 0 1 3 1v17a7 7 0 0 0-3-1H3a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Zm13 0h5a1 1 0 0 1 1 1v15a1 1 0 0 1-1 1h-5a7 7 0 0 0-3 1V4a6 6 0 0 1 3-1Z"/>',
  research:'<path fill-rule="evenodd" d="M9 2a1 1 0 0 0 0 2v5L3.4 19a2 2 0 0 0 1.8 3h13.6a2 2 0 0 0 1.8-3L15 9V4a1 1 0 0 0 0-2Zm2 2h2v5.5l2.5 4.5h-7L11 9.5ZM8 17a1 1 0 1 0 2 0 1 1 0 0 0-2 0Zm5 2a1 1 0 1 0 2 0 1 1 0 0 0-2 0Z"/>',
  settings:'<rect x="3" y="4.5" width="18" height="3" rx="1.5"/><circle cx="8" cy="6" r="3.5"/><rect x="3" y="10.5" width="18" height="3" rx="1.5"/><circle cx="16" cy="12" r="3.5"/><rect x="3" y="16.5" width="18" height="3" rx="1.5"/><circle cx="10" cy="18" r="3.5"/>'
};
const navIcon=(n,active)=>active?`<svg class="icon nav-solid" viewBox="0 0 24 24" aria-hidden="true">${navSolidIcons[n]}</svg>`:icon(n);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const modules=[{name:'情报局',icon:'radar',tabs:['情报流','选题卡','待生产']},{name:'藏经阁',icon:'book',tabs:['知识浏览','入库处理','审核队列','回收站']},{name:'研判室',icon:'research',tabs:['内容研判','发布复盘','规律验证']},{name:'控制台',icon:'settings',tabs:['采集配置','处理配置','评价标准','权限管理','运行状态','模型配置']}];
const navOrder=[0,2,1,3];
const businesses=['AI漫剧','故事短片','电商短视频'];
const seed={intel:[
{id:'S-2401',title:'“身份错位”开场：让观众先知道一个秘密',summary:'三段开场样本都把身份信息先交给观众，再让角色进入误会。值得观察的是信息差如何推动第一轮冲突，而非单纯增加反转。',biz:['AI漫剧'],source:'短剧观察',type:'案例拆解',time:'09:42',tag:'叙事结构',evidence:'样本片段 00:00–00:08：主角收起工牌，转身进入面试间。观众知道身份，面试官尚不知情。'},
{id:'S-2402',title:'一个空着的座位，如何成为故事的情绪支点',summary:'用日常物件承载人物缺席，让信息在动作里出现。可作为亲情、返乡与告别主题的视听表达参考。',biz:['故事短片'],source:'影像手记',type:'创作观察',time:'09:18',tag:'情绪表达',evidence:'样本文本第 3 段：家人习惯性多摆了一双筷子，随后停住。'},
{id:'S-2403',title:'先展示使用难题，再解释收纳产品的卖点',summary:'小空间、杂物堆叠与取用不便是三种不同痛点。样本将具体场景前置，但缺少同口径转化数据，暂不能认定为有效增长方法。',biz:['电商短视频'],source:'消费内容研究',type:'商品案例',time:'08:56',tag:'场景痛点',evidence:'样本 00:02–00:06 展示取用困难，00:07 才出现产品。暂无转化实绩。'},
{id:'S-2404',title:'“善意被误解”题材，如何避免人物动机悬空',summary:'动机线索先于冲突出现，可以减少结尾解释负担。适合研究短时长叙事中的铺垫与回收。',biz:['AI漫剧'],source:'故事实验室',type:'方法讨论',time:'08:30',tag:'人物动机',evidence:'样本第 2、5、8 段分别出现铺垫、误解和回收。'},
{id:'S-2405',title:'商品演示里的“前后对比”，需要保留哪些条件',summary:'拍摄角度、使用时间与环境不同，会让对比失去可信度。可提炼为电商内容评价中的事实检查项。',biz:['电商短视频'],source:'消费内容研究',type:'行业信息',time:'昨天 17:20',tag:'真实性',evidence:'原始资料未完整获取，请补充截图或全文。',failed:true}],
topics:[{id:'T-103',title:'他来应聘，却被自己公司的面试官淘汰',summary:'用身份信息差建立冲突；第一轮反转后，把问题转向公司的真实用人标准。',biz:['AI漫剧'],sourceId:'S-2401',audience:'偏好职场反转的短剧观众',status:'候选',version:1,evaluation:'已评价',origin:'AI选题',createdAt:'2026-09-30T08:40:00+08:00',history:['v1 · AI生成，评价已完成']},{id:'T-102',title:'妈妈每天多留的一副碗筷',summary:'从一张饭桌切入，通过三次相似动作的变化，让人物关系自然显露。',biz:['故事短片'],sourceId:'S-2402',audience:'关注家庭关系的观众',status:'候选',version:2,evaluation:'待重评',origin:'人工编辑',createdAt:'2026-09-30T08:25:00+08:00',history:['v1 · AI生成','v2 · 人工修改，旧评价不适用']},{id:'T-101',title:'30厘米的厨房缝隙，能解决什么问题',summary:'围绕一个窄缝空间演示真实取用过程，验证尺寸与承重后再表达卖点。',biz:['电商短视频'],sourceId:'S-2403',audience:'小户型租房人群',status:'待生产',version:1,evaluation:'已评价',origin:'AI选题',createdAt:'2026-09-30T08:10:00+08:00',history:['v1 · 人工确认进入待生产池']}],
knowledge:[{id:'K-031',title:'以可观察的动作建立人物动机',summary:'在人物作出关键选择之前，提供一个能被观众直接观察的行为线索。避免在结尾集中用旁白解释动机。',biz:['AI漫剧','故事短片'],stage:'脚本',type:'方法规则',status:'已入库',version:2,ai:'通过',sourceId:'S-2404',evidence:'来源：故事实验室，样本文本第 2、5、8 段。适用短时长关系叙事；样本不足以证明市场效果。'},
{id:'K-032',title:'商品对比演示应保持使用条件一致',summary:'记录对比双方的拍摄角度、环境、使用时间和商品规格，缺失条件时标记证据不足。',biz:['电商短视频'],stage:'成片',type:'方法规则',status:'已入库',version:1,ai:'通过',sourceId:'S-2405',evidence:'人工提供的对比检查清单 v1。审核范围是表达真实性，不证明转化提升。'},
{id:'K-033',title:'用日常物件表达人物的缺席',summary:'通过物件的重复出现和使用动作变化，传递关系的变化。',biz:['故事短片'],stage:'脚本',type:'案例经验',status:'待人工审核',version:1,ai:'通过',sourceId:'S-2402',evidence:'影像手记第 3 段；仅一个案例，尚未验证通用效果。'},
{id:'K-034',title:'前三秒使用身份反转一定能提高完播率',summary:'候选结论的因果措辞超出了来源支持范围，需要补充对照样本或缩小结论。',biz:['AI漫剧'],stage:'选题',type:'方法规则',status:'待AI审核',version:1,ai:'需修订',sourceId:'S-2401',evidence:'只观察到叙事结构，没有同窗口完播数据。'}],
works:[
 {id:'WORK-A-001',coverUrl:'assets/work-samples/campus-cover.png',creatorId:'demo_creator_001',title:'开学那天，我被当成传说',biz:['AI漫剧'],genre:'都市奇幻 · 校园',sourceId:'S-2401',collectedCount:8,analyzedCount:0,totalEpisodes:null},
 {id:'WORK-A-002',coverUrl:'assets/work-samples/sword-cover.png',creatorId:'demo_creator_002',title:'她与剑的告白',biz:['AI漫剧'],genre:'奇幻 · 爱情',collectedCount:5,analyzedCount:0,totalEpisodes:null},
 {id:'WORK-A-003',frameUrl:'assets/work-samples/ocean-frame.png',creatorId:'demo_creator_003',title:'深渊回声',biz:['AI漫剧'],genre:'科幻 · 悬疑',collectedCount:12,analyzedCount:4,totalEpisodes:null},
 {id:'WORK-A-004',title:'长夜无名',biz:['AI漫剧'],genre:'悬疑 · 都市',collectedCount:4,analyzedCount:1,totalEpisodes:null},
 {id:'WORK-A-005',title:'星落于你',biz:['AI漫剧'],genre:'青春 · 治愈',collectedCount:3,analyzedCount:0,totalEpisodes:null},
 {id:'WORK-A-006',title:'山河不语',biz:['AI漫剧'],genre:'历史 · 权谋',collectedCount:6,analyzedCount:2,totalEpisodes:null},
 {id:'WORK-S-001',title:'空着的座位',biz:['故事短片'],genre:'亲情 · 告别',sourceId:'S-2402',collectedCount:1,analyzedCount:1},
 {id:'WORK-E-001',title:'收纳演示',biz:['电商短视频'],genre:'家居 · 收纳',sourceId:'S-2403',collectedCount:1,analyzedCount:0}],
research:[{id:'C-081',workId:'WORK-S-001',title:'空着的座位 · 成片 v2',biz:['故事短片'],status:'已完成',sourceId:'S-2402',version:2,lastAnalyzedAt:'2026-10-07 10:20'},{id:'C-082',workId:'WORK-E-001',title:'收纳演示 · 成片 v1',biz:['电商短视频'],status:'证据不足',sourceId:'S-2403',version:1,lastAnalyzedAt:'2026-10-04 16:08'},{id:'C-083',workId:'WORK-A-001',title:'身份错位 · 脚本 v1',biz:['AI漫剧'],status:'待研判',sourceId:'S-2401',version:1},
 {id:'C-084',workId:'WORK-A-002',title:'她与剑的告白 · 成片 v1',biz:['AI漫剧'],status:'待分析',sourceId:'人工提交',version:1},
 {id:'C-085',workId:'WORK-A-003',title:'深渊回声 · 成片 v1',biz:['AI漫剧'],status:'分析中',sourceId:'人工提交',version:1,lastAnalyzedAt:'2026-10-06 18:35'},
 {id:'C-086',workId:'WORK-A-004',title:'长夜无名 · 成片 v1',biz:['AI漫剧'],status:'解析失败',sourceId:'人工提交',version:1,lastAnalyzedAt:'2026-10-05 14:12'},
 {id:'C-087',workId:'WORK-A-005',title:'星落于你 · 成片 v1',biz:['AI漫剧'],status:'证据不足',sourceId:'人工提交',version:1,lastAnalyzedAt:'2026-10-04 16:08'},
 {id:'C-088',workId:'WORK-A-006',title:'山河不语 · 成片 v1',biz:['AI漫剧'],status:'已完成',sourceId:'人工提交',version:1,lastAnalyzedAt:'2026-10-03 11:26'}],
sources:[{id:'SRC-01',name:'短剧观察 · 样本来源',type:'定向采集',use:'情报与知识',freq:'每 2 小时',status:'启用',last:'09:42 · 演示成功'},{id:'SRC-02',name:'影像手记 · 样本来源',type:'订阅源',use:'情报',freq:'每日 09:00',status:'启用',last:'09:18 · 演示成功'},{id:'SRC-03',name:'消费内容研究 · 样本来源',type:'定向采集',use:'情报与知识',freq:'每 4 小时',status:'启用',last:'08:56 · 解析失败'}],publications:[{id:'P-021',title:'空着的座位',content:'C-081',version:2,biz:['故事短片'],likes:1260,comments:86,shares:null,saves:214,window:'发布后 24 小时',source:'手工录入',history:[]}],handoffs:[],retries:[]};
const topicIdeas={
 'AI漫剧':[
  ['倒计时只剩三分钟，配角先看见结局','配角提前看见主角失败的片段，必须在三分钟内改变一个微小选择。','偏好悬疑反转的漫剧观众'],
  ['失忆反派记得所有人的秘密','反派忘了自己的身份，却记得每个人试图隐瞒的事。','偏好人物博弈的漫剧观众'],
  ['城市停电后，影子开始替人说话','一次停电让人物的影子说出未出口的真相，关系在同一夜被迫重组。','偏好都市奇幻的漫剧观众'],
  ['她拿到了未来自己的辞职信','主角收到未来寄来的辞职信，必须查清哪次妥协改变了职业选择。','偏好职场成长的漫剧观众'],
  ['假面舞会上的身份互换','两个身份相反的人在舞会后被所有人误认，只能合作找出背后的安排。','偏好身份错位的漫剧观众']
 ],
 '故事短片':[
  ['最后一班公交车上的空座','司机每天为同一位缺席的乘客留座，直到有人问起原因。','关注城市情感的观众'],
  ['父亲学会发送语音的那一天','一条反复录制的语音，让父女重新理解彼此沉默的原因。','关注家庭关系的观众'],
  ['雨伞归还处','社区里总有人归还一把旧伞，伞上的字条串起几段互不相识的善意。','喜欢生活故事的观众'],
  ['夜班便利店的第二张收据','店员发现每天多出一张收据，顺着小票找到一个被忽略的邻居。','喜欢温情悬疑的观众'],
  ['搬家时没带走的植物','一盆植物在几位住户之间传递，让他们逐渐看见彼此的生活。','关注都市独居的观众']
 ]
};
const genreLoadDimensions=[
 {key:'emotion',group:'content',name:'情绪承重力',question:'能否承载Logline的核心情绪？'},
 {key:'conflict',group:'content',name:'冲突厚度',question:'80集要的冲突够不够多？'},
 {key:'contrast',group:'content',name:'反差容量',question:'能容纳多少种反差萌？'},
 {key:'antagonist',group:'content',name:'反派承重',question:'反派阵营能否撑80集？'},
 {key:'twist',group:'content',name:'反转空间',question:'能埋多少波钩子？'},
 {key:'audience',group:'market',name:'用户基数',question:'目标用户群体够不够大？'},
 {key:'platform',group:'market',name:'平台调性',question:'与主投放平台是否匹配？'},
 {key:'acquisition',group:'market',name:'投流潜力',question:'CPI能否做到合理水平？'},
 {key:'sequel',group:'market',name:'复购预期',question:'观众会不会期待续作？'},
 {key:'differentiation',group:'market',name:'竞品差异',question:'与同类爆款的差异化？'}
];
const topicBlueprintSamples=[
 ['能预见主角失败的配角，必须在三分钟内改变一个关键选择，却发现每次救场都会带来新的代价。','预见失败片段的配角：想救下主角，却习惯依赖预知而忽略他人的选择。','维护既定结局的幕后势力：通过误导与阻拦迫使事件沿原轨迹发生；具体身份待补充。','1—10集：建立预知规则与第一次救场。\n11—30集：改变选择的代价浮现，人物关系分化。\n31—60集：追查结局背后的力量，预知可靠性受到挑战。\n61—80集：主角主动承担选择，回收因果与牺牲。'],
 ['失去自我记忆的反派却记得所有人的秘密，他必须在各方追查中找到真实身份，并决定是否继续利用这些秘密。','失忆的反派：渴望找回自己，擅长洞察他人，却无法判断自己的过去是否可信。','秘密的受益者与旧阵营：一方试图利用他，另一方试图让其永远失忆；动机需在大纲中细化。','1—10集：秘密能力暴露，引来追查。\n11—30集：用秘密交换线索，建立脆弱联盟。\n31—60集：身份与阵营层层翻转，旧行为的代价显现。\n61—80集：确认自我立场，回收记忆与秘密来源。'],
 ['城市停电后，每个人的影子都开始说出未出口的真相，一名隐瞒关键秘密的人必须查明规则，阻止关系与城市一起失控。','隐瞒关键秘密的普通人：想保护重要关系，却不得不学习坦诚承担后果。','利用影子泄密操纵关系的幕后力量：目标与规则来源尚待补足。','1—10集：停电与泄密建立异常规则。\n11—30集：秘密改变关系，人物寻找控制方法。\n31—60集：追查操纵者，规则代价与关键秘密揭晓。\n61—80集：在坦诚与保护之间作出选择，回收停电原因。'],
 ['收到未来自己辞职信的职场新人，必须找到改变职业命运的那次妥协，同时面对每次改选带来的现实代价。','职场新人：想证明能力，害怕失去认可，习惯用妥协换取暂时安稳。','维护既有利益的管理层与竞争者：利用考核和资源分配阻止改变；具体阵营尚待补充。','1—10集：收到信件，识别第一个妥协节点。\n11—30集：主动改变工作选择，关系和资源受到冲击。\n31—60集：追查未来寄信原因，短期成功与长期代价对撞。\n61—80集：建立自己的职业标准，回收信件与未来变化。'],
 ['两个身份相反的人在假面舞会后被所有人误认，只能在扮演彼此的过程中合作寻找幕后安排，并重新选择真实的自己。','身份相反的两位合作者：分别追求认可与自由，擅长的能力恰好能补足对方的困境。','操纵误认的利益方：利用身份交换改变权力与关系；幕后目的需进一步明确。','1—10集：互换误认发生，两人被迫合作。\n11—30集：适应错位关系，各自付出代价。\n31—60集：查到幕后利益，合作面临信任和背叛。\n61—80集：主动选择身份与关系，回收舞会安排。'],
 ['隐瞒身份回到自己公司应聘的创始人，被面试官淘汰后决定追查用人机制，却发现改革会触动更深的利益。','公司创始人：想了解真实组织，容易把制度问题误判为个别员工的态度问题。','受益于旧用人机制的管理阵营：借考核和信息控制保护利益，具体人物待补充。','1—10集：应聘受挫，身份信息差建立冲突。\n11—30集：调查用人机制，发现利益与员工处境。\n31—60集：改革受阻，创始人与团队关系受到考验。\n61—80集：承担改革代价，回收身份与组织矛盾。']
];
function topicLogline(topic){return topic.logline??topic.summary??''}
function topicCharactersText(topic){return topic.characterSettings??[topic.characters?.protagonist?`主角：${topic.characters.protagonist}`:'',topic.characters?.antagonist?`反派：${topic.characters.antagonist}`:''].filter(Boolean).join('\n\n')}
function topicBlueprintInput(topic){return {title:topic.title||'',logline:topicLogline(topic),characterSettings:topicCharactersText(topic),globalRhythm:topic.globalRhythm||'',audience:topic.audience||''}}
function assessmentBlueprintInput(input){return topicBlueprintInput({...input,characters:{protagonist:input?.protagonist||'',antagonist:input?.antagonist||''}})}
function comparableTopicContent(topic){const input=topicBlueprintInput(topic);for(const key of ['title','logline','characterSettings','globalRhythm'])input[key]=input[key].trim();return JSON.stringify({...input,biz:topic.biz||[]})}
function pendingTopicScoreRequest(topic){return (topic.scoreRequests||[]).find(request=>request.topicVersion===topic.version&&request.status==='待评分')}
function genreLoadScoreLabel(topic){const a=currentGenreLoadAssessment(topic);return a?genreLoadTotal(a)+' / 50':pendingTopicScoreRequest(topic)?'待评分':topic.genreLoadAssessment?'待重评':'待评估'}
function requestTopicScore(topic){const requests=topic.scoreRequests??=[];if(requests.some(request=>request.topicVersion===topic.version))return;requests.push({id:`SCORE-${topic.id}-v${topic.version}`,topicId:topic.id,topicVersion:topic.version,business:topic.biz?.[0]||'',rubric:topic.biz?.[0]==='AI漫剧'?'genre-load-v2':null,status:'待评分',requestedAt:new Date().toISOString(),input:topicBlueprintInput(topic)});topic.evaluation='待评分'}
function attachTopicBlueprintSample(topic,index){const sample=topicBlueprintSamples[index];topic.logline=sample[0];topic.characters={protagonist:sample[1],antagonist:sample[2]};topic.globalRhythm=sample[3]}
// Authored demonstration assessments, not runtime AI inference or market forecasts.
const genreLoadSamples=[
 [[4,'预见失败与改变命运能承载Logline中的紧迫、恐惧和希望；需要明确配角为何愿意承担代价。'],[3,'三分钟倒计时适合强开场，但支撑80集需扩展失败原因、不同时间窗口与人物目标，不能重复同一救场。'],[4,'配角弱势身份与关键决策权形成反差，可加入认知、能力和立场差异；目前人物关系尚未展开。'],[2,'现有简介未明确反派阵营与长期目标，命运压力尚不能替代能持续升级的对手。'],[4,'未来片段可留真假、代价和因果钩子；应提前规划回收，避免无限追加预知规则。']],
 [[4,'失忆与掌握秘密形成身份焦虑和人物博弈，可持续追问主角究竟是谁、是否值得信任。'],[4,'不同秘密牵连不同利益与关系，具备冲突扩展方向；80集仍需安排阶段目标，避免每集只揭一个秘密。'],[5,'反派身份与无辜状态、失去自我与看透他人形成多重反差，能容纳强弱和善恶立场变化。'],[4,'旧阵营、秘密受益者与追查者可形成对手层次，但各方目标与升级路径仍需在大纲中明确。'],[5,'身份、记忆与秘密来源可分层设置钩子；需保留可回溯证据，不能靠临时恢复记忆解释全部反转。']],
 [[4,'影子说出真相能承载羞耻、恐惧与坦诚的情绪变化，Logline具有明确的情绪触发机制。'],[3,'人物隐瞒与公开真相能扩展关系冲突，但同一夜的时间限制对80集容量构成压力，需要持续升级事件。'],[4,'表面体面与影子直白、强势身份与脆弱秘密形成反差；需区分各人物的反差，避免同质笑点。'],[3,'控制停电或操纵影子的力量可形成长期对抗，但简介尚未确定对手、规则及利益链。'],[4,'停电原因、影子规则与人物秘密可交错埋钩子；核心谜底应分阶段回收，防止只靠隐藏信息拖延。']],
 [[4,'未来辞职信将后悔与自主选择落到具体行动，可承载职场成长情绪；需明确主角最不愿失去什么。'],[3,'妥协选择、职场规则和家庭压力有扩展空间，但80集需要多个阶段目标及选择代价，不能只追查信件。'],[3,'现在与未来自我、职业外表与真实愿望形成反差；配角和关系中的反差仍待补足。'],[2,'当前设定主要依赖环境压力，尚无明确且可升级的反派阵营，长期对抗结构较薄。'],[4,'寄信动机、妥协节点与未来变化可构成钩子；因果规则必须稳定，不能让未来随时改变来制造反转。']],
 [[4,'身份被误认与被迫合作可承载羞耻、信任和身份认同，需明确两人为什么不能立即澄清。'],[3,'阶层差异、错位关系和幕后安排能扩展冲突；80集需要多阶段外部目标，避免重复认错人。'],[5,'身份、能力、行为与关系位置的互换适合多重反差；角色应有独立目标，而非只承担反差笑点。'],[3,'幕后安排者可串联阵营与利益，但目前只有方向，没有足以支撑80集的对手层次和行动计划。'],[4,'互换原因、误认范围和合作背叛可埋多波钩子；每次反转应改变关系或目标，并回收先前线索。']],
 [[4,'拥有公司却被拒绝能承载被轻视后的不甘与正名，核心情绪明确；需避免只剩身份揭晓的单次爽感。'],[3,'面试误会是有效开场，80集需转向用人制度、团队利益与改革代价，不能持续复制打脸场景。'],[4,'所有者与求职者、真实能力与表面评价形成反差；还可通过员工和管理层的认知差扩展关系反差。'],[2,'面试官尚不足以构成长线反派阵营，需要明确制度受益者及他们阻止改革的持续行动。'],[3,'身份揭晓、错误用人和隐藏利益可产生钩子，但主身份谜底较短，应及时建立下一阶段悬念。']]
];
const genreLoadMarketScores=[[3,3,2,3,4],[4,3,3,4,4],[4,3,2,3,4],[3,3,2,3,3],[4,3,3,4,3],[4,3,2,3,3]];
function genreLoadMarketAnalyses(topic){return [
 `目标人群为${topic.audience||'尚未明确的观众'}；题材可以提出受众假设，但用户规模仍需平台人群与同类内容数据验证。`,
 '需要确认主投放平台、用户观看习惯与内容限制，才能判断匹配程度；当前未指定主平台，该分数仅为演示样例。',
 '开场冲突可作为投放素材测试方向；尚无投放成本与转化数据，不能预测实际CPI，需用素材测试和渠道数据验证。',
 '人物目标与世界规则可提供续作线索；期待续作不等于真实付费复购，需要完播、追更及续作反馈验证。',
 '设定提供了差异化方向，但需要与同题材竞品的角色、冲突和钩子逐项比较；目前没有完整竞品样本，不能确认竞争优势。'
]}
function sampleGenreLoadAssessment(topic,index){
 const market=genreLoadMarketAnalyses(topic);
 return {schemaVersion:'genre-load-v2',topicVersion:topic.version,business:'AI漫剧',scopeEpisodes:80,maxScore:50,provenance:'demo',assessedAt:topic.createdAt||new Date().toISOString(),input:topicBlueprintInput(topic),dimensions:genreLoadDimensions.map((dimension,i)=>({key:dimension.key,score:i<5?genreLoadSamples[index][i][0]:genreLoadMarketScores[index][i-5],analysis:i<5?genreLoadSamples[index][i][1]:market[i-5]}))};
}
function validGenreLoadAssessment(a){return !!(a&&a.schemaVersion==='genre-load-v2'&&a.business==='AI漫剧'&&a.scopeEpisodes===80&&a.maxScore===50&&a.dimensions?.length===10&&genreLoadDimensions.every((d,i)=>{const item=a.dimensions[i];return item.key===d.key&&Number.isInteger(item.score)&&item.score>=0&&item.score<=5&&typeof item.analysis==='string'&&item.analysis.trim()}))}
function currentGenreLoadAssessment(topic){const a=topic.genreLoadAssessment;return topic.biz?.[0]==='AI漫剧'&&validGenreLoadAssessment(a)&&a.topicVersion===topic.version&&JSON.stringify(assessmentBlueprintInput(a.input))===JSON.stringify(topicBlueprintInput(topic))?a:null}
function genreLoadTotal(a){return a.dimensions.reduce((sum,item)=>sum+item.score,0)}
function needsGenreLoadAssessment(topic){return topic.biz?.[0]==='AI漫剧'&&(topic.origin?.startsWith('AI选题')||!!topic.genreLoadAssessment||!!pendingTopicScoreRequest(topic))}
function genreLoadBadge(topic){if(!needsGenreLoadAssessment(topic))return '';const a=currentGenreLoadAssessment(topic),score=genreLoadScoreLabel(topic);return `<button type="button" class="genre-load-badge" aria-label="题材承重力${a?.provenance==='demo'?'演示评分':''}：${score}" data-action="topic-detail" data-id="${esc(topic.id)}"><strong>${score}</strong></button>`}

function genreLoadRow(dimension,score=null){
 const known=Number.isInteger(score)&&score>=0&&score<=5;
 const meter=known?`<span class="genre-load-meter" role="meter" aria-label="${esc(dimension.name)}评分" aria-valuemin="0" aria-valuemax="5" aria-valuenow="${score}"><i aria-hidden="true" style="width:${score*20}%"></i></span>`:'<span class="genre-load-meter is-pending" aria-hidden="true"></span>';
 return `<div class="genre-load-row"><h4>${dimension.name}</h4><span class="genre-load-question">${dimension.question}</span>${meter}<strong>${known?score+' / 5':'待评估'}</strong></div>`;
}
function renderGenreLoadAssessment(a,includeHeading=true){
 if(!validGenreLoadAssessment(a))return '';
 const heading=includeHeading?`<h3 class="genre-load-heading"><span>承重力评估</span><strong>${genreLoadTotal(a)} / 50</strong></h3>`:'';
 return heading+['content','market'].map(group=>`<section class="genre-load-group"><h4>${group==='content'?'内容承重维度':'市场承重维度'} <span>${a.dimensions.filter((item,i)=>genreLoadDimensions[i].group===group).reduce((sum,item)=>sum+item.score,0)} / 25</span></h4><div class="genre-load-dimensions">${genreLoadDimensions.map((d,i)=>d.group===group?genreLoadRow(d,a.dimensions[i].score):'').join('')}</div></section>`).join('');
}
function genreLoadDetail(topic){const a=currentGenreLoadAssessment(topic);return `<section class="detail-block"><h3 class="genre-load-heading"><span>承重力评估</span><strong id="topicAssessmentTotal">${genreLoadScoreLabel(topic)}</strong></h3><p id="topicAssessmentNotice" class="small muted" hidden>内容已编辑，保存后待重评。</p><div id="topicAssessmentResults">${a?renderGenreLoadAssessment(a,false):['content','market'].map(group=>`<section class="genre-load-group"><h4>${group==='content'?'内容承重维度':'市场承重维度'}</h4><div class="genre-load-dimensions">${genreLoadDimensions.filter(d=>d.group===group).map(d=>genreLoadRow(d)).join('')}</div></section>`).join('')}</div></section>`}
let topicEditContext=null;
const topicEditorFields={titleInput:'title',audienceInput:'audience',topicLogline:'logline',topicCharacterSettings:'characterSettings',topicGlobalRhythm:'globalRhythm'};
function topicEditorContent(){const content={};for(const [id,key] of Object.entries(topicEditorFields))content[key]=document.getElementById(id).value;const biz=document.getElementById('bizInput').value;content.biz=biz?[biz]:[];return content}
function refreshTopicEditorState(){if(!topicEditContext)return;const content=topicEditorContent(),changed=comparableTopicContent(content)!==topicEditContext.baseline;draftDirty=changed;document.getElementById('topicSaveButton').disabled=topicEditContext.existing&&!changed;document.getElementById('topicAssessmentScope').hidden=content.biz[0]!=='AI漫剧';document.getElementById('topicAssessmentNotice').hidden=!changed;document.getElementById('topicAssessmentResults').hidden=changed;document.getElementById('topicAssessmentTotal').textContent=changed?'待重评':topicEditContext.scoreLabel}
function topicAssessmentStatus(topic){const a=currentGenreLoadAssessment(topic);return a?'承重力已评估'+(a.provenance==='demo'?'（演示）':''):pendingTopicScoreRequest(topic)?'待评分':needsGenreLoadAssessment(topic)?topic.genreLoadAssessment?'待重评':'待评估':topic.evaluation}
function topicBatch(biz,round){const createdAt=round===1?'2026-09-30T09:00:00+08:00':new Date().toISOString();return topicIdeas[biz].map(([title,summary,audience],index)=>{const topic={id:`T-DEMO-${biz==='AI漫剧'?'A':'S'}-${round}-${index+1}`,title:round===1?title:`${title} · 方向${round}`,summary,biz:[biz],audience,sourceId:'',status:'候选',version:1,evaluation:'未评价',origin:'AI选题 · 演示',createdAt,history:[`v1 · 第${round}批本地演示；未调用AI`]};if(biz==='AI漫剧'){attachTopicBlueprintSample(topic,index);topic.genreLoadAssessment=sampleGenreLoadAssessment(topic,index)}return topic})}
attachTopicBlueprintSample(seed.topics[0],5);seed.topics[0].genreLoadAssessment=sampleGenreLoadAssessment(seed.topics[0],5);
for(const biz of Object.keys(topicIdeas))seed.topics.push(...topicBatch(biz,1));
seed.topicBatchCounts={'AI漫剧':1,'故事短片':1};
seed.materials=[
 {id:'M-001',title:'叙事结构样本文本',biz:['AI漫剧','故事短片'],type:'文本',status:'已拆解 · 1 条候选'},
 {id:'M-002',title:'商品演示参考资料',biz:['电商短视频'],type:'外部链接',status:'失败 · 正文获取不完整'}
];
const validationSamples=[
 {id:'R-007',title:'场景先于卖点，能否改善内容理解？',biz:['电商短视频'],standard:'商品表达 v1.1 / 候选 v1.2',status:'样本不足 · 2 个观察样本',samples:2,target:'商品表达 / 内容理解'},
 {id:'R-008',title:'身份信息差对叙事清晰度的影响',biz:['AI漫剧'],standard:'叙事清晰度 v2.0 / 候选 v2.1',status:'待验证 · 尚无独立样本',samples:0,target:'叙事清晰度'}
];
// Independent fixtures for work/episode navigation, never runtime AI output.
const demoWorkId='WORK-A-DEMO-080';
const demoEpisodes=Array.from({length:55},(_,index)=>{
 const number=index+1,status=number<=40?'已分析':number<=50?'分析中':'解析失败';
 const title=number===1?'返城的第一封信':number===8?'被误读的邀请':number===24?'旧档案的另一页':`归城之后 · 第${number}集`;
 const quote='他把旧信放回抽屉，却发现信封背面留着另一个人的名字。';
 return {id:`DEMO-A080-EP-${number}`,workId:demoWorkId,episodeNumber:number,title,biz:['AI漫剧'],materialType:'成片',version:1,status,batchId:number<=40?'DEMO-BATCH-03':'DEMO-BATCH-04',sourceId:'人工提交',submittedAt:'2026-10-12T10:00:00+08:00',lastAnalyzedAt:number<=40?'2026-10-12 10:30':'',input:`第${number}集演示文字材料：返城青年调查旧信背后的关系，在新的线索与家人的隐瞒之间作出选择。\n${quote}`,failureReason:status==='解析失败'?'演示异常：视频来源不可访问，未获得完整正文。':'',sourceSnapshot:{title,url:'',creator:'归城故事 · 演示账号',creatorId:'demo_return_city',frameUrl:'',evidence:'固定演示文字材料，未采集真实作品。'},analysis:number<=40?{provenance:'demo',standard:'叙事清晰度 v2.0',sections:[{title:'剧情推进与冲突',text:'新线索改变了主角对家人隐瞒的判断；寻找真相与保护关系形成选择冲突。'},{title:'情绪与爽点',text:'先压低信息，再让主角发现被遗漏的证据，形成主动调查的转折。'},{title:'节奏与钩子',text:'日常动作接入线索，结尾出现新的姓名，将问题从“谁寄信”推进到“为什么隐瞒”。'},{title:'视听表达',text:'当前只有文字材料，镜头、声音及声画一致性证据不足，不能评价。'}],evidence:[{start:'00:12',end:'00:24',quote}],knowledgeDraft:{title:'用日常动作承接新的关系线索',text:'日常动作中出现新信息，可作为关系转折的候选表达方式；此处仅为演示案例，尚未验证。'}}:null};
});
demoEpisodes[0].rating='A';demoEpisodes[0].learningTags=['剧情反转'];demoEpisodes[0].learningText='关注结尾姓名线索如何承接下一集。';
const demoReports=[10,25,40].map((count,index)=>({id:`DEMO-REPORT-A080-${index+1}`,version:index+1,status:index===2?'已复核':'已复核',createdAt:`2026-10-${String(10+index).padStart(2,'0')} 10:30`,provenance:'demo',coverage:Array.from({length:count},(_,i)=>i+1),inputRefs:demoEpisodes.slice(0,count).map(task=>({taskId:task.id,version:1})),standard:'叙事清晰度 v2.0',quality:'A · 演示判断',sections:[{title:'题材与核心设定',text:'都市关系悬疑，以返城青年追查旧信为核心设定。仅覆盖现有材料，不推断未收集剧情。',evidence:[{taskId:'DEMO-A080-EP-1',start:'00:12',end:'00:24'}]},{title:'人物关系与成长',text:'主角从被动接受解释转为主动核对证据，家人的隐瞒构成关系张力。',evidence:[{taskId:'DEMO-A080-EP-8',start:'00:12',end:'00:24'}]},{title:'主线与跨集节奏',text:'线索逐步改变人物立场；不能以单集评分的平均值代表作品质量。',evidence:[{taskId:count>=24?'DEMO-A080-EP-24':'DEMO-A080-EP-8',start:'00:12',end:'00:24'}]},{title:'世界观与伏笔回收',text:'旧信与档案构成可追踪的线索链，后续回收仍须补集验证。',evidence:[{taskId:'DEMO-A080-EP-8',start:'00:12',end:'00:24'}]}],knowledgeDrafts:[{id:'DEMO-WORK-KNOWLEDGE',title:'跨集线索要改变人物的行动',text:'同一线索在后续集出现时，需要推进人物的选择与关系；当前仅为候选观察，不是已验证规律。',evidence:[{taskId:'DEMO-A080-EP-1',start:'00:12',end:'00:24'},{taskId:'DEMO-A080-EP-8',start:'00:12',end:'00:24'}]}]}));
seed.works.push({id:demoWorkId,title:'逆风归城 · 多集演示',biz:['AI漫剧'],genre:'都市 · 悬疑',creatorId:'demo_return_city',coverUrl:'assets/work-samples/campus-cover.png',collectedCount:55,analyzedCount:40,totalEpisodes:80,coverageSchema:'episodes-v1',reports:demoReports});
seed.research.push(...demoEpisodes);
seed.materials.push({id:'DEMO-WORK-BIBLE',workId:demoWorkId,title:'逆风归城 · 作品设定资料',biz:['AI漫剧'],scope:'work',type:'文本',version:1,status:'演示资料',input:'作品级演示资料：返城青年追查旧信，人物关系随证据发生变化。不能据此补写未出现的剧情。'});
seed.workDetailSamplesVersion=1;

seed.modelConnections=[];seed.modelBindings={};seed.sparks=[];seed.brainstorms={};
seed.novels=[
 {id:'N-DEMO-A-1',sourceType:'novel',title:'我在旧城修补被人遗忘的时间',source:'纸上旅人（演示）',platform:'小说平台（演示）',board:'热门阅读榜',biz:['AI漫剧'],genre:'都市奇幻',rank:1,readers:238000,plot:'旧城钟表铺的学徒发现，每一块停摆的旧表都藏着一段被遗忘的人生。他每修好一块表，就必须替委托人承担一次命运的偏移；而全城同时停下的钟声，正指向父亲失踪前留下的最后一份委托。',time:'10:00',url:'',evidence:'固定小说演示简介，未采集平台正文或在读数据。',workTitle:'我在旧城修补被人遗忘的时间'},
 {id:'N-DEMO-A-2',sourceType:'novel',title:'反派离职后，整个修仙界开始排队请他回来',source:'青山有信（演示）',platform:'小说平台（演示）',board:'新书阅读榜',biz:['AI漫剧'],genre:'仙侠反转',rank:2,readers:86000,plot:'被迫替宗门背锅多年的反派决定离职，却发现正派阵营的每一次胜利都建立在他暗中收拾残局之上。如今结界失守、盟约失效，曾经驱逐他的人必须逐一说出当年隐瞒的真相。',time:'10:00',url:'',evidence:'固定小说演示简介，未采集平台正文或在读数据。',workTitle:'反派离职后，整个修仙界开始排队请他回来'},
 {id:'N-DEMO-S-1',sourceType:'novel',title:'寄往明天的第十三封信',source:'南窗（演示）',platform:'小说平台（演示）',board:'热门阅读榜',biz:['故事短片'],genre:'家庭情感',rank:1,readers:42000,plot:'整理母亲遗物时，女孩发现一盒写给未来的信。每封信都记录着母亲未曾说出口的选择，最后一封却写着明天的日期。',time:'10:00',url:'',evidence:'固定小说演示简介，未采集平台正文或在读数据。'}
];
const storageKey=new URLSearchParams(location.search).has('qa')?'cip-demo-qa-v1':'cip-demo-v1';
let db;try{db=JSON.parse(localStorage.getItem(storageKey))||structuredClone(seed)}catch{db=structuredClone(seed)}
for(const item of seed.topics){if(!db.topics.some(topic=>topic.id===item.id))db.topics.push(structuredClone(item))}
for(const item of db.topics){if(!item.createdAt){const sample=seed.topics.find(topic=>topic.id===item.id);if(sample?.createdAt)item.createdAt=sample.createdAt}}
// Only untouched built-in AI samples receive the new demo blueprint and v2 rubric.
for(const topic of db.topics){
 if(topic.version!==1||topic.biz?.[0]!=='AI漫剧'||!topic.origin?.startsWith('AI选题')||topic.genreLoadAssessment&&topic.genreLoadAssessment.schemaVersion==='genre-load-v2')continue;
 let sample=seed.topics.find(item=>item.id===topic.id);const match=topic.id.match(/^T-DEMO-A-(\d+)-(\d+)$/);
 if(!sample&&match)sample=topicBatch('AI漫剧',Number(match[1]))[Number(match[2])-1];
 if(!sample?.genreLoadAssessment||topic.title!==sample.title||topic.summary!==sample.summary||(topic.audience||'')!==(sample.audience||''))continue;
 for(const key of ['logline','characters','globalRhythm'])if(!Object.hasOwn(topic,key))topic[key]=structuredClone(sample[key]);
 if(JSON.stringify(topicBlueprintInput(topic))===JSON.stringify(topicBlueprintInput(sample))){topic.genreLoadAssessment=structuredClone(sample.genreLoadAssessment);topic.genreLoadAssessment.assessedAt=topic.createdAt||sample.createdAt}
}
db.novels||=structuredClone(seed.novels);
db.modelConnections||=[];db.modelBindings||={};
db.sparks||=[];db.brainstorms||={};
for(const topic of db.topics.filter(x=>x.origin==='闪念胶囊'))if(!db.sparks.some(x=>x.legacyTopicId===topic.id))db.sparks.push({id:'S-legacy-'+topic.id,legacyTopicId:topic.id,title:topic.title,text:topic.sparkText??topic.summary??'',version:1,createdAt:topic.createdAt||new Date().toISOString(),versions:[]});
db.topicBatchCounts||={'AI漫剧':1,'故事短片':1};
db.materials||=structuredClone(seed.materials);
if(!db.researchWorkSamplesVersion){for(const task of seed.research.slice(3))if(!db.research.some(item=>item.id===task.id))db.research.push(structuredClone(task));db.researchWorkSamplesVersion=1}
seed.researchWorkSamplesVersion=1;
// 旧版只存研判任务：按来源 ID 关联已有作品，其余任务各建一条作品，绝不按相似标题自动合并。
db.works||=structuredClone(seed.works);
if(!db.workDetailSamplesVersion){
 for(const sample of seed.works.filter(work=>work.id===demoWorkId))if(!db.works.some(work=>work.id===sample.id))db.works.push(structuredClone(sample));
 for(const sample of demoEpisodes)if(!db.research.some(task=>task.id===sample.id))db.research.push(structuredClone(sample));
 for(const sample of seed.materials.filter(material=>material.workId===demoWorkId))if(!db.materials.some(material=>material.id===sample.id))db.materials.push(structuredClone(sample));
 db.workDetailSamplesVersion=1;
}

// Add missing demo media and blogger metadata without replacing user edits.
for(const sample of seed.works){const work=db.works.find(item=>item.id===sample.id);if(work)for(const key of ['coverUrl','frameUrl','creatorId'])if(sample[key]&&!work[key])work[key]=sample[key]}

for(const task of db.research){
 if(task.workId&&db.works.some(work=>work.id===task.workId))continue;
 const known=db.works.find(work=>task.sourceId&&task.sourceId!=='人工提交'&&work.sourceId===task.sourceId&&work.biz?.[0]===task.biz?.[0]);
 if(known){task.workId=known.id;continue}
 const id='WORK-'+task.id;task.workId=id;
 if(!db.works.some(work=>work.id===id))db.works.push({id,title:task.title,biz:task.biz,genre:task.genre||'',sourceId:task.sourceId,collectedCount:1,analyzedCount:task.status==='已完成'?1:0,totalEpisodes:null});
}
const defaultRankBoards=[
 {id:'RB-A1',biz:'AI漫剧',name:'TikHub抖音短剧热榜'},{id:'RB-A2',biz:'AI漫剧',name:'红果热播榜'},{id:'RB-A3',biz:'AI漫剧',name:'番茄小说黑马榜'},{id:'RB-A4',biz:'AI漫剧',name:'哔哩哔哩热榜'},
 {id:'RB-S1',biz:'故事短片',name:'抖音故事榜'},{id:'RB-S2',biz:'故事短片',name:'快手短片榜'},{id:'RB-S3',biz:'故事短片',name:'哔哩哔哩热榜'},
 {id:'RB-E1',biz:'电商短视频',name:'抖音带货榜'},{id:'RB-E2',biz:'电商短视频',name:'快手好物榜'},{id:'RB-E3',biz:'电商短视频',name:'哔哩哔哩热榜'}
];
if(!Array.isArray(db.rankBoards))db.rankBoards=structuredClone(defaultRankBoards);
const defaultCreators=[{id:'CR-1',biz:'AI漫剧',name:'阿呆短剧站'},{id:'CR-2',biz:'故事短片',name:'解锁地球另一面'},{id:'CR-3',biz:'电商短视频',name:'妹等Mayden'}];
if(!Array.isArray(db.creators))db.creators=structuredClone(defaultCreators);
// 真实可打开的原视频链接；标题和创作者来自公开视频页，指标与榜单位置仅为原型演示。
const videoSamples={
'S-2401':{rank:1,title:'开学那天，我被当成传说',plot:'主角重生后决定低调返校，却在一连串误会中被同学当作传奇人物；身份认知差推动后续反转。',source:'阿呆短剧站',platform:'哔哩哔哩',url:'https://www.bilibili.com/video/BV1PdNA6cEwZ/',likes:18640,shares:931,comments:422,saves:3470,genre:'都市奇幻',tag:'身份反转',type:'榜单视频'},
'S-2402':{rank:2,title:'风听螃蟹：饭桌上多出的那一只螃蟹',plot:'中秋家宴里，多出的一只螃蟹被夹走后，母亲的反应让熟悉的餐桌突然变得紧张。',source:'解锁地球另一面',platform:'哔哩哔哩',url:'https://www.bilibili.com/video/BV19m4LzSEFX/',likes:13280,shares:621,comments:875,saves:1850,genre:'悬疑',tag:'家庭关系',type:'榜单视频'},
'S-2403':{rank:3,title:'冰箱旁15cm缝隙终于给安排明白了',plot:'创作者展示厨房冰箱旁的狭窄空间，放入缝隙置物架，同时说明收纳收益与承重、散热等限制。',source:'妹等Mayden',platform:'哔哩哔哩',url:'https://www.bilibili.com/video/BV1Fy4y1s76i/',likes:9240,shares:472,comments:316,saves:2920,genre:'家居',tag:'场景痛点',type:'榜单视频'},
'S-2404':{rank:4,title:'错把善意当情谊',plot:'人物把他人的善意理解为更深的关系，期待与真实动机逐渐错位，冲突随误会持续升级。',source:'短剧样本',platform:'哔哩哔哩',url:'https://www.bilibili.com/video/BV18wJnz3EHG/',likes:8720,shares:502,comments:264,saves:1030,genre:'都市情感',tag:'人物动机',type:'榜单视频'},
'S-2405':{rank:5,title:'小户型厨房收纳改造：挤出更多空间',plot:'创作者逐步展示小厨房动线和分区调整，说明哪些收纳变化能减少台面堆放。',source:'妹等Mayden',platform:'哔哩哔哩',url:'https://www.bilibili.com/video/BV1Zv411z73s/',likes:6530,shares:348,comments:181,saves:2210,genre:'家居',tag:'空间改造',type:'榜单视频'}
};
const sampleBoardIds={'S-2401':['RB-A4'],'S-2402':['RB-S3'],'S-2403':['RB-E3'],'S-2404':['RB-A4'],'S-2405':['RB-E3']};
// 仅用于展示测试的虚构记录，不关联真实视频或真实创作者；长文放在首页。
const feedDisplayGroups={
 'AI漫剧':{code:'A',creator:'漫剧演示作者',board:'RB-A4',ranks:[2,3,5,6,7,8,9,10,11,12],rows:[
  ['为了不暴露自己其实是守护整座城市的最后一位契约者，他决定在开学第一天假装成普通转学生，却没想到随手修好的广播、借给同桌的旧雨伞和写错名字的学生证，让全校都开始追查那个从未露面的传说究竟是谁','转学生想安静度过第一天，却被三个偶然事件推到了聚光灯下。','校园奇幻'],
  ['旧书店的第十三页',`少年在旧书店买下一本没有封面的练习册，发现每到午夜，第十三页就会出现一件第二天即将发生的小事。最初只是食堂停电、同桌忘带作业和公交车提前到站，他以为自己得到了一种毫无危险的便利，于是开始偷偷替身边的人解决麻烦。每解决一件事，原本写在纸上的一句话就会消失，取而代之的是一个他不认识的名字。

第三天，册子预告校园钟楼会在放学时坍塌。少年提前找到负责检修的老师，却被当成逃课找借口的学生；他试图直接切断楼里的电源，又让所有人误以为是他造成了故障。同桌注意到他每次说谎前都会摸一下书包，开始跟着他调查旧书店，发现店主保存着一张二十年前的班级合照，照片里有一个人与少年长得一模一样。

钟楼的危险暂时解除，练习册却突然出现整页空白。少年发现那些消失的名字都属于曾经帮助过自己的人，而他们开始忘记与他共同经历的细节：借过的铅笔、一起参加的比赛，甚至第一次相识的地点。他必须弄清这种能力究竟是在改变未来，还是在用人与人之间的记忆交换结果。

故事并不马上揭开店主身份，而是通过三次不同的帮助展示能力边界。第一次成功让少年得到满足，第二次误会让同桌产生怀疑，第三次代价则把他推向真正的选择。他找到旧班主任留下的修理记录，才知道钟楼并非偶然失修，有人正在利用学生的记忆维持一个早该结束的契约。

高潮发生在毕业演出的最后一场排练。少年可以再次使用练习册，让所有人安全离开，但代价是同桌彻底忘记他。他没有选择简单地牺牲关系，而是把册子上的信息拆成能够被其他人观察到的线索，请同桌和老师分别验证，让原本只有他承担的风险变成共同解决的问题。

结尾，练习册恢复成普通空白本。同桌在第十三页写下当天发生的事，并告诉他：“记不住的时候，就重新认识一次。”旧书店依旧开着，门口多了一张学生画的钟楼速写；镜头停在速写背面的一个陌生名字，为后续单集留下新的疑问。`,'校园悬疑'],
  ['当所有人的影子都在停电后说出一句隐藏多年的真话，唯独便利店夜班店员的影子保持沉默，而他必须在天亮之前找到那个正在替全城人改写记忆的陌生顾客','全城停电后，影子开始代替主人说出秘密。夜班店员为了保护邻居，沿着三张收据寻找源头，却发现自己早已签署过一份遗忘契约。调查过程中，朋友因真话产生误会，陌生人的善意又带来新的线索；他需要让每个人主动承担自己的选择，而不是用另一轮遗忘恢复表面的平静。','都市奇幻'],
  ['最后一排的空座位','新同学每天替空座位交一份作业，老师却始终说班里没有这个人。','校园悬疑'],
  ['反派的第二份辞职信','反派决定离开组织，发现自己的辞职信在不同时间线中被批准过三次。','身份反转'],
  ['她收到明天的语音','女孩收到未来自己的留言，最重要的一句恰好被雨声盖住。','都市奇幻'],
  ['只营业一分钟的面馆','一间面馆每天只开一分钟，来不及说出口的道歉都能在这里被听见。','温情奇幻'],
  ['我把超能力借给了班长','少年暂时借出能力，却发现班长用它解决了一个没人愿意承认的问题。','校园成长'],
  ['门牌号不存在的邻居','快递员在不存在的楼层遇到旧友，门后的城市比现实慢了整整一天。','都市悬疑'],
  ['毕业照里迟到的人','拍照结束后，所有人的手机里多出了一名站在边缘的同学。','校园奇幻']
 ]},
 '故事短片':{code:'S',creator:'短片演示作者',board:'RB-S3',ranks:[1,3,4,5,6,7,8,9,10,11,12],rows:[
  ['母亲坚持在搬家前把阳台上的每一盆植物送给不同的邻居，直到女儿在最后一盆没有开花的茉莉下面找到一张写着旧地址的车票，才知道这些年她从未真正放下过那个已经拆掉的家，以及那个总在晚饭前帮所有邻居修好门锁、却从未出现在全家合影里的人','搬家前的一次送花，让女儿重新认识母亲与老街的关系。','家庭故事'],
  ['末班车的灯',`公交司机即将退休，最后一个夜班仍沿着熟悉的路线行驶。车上只有三位乘客：刚结束面试的年轻人、拎着保温盒的护士，以及抱着纸箱准备搬家的老人。每到一个站点，司机都会等十秒再关门，年轻人觉得他在拖延，护士却像早已熟悉这个习惯。

车辆经过一座停用的工厂时，老人要求在没有站牌的路口下车。司机没有立刻答应，而是停在下一个正式站点，陪老人走回原来的厂门。老人把纸箱里的搪瓷杯放到门卫室窗台，解释自己曾经值夜班，常常搭这辆末班车回家。年轻人隔着车窗看到两个人沉默地站在路灯下，第一次停止催促。

护士接到医院的电话，发现自己忘在值班室的钥匙不能等到明天再取。司机提出在终点站交班后陪她折返，但护士说，他今天已经替太多人等过了。她从保温盒里拿出多做的一份饭，放在驾驶座后面；司机认出那个盒子，与多年前一位每天乘车探望家人的老人使用的一模一样。

片子通过重复的关门声、车内灯光和司机看后视镜的动作推进，不使用解释性的旁白。三位乘客的需求彼此不同，却在这段共同路程中慢慢影响了对方。年轻人给家里打电话，承认面试并不顺利；老人请他帮忙拍一张厂门照片；护士把刚才接到的消息改写成一句简单的报平安。

到达终点站后，司机按照流程检查车辆。后排座位上放着一张手绘线路图，上面标着沿途那些没有被正式记入站名的生活片段：第一次上班、深夜出院、搬家、重逢。三位乘客没有留下姓名，只把各自想记住的地点画在了图上。

最后一个镜头是司机回家。他没有马上打开保温盒，而是先把那张线路图放进抽屉，与旧车票和妻子留下的照片摆在一起。门外响起新一班公交车经过的声音，他看了一眼时钟，终于允许自己不再赶去发车。`,'生活温情'],
  ['父亲每天在同一时间拨打一个已经停机的号码，女儿以为他忘记了那场告别，却在修理旧手机时听到一段从未被成功发送的留言，里面只有厨房的水声和一句迟到了十年的对不起','女儿修理旧手机，逐段听到父亲没有发出的留言。每一段录音对应一次普通的家庭争执，直到最后她理解了那句道歉为何一直停在发送之前。','亲情'],
  ['楼下的修鞋摊','修鞋师傅即将离开，最后一位顾客带来一双已经无法修好的旧皮鞋。','人物故事'],
  ['门口的两把伞','陌生住户每天交换门口的伞，在一场晴天里终于碰面。','生活温情'],
  ['未寄出的明信片','邮递员在退回的信里找到一张没有写地址的明信片。','告别'],
  ['冰箱上的第三张便签','独居老人发现冰箱上多出一张便签，循着字迹寻找留下它的人。','家庭故事'],
  ['邻居的晚饭声','年轻租客每晚都听见隔壁摆碗筷，却从来没有见过那家人开门。','悬疑'],
  ['被借走的录音机','毕业生归还录音机，磁带里保存着宿舍四个人没说出口的计划。','青春'],
  ['打烊后的生日蛋糕','面包店老板在打烊后烤了一只没有写名字的小蛋糕。','生活温情'],
  ['一盏没有关掉的台灯','老房子拆迁前，女儿发现书桌台灯仍定时亮起。','家庭故事']
 ]},
 '电商短视频':{code:'E',creator:'好物演示作者',board:'RB-E3',ranks:[1,2,4,6,7,8,9,10,11,12],rows:[
  ['租房厨房只有两平方米、冰箱旁还剩十三厘米窄缝，怎么在不打孔、不挡散热、不影响柜门开启的前提下，把调味瓶、清洁用品和每天都要拿取的锅盖分别放到顺手的位置，同时保留清洁通道、柜门开合空间与不同瓶罐高度的实际测量记录','用同机位展示窄缝收纳的前后变化，并记录实际尺寸。','厨房收纳'],
  ['抽屉真的更好用了？',`创作者从一个每天都会发生的取用问题开始：调味瓶放在厨房抽屉里，拿最里面的一瓶时必须先移开前面的东西。视频先完整记录原来的取用过程，再介绍一组可以调整宽度的分隔件。整个演示固定机位、光线、抽屉内物品及取用顺序，避免单靠改变拍摄条件制造前后反差。

第一步测量抽屉内部宽度、深度和可用高度，同时展示轨道突出部分，说明为什么标注的柜体外尺寸不能直接作为购买依据。第二步按使用频率分类，把每天都会拿的调味瓶留在前排，把备用物品放在后排；创作者说明这一步依靠摆放顺序，并不意味着任何分隔件都能自动提升空间利用率。

安装后分别测试空载、日常载荷和放满物品时的推拉过程。视频展示分隔件与抽屉底部接触的位置，记录几次正常开合后的偏移情况，并明确这些都是当前场景的展示测试，不能替代商品正式承重检测。如果原有轨道已经损坏，先维修轨道比增加收纳附件更重要。

中段增加一段失败演示：一只瓶子略高于抽屉可用高度，安装分隔件后仍无法关上。创作者重新测量瓶盖高度，解释怎样预留拿取和开合空间，并列出不适合该方案的情况，包括潮湿底板、异形抽屉及需要频繁移动的大锅具。画面不剪掉失败过程，让观众理解适用边界。

随后展示清洁与恢复原状：取出分隔件，检查底部是否积水，说明材质信息应以实际商品资料为准；租房用户如果担心留下痕迹，应先在不显眼位置验证，并征得必要的使用许可。预算按必要物品和可选附件分别记录，不把装饰用品计入基础解决方案。

最后回到开头的取用动作，以相同物品和同一顺序重新演示。创作者没有承诺所有家庭都能照搬，而是给出一张测量清单：内部尺寸、物品高度、开合空间、清洁需求及预算。结尾提出后续观察的问题——持续使用一段时间后，分区是否仍能保持，是否存在更难清洁或容易滑动的地方。`,'家居整理'],
  ['同一张桌子放下电脑、显示器、台灯和水杯之后，究竟是先增加收纳盒还是先重新安排电源线：一次保留真实使用顺序、桌面尺寸与清洁限制的办公角整理演示','先保留实际工作动作，再调整电源线和高频物品位置；前后对比保持同角度，说明不同桌面厚度、插座位置和设备重量的适用限制。','桌面整理'],
  ['玄关的雨伞去哪了','雨天回家先放伞，再展示如何处理积水与地面清洁。','家居'],
  ['小阳台晾晒对比','在相同衣物数量和光照条件下展示两种晾晒布局。','生活用品'],
  ['厨房台面的清洁路线','先展示擦洗过程，再比较哪些物品需要留下取用空间。','厨房收纳'],
  ['行李箱里的一周衣物','逐件装入实际出行物品，说明箱体空间和重量限制。','旅行用品'],
  ['一张桌子的线材整理','记录线材长度、接口位置和设备散热空间，再演示整理。','办公用品'],
  ['洗手台下的弯管空间','测量管道与柜体的实际距离，展示可拆卸收纳层的位置。','卫浴收纳'],
  ['宠物用品的清洗顺序','先列出实际清洁步骤，再展示收纳与干燥空间的安排。','生活用品']
 ]}
};
const feedDisplaySamples=[];
for(const [biz,group] of Object.entries(feedDisplayGroups)){
 const creator={id:'CR-DEMO-'+group.code,biz,name:group.creator};defaultCreators.push(creator);
 if(!db.feedDisplaySamplesVersion&&!db.creators.some(x=>x.id===creator.id))db.creators.push(structuredClone(creator));
 group.rows.forEach(([title,plot,genre],i)=>{
  const id=`S-DISPLAY-${group.code}-${String(i+1).padStart(2,'0')}`;
  const sample={id,title,plot,summary:plot,biz:[biz],source:group.creator,platform:'展示测试样例',type:'榜单视频',genre,tag:genre,rank:group.ranks[i],rankBoardIds:[group.board],time:'10:00',url:'',likes:12000-i*613,shares:600-i*31,comments:240-i*13,saves:1500-i*73,displaySample:true,failed:false,evidence:'虚构展示测试样例，仅用于长标题、长简介、悬停全文、筛选与分页检查；无真实原视频或采集数据。'};
  feedDisplaySamples.push(sample);sampleBoardIds[id]=sample.rankBoardIds;seed.intel.push(structuredClone(sample));
  if(!db.intel.some(x=>x.id===id))db.intel.push(structuredClone(sample));
 });
}
seed.feedDisplaySamplesVersion=1;db.feedDisplaySamplesVersion=1;
function prepareIntel(){for(const item of db.intel){item.biz=item.biz?.slice(0,1)||[];const sample=videoSamples[item.id];if(sample)Object.assign(item,sample,{summary:sample.plot,evidence:'此处仅展示根据公开标题和简介整理的演示提要；完整内容请前往原视频核对。',failed:false});item.rankBoardIds=sampleBoardIds[item.id]||[]}}
prepareIntel();
const creatorUpdates=[{sourceId:'S-2401',handle:'阿呆短剧站',biz:'AI漫剧',time:'09:42'},{sourceId:'S-2402',handle:'解锁地球另一面',biz:'故事短片',time:'09:18'},{sourceId:'S-2403',handle:'妹等Mayden',biz:'电商短视频',time:'08:56'}];
creatorUpdates.push(...feedDisplaySamples.map(x=>({sourceId:x.id,handle:x.source,biz:x.biz[0],time:x.time})));
let theme='light';try{theme=localStorage.getItem('cip-demo-theme')==='dark'?'dark':'light'}catch{}
document.documentElement.dataset.theme=theme;


const latestFeedDate='2026-10-04'; // 固定的最新演示日，不冒充实时平台采集。
const feedMetricSeed={
 'AI漫剧':{videos:58,creators:18,comments:3594,likes:1203400},
 '故事短片':{videos:43,creators:13,comments:2710,likes:934000},
 '电商短视频':{videos:37,creators:11,comments:2112,likes:708600}
};
const feedInsightSeed={
 'AI漫剧':{summary:['逆袭、误解与身份认知','身份错位 · 人物动机','都市奇幻 · 都市情感'],directions:['校园身份误会：用日常小事逐步放大人物身份反差。','善意被误读：围绕动机错位设计连续反转。']},
 '故事短片':{summary:['紧张、亲情与家庭关系','日常冲突 · 熟悉场景中的异常','悬疑 · 家庭故事'],directions:['家庭餐桌中的异常物件：从熟悉场景建立悬念。','重复日常动作，逐次改变细节来揭示亲情关系。']},
 '电商短视频':{summary:['空间焦虑与生活改善','场景痛点 · 前后对比','家居 · 厨房收纳'],directions:['狭窄空间改造：清楚展示使用前后的收纳变化。','围绕一个真实使用痛点展示商品，并说明适用限制。']}
};

// 所有评论、归纳与建议均为虚构交互样例，不来自链接中的真实评论，不执行AI分析。
const feedbackSamples={
 'S-2401':{
  summary:'身份反转带来爽感，能力规则仍需交代。',
  emotionTriggers:{'爽感':'身份揭晓与对白回收','愉悦':'配角反应与对白','困惑':'能力规则缺失','好奇':'配角选择与能力代价','失望':'误会重复','期待':'延后揭示底牌'},
  comments:[
   ['身份揭晓那一刻很爽，前面低调的细节终于接上了。',286,['爽感']],
   ['同学误会越滚越大，配角的反应比主角还好笑。',193,['愉悦']],
   ['能力为什么突然变强？规则没有讲清楚。',148,['困惑']],
   ['想看那个一直怀疑主角的同学后面怎么选择。',97,['好奇']],
   ['“我只想安静上课”这句配上全班反应有记忆点。',86,['愉悦','爽感']],
   ['身份反转喜欢，但类似误会连续来几次有点重复。',12,['失望']],
   ['低调返校可以慢一点铺开，别一下把底牌用完。',8,['期待']],
   ['世界观有趣，想知道能力会不会有代价。',4,['好奇','期待']]
  ],
  findings:[['受欢迎点','剧情反转','身份揭晓回收了前面的低调铺垫。',[0,4]],['受欢迎点','人物与金句','配角反应与重复对白形成记忆点。',[1,4]],['问题点','世界观','能力规则不清晰，部分观众难以理解。',[2]],['问题点','节奏','重复误会可能削弱后续新鲜感。',[5]]],
  expectations:[['明确表达','想看怀疑主角的同学如何选择。',[3]],['系统推测','能力代价可能成为后续悬念，需更多样本确认。',[7]]],
  suggestions:[['优先','脚本','能力规则不清晰','在反转前补一个能力限制或代价的动作线索。','比较新版中规则困惑类反馈是否减少。',[2]],['次优先','脚本','配角反应和对白获得关注','保留记忆点，同时让下一次误会带来新的关系变化。','观察对白引用与配角讨论是否持续，避免重复抱怨。',[1,4]]]
 },
 'S-2402':{
  summary:'餐桌异常引发紧张，结尾解释与声画平衡值得调整。',
  emotionTriggers:{'紧张':'异常物件、人物停顿与餐具声','好奇':'人物反应','困惑':'结尾信息差','期待':'母亲过往与结尾停顿','感动':'日常对白与亲情','失望':'音乐遮挡对白'},
  comments:[
   ['多出的那只螃蟹一出现，我就开始盯着每个人的反应。',341,['紧张','好奇']],
   ['母亲突然停住的动作很真实，熟悉的饭桌一下变陌生了。',226,['紧张']],
   ['最后谁知道这件事？看完还是没理解人物之间的信息差。',167,['困惑']],
   ['想看母亲之前经历了什么，别只靠结尾一句话解释。',109,['期待']],
   ['“再添一双筷子”比长篇解释更有亲情的感觉。',88,['感动']],
   ['背景音乐太满了，有一段对白听不清。',14,['失望']],
   ['安静的餐具声已经够紧张，可以少一点惊吓音效。',9,['紧张']],
   ['结尾慢半拍，我可能会更难过。',5,['期待','感动']]
  ],
  findings:[['受欢迎点','场景与镜头','异常物件与人物停顿建立紧张感。',[0,1]],['受欢迎点','对白与情绪','日常对白比解释性台词更能承载亲情。',[4]],['问题点','信息揭示','结尾的信息差没有完全被理解。',[2]],['问题点','声音','音乐可能遮挡重要对白。',[5]]],
  expectations:[['明确表达','希望看到母亲过往的线索。',[3]],['系统推测','结尾停顿可能增强情绪回收，需版本对照。',[7]]],
  suggestions:[['优先','脚本','人物信息差难理解','前置一个母亲知道异常的可见线索，减少结尾解释。','比较信息差困惑反馈及线索讨论。',[2,3]],['次优先','成片','声音遮挡对白','降低重要对白处的音乐，保留餐具声和必要停顿。','核对对白可懂度并观察声音相关抱怨。',[5,6]]]
 },
 'S-2403':{
  summary:'窄缝利用获得认可，承重与散热信息仍需补足。',
  emotionTriggers:{'惊喜':'具体窄缝解决办法','满意':'前后对比与取用演示','担忧':'散热与满载稳定性','期待':'尺寸、承重与实测','失望':'尺寸适用条件'},
  comments:[
   ['家里也是这种窄缝，终于看到一个能直接参考的办法。',208,['惊喜']],
   ['前后对比很直观，台面清爽很多。',174,['满意']],
   ['放进去以后冰箱怎么散热？需要留多少距离？',135,['担忧']],
   ['希望把架子的尺寸和承重写清楚，我家的缝只有十三厘米。',98,['期待']],
   ['取用过程拍出来比只摆成品更有说服力。',75,['满意']],
   ['画面里没有看到放满之后抽拉会不会晃。',11,['担忧']],
   ['尺寸不合适的话，好看也没用。',7,['失望']],
   ['能不能加一个放满瓶罐后的实测？',3,['期待']]
  ],
  findings:[['受欢迎点','场景痛点','具体窄缝场景与前后对比容易被理解。',[0,1]],['受欢迎点','演示','取用过程比静态展示更有说服力。',[4]],['问题点','适用边界','散热、尺寸及承重条件尚未充分说明。',[2,3]],['问题点','事实证据','满载抽拉缺少可见实测。',[5]]],
  expectations:[['明确表达','希望提供尺寸、承重和满载演示。',[3]],['系统推测','不同家庭尺寸可能需要不同适用说明。',[6]]],
  suggestions:[['优先','脚本 / 成片','适用条件不清晰','按实际商品资料补尺寸与散热要求，避免通用承诺。','核对商品事实并比较适用条件疑问。',[2,3]],['次优先','成片','满载稳定性证据不足','在相同机位和条件下补充满载取用演示。','检查演示完整性；不凭评论推断转化提升。',[5]]]
 },
 'S-2404':{
  summary:'关系错位有共鸣，人物动机与误会升级仍需铺垫。',
  emotionTriggers:{'共鸣':'关系误读与质问对白','认可':'配角没有被刻意反派化','困惑':'主角缺少判断关系的依据','期待':'真相后的主动选择','难过':'关系质问对白','失望':'误会刻意拖延'},
  comments:[
   ['以为对方喜欢自己，原来只是习惯照顾别人，这段很有共鸣。',178,['共鸣']],
   ['配角没有被写成坏人，这一点比强行反转舒服。',132,['认可']],
   ['主角为什么认定是爱情？前面没有看到足够的依据。',106,['困惑']],
   ['想看主角知道真相以后怎么面对自己的期待。',83,['期待']],
   ['“你对谁都这么好吗”这句很扎心。',66,['难过','共鸣']],
   ['如果早点说清楚，后面的冲突就没了，有点刻意。',10,['失望']],
   ['希望双方都有自己的选择，不要只靠误会拖剧情。',6,['期待']],
   ['普通的关心被误读，这种关系比夸张狗血更真实。',3,['共鸣']]
  ],
  findings:[['受欢迎点','人物关系','善意与期待错位引发共鸣。',[0,1]],['受欢迎点','金句','关系质问对白形成情绪记忆点。',[4]],['问题点','人物动机','主角认定关系的依据不足。',[2]],['问题点','冲突','误会升级可能显得人为拖延。',[5]]],
  expectations:[['明确表达','希望看到真相揭晓后的主动选择。',[3]],['系统推测','双向人物动机可能比继续延长误会更有价值。',[6]]],
  suggestions:[['优先','脚本','关系判断缺少依据','补一个主角误读善意的具体事件，并展示其个人需求。','观察人物动机困惑是否减少。',[2]],['次优先','脚本','观众期待人物主动选择','让真相推动下一次选择，保留金句但减少解释台词。','观察主动选择的讨论，验证情绪回收。',[3,4]]]
 },
 'S-2405':{
  summary:'收纳步骤清楚，实际成本与长期维护是主要疑问。',
  emotionTriggers:{'满意':'分区步骤清晰','愉悦':'同机位前后对比','担忧':'预算与长期维护','期待':'使用记录与购买清单','认可':'高频物品的位置解释','失望':'深处物品取用不便'},
  comments:[
   ['先分区再收纳的步骤很清楚，比一口气堆产品好理解。',156,['满意']],
   ['同角度的前后对比很解压。',119,['愉悦']],
   ['一共花了多少钱？小厨房照着做会不会超预算？',91,['担忧']],
   ['想看用了一个月以后还好不好拿、好不好清洗。',72,['期待']],
   ['先把常用物品留在手边，这个思路能直接借鉴。',58,['认可']],
   ['整齐是整齐，取最里面的东西好像还得搬出来。',9,['失望']],
   ['能列一份必要购买和可以不买的清单吗？',5,['期待']],
   ['长期保持比刚改完漂亮更重要。',2,['担忧']]
  ],
  findings:[['受欢迎点','演示结构','分区步骤与同机位对比便于学习。',[0,1]],['受欢迎点','使用场景','高频物品位置的解释有实用价值。',[4]],['问题点','成本','缺少总预算及必要购买说明。',[2]],['问题点','长期使用','取用便利和维护成本尚需验证。',[5]]],
  expectations:[['明确表达','希望看到一个月后的使用与清洁情况。',[3]],['系统推测','预算分级清单可能降低模仿门槛。',[6]]],
  suggestions:[['优先','脚本','预算信息缺失','区分必要与可选购买项，补充实际预算和适用条件。','观察成本疑问及清单反馈，不推断购买转化。',[2]],['次优先','成片','长期维护信息不足','补真实取用演示与后续使用记录。','比较维护、清洗与取用方面的反馈。',[3]]]
 }
};
function createAudienceFeedback(video,date,capturedAt){
 const sample=feedbackSamples[video.id];if(!sample)return null;
 const count=date==='2026-10-02'?5:date==='2026-10-03'?7:8;
 const comments=sample.comments.slice(0,count).map(([text,likes,emotions],i)=>({id:`CM-${video.id}-${date}-${i+1}`,text,likes:Math.round(likes*(date==='2026-10-02'?.55:date==='2026-10-03'?.8:1)),emotions,user:`演示观众${String(i+1).padStart(2,'0')}`,publishedAt:date+` 09:${String(10+i).padStart(2,'0')}`,kind:i<5?'热评':'普通评论'}));
 const supported=rows=>rows.filter(row=>row.at(-1).some(i=>i<count)).map(row=>[...row.slice(0,-1),row.at(-1).filter(i=>i<count)]);
 return {id:`AF-${video.id}-${date}`,version:1,status:'ready',demo:true,sourceId:video.id,sourceDate:date,capturedAt,platform:video.platform,totalComments:video.comments??null,summary:sample.summary,emotionTriggers:sample.emotionTriggers,comments,findings:supported(sample.findings),expectations:supported(sample.expectations),suggestions:supported(sample.suggestions)};
}
function initializeAudienceFeedback(){
 const add=(items,date,capturedAt)=>{for(const video of items){if(!Object.hasOwn(video,'audienceFeedback')&&feedbackSamples[video.id])video.audienceFeedback=createAudienceFeedback(video,date,capturedAt)}};
 add(db.intel,latestFeedDate,currentFeedSnapshot().capturedAt);
 for(const snapshot of Object.values(db.feedArchive))if(snapshot.date!==latestFeedDate)add(snapshot.intel||[],snapshot.date,snapshot.capturedAt);
}
function currentFeedSnapshot(){return {id:'FS-'+latestFeedDate,version:1,date:latestFeedDate,capturedAt:db.feedArchive?.[latestFeedDate]?.capturedAt||'2026-10-04T10:00:00+08:00',intel:db.intel,novels:db.novels,updates:creatorUpdates,rankBoards:db.rankBoards,creators:db.creators,metrics:feedMetricSeed,insights:feedInsightSeed}}
function initializeFeedArchive(){
 if(!db.feedArchive||typeof db.feedArchive!=='object'||Array.isArray(db.feedArchive))db.feedArchive={};
 for(const [date,factor] of [['2026-10-02',.58],['2026-10-03',.81]]){
  if(db.feedArchive[date])continue;
  const snapshot=structuredClone(currentFeedSnapshot());snapshot.id='FS-'+date;snapshot.date=date;snapshot.capturedAt=date+'T23:00:00+08:00';
  snapshot.rankBoards=structuredClone(defaultRankBoards);snapshot.creators=structuredClone(defaultCreators.filter(c=>!c.id.startsWith("CR-DEMO-")));
  snapshot.novels=[];snapshot.intel=snapshot.intel.filter(v=>!v.displaySample&&(date==='2026-10-03'||['S-2401','S-2402','S-2403'].includes(v.id)));
  snapshot.updates=snapshot.updates.filter(u=>snapshot.intel.some(v=>v.id===u.sourceId));
  for(const v of snapshot.intel){for(const key of ['likes','shares','comments','saves'])if(v[key]!=null)v[key]=Math.round(v[key]*factor);v.rank=10-(v.rank||0);v.time=date==='2026-10-03'?'16:20':'14:10';delete v.audienceFeedback}
  for(const u of snapshot.updates)u.time=date==='2026-10-03'?'16:20':'14:10';
  for(const m of Object.values(snapshot.metrics))for(const key of Object.keys(m))m[key]=Math.round(m[key]*factor);
  const older=date==='2026-10-02';
  snapshot.insights['AI漫剧']={summary:[older?'成长焦虑与自我证明':'关系误解与身份反差',older?'能力觉醒 · 小人物成长':'动机错位 · 身份秘密',older?'校园奇幻':'都市情感 · 校园奇幻'],directions:older?['用一次不起眼的校园任务揭示主角的新能力。','从配角视角观察主角，延后揭露真实身份。']:['围绕一次善意误读设计人物关系反转。','把身份秘密藏在日常对话和动作细节中。']};
  snapshot.insights['故事短片']={summary:[older?'离别、孤独与陪伴':'亲情张力与餐桌悬疑',older?'旧物 · 未说出口的告别':'异常物件 · 日常仪式',older?'都市生活 · 家庭故事':'家庭悬疑'],directions:older?['用一件旧物串起人物之间未完成的告别。','以固定日常动作表达独居者的情绪变化。']:['从餐桌上不该出现的物件建立悬念。','让家人的不同反应逐步揭露隐藏关系。']};
  snapshot.insights['电商短视频']={summary:[older?'整理需求与实用期待':'小空间焦虑与秩序感',older?'场景对比 · 使用限制':'厨房动线 · 收纳改造',older?'家居整理':'厨房收纳'],directions:older?['围绕一次整理任务比较商品的使用前后差异。','用真实尺寸和适用边界说明商品价值。']:['聚焦冰箱旁狭窄空间，展示收纳和动线变化。','展示一个操作步骤，同时交代承重与散热限制。']};
  db.feedArchive[date]=snapshot;
 }
 initializeAudienceFeedback();db.feedArchive[latestFeedDate]=structuredClone(currentFeedSnapshot());save();
}
function getFeedSnapshot(date=latestFeedDate){return date===latestFeedDate?currentFeedSnapshot():db.feedArchive?.[date]||null}

function feedSource(id,date){const snapshot=getFeedSnapshot(date);return snapshot?.intel.find(v=>v.id===id)||snapshot?.novels?.find(v=>v.id===id)}



const workspaceStorageKey=storageKey+'-workspace';
let workspaceBusiness='故事短片';try{const saved=localStorage.getItem(workspaceStorageKey);if(businesses.includes(saved))workspaceBusiness=saved}catch{}
let state={module:0,tab:0,biz:[workspaceBusiness],hongguoBoard:'',hongguoGenre:'',hongguoSubgenre:'',topicPage:1,query:'',workGenre:'全部题材',knowledgeCategory:'全部',status:'全部状态',stage:'全部环节',mode:'正常',workId:'',workView:'episodes',workUnit:'',workTaskId:'',workReportId:'',episodeNavPage:1},draftDirty=false,lastFocus=null;
const page=document.getElementById('page'),dialog=document.getElementById('dialog');
const save=()=>{try{localStorage.setItem(storageKey,JSON.stringify(db))}catch{toast('浏览器存储不可用，本次修改仅保留在当前页面')}};
let toastTimer;function toast(msg){const t=document.getElementById('toast');t.textContent=msg;t.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>t.classList.remove('show'),3200)}
const tags=(a)=>a.map(x=>`<span class="tag">${esc(x)}</span>`).join('');
const btn=(label,action,id='',primary=false)=>`<button class="btn ${primary?'primary':''}" data-action="${action}" data-id="${esc(id)}">${label}</button>`;
const empty=(title='没有匹配的内容',desc='试试其他关键词，或清除当前筛选。')=>`<div class="empty">${icon('search')}<h2>${title}</h2><p>${desc}</p>${btn('清除筛选','clear')}</div>`;
function notice(text){return `<div class="notice">${icon('info')}<p>${text}</p></div>`}
function heading(title,_desc,action='',actionClass=''){return `<h1 class="sr-only">${title}</h1>`+(action?`<div class="page-heading page-actions ${actionClass}">${action}</div>`:'')}
function filters(stage=false){return stage?`<div class="filter-line"><span class="filter-label">适用环节</span>${['全部环节','选题','脚本','资产','成片'].map(x=>`<button class="chip ${state.stage===x?'active':''}" aria-pressed="${state.stage===x}" data-action="stage" data-id="${x}">${x}</button>`).join('')}</div>`:''}
function toolbar(placeholder,statuses=[]){return `<div class="toolbar"><label class="search">${icon('search')}<span class="sr-only">搜索当前工作区</span><input id="search" placeholder="${placeholder}" value="${esc(state.query)}" autocomplete="off"></label>${statuses.length?`<select id="statusFilter" aria-label="状态筛选">${['全部状态',...statuses].map(x=>`<option ${state.status===x?'selected':''}>${x}</option>`).join('')}</select>`:''}<span class="small muted">${state.module===0&&state.tab===0?'演示数据 · 榜单按样例序号':'当前工作区内搜索'}</span></div>`}
function inWorkspace(item){return item.biz?.includes(state.biz[0])}
function scoped(items){return items.filter(inWorkspace)}
function filtered(items,options={}){return scoped(items).filter(x=>(!state.query||[x.title,x.logline,x.summary,x.characters?.protagonist,x.characters?.antagonist,x.globalRhythm,x.source,x.tag,x.genre,x.category,x.id].join(' ').toLowerCase().includes(state.query.toLowerCase()))&&(options.ignoreStatus||state.status==='全部状态'||x.status===state.status||x.type===state.status)&&(options.ignoreStage||state.stage==='全部环节'||(x.stage|| (x.title.includes('成片')?'成片':x.title.includes('脚本')?'脚本':''))===state.stage))}


function compactNum(n){if(n===null||n===undefined||n==='')return '未获取';return Number(n)>=10000?(Number(n)/10000).toFixed(1).replace(/\.0$/,'')+'万':Number(n).toLocaleString('zh-CN')}








function feedbackComments(feedback){
 const seen=new Set();return (Array.isArray(feedback?.comments)?feedback.comments:[]).filter(c=>{if(!c||!c.id||typeof c.text!=='string'||!c.text.trim()||seen.has(c.id))return false;seen.add(c.id);return true}).map(c=>({...c,emotions:Array.isArray(c.emotions)?c.emotions.filter(e=>typeof e==='string'&&e.trim()):[],likes:Number.isSafeInteger(c.likes)&&c.likes>=0?c.likes:null}));
}
function feedbackEmotions(feedback){
 const comments=feedbackComments(feedback).filter(c=>Array.isArray(c.emotions)&&c.emotions.length),counts=new Map();
 for(const c of comments)for(const name of new Set(c.emotions))counts.set(name,(counts.get(name)||0)+1);
 return [...counts].map(([name,count])=>({name,count,percent:Math.round(count/comments.length*100)})).sort((a,b)=>b.count-a.count);
}
function feedbackMissing(feedback){return feedback?.status==='empty'?'该日期确认无评论':feedback?.status==='failed'?'评论采集失败':feedback?.status==='pending'?'观众反馈待分析':'该日期评论未获取'}

function feedbackEvidenceLink(refs,comments){
 const valid=(Array.isArray(refs)?refs:[]).filter(i=>comments[i]);
 return valid.length?`<button class="feedback-evidence-link" data-action="feedback-evidence" data-id="${valid.join(',')}">查看${valid.length}条证据 ›</button>`:'<span class="small muted">支持评论未获取</span>';
}
function feedbackReport(feedback,showKeyFeedback=false){
 if(!feedback)return `<p class="feedback-empty">${feedbackMissing(feedback)}</p>`;
 const comments=feedbackComments(feedback),emotions=feedbackEmotions(feedback),classified=comments.filter(c=>c.emotions?.length).length;
 if(!comments.length)return `<p class="feedback-empty">${feedback.status==='ready'?'暂无有效评论样本，暂不分析':feedbackMissing(feedback)}</p>`;
 const supported=rows=>(Array.isArray(rows)?rows:[]).filter(row=>Array.isArray(row)&&Array.isArray(row.at(-1))).map(row=>[...row.slice(0,-1),[...new Set(row.at(-1))].filter(i=>Number.isInteger(i)&&comments[i])]).filter(row=>row.at(-1).length);
 const top=comments.map((c,i)=>({...c,index:i})).sort((a,b)=>(b.likes??-1)-(a.likes??-1)).slice(0,5),topIds=new Set(top.map(c=>c.id));
 const remaining=comments.map((c,i)=>({...c,index:i})).filter(c=>!topIds.has(c.id));
 const renderComment=(c,rank)=>`<article class="feedback-comment" id="feedback-comment-${c.index}" tabindex="-1"><div class="feedback-comment-meta"><span>${rank?`TOP ${rank} · `:''}${esc(c.user||'匿名观众')} · ${esc(c.kind||'评论')}</span><span>赞 ${compactNum(c.likes)}</span></div><p>${esc(c.text)}</p><div class="feedback-comment-meta"><span>${esc(c.publishedAt||'发布时间未获取')}</span><span>${(c.emotions||[]).map(esc).join(' · ')||'未分类'}</span></div></article>`;
 const scope=comments.every(c=>c.kind==='热评')?'仅热评样本，不代表整体观众':'热评与普通评论混合样本，不代表整体观众';
 return `<div class="feedback-report"><div class="feedback-scope"><strong>${feedback.demo?'虚构演示 · 未调用AI':'已保存的观众反馈'}</strong><p>${esc(feedback.platform||'平台未获取')} · 情报日期 ${esc(feedback.sourceDate||'未获取')} · ${esc(feedback.capturedAt||'采集时间未获取')}</p><p>作品评论 ${compactNum(feedback.totalComments)} · 已采集 ${Array.isArray(feedback.comments)?feedback.comments.length:0} 条 · 有效 ${comments.length} 条 · 已分类 ${classified} 条</p><p>${scope}。归纳与建议为待验证观察，不自动形成正式规律。</p><small>${esc(feedback.id||'快照ID未获取')} · v${esc(feedback.version||'未获取')}</small></div><section class="feedback-section"><h3>情绪分布</h3><p class="small muted">占已分类样本的比例；同一评论可有多个情绪标签，占比合计可能超过100%。</p><div class="feedback-emotions">${emotions.map(e=>`<div class="feedback-emotion"><div><span>${esc(e.name)}</span><span>${e.count} 条 · ${e.percent}%</span></div><div class="feedback-meter" aria-hidden="true"><span style="width:${e.percent}%"></span></div>${feedback.emotionTriggers?.[e.name]?`<p class="small muted">触发：${esc(feedback.emotionTriggers[e.name])}</p>`:''}${feedbackEvidenceLink(comments.map((c,i)=>c.emotions?.includes(e.name)?i:null).filter(i=>i!==null),comments)}</div>`).join('')||'<p class="small muted">暂无情绪分类，不能推断情绪占比。</p>'}</div>${showKeyFeedback?`<p class="feedback-trigger">关键反馈：${esc(feedback.summary||'尚未归纳')}</p>`:''}</section><section class="feedback-section"><h3>受欢迎点与问题点</h3><div class="feedback-findings">${supported(feedback.findings).map(([type,aspect,text,refs])=>`<article><div class="feedback-finding-head"><span class="tag">${esc(type)}</span><strong>${esc(aspect)}</strong><span class="small muted">${refs.length>1?'重复反馈':'个别意见'}</span></div><p>${esc(text)}</p>${feedbackEvidenceLink(refs,comments)}</article>`).join('')||'<p class="small muted">证据不足，尚无可展示的归纳。</p>'}</div></section><section class="feedback-section"><h3>观众期待</h3>${supported(feedback.expectations).map(([type,text,refs])=>`<article class="feedback-expectation"><span class="tag">${esc(type)}</span><p>${esc(text)}</p>${feedbackEvidenceLink(refs,comments)}</article>`).join('')||'<p class="small muted">暂无有证据支持的观众期待。</p>'}</section><section class="feedback-section"><h3>创作建议</h3><p class="small muted">依据较弱 · 小样本假设；需人工判断与新版本验证。</p>${supported(feedback.suggestions).map(([priority,stage,reason,change,verify,refs])=>`<article class="feedback-suggestion"><div class="feedback-finding-head"><span class="tag">${esc(priority)}</span><strong>${esc(stage)}</strong><span class="small muted">待验证</span></div><dl><dt>反馈</dt><dd>${esc(reason)}</dd><dt>调整</dt><dd>${esc(change)}</dd><dt>验证</dt><dd>${esc(verify)}</dd></dl>${feedbackEvidenceLink(refs,comments)}</article>`).join('')||'<p class="small muted">证据不足，暂不给出创作建议。</p>'}</section><details class="feedback-section feedback-comments" id="feedbackComments"><summary>TOP评论 · ${top.length}条</summary><p id="feedbackEvidenceNote" class="small muted" role="status"></p><p class="small muted">已采集样本按点赞排序，非全站排名。原始正文仅作反馈证据。</p>${top.map((c,i)=>renderComment(c,i+1)).join('')}${remaining.length?`<details id="feedbackOtherComments"><summary>其他样本 · ${remaining.length}条</summary>${remaining.map(c=>renderComment(c)).join('')}</details>`:''}</details></div>`;
}


function revealFeedbackEvidence(value){
 const comments=document.getElementById('feedbackComments');if(!comments)return;comments.open=true;
 const other=document.getElementById('feedbackOtherComments');if(other)other.open=true;
 const refs=String(value).split(',').filter(i=>/^\d+$/.test(i));
 for(const c of document.querySelectorAll('.feedback-comment.is-evidence'))c.classList.remove('is-evidence');
 for(const index of refs)document.getElementById('feedback-comment-'+index)?.classList.add('is-evidence');
 const note=document.getElementById('feedbackEvidenceNote');if(note)note.textContent=refs.length?`已突出显示 ${refs.length} 条相关评论证据。`:'';
 const target=document.getElementById('feedback-comment-'+(refs[0]||'0'));if(target){target.scrollIntoView({block:'nearest'});target.focus({preventScroll:true})}
}
function researchFeedbackBlock(feedback){return feedback?`<details class="feedback-research"><summary>观众反馈与关键反馈</summary>${feedbackReport(feedback,true)}</details>`:''}

let feedTextSource=null,feedTextDescription=null,feedTextHideTimer;
function hideFeedFullText(){
 clearTimeout(feedTextHideTimer);
 const box=document.getElementById('feedTextPopover');box.hidden=true;box.textContent='';
 if(feedTextSource){if(feedTextDescription===null)feedTextSource.removeAttribute('aria-describedby');else feedTextSource.setAttribute('aria-describedby',feedTextDescription)}
 feedTextSource=null;feedTextDescription=null;
}
function showFeedFullText(source){
 clearTimeout(feedTextHideTimer);
 if(!source?.isConnected||!(source.scrollWidth>source.clientWidth||source.scrollHeight>source.clientHeight)){hideFeedFullText();return}
 if(feedTextSource!==source){hideFeedFullText();feedTextSource=source;feedTextDescription=source.getAttribute('aria-describedby')}
 const box=document.getElementById('feedTextPopover'),rect=source.getBoundingClientRect(),margin=12,gap=8;
 const width=window.innerWidth,height=window.innerHeight;
 const below=Math.max(0,height-rect.bottom-gap-margin),above=Math.max(0,rect.top-gap-margin),placeBelow=below>=Math.min(360,above);
 box.textContent=source.dataset.feedFullText;box.style.maxHeight=Math.min(360,Math.max(1,placeBelow?below:above))+'px';box.hidden=false;
 box.style.left=Math.max(margin,Math.min(rect.left,width-box.offsetWidth-margin))+'px';
 box.style.top=Math.max(margin,Math.min(placeBelow?rect.bottom+gap:rect.top-gap-box.offsetHeight,height-box.offsetHeight-margin))+'px';
 source.setAttribute('aria-describedby',[feedTextDescription,'feedTextPopover'].filter(Boolean).join(' '));
}
function deferHideFeedFullText(){
 clearTimeout(feedTextHideTimer);feedTextHideTimer=setTimeout(()=>{
  const box=document.getElementById('feedTextPopover');
  if(document.activeElement!==feedTextSource&&!box.contains(document.activeElement))hideFeedFullText();
 },150);
}






const hongguoBoards=[['hot-drama','红果热播榜'],['hot-real-drama','真人剧热播榜'],['hot-ai-drama','AI剧热播榜'],['hot-comic-drama','漫剧热播榜']];






const topicPageSize=9;
function topicTime(value){if(!value||Number.isNaN(Date.parse(value)))return '未记录';return new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).replace(/\//g,'-')}
function topicPage(){
 const pool=state.tab===2,paused=!pool&&state.biz[0]==='电商短视频';
 const items=paused?[]:filtered(db.topics.filter(x=>pool?x.status!=='候选':x.status==='候选'&&x.biz[0]!=='电商短视频'));
 const pages=Math.max(1,Math.ceil(items.length/topicPageSize));
 state.topicPage=Math.min(Math.max(1,state.topicPage),pages);
 const rows=pool?items:items.slice((state.topicPage-1)*topicPageSize,state.topicPage*topicPageSize);
 const generate=!pool&&topicIdeas[state.biz[0]]?btn('AI再来5个','topic-more',state.biz[0],true):'';
 const tools=pool?toolbar('搜索选题、方向或选题编号',['待生产','已交接','已采用']):'';
 const intro=pool?notice('复制或导出只代表选题交接；正式内容制作与发布在外部工具完成。'):paused?notice('电商短视频的选题流程仍待讨论，暂缓展示与生成选题卡。'):notice(state.biz[0]==='AI漫剧'?'每次生成5张漫剧选题卡，附内容与市场十维承重力演示评估；未调用AI。':'每次按当前业务生成5张选题卡。此原型使用本地演示方向，不调用AI；评价状态为“未评价”。');
 const pager=!pool&&pages>1?`<div class="feed-pager topic-pagination" aria-label="选题卡翻页"><span>第 ${state.topicPage} / ${pages} 页 · 共 ${items.length} 张</span><div class="pager-actions"><button data-action="topic-page" data-id="-1" aria-label="选题卡上一页" ${state.topicPage===1?'disabled':''}>上一页</button><button data-action="topic-page" data-id="1" aria-label="选题卡下一页" ${state.topicPage===pages?'disabled':''}>下一页</button></div></div>`:'';
 return heading(pool?'待生产':'选题卡',pool?'人工确认的选题，在这里完成复制与导出交接。':'把灵感整理为有依据、可判断的创作方向。',(!paused?btn(icon('plus')+' 新增选题','new-topic'):'')+(!pool&&!paused?btn('头脑风暴','brainstorm'):'')+generate,'actions-left')+filters()+tools+intro+`<div class="cards-grid topic-grid">${rows.map(x=>`<article class="card topic-card" role="group" tabindex="0" aria-label="查看选题详情：${esc(x.title)}" data-topic-id="${esc(x.id)}" data-action="topic-detail" data-id="${esc(x.id)}"><div class="card-top"><div class="meta">${x.biz?.[0]==='AI漫剧'?genreLoadBadge(x):tags(x.biz)}<span>${x.id} · v${x.version}</span></div><span class="tag">${pool?x.status:x.origin}</span></div><button class="title-button" data-action="topic-detail" data-id="${x.id}">${esc(x.title)}</button><p class="summary">${esc(topicLogline(x))}</p><div class="detail-block small"><span class="muted">目标人群</span>　${esc(x.audience||'尚未补充')}</div><p class="topic-time"><span>生成时间</span>${x.createdAt?`<time datetime="${esc(x.createdAt)}">${esc(topicTime(x.createdAt))}</time>`:'<span>未记录</span>'}</p><div class="card-foot ${needsGenreLoadAssessment(x)?'topic-actions-only':''}">${needsGenreLoadAssessment(x)?'':`<span class="small muted">${x.evaluation==='已评价'?'评价已完成 · 可查看依据':x.evaluation==='待重评'?'内容已修改 · 旧评价待更新':'尚未评价'}</span>`}<div class="row-actions">${pool?btn('交接选题','topic-detail',x.id):btn('编辑','edit-topic',x.id)+btn('加入待生产','topic-add-production',x.id,true)}</div></div></article>`).join('')||empty(paused?'电商选题暂缓':pool?'暂无待生产内容':'没有匹配的选题',paused?'选题流程确定后再开放。':pool?'到选题卡选择一个选题，即可在这里交接。':'切换业务或记录一条灵感。')}</div>${pager}`
}
const knowledgeCategories=['题材库','金句库','爽点库','翻车点','DNA经典案例'];
function knowledgeCategoryLabel(item){return knowledgeCategories.includes(item.category)?item.category:'未分类'}
function knowledgeCategoryTabs(items){return `<div class="knowledge-category-tabs" role="group" aria-label="知识分类">${['全部',...knowledgeCategories].map(category=>`<button class="${state.knowledgeCategory===category?'active':''}" data-action="knowledge-category" data-id="${category}" aria-pressed="${state.knowledgeCategory===category}">${category}<span>${category==='全部'?items.length:items.filter(item=>item.category===category).length}</span></button>`).join('')}</div>`}
function knowledgePage(){
 const browse=state.tab===0,records=db.knowledge.filter(item=>browse?item.status==='已入库':state.tab===2?['待人工审核','待AI审核'].includes(item.status):item.status==='回收站');
 const counts=scoped(records),items=filtered(records,{ignoreStage:true,ignoreStatus:browse}).filter(item=>!browse||state.knowledgeCategory==='全部'||item.category===state.knowledgeCategory),name=modules[1].tabs[state.tab];
 return heading(name,'',browse?btn(icon('plus')+' 人工新增','new-knowledge'):'',browse?'actions-left':'')+(browse?knowledgeCategoryTabs(counts):'')+toolbar('搜索知识、摘要或知识编号',state.tab===2?['待AI审核','待人工审核']:[])+(state.tab===2?notice('AI审核与人工审核分别留档。修改知识内容后，应对新版本重新执行AI审核。'):state.tab===3?notice('此原型不运行自动清理任务。恢复权限、计时起点与历史引用处理仍待业务确认。'):'')+`<div class="list-head"><span>${items.length} 条${browse?'正式知识':'记录'}</span><span>${browse?'仅显示双审通过的版本':'候选知识不进入正式检索'}</span></div><div class="cards-grid">${items.map(item=>`<article class="card"><div class="card-top"><div class="meta">${tags([knowledgeCategoryLabel(item),item.type,item.stage].filter(Boolean))}</div><span class="small muted">${esc(item.id)} · v${esc(item.version)}</span></div><button class="title-button" data-action="knowledge-detail" data-id="${esc(item.id)}">${esc(item.title)}</button><p class="summary">${esc(item.summary)}</p><div class="card-foot"><div class="meta">${tags(item.biz)}</div><button class="btn small" data-action="knowledge-detail" data-id="${esc(item.id)}">${state.tab===2?'审核详情':'查看知识'} ${icon('arrow')}</button></div></article>`).join('')||empty(state.tab===3?'回收站为空':browse&&state.knowledgeCategory!=='全部'?state.knowledgeCategory+'暂无匹配的正式知识':'没有匹配的知识',state.tab===3?'正式知识删除后会出现在这里。':'调整分类或搜索条件，待审核条目请到审核队列查看。')}</div>`;
}

function intake(){const items=scoped(db.materials);return heading('入库处理','提交资料，跟踪解析与拆解，候选知识进入统一审核。',btn(icon('plus')+' 提交资料','new-material'))+notice('资料解析与研判共用处理能力。同一来源保留关联，解析失败不会产出正式知识。')+table(['资料','输入类型','处理状态','操作'],items.map(x=>[`<strong>${esc(x.title)}</strong><p>${esc(x.id)} · ${esc(x.biz.join('、'))}</p>`,esc(x.type),esc(x.status),x.status.startsWith('已拆解')?btn('查看审核队列','goto','1,2'):x.status.startsWith('失败')?btn('补充资料','new-material'):'等待处理服务接入']))+(items.length?'':empty('当前业务暂无入库资料','点击“提交资料”，记录本业务的资料。'))}
function table(headers,rows){return `<div class="table-wrap"><table><thead><tr>${headers.map(x=>`<th scope="col">${x}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map(c=>`<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`}
function workTasks(work){return db.research.filter(task=>task.workId===work.id)}
function taskPhase(task){return {'已完成':'已分析','待研判':'待处理','证据不足':'需补充'}[task.status]||task.status||'待处理'}
function unitNumber(task){const number=Number(task.episodeNumber);return Number.isSafeInteger(number)&&number>0?number:null}
function currentUnitTask(tasks){return [...tasks].sort((a,b)=>(b.version||1)-(a.version||1)||String(b.submittedAt||b.lastAnalyzedAt||'').localeCompare(String(a.submittedAt||a.lastAnalyzedAt||''))||(b.attempt||0)-(a.attempt||0))[0]}
function workUnits(work){
 const comic=work.biz?.[0]==='AI漫剧',groups=new Map();
 for(const task of workTasks(work).filter(task=>task.scope!=='work')){const number=comic?unitNumber(task):null,key=comic?(number==null?'unknown:'+task.id:'ep:'+number):'content';if(!groups.has(key))groups.set(key,{key,number,tasks:[]});groups.get(key).tasks.push(task)}
 return [...groups.values()].map(unit=>({...unit,current:currentUnitTask(unit.tasks)})).sort((a,b)=>a.number==null?b.number==null?0:1:b.number==null?-1:a.number-b.number);
}
function workReports(work){
 const reports=(work.reports||[]).filter(report=>(report.inputRefs||[]).every(ref=>workTasks(work).some(task=>task.id===ref.taskId&&(task.version||1)===ref.version)));
 if(reports.length)return [...reports].sort((a,b)=>(b.version||1)-(a.version||1));
 // Read existing material reports without pretending they are full-work reports.
 return workTasks(work).filter(task=>['已完成','已分析'].includes(task.status)).map(task=>({id:'material-report:'+task.id,version:task.version||1,status:'未记录复核状态',createdAt:task.lastAnalyzedAt||'',legacy:true,coverage:unitNumber(task)?[unitNumber(task)]:[],inputRefs:[{taskId:task.id,version:task.version||1}],sourceTaskId:task.id})).sort((a,b)=>String(b.createdAt).localeCompare(String(a.createdAt)));
}
function workProgress(work){
 const units=workUnits(work),numbered=units.filter(unit=>unit.number!=null),counts={},knownCounts={};
 for(const unit of units){const phase=taskPhase(unit.current);counts[phase]=(counts[phase]||0)+1;if(unit.number!=null)knownCounts[phase]=(knownCounts[phase]||0)+1}
 const comic=work.biz?.[0]==='AI漫剧',partial=comic&&work.coverageSchema!=='episodes-v1'&&(work.collectedCount||0)>numbered.length;
 const collected=comic?Math.max(numbered.length,partial?work.collectedCount||0:0):Math.max(units.length,work.collectedCount||0);
 const analyzed=comic?Math.max(knownCounts['已分析']||0,partial?work.analyzedCount||0:0):units.filter(unit=>taskPhase(unit.current)==='已分析').length;
 return {units,counts,knownCounts,collected,analyzed,partial,unassigned:comic?units.length-numbered.length:0,parsed:numbered.filter(unit=>['待分析','分析中','已分析','分析失败'].includes(taskPhase(unit.current))).length,processing:(counts['解析中']||0)+(counts['分析中']||0),needsAttention:['待处理','待分析','解析失败','分析失败','需补充'].some(phase=>counts[phase]),report:workReports(work)[0]||null};
}
function workMatchesStatus(work,group){const p=workProgress(work);return group==='全部'||group==='处理中'&&p.processing>0||group==='需处理'&&p.needsAttention||group==='待复核'&&p.report?.status==='待复核'||group==='已有报告'&&!!p.report}
function workProgressText(work,p=workProgress(work)){
 const comic=work.biz?.[0]==='AI漫剧';
 const numbered=Object.entries(p.knownCounts).filter(([phase])=>phase!=='已分析').map(([phase,count])=>`${count}集${phase}`);
 const unknown=comic&&p.unassigned?`${p.unassigned}份未标集资料`:'';
 const content=!comic?Object.entries(p.counts).map(([phase,count])=>`${count}份${phase}`).join(' · '):numbered.join(' · ');
 return [content,unknown].filter(Boolean).join(' · ')||'暂无运行或异常任务';
}
function workCoverage(work){const p=workProgress(work),unit=work.biz?.[0]==='AI漫剧'?'集':'份';return `已收集 ${p.collected} ${unit} · 已分析 ${p.analyzed} ${unit}`}
function reportCoverageText(work,report){if(!report)return '尚无报告';if(report.legacy&&!report.coverage.length)return '既有材料报告 · 集号未标明';return `${report.legacy?'材料报告':'阶段报告'} v${report.version} · 覆盖 ${report.coverage?.length||0} ${work.biz?.[0]==='AI漫剧'?'集':'份'}`}
function unitLabel(work,unit){return work.biz?.[0]!=='AI漫剧'?'作品内容':unit.number==null?'未标集资料':`第 ${unit.number} 集`}
function unitEvidenceButtons(refs,report=null){return (refs||[]).filter(ref=>!report||(report.inputRefs||[]).some(input=>input.taskId===ref.taskId)).map(ref=>{const task=db.research.find(item=>item.id===ref.taskId);if(!task)return '';const number=unitNumber(task);return `<button class="evidence-link" data-action="work-evidence" data-id="${esc(JSON.stringify({taskId:task.id,start:ref.start||''}))}">${number?'第'+number+'集':'来源材料'}${ref.start?' · '+esc(ref.start)+'—'+esc(ref.end||ref.start):''} ${icon('out')}</button>`}).join('')}
function workRoute(){const root=`2/0/work/${encodeURIComponent(state.workId)}/${state.workView}`;return '#'+root+(state.workView==='episodes'?'/'+encodeURIComponent(state.workUnit)+'/'+encodeURIComponent(state.workTaskId):state.workView==='analysis'&&state.workReportId?'/'+encodeURIComponent(state.workReportId):'')}
function updateWorkRoute(){location.hash=workRoute()}
function restoreWorkspaceRoute(){
 const parts=location.hash.slice(1).replace(/^\//,'').split('/');const m=Number(parts[0]),t=Number(parts[1]);if(!modules[m]?.tabs[t])return false;
 state.module=m;state.tab=t;state.workId='';
 if(m===2&&t===0&&parts[2]==='work'){
  try{state.workId=decodeURIComponent(parts[3]||'');state.workView=['episodes','analysis','materials'].includes(parts[4])?parts[4]:'episodes';state.workUnit=state.workView==='episodes'?decodeURIComponent(parts[5]||''):'';state.workTaskId=state.workView==='episodes'?decodeURIComponent(parts[6]||''):'';state.workReportId=state.workView==='analysis'?decodeURIComponent(parts[5]||''):''}catch{state.workId=''}
  const number=Number(state.workUnit.startsWith('ep:')?state.workUnit.slice(3):0);state.episodeNavPage=Number.isSafeInteger(number)&&number>0?Math.floor((number-1)/100)+1:1;
 }
 return true;
}
function selectedWork(){return db.works.find(work=>work.id===state.workId&&work.biz?.includes(state.biz[0]))}
function episodeExtent(work){return workUnits(work).reduce((max,unit)=>Math.max(max,unit.number||0),Number.isSafeInteger(work.totalEpisodes)&&work.totalEpisodes>0?work.totalEpisodes:0)}
function emptyEpisodeEntry(work,number){return {key:'ep:'+number,number,title:work.episodeTitles?.[number]||'标题未获取',tasks:[],current:null}}
function workEpisodeEntries(work){
 const units=workUnits(work);if(work.biz?.[0]!=='AI漫剧')return units;
 const count=episodeExtent(work),pages=Math.max(1,Math.ceil(count/100)),page=Math.min(Math.max(1,state.episodeNavPage||1),pages),start=(page-1)*100+1;
 const indexed=new Map(units.filter(unit=>unit.number!=null).map(unit=>[unit.number,unit]));
 const entries=Array.from({length:Math.max(0,Math.min(100,count-start+1))},(_,index)=>indexed.get(start+index)||emptyEpisodeEntry(work,start+index));
 return [...entries,...units.filter(unit=>unit.number==null)];
}
function visibleWorkUnits(work){return workEpisodeEntries(work)}
function workPerformanceValue(work,key){
 const snapshot=work.performanceSnapshot||{},valid=value=>typeof value==='number'&&Number.isSafeInteger(value)&&value>=0;let value=snapshot[key];
 if(key==='interactions'&&!valid(value)){const parts=['likes','comments','shares','saves'].map(field=>snapshot[field]);value=parts.every(valid)?parts.reduce((sum,count)=>sum+count,0):null}
 return valid(value)?value.toLocaleString('zh-CN'):'';
}
function workPerformanceMeta(work){const snapshot=work.performanceSnapshot;if(!snapshot)return '';return [snapshot.provenance==='demo'?'演示表现数据':'表现快照',snapshot.platform||'',snapshot.coverageEpisodes?.length?'覆盖'+snapshot.coverageEpisodes.length+'集':snapshot.scope==='work'?'作品整体口径':'统计范围未记录',snapshot.capturedAt||'时间未记录'].filter(Boolean).join(' · ')}

function selectedWorkUnit(work){const units=visibleWorkUnits(work);return units.find(unit=>unit.key===state.workUnit)||units[0]||null}
function selectedUnitTask(unit){return unit?.tasks.find(task=>task.id===state.workTaskId)||unit?.current||null}
function selectedWorkReport(work){const reports=workReports(work);return reports.find(report=>report.id===state.workReportId)||reports[0]||null}

function workDate(value){return /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/.test(value||'')?value:topicTime(value)}
function workMediaUrl(value){
 if(typeof value!=='string'||!value.trim())return '';
 try{const url=new URL(value,location.href||'file:///prototype/index.html');return ['https:','http:','blob:','file:'].includes(url.protocol)||/^data:image\//i.test(value)?value:''}catch{return ''}
}
function workThumbnailSources(work){
 const tasks=workTasks(work),source=db.intel.find(item=>item.id===work.sourceId);
 const records=[work,...tasks.map(task=>task.sourceSnapshot).filter(Boolean),source].filter(Boolean);
 const covers=[...new Set(records.map(item=>workMediaUrl(item.coverUrl)).filter(Boolean))];
 const frames=[...new Set(records.map(item=>workMediaUrl(item.frameUrl)).filter(Boolean))];
 return {images:[...covers,...frames.filter(url=>!covers.includes(url))],video:records.map(item=>workMediaUrl(item.mediaUrl)).find(Boolean)||''};
}
const workThumbnailCache=new Map(),workThumbnailCleanups=[];
function clearWorkThumbnails(){workThumbnailCleanups.splice(0).forEach(cleanup=>cleanup())}
function captureWorkFrame(url,onResult){
 const video=document.createElement('video');let settled=false;
 video.crossOrigin='anonymous';video.muted=true;video.preload='auto';
 const finish=value=>{if(settled)return;settled=true;clearTimeout(timer);video.onloadeddata=video.onseeked=video.onerror=null;video.removeAttribute('src');video.load();onResult(value)};
 const timer=setTimeout(()=>finish(''),7000);
 const capture=()=>{try{if(!video.videoWidth||!video.videoHeight)return finish('');const canvas=document.createElement('canvas');canvas.width=116;canvas.height=Math.max(1,Math.round(video.videoHeight*116/video.videoWidth));canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);finish(canvas.toDataURL('image/jpeg',.82))}catch{finish('')}};
 video.onloadeddata=()=>{const point=Number.isFinite(video.duration)&&video.duration>0?Math.min(1,video.duration/3):0;if(point>0){video.onseeked=capture;video.currentTime=point}else capture()};
 video.onerror=()=>finish('');video.src=url;
 return ()=>finish('');
}
function hydrateWorkThumbnails(){
 if(state.module!==2||state.tab!==0)return;
 document.querySelectorAll('[data-work-thumbnail]').forEach(box=>{
  const work=db.works.find(item=>item.id===box.dataset.workThumbnail);if(!work)return;
  const sources=workThumbnailSources(work),key=JSON.stringify(sources);let stopped=false,timer,cancelFrame;
  const image=document.createElement('img');image.alt='';image.decoding='async';
  const fallback=()=>{if(stopped)return;box.classList.remove('is-loading');image.remove()};
  const show=url=>{if(stopped||!box.isConnected)return;clearTimeout(timer);image.onload=image.onerror=null;image.src=url;box.classList.remove('is-loading');box.classList.add('has-image');workThumbnailCache.set(key,url)};
  const next=()=>{
   if(stopped)return;clearTimeout(timer);
   const url=sources.images.shift();
   if(url){image.onload=()=>show(url);image.onerror=next;timer=setTimeout(next,5000);image.src=url}
   else if(sources.video){const video=sources.video;sources.video='';image.onload=image.onerror=null;cancelFrame=captureWorkFrame(video,result=>result?show(result):fallback())}
   else fallback();
  };
  if(!sources.images.length&&!sources.video)return;
  box.classList.add('is-loading');box.append(image);
  if(workThumbnailCache.has(key)){image.src=workThumbnailCache.get(key);box.classList.remove('is-loading');box.classList.add('has-image')}else next();
  workThumbnailCleanups.push(()=>{stopped=true;clearTimeout(timer);image.onload=image.onerror=null;cancelFrame?.()});
 });
}
function workCard(work){
 const p=workProgress(work),report=p.report;
 return `<article class="work-card" tabindex="0" role="group" aria-label="查看作品详情：${esc(work.title)}" data-work-id="${esc(work.id)}" data-action="work-detail" data-id="${esc(work.id)}"><div class="work-identity"><div class="work-cover" data-work-thumbnail="${esc(work.id)}" aria-hidden="true"><span class="work-cover-letter">${esc(work.title.slice(0,1))}</span></div><div class="work-identity-text"><button class="work-title" data-action="work-detail" data-id="${esc(work.id)}">${esc(work.title)}</button><span class="work-id">${esc(work.id)}</span><span class="work-genre">${esc(work.genre||'题材待补充')}</span><span class="work-genre">${esc(work.creatorId||'博主ID未记录')}</span></div></div><div class="work-cell"><span class="work-label">资料覆盖</span><strong>${workCoverage(work)}</strong><small>${work.biz?.[0]==='AI漫剧'?`总集数${work.totalEpisodes==null?'未知':esc(work.totalEpisodes)+' 集'}`:'按作品材料组织'}${p.partial?' · 含历史汇总':''}</small></div><div class="work-cell"><span class="work-label">处理进度</span><strong>${esc(workProgressText(work,p))}</strong>${work.biz?.[0]==='AI漫剧'&&!p.partial?`<small>已解析 ${p.parsed} 集</small>`:''}</div><div class="work-cell"><span class="work-label">最新报告</span><strong>${esc(reportCoverageText(work,report))}</strong><small>${report?esc(report.status)+' · '+esc(workDate(report.createdAt||'')):'有效分析形成后生成'}</small></div><div class="work-actions">${report?btn('查看报告','work-report',work.id,true):btn('查看作品','work-detail',work.id)}${btn('补充资料','new-material',work.id)}</div></article>`;
}
function workGenres(work){return (work.genre||'').split(/[·、,，/|]/).map(value=>value.trim()).filter(Boolean)}
function workSearchText(work){
 const tasks=workTasks(work),records=[work,...tasks,...tasks.map(task=>task.sourceSnapshot),db.intel.find(item=>item.id===work.sourceId)].filter(Boolean);
 return records.flatMap(item=>[item.title,item.id,item.genre,item.creatorId,item.creator,item.source]).filter(Boolean).join(' ').toLocaleLowerCase();
}
function workToolbar(all){
 const genres=[...new Set(all.flatMap(workGenres))].sort((a,b)=>a.localeCompare(b,'zh-CN'));
 return `<div class="toolbar"><label class="search">${icon('search')}<span class="sr-only">搜索作品名称、作品编号、博主ID或名称</span><input id="search" placeholder="搜索作品名称、编号、博主ID或名称" value="${esc(state.query)}" autocomplete="off"></label><label class="work-genre-filter"><span class="small muted">作品题材</span><select id="workGenreFilter" aria-label="作品题材筛选">${['全部题材',...genres].map(genre=>`<option value="${esc(genre)}" ${state.workGenre===genre?'selected':''}>${esc(genre)}</option>`).join('')}</select></label></div>`;
}
function researchPage(){
 if(state.workId)return workDetailPage();
 const all=scoped(db.works),groups=['全部','处理中','需处理','待复核','已有报告'];
 const counts=Object.fromEntries(groups.map(group=>[group,all.filter(work=>workMatchesStatus(work,group)).length]));
 const selected=groups.includes(state.status)?state.status:'全部';
 const items=all.filter(work=>workMatchesStatus(work,selected)&&(state.workGenre==='全部题材'||workGenres(work).includes(state.workGenre))&&(!state.query.trim()||workSearchText(work).includes(state.query.trim().toLocaleLowerCase())));
 return heading('内容研判','按作品汇总资料与分析任务。',btn(icon('plus')+' 新建研判','new-research'),'actions-left')+`<div class="work-status-tabs" role="group" aria-label="作品筛选，可交叉命中">${groups.map(group=>`<button class="${selected===group?'active':''}" data-action="work-status" data-id="${group}" aria-pressed="${selected===group}">${group} <span>(${counts[group]})</span></button>`).join('')}</div>`+workToolbar(all)+`<div class="work-list" aria-label="作品列表">${items.map(workCard).join('')||empty('没有匹配的作品','调整状态、题材或搜索词，或新建一部作品。')}</div>`;
}
function publicationPage(){const items=scoped(db.publications);return heading('发布复盘','对齐内容版本、指标和观察窗口，再比较预测与实绩。',btn(icon('plus')+' 登记发布','new-publication'))+notice('没有事前预测的发布也可复盘，但不进入盲预测校准。缺失实绩显示“未获取”，不记作零。')+table(['发布记录','预测与窗口','实绩来源','操作'],items.map(x=>[`<strong>${esc(x.title)}</strong><p>${x.id} · ${x.content} v${x.version}</p>`,`无事前预测<p>${x.window}</p>`,`${x.source}<p>点赞 ${x.likes??'未获取'} · 转发 ${x.shares??'未获取'}</p>`,btn('对账与补录','publication-detail',x.id)]))+(items.length?'':empty('当前业务暂无发布记录','登记当前业务的发布链接，并关联对应内容版本。'))}
function validationPage(){const items=scoped(validationSamples);return heading('规律验证','单条案例提出假设，独立样本支持结论。')+notice('此页为验证结构提案。样本不足的候选不能启用；正式标准仍由控制台配置发布。')+table(['候选规律','新旧标准','验证状态','操作'],items.map(x=>[`${esc(x.title)}<p>候选 ${x.id} · ${esc(x.biz.join('、'))}</p>`,esc(x.standard),esc(x.status),btn('查看验证依据','validation-detail',x.id)]))+(items.length?'':empty('当前业务暂无候选规律','研判与复盘形成候选后，在这里验证。'))}

// UI-only model references. No raw secret, provider request or active runtime change.
const modelCapabilities={text:'单文本',vision:'多模态'};
const modelStages=[
 ['decompose','脚本分析','text'],['report','输出分析报告','text'],['feedback','用户评论分析','text'],['insight','情报洞察','text'],
 ['topic','选题生成','text'],['topic_score','选题评分','text'],['evaluate','质量评价','text'],['predict','市场预测','text'],
 ['extract','知识提炼','text'],['review','AI审核','text'],['retrospect','复盘分析','text'],['visual','视频分析','vision'],['image','画面与文字解析','vision']
];
function migrateModelSources(){
 let changed=false;
 const active=db.modelConnections.filter(source=>Object.hasOwn(modelCapabilities,source.capability));
 for(const source of db.modelConnections){if(active.includes(source))continue;(db.legacyModelConnections||=[]).push(structuredClone(source));changed=true}
 db.modelConnections=active;
 for(const [business,bindings] of Object.entries(db.modelBindings)){
  for(const [stage,sourceId] of Object.entries(bindings)){
   const required=modelStages.find(item=>item[0]===stage)?.[2],source=active.find(item=>item.id===sourceId);
   if(required&&source?.capability===required)continue;
   (db.legacyModelBindings||=[]).push({business,stage,sourceId});delete bindings[stage];changed=true;
  }
 }
 if(changed)save();
}
migrateModelSources();

function safeConfigUrl(value){try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password&&!u.search&&!u.hash}catch{return false}}
function modelConfigPage(){
 const connections=db.modelConnections,bindings=db.modelBindings[state.biz[0]]||{};
 return heading('模型配置','')+
 notice('当前为配置交互演示：只保存本地草稿，不调用模型、不测试连接、不改变已运行任务。密钥仅填写服务端引用名。')+
 Object.entries(modelCapabilities).map(([capability,label])=>{
  const sources=connections.filter(x=>x.capability===capability);
  return `<section class="detail-block model-section" aria-labelledby="model-group-${capability}"><div class="model-section-head"><div><h2 id="model-group-${capability}">${label}模型源 <span class="small muted">${sources.length} 个</span></h2><p class="small muted">${capability==='text'?'用于脚本、报告、评论等文本处理':'用于视频、画面等多模态内容分析'} · 可新增多个来源</p></div>${btn(icon('plus')+' 新增'+label+'模型源','new-model',capability)}</div>${sources.length?table(['模型源名称','供应商／模型','接入地址','版本／状态','操作'],sources.map(x=>[`<strong>${esc(x.name)}</strong>`,`${esc(x.provider)}<p>${esc(x.model)}</p>`,`<span class="model-endpoint">${esc(x.endpoint)}</span>`, `v${x.version}<p>本地草稿 · 未验证</p>`,btn('编辑','edit-model',x.id)])):`<div class="empty"><h3>尚未配置${label}模型源</h3><p>新增后，可供多个对应环节选择。</p></div>`}</section>`;
 }).join('')+
 (db.legacyModelConnections?.length?`<p class="small muted">${db.legacyModelConnections.length} 条旧版其他类型配置已保留在本地历史中，未自动归入单文本或多模态。</p>`:'')+
 `<section class="detail-block model-section"><div class="model-section-head"><h2>环节使用模型源</h2><span class="small muted">${esc(state.biz[0])} · 各环节独立选择，可复用同一来源</span></div><form id="modelBindingsForm">${Object.entries(modelCapabilities).map(([kind,label])=>`<div class="model-stage-group"><h3>${label}处理环节</h3><div class="model-bindings">${modelStages.filter(item=>item[2]===kind).map(([key,name])=>`<div class="field"><label for="model-stage-${key}">${name}</label><select id="model-stage-${key}" name="binding:${key}"><option value="">暂不配置</option>${connections.filter(x=>x.capability===kind).map(x=>`<option value="${esc(x.id)}" ${bindings[key]===x.id?'selected':''}>${esc(x.name)} · ${esc(x.model)}</option>`).join('')}</select></div>`).join('')}</div></div>`).join('')}<p class="form-error" id="modelBindingError" role="alert"></p><button class="btn primary" type="submit">保存环节分配</button></form></section>`;
}
function modelConfigForm(id='',kind='text'){
 const x=db.modelConnections.find(x=>x.id===id)||{name:'',provider:'OpenAI兼容',endpoint:'',model:'',capability:Object.hasOwn(modelCapabilities,kind)?kind:'text',secretRef:'',timeout:60,retries:1,maxTokens:4096};
 const field=(label,name,value,type='text',extra='')=>`<div class="field"><label for="model-${name}">${label}</label><input id="model-${name}" name="${name}" type="${type}" value="${esc(value)}" ${extra} required></div>`;
 openDialog(id?'编辑模型源':'新增'+modelCapabilities[x.capability]+'模型源',`<form id="modelConfigForm"><input type="hidden" name="id" value="${esc(id)}">${field('模型源名称','name',x.name,'text','maxlength="80"')}<div class="model-form-grid"><div class="field"><label for="model-provider">供应商／接口协议</label><select id="model-provider" name="provider">${['OpenAI兼容','DeepSeek','其他适配器'].map(p=>`<option ${x.provider===p?'selected':''}>${p}</option>`).join('')}</select></div><div class="field"><label for="model-capability">模型类型</label><select id="model-capability" name="capability">${Object.entries(modelCapabilities).map(([key,label])=>`<option value="${key}" ${x.capability===key?'selected':''}>${label}</option>`).join('')}</select></div></div>${field('API地址','endpoint',x.endpoint,'url','placeholder="https://api.example.com/v1" maxlength="500"')}${field('模型名称','model',x.model,'text','maxlength="120" placeholder="供应商提供的模型标识"')}${field('服务端密钥引用','secretRef',x.secretRef,'text','maxlength="100" placeholder="例如 MODEL_API_KEY，勿填密钥原文" autocomplete="off"')}<div class="model-form-grid">${field('超时（秒）','timeout',x.timeout,'number','min="1" max="600" step="1"')}${field('重试次数','retries',x.retries,'number','min="0" max="3" step="1"')}${field('最大输出长度（Token）','maxTokens',x.maxTokens,'number','min="1" max="131072" step="1"')}</div><p class="small muted">同一来源可被多个同类环节引用。仅保存配置草稿，历史任务保留原配置版本。</p><p class="form-error" id="formError" role="alert"></p></form>`,btn('取消','close')+'<button class="btn primary" type="submit" form="modelConfigForm">保存配置草稿</button>',true);
}
function submitModelConfig(values){
 const error=document.getElementById('formError'),name=String(values.name||'').trim(),provider=String(values.provider||''),endpoint=String(values.endpoint||'').trim(),model=String(values.model||'').trim(),secretRef=String(values.secretRef||'').trim(),capability=String(values.capability||'');
 if(!name||name.length>80||!model||model.length>120||!Object.hasOwn(modelCapabilities,capability)||!['OpenAI兼容','DeepSeek','其他适配器'].includes(provider)){error.textContent='请填写模型源名称、供应商、模型名称，并选择单文本或多模态。';return}
 if(endpoint.length>500||!safeConfigUrl(endpoint)){error.textContent='API地址须为HTTPS地址，且不能含账号、密码、查询参数或片段。';return}
 if(!/^[A-Z][A-Z0-9_]{0,99}$/.test(secretRef)){error.textContent='请填写大写字母、数字和下划线组成的服务端密钥引用，不能填写密钥原文。';return}
 const timeout=Number(values.timeout),retries=Number(values.retries),maxTokens=Number(values.maxTokens);
 if(![timeout,retries,maxTokens].every(Number.isSafeInteger)||timeout<1||timeout>600||retries<0||retries>3||maxTokens<1||maxTokens>131072||[values.timeout,values.retries,values.maxTokens].some(v=>!String(v??'').trim())){error.textContent='请检查超时、重试次数与输出长度的有效范围。';return}
 let old=values.id?db.modelConnections.find(x=>x.id===values.id):null;
 if(values.id&&!old){error.textContent='原配置不存在，请关闭后重新打开。';return}
 if(db.modelConnections.some(x=>x.id!==values.id&&x.name.toLocaleLowerCase()===name.toLocaleLowerCase())){error.textContent='已有同名模型源，请修改名称。';return}
 if(old&&old.capability!==capability&&Object.values(db.modelBindings).some(bindings=>Object.values(bindings).includes(old.id))){error.textContent='此模型已被环节引用，请先取消相关分配，再修改模型类型。';return}
 const patch={name,provider,endpoint,model,secretRef,capability,timeout,retries,maxTokens};
 if(old){const {versions,...snapshot}=old;old.versions=[...(versions||[]),structuredClone(snapshot)];Object.assign(old,patch,{version:old.version+1})}
 else db.modelConnections.push({id:'MODEL-'+Date.now()+'-'+db.modelConnections.length,...patch,version:1,versions:[]});
 save();draftDirty=false;closeDialog();render();toast('模型配置草稿已保存，未验证或启用');
}
function submitModelBindings(values){
 const patch={},error=document.getElementById('modelBindingError');
 for(const [key,label,capability] of modelStages){const id=String(values['binding:'+key]||'');if(!id)continue;const model=db.modelConnections.find(x=>x.id===id);if(!model||model.capability!==capability){error.textContent=label+'所选模型源不存在或类型不匹配。';return}patch[key]=id}
 db.modelBindings[state.biz[0]]=patch;save();draftDirty=false;render();toast('环节分配草稿已保存，未改变服务端运行配置');
}

function consolePage(){switch(state.tab){case 5:return modelConfigPage();case 1:return heading('处理配置','解析、知识提炼与评价共用版本化处理规则。')+`<div class="toolbar"><span class="small muted">模型连接在独立模型配置中统一维护，处理环节仅引用。</span>${btn('模型配置','goto','3,5')}</div>`+table(['处理模板','适用资料','当前版本','操作'],[['叙事文本拆解','剧本 / 小说文本','v1.2',btn('查看配置','config-detail','narrative')],['商品事实检查','商品文本 / 参考资料','v1.0',btn('查看配置','config-detail','product')],['视频内容解析','视频 / 字幕 / 关键帧','v0.3 · 配置提案',btn('查看配置','config-detail','video')]]);case 2:return heading('评价标准','按业务与对象定义判断标准，历史报告保留原版本。')+table(['评价标准','适用对象','版本与状态','操作'],[['叙事清晰度','AI漫剧 / 脚本','v2.0 · 已生效',btn('查看维度','rubric-detail','story')],['视听表达','故事短片 / 成片','v1.3 · 已生效',btn('查看维度','rubric-detail','film')],['商品表达与事实','电商短视频 / 成片','v1.1 · 已生效',btn('查看维度','rubric-detail','commerce')]])+`<div style="margin-top:16px">${btn('查看候选标准验证','goto','2,2')}</div>`;case 3:return heading('权限管理','成员身份与操作授权分开，管理员同样遵守审核流程。')+notice('权限矩阵为只读设计样例；实际权限必须由服务端验证，原型不提供真实访问控制。')+table(['成员 / 角色','授权范围','审核与发布','状态'],[['南哥 / 演示管理员','全部示例对象','审核、标准发布、配置管理','演示授权'],['知识编辑 / 示例','知识浏览、上传、编辑','无标准发布权限','演示授权'],['评测人员 / 示例','内容评价、复盘、验证','无知识审核权限','演示授权']]);default:return heading('运行状态','查看采集、解析和评价任务，定位失败原因。')+table(['任务','输入与版本','运行状态','操作'],[['来源采集 · JOB-091','SRC-01 · 09:42','演示成功',btn('查看记录','job-detail','JOB-091')],['正文解析 · JOB-092','SRC-03 · v1',db.retries.length?'重试失败 · 连接器未接入':'失败 · 正文不完整',btn('模拟重试','retry-job','JOB-092')],['知识AI审核 · JOB-093','K-033 · v1','演示成功',btn('查看记录','job-detail','JOB-093')]])}}

function render(){
 clearWorkThumbnails();hideFeedFullText();
 publish();
 if(state.mode!=='正常'){page.innerHTML=heading(modules[state.module].tabs[state.tab],'')+stateView();return}
 page.innerHTML=renderWorkspace(state.module,state.tab,{
   topicPage,knowledgePage,intake,researchPage,publicationPage,validationPage,consolePage
 });
 hydrateWorkThumbnails();
}
function stateView(){if(state.mode==='加载中')return `<div class="card state-panel" role="status"><span class="muted">正在获取内容…</span><div class="skeleton"></div><div class="skeleton"></div>${btn('结束加载预览','normal')}</div>`;const messages={'空数据':['还没有内容','添加第一份资料，开始积累。'],'失败':['暂时无法获取内容','连接已中断；可以重试，不会显示伪造的成功结果。'],'无权限':['当前账号没有访问权限','请联系管理员申请当前对象的访问范围。'],'证据不足':['材料不足，暂不能判断','缺少正文或必要参考资料，请先补充。'],'评价过期':['内容版本已变化','旧评价仍保留，但不能作为新版内容的评价。']};let m=messages[state.mode];return `<div class="empty">${icon('info')}<h2>${m[0]}</h2><p>${m[1]}</p>${btn(state.mode==='失败'?'重试（恢复演示）':'返回正常页面','normal')}</div>`}
function navigate(m,t=0){state.workId='';state.workTaskId='';state.workUnit='';state.workReportId='';state.module=m;state.tab=t;state.query='';state.workGenre='全部题材';state.knowledgeCategory='全部';state.status='全部状态';state.stage='全部环节';state.mode='正常';location.hash=`${m}/${t}`;render()}
function openDialog(title,body,foot='',drawer=false){intakeWorkContext=null;sparkCapture=null;brainstormContext=null;topicEditContext=null;lastFocus=document.activeElement;draftDirty=false;dialog.className=drawer?'drawer':'';dialog.innerHTML=`<div class="dialog-head"><h2 id="dialogTitle">${title}</h2><button class="iconbtn" data-action="close" aria-label="关闭">${icon('close')}</button></div><div class="dialog-body">${body}</div>${foot?`<div class="dialog-foot">${foot}</div>`:''}`;if(!dialog.open)dialog.showModal()}
function closeDialog(){if(draftDirty&&!confirm('有尚未保存的修改，确定放弃吗？'))return;const wasSpark=!!sparkCapture;draftDirty=false;sparkCapture=null;brainstormContext=null;intakeWorkContext=null;topicEditContext=null;dialog.close();if(wasSpark)render();if(lastFocus?.isConnected)lastFocus.focus()}
listen(dialog,'cancel',e=>{e.preventDefault();closeDialog()});listen(dialog,'input',e=>{if(e.target.id==='sparkBody'&&sparkCapture)saveSparkText(e.target.value);else if(brainstormContext&&e.target.id.startsWith('brainstorm-'))brainstormInput(e.target);else{draftDirty=true;if([...Object.keys(topicEditorFields),'bizInput'].includes(e.target.id))refreshTopicEditorState()}});
function detailIntro(x){return `<h3 class="detail-title">${esc(x.title)}</h3><div class="meta">${tags(x.biz||[])}<span>${x.id} ${x.version?'· v'+x.version:''}</span></div>`}
function sourceEvidence(id,snapshot=null){const s=snapshot?{...snapshot,id,source:snapshot.creator,time:snapshot.collectedAt,evidence:snapshot.evidence||'提交时保存的演示快照。'}:db.intel.find(x=>x.id===id);return s?`<div class="detail-block"><h3>来源与证据</h3><div class="evidence">${esc(s.evidence)}<div class="small" style="margin-top:8px">${s.id} · ${esc(s.platform||s.source)} · 演示采集 ${esc(s.sourceDate||'')} ${esc(s.time||'未记录')}</div></div><p class="small" style="margin-top:8px">${s.url?`<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">打开原视频 ${icon('out')}</a>`:'原视频链接未获取'}</p></div>`:`<div class="detail-block"><h3>来源与证据</h3><p>人工输入；来源须在审核前补充核实。</p></div>`}
function topicDetail(id){topicForm(id)}
function topicForm(id='',sourceId=''){
 const x=db.topics.find(topic=>topic.id===id),source=db.intel.find(item=>item.id===sourceId);
 const draft=x||{id:'',title:source?.title||'',summary:source?.summary||'',biz:[source?.biz?.[0]||state.biz[0]],audience:'',version:1,origin:'手工灵感',evaluation:'未评价'};
 const pool=x&&x.status!=='候选',biz=draft.biz?.[0]||'';
 const history=x?`<section class="detail-block"><h3>版本与交接记录</h3><div class="timeline">${(x.history||[]).map(h=>`<div>${esc(h)}</div>`).join('')}</div>${(x.versions||[]).map(v=>`<details class="evidence"><summary>查看 v${esc(v.version)} 历史内容</summary><h3>${esc(v.title)}</h3><p>${esc(topicLogline(v))}</p><h4>角色设定</h4><p class="human-review-text">${esc(topicCharactersText(v)||'未记录')}</p><h4>全局节奏</h4><p class="human-review-text">${esc(v.globalRhythm||'未记录')}</p>${renderGenreLoadAssessment(v.genreLoadAssessment)}</details>`).join('')}</section>`:'';
 const body=`${x?detailIntro(x):''}<form id="topicForm"><input type="hidden" name="id" value="${esc(id)}"><input type="hidden" name="sourceId" value="${esc(x?.sourceId||sourceId)}"><div class="field"><label for="titleInput">选题标题</label><input id="titleInput" name="title" maxlength="90" required value="${esc(draft.title)}"></div><div class="review-intake-row"><div class="field"><label for="bizInput">主业务线</label><select id="bizInput" name="biz"><option value="">暂不选择（草稿）</option>${businesses.map(b=>`<option value="${b}" ${biz===b?'selected':''} ${b==='电商短视频'?'disabled':''}>${b}</option>`).join('')}</select></div><div class="field"><label for="audienceInput">目标人群</label><input id="audienceInput" name="audience" value="${esc(draft.audience||'')}" placeholder="这条内容为谁而作"></div></div><section class="topic-editor-section"><h3>Logline</h3><div class="field"><label class="sr-only" for="topicLogline">Logline</label><textarea id="topicLogline" name="logline" required placeholder="用一句话写清主角、目标、阻碍和核心情绪">${esc(topicLogline(draft))}</textarea></div></section><section class="topic-editor-section"><h3>角色设定</h3><div class="field"><label class="sr-only" for="topicCharacterSettings">角色设定</label><textarea id="topicCharacterSettings" name="characterSettings" placeholder="自由编写主角、反派、配角及人物关系">${esc(topicCharactersText(draft))}</textarea></div></section><section class="topic-editor-section"><h3>全局节奏</h3><div class="field"><label class="sr-only" for="topicGlobalRhythm">全局节奏</label><textarea id="topicGlobalRhythm" name="globalRhythm" placeholder="阶段目标、冲突升级、关键钩子与回收安排">${esc(draft.globalRhythm||'')}</textarea></div></section><p class="small muted">${x?'实质修改保存为新版本并请求重新评分；原结果留在历史版本。':'人工草稿不自动产生AI评分。'}</p><p id="formError" class="form-error" role="alert"></p></form><div id="topicAssessmentScope" ${biz==='AI漫剧'?'':'hidden'}>${genreLoadDetail(draft)}</div>${x?.ideaRefs?.length?`<section class="detail-block"><h3>来源闪念</h3>${x.ideaRefs.map(ref=>`<details class="evidence"><summary>${esc(ref.title)} · v${esc(ref.version)}</summary><p class="human-review-text">${esc(ref.text)}</p></details>`).join('')}</section>`:x?sourceEvidence(x.sourceId):''}${history}`;
 const foot=btn('取消','close')+`<button type="submit" id="topicSaveButton" ${x?'disabled':''} form="topicForm" class="btn ${pool?'':'primary'}" value="draft">${x?'保存并重新评分':'保存草稿'}</button>`+(pool?btn('复制','copy-topic',id)+btn('导出 Markdown','export-topic',id,true)+(x.status!=='已采用'?btn('标记已采用','adopt-topic',id):''):'<button type="submit" form="topicForm" class="btn" value="production">加入待生产</button>');
 openDialog(x?'选题详情':'新增选题',body,foot,true);
 for(const [field,key] of Object.entries(topicEditorFields))document.getElementById(field).value=topicBlueprintInput(draft)[key];document.getElementById('bizInput').value=biz;
 topicEditContext={existing:!!x,baseline:comparableTopicContent(topicEditorContent()),scoreLabel:genreLoadScoreLabel(draft)};refreshTopicEditorState();
}
function knowledgeDetail(id){const x=db.knowledge.find(k=>k.id===id),review=['待AI审核','待人工审核'].includes(x.status);openDialog(review?'知识审核':'知识详情',detailIntro(x)+`<div class="steps"><span class="done">候选 v${x.version}</span>→<span class="${x.ai==='通过'?'done':''}">AI审核：${x.ai}</span>→<span class="${x.status==='已入库'?'done':''}">人工审核：${x.status==='已入库'?'通过':'待完成'}</span></div><div class="detail-block"><h3>知识内容</h3><p>${esc(x.summary)}</p></div><dl class="keyvalues"><dt>知识分类</dt><dd>${esc(knowledgeCategoryLabel(x))}</dd><dt>知识类型</dt><dd>${esc(x.type)}</dd><dt>适用环节</dt><dd>${x.stage}</dd><dt>当前状态</dt><dd>${x.status}</dd><dt>责任人</dt><dd>知识编辑 · 演示身份</dd></dl><div class="detail-block"><h3>证据与适用限制</h3><div class="evidence">${esc(x.evidence)}</div></div>`+(review?`<div class="detail-block"><h3>AI审核意见（演示）</h3><p>${x.ai==='通过'?'来源支持当前表述，适用范围已标注。仍需人工核实后发布。':x.ai==='需修订'?'结论包含未经验证的效果承诺，不满足来源支持要求。':'尚未执行审核，本原型不调用模型。'}</p></div><label class="checkrow"><input id="reviewConfirm" type="checkbox">已人工核实来源、适用范围及限制，批准当前版本</label>`:''),review?`${btn('修订候选','edit-knowledge',id)}<button class="btn primary" data-action="approve-knowledge" data-id="${id}" ${x.ai!=='通过'?'disabled':''}>人工通过并入库</button>`:x.status==='已入库'?btn('移入回收站','delete-knowledge',id):btn('关闭','close'),true)}
function knowledgeForm(id=''){const x=db.knowledge.find(k=>k.id===id);openDialog(x?'修订候选知识':'人工新增知识',`<form id="knowledgeForm"><input name="id" type="hidden" value="${id}"><div class="field"><label for="kt">知识标题</label><input id="kt" name="title" required maxlength="90" value="${esc(x?.title||'')}"></div><div class="field"><label for="kb">业务线</label><select id="kb" name="biz">${businesses.map(b=>`<option ${(x?x.biz.includes(b):state.biz[0]===b)?'selected':''}>${b}</option>`).join('')}</select></div><div class="field"><label for="ks">适用环节</label><select id="ks" name="stage">${['选题','脚本','资产','成片'].map(s=>`<option ${x?.stage===s?'selected':''}>${s}</option>`).join('')}</select></div><div class="field"><label for="knowledgeCategory">知识分类</label><select id="knowledgeCategory" name="category" required><option value="">请选择知识分类</option>${knowledgeCategories.map(category=>`<option value="${category}" ${(x?x.category:state.knowledgeCategory)===category?'selected':''}>${category}</option>`).join('')}</select></div><div class="field"><label for="kc">知识内容</label><textarea id="kc" name="summary" required>${esc(x?.summary||'')}</textarea></div><div class="field"><label for="ke">来源与适用限制</label><textarea id="ke" name="evidence" required>${esc(x?.evidence||'')}</textarea></div>${notice('提交后进入待AI审核，人工新增同样不能跳过双审。模型未接入，原型不会自动标记审核通过。')}<p class="form-error" id="formError" role="alert"></p></form>`,btn('取消','close')+`<button class="btn primary" type="submit" form="knowledgeForm">提交候选</button>`)}
let intakeWorkContext=null;
function normalizedWorkName(value){return (value||'').normalize('NFKC').trim().toLocaleLowerCase()}
function suggestedIntakeWork(video,pending,biz){
 if(biz!=='AI漫剧')return null;
 const works=db.works.filter(work=>work.biz?.includes('AI漫剧'));
 const linkedTask=db.research.find(task=>task.sourceId===video.id&&works.some(work=>work.id===task.workId));
 const stable=works.find(work=>work.id===(pending?.workId||video.workId))||works.find(work=>work.id===linkedTask?.workId)||works.find(work=>work.sourceId===video.id);
 if(stable)return stable;
 // Prototype pre-match only: no model is invoked and fuzzy titles never merge works.
 const clue=normalizedWorkName(video.workTitle||video.title);
 const matches=works.filter(work=>normalizedWorkName(work.title)===clue&&(!video.creatorId||!work.creatorId||video.creatorId===work.creatorId));
 return matches.length===1?matches[0]:null;
}
function closeIntakeWorkOptions(){
 if(!intakeWorkContext)return;
 document.getElementById('reviewWorkOptions').hidden=true;
 const input=document.getElementById('reviewWorkName');input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');
}
function renderIntakeWorkOptions(query){
 if(!intakeWorkContext||document.getElementById('reviewBiz').value!=='AI漫剧')return;
 const needle=normalizedWorkName(query);
 const matches=db.works.filter(work=>work.biz?.includes('AI漫剧')&&(!needle||normalizedWorkName(work.title).includes(needle)));
 intakeWorkContext.options=matches.map(work=>work.id);intakeWorkContext.active=-1;
 const box=document.getElementById('reviewWorkOptions');
 box.innerHTML=matches.map((work,i)=>`<button type="button" role="option" id="reviewWorkOption-${i}" aria-selected="false" tabindex="-1" data-action="review-work-select" data-id="${esc(work.id)}"><span>${esc(work.title)}</span><small>${esc(work.id)} · ${esc(work.genre||'题材待补充')}</small></button>`).join('')||'<p class="small muted">没有匹配作品，可输入新作品名称后提交。</p>';
 box.hidden=false;document.getElementById('reviewWorkName').setAttribute('aria-expanded','true');
}
function chooseIntakeWork(id){
 if(!intakeWorkContext||document.getElementById('reviewBiz').value!=='AI漫剧')return;
 const work=db.works.find(work=>work.id===id&&work.biz?.includes('AI漫剧'));if(!work)return;
 document.getElementById('reviewWorkName').value=work.title;document.getElementById('reviewWorkId').value=work.id;
 document.getElementById('reviewTotalEpisodes').value=work.totalEpisodes??'';
 document.getElementById('reviewWorkHint').textContent='已选择已有作品：'+work.id;
 draftDirty=true;document.getElementById('reviewWorkName').focus();closeIntakeWorkOptions();
}
function toggleIntakeComicFields(biz){
 const enabled=biz==='AI漫剧';
 document.getElementById('reviewWorkField').hidden=!enabled;document.getElementById('reviewEpisodeFields').hidden=!enabled;
 for(const id of ['reviewWorkName','reviewWorkId','reviewTotalEpisodes','reviewEpisodeNumber'])document.getElementById(id).disabled=!enabled;
 document.getElementById('reviewWorkName').required=enabled;
 if(enabled&&intakeWorkContext&&!document.getElementById('reviewWorkName').value){const work=suggestedIntakeWork(intakeWorkContext.video,intakeWorkContext.pending,biz);if(work){document.getElementById('reviewWorkName').value=work.title;document.getElementById('reviewWorkId').value=work.id;document.getElementById('reviewTotalEpisodes').value=work.totalEpisodes??'';document.getElementById('reviewWorkHint').textContent='已匹配已有作品，请确认归属'}}
 if(!enabled)closeIntakeWorkOptions();
}
function intakeWorkKeydown(e){
 if(e.target?.id!=='reviewWorkName'||!intakeWorkContext)return false;
 const box=document.getElementById('reviewWorkOptions');
 if(e.key==='Escape'&&!box.hidden){closeIntakeWorkOptions();e.preventDefault();e.stopPropagation?.();return true}
 if(e.key==='ArrowDown'||e.key==='ArrowUp'){
  if(box.hidden)renderIntakeWorkOptions(e.target.value);
  const count=intakeWorkContext.options.length;if(!count)return false;
  const old=intakeWorkContext.active;
  if(old>=0)document.getElementById('reviewWorkOption-'+old).setAttribute('aria-selected','false');
  intakeWorkContext.active=(old+(e.key==='ArrowDown'?1:old<0?0:-1)+count)%count;
  const option=document.getElementById('reviewWorkOption-'+intakeWorkContext.active);option.setAttribute('aria-selected','true');option.scrollIntoView({block:'nearest'});
  e.target.setAttribute('aria-activedescendant',option.id);e.preventDefault();return true;
 }
 if(e.key==='Enter'&&!box.hidden&&intakeWorkContext.active>=0){e.preventDefault();chooseIntakeWork(intakeWorkContext.options[intakeWorkContext.active]);return true}
 if(e.key==='Tab')closeIntakeWorkOptions();
 return false;
}
const learningPointOptions=['画面质感','动效冲击','世界观设定','剧情反转','人物塑造','情绪共鸣','节奏控制','镜头语言'];
function researchIntake(id,sourceDate=state.module===0&&state.tab===0?latestFeedDate:latestFeedDate){
 const video=feedSource(id,sourceDate);if(!video){toast('原始内容不存在，无法发起研判');return}
 const pending=db.research.find(r=>r.sourceId===id&&(r.sourceDate||latestFeedDate)===sourceDate&&['待研判','待分析'].includes(r.status));
 const selected=new Set(pending?.learningTags||[]);
 const reviewBusiness=pending?.biz?.[0]||video.biz?.[0];
 const associatedWork=suggestedIntakeWork(video,pending,reviewBusiness);
 const workName=associatedWork?.title||(reviewBusiness==='AI漫剧'?pending?.workName:'')||video.workTitle||'';
 const episodeNumber=pending?.episodeNumber??video.episodeNumber??'';
 const totalEpisodes=pending&&Object.hasOwn(pending,'totalEpisodes')?pending.totalEpisodes:associatedWork?.totalEpisodes;
 const stat=(label,value)=>`<div><dt>${label}</dt><dd>${compactNum(value)}</dd></div>`;
 const source=video.url?`<a href="${esc(video.url)}" target="_blank" rel="noopener noreferrer">${esc(video.title)} ${icon('out')}</a>`:esc(video.title);
 const novel=video.sourceType==='novel';
 const body=`<div class="review-summary"><h3 class="detail-title">${source}</h3><div class="meta">${tags(video.biz||[])}${video.genre?`<span class="tag">${esc(video.genre)}</span>`:''}<span>${esc(video.platform||'平台未记录')} · ${esc(video.source||'博主未记录')} · ${esc(video.time||'时间未记录')}</span></div><p class="rank-plot">${esc(video.plot||video.summary||'剧情简介未获取')}</p><dl class="review-stats ${novel?'novel-review-stats':''}">${novel?stat('在读人数',video.readers):stat('赞',video.likes)+stat('评',video.comments)+stat('转',video.shares)+stat('藏',video.saves)}</dl></div>${notice('原始内容和互动数据为演示快照。提交后只记录人工判断与待分析任务，原型不会调用AI生成报告。')}${novel?'':researchFeedbackBlock(video.audienceFeedback)}<form id="researchIntakeForm" class="review-form"><input type="hidden" name="sourceId" value="${esc(id)}"><input type="hidden" name="sourceDate" value="${esc(sourceDate)}"><p class="small muted">情报日期：${esc(sourceDate)} · 演示快照</p><fieldset><legend>人工评级 · S / A / B / C</legend><div class="review-options">${['S','A','B','C'].map(grade=>`<label class="review-option"><input type="radio" name="grade" value="${grade}" ${pending?.rating===grade?'checked':''}><span>${grade}</span></label>`).join('')}</div></fieldset><div class="review-intake-row"><div class="field"><label for="reviewBiz">业务类型标签</label><select id="reviewBiz" name="biz">${businesses.map(b=>`<option value="${b}" ${(pending?.biz?.[0]||video.biz?.[0])===b?'selected':''}>${b}</option>`).join('')}</select></div><div class="field" id="reviewWorkField" ${reviewBusiness==='AI漫剧'?'':'hidden'}><label for="reviewWorkName">作品名称</label><div class="review-work-combobox"><input id="reviewWorkName" name="workName" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="reviewWorkOptions" aria-describedby="reviewWorkHint" autocomplete="off" maxlength="100" value="${esc(workName)}" placeholder="搜索已有作品或输入新作品名称" ${reviewBusiness==='AI漫剧'?'required':'disabled'}><input id="reviewWorkId" name="workId" type="hidden" value="${esc(associatedWork?.id||'')}" ${reviewBusiness==='AI漫剧'?'':'disabled'}><div id="reviewWorkOptions" class="review-work-options" role="listbox" aria-label="匹配的作品" hidden></div></div><small id="reviewWorkHint">${associatedWork?'已匹配已有作品，请确认归属':'选择已有作品，或输入新作品名称'}</small></div></div><div class="review-intake-row" id="reviewEpisodeFields" ${reviewBusiness==='AI漫剧'?'':'hidden'}><div class="field"><label for="reviewTotalEpisodes">总集数</label><input id="reviewTotalEpisodes" name="totalEpisodes" type="number" min="1" step="1" inputmode="numeric" value="${esc(totalEpisodes??'')}" placeholder="例如：80" aria-describedby="reviewTotalEpisodesHint" ${reviewBusiness==='AI漫剧'?'':'disabled'}><small id="reviewTotalEpisodesHint">留空表示未知</small></div><div class="field"><label for="reviewEpisodeNumber">当前第几集</label><input id="reviewEpisodeNumber" name="episodeNumber" type="number" min="1" step="1" inputmode="numeric" value="${esc(episodeNumber)}" placeholder="例如：10" aria-describedby="reviewEpisodeNumberHint" ${reviewBusiness==='AI漫剧'?'':'disabled'}><small id="reviewEpisodeNumberHint">留空表示未知</small></div></div><div class="field"><label for="reviewGenre">题材标签</label><input id="reviewGenre" name="genre" maxlength="30" required value="${esc(pending?.genre||video.genre||'')}" placeholder="例如：科幻、悬疑"></div><fieldset><legend>你认为它好在哪里？</legend><div class="review-options">${learningPointOptions.map(tag=>`<label class="review-option"><input type="checkbox" name="learningTag" value="${tag}" ${selected.has(tag)?'checked':''}><span>${tag}</span></label>`).join('')}</div></fieldset><div class="field"><label for="learningText">补充学习点</label><textarea id="learningText" name="learningText" maxlength="1000" placeholder="也可以用自己的话写出值得学习的具体做法">${esc(pending?.learningText||'')}</textarea><small>选择至少一个默认标签，或填写文字。</small></div><p id="formError" class="form-error" role="alert"></p></form>`;
 openDialog('提交内容研判',body,btn('取消','close')+'<button class="btn primary" type="submit" form="researchIntakeForm">提交研判</button>',true);
 intakeWorkContext={options:[],active:-1,video,pending};
 for(const [key,value] of [['reviewBiz',reviewBusiness],['reviewWorkName',workName],['reviewWorkId',associatedWork?.id||''],['reviewTotalEpisodes',totalEpisodes??''],['reviewEpisodeNumber',episodeNumber]])document.getElementById(key).value=value;
 toggleIntakeComicFields(reviewBusiness);
}
function hasHumanReview(x){return !!(x.rating||x.learningText?.trim()||x.learningTags?.length)}
function humanReviewSnapshot(x){return structuredClone({rating:x.rating||'',learningTags:x.learningTags||[],learningText:x.learningText||'',genre:x.genre||'',biz:x.biz||[],sourceId:x.sourceId||'',sourceDate:x.sourceDate||'',submittedAt:x.submittedAt||'',taskId:x.id,version:x.version||1,title:x.title||'',totalEpisodes:x.totalEpisodes??null,episodeNumber:x.episodeNumber??null,workName:x.workName||'',workId:x.workId||''})}
function humanReviewEntries(x){return x.humanReviews?.length?x.humanReviews:(hasHumanReview(x)?[humanReviewSnapshot(x)]:[])}
function humanReviewFields(review){
 const time=review.submittedAt&&Number.isFinite(Date.parse(review.submittedAt))?new Date(review.submittedAt).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'未记录';
 return `<dl class="keyvalues"><dt>人工评级</dt><dd>${review.rating?esc(review.rating)+' 级':'未记录'}</dd><dt>业务标签</dt><dd>${(review.biz||[]).map(esc).join('、')||'未记录'}</dd>${review.biz?.includes('AI漫剧')?`<dt>作品名称</dt><dd>${esc(review.workName||'未记录')}</dd><dt>当前集数</dt><dd>${review.episodeNumber==null?'未知':'第 '+esc(review.episodeNumber)+' 集'}</dd><dt>总集数</dt><dd>${review.totalEpisodes==null?'未知':esc(review.totalEpisodes)+' 集'}</dd>`:''}<dt>题材标签</dt><dd>${esc(review.genre||'未标注')}</dd><dt>学习点标签</dt><dd>${(review.learningTags||[]).map(esc).join('、')||'未选择'}</dd><dt>补充学习点</dt><dd class="human-review-text">${esc(review.learningText||'未填写')}</dd><dt>情报日期</dt><dd>${esc(review.sourceDate||'未记录')}</dd><dt>提交时间</dt><dd>${esc(time)}</dd></dl>`;
}
function humanReviewCard(task){
 const reviews=humanReviewEntries(task);if(!reviews.length)return '';
 const latest=reviews.at(-1);
 return `<article class="human-review-card"><h4>${esc(task.title)}</h4><p class="small muted">${esc(task.id)} · 材料 v${esc(latest.version||task.version||1)} · 来源 ${esc(latest.sourceId||task.sourceId||'未记录')}</p>${humanReviewFields(latest)}${reviews.length>1?`<details class="human-review-history"><summary>历史初评（${reviews.length-1}条）</summary>${reviews.slice(0,-1).map((review,i)=>`<div><h4>第${i+1}次提交 · 材料 v${esc(review.version||1)}</h4>${humanReviewFields(review)}</div>`).join('')}</details>`:''}</article>`;
}
function humanReviewBlock(x){return `<section class="detail-block"><h3>本次材料的人工初评</h3>${humanReviewCard(x)||'<p class="muted">尚无人工初评记录。</p>'}</section>`}
function workHumanReviewBlock(workId,excludeId=''){
 const tasks=workId?db.research.filter(task=>task.workId===workId&&task.id!==excludeId&&humanReviewEntries(task).length):[];
 if(excludeId&&!tasks.length)return '';
 return `<section class="detail-block"><h3>${excludeId?'作品关联人工初评':'人工初评'}</h3><p class="small muted">按来源与材料版本保留人工判断，与AI评价分开展示。${excludeId?'关联记录供查阅，不代表该历史报告的输入或结论。':''}</p>${tasks.map(humanReviewCard).join('')||'<p class="muted">尚无人工初评记录。</p>'}</section>`;
}
function workDetail(id,view='episodes'){
 const work=db.works.find(item=>item.id===id&&item.biz?.includes(state.biz[0]));if(!work){toast('当前业务内没有这部作品');return}
 if(dialog.open){closeDialog();if(dialog.open)return}
 state.module=2;state.tab=0;state.mode='正常';state.workId=id;state.workView=view;state.workReportId='';state.episodeNavPage=1;
 const first=workUnits(work)[0]||workEpisodeEntries(work)[0];state.workUnit=first?.key||'';state.workTaskId=first?.current?.id||'';updateWorkRoute();render();document.getElementById('workDetailTitle')?.focus({preventScroll:true});
}
function workDetailPage(){
 const work=selectedWork();if(!work)return btn('返回作品列表','work-back')+empty('当前业务内没有这部作品','作品可能已移除，或属于另一业务线。');
 const p=workProgress(work),comic=work.biz?.[0]==='AI漫剧',unit=comic?'集':'份',missing=work.totalEpisodes==null?null:Math.max(0,work.totalEpisodes-p.collected);
 const tabs=[['analysis','作品分析'],['episodes',comic?'分集分析':'内容分析'],['materials','资料与记录']];
 const header=`<div class="work-back-row">${btn('‹ 返回作品列表','work-back')}<span class="small muted">研判室 / 内容研判 / 作品详情</span></div><section class="work-detail-header"><div class="work-detail-identity"><div class="work-cover" data-work-thumbnail="${esc(work.id)}" aria-hidden="true"><span class="work-cover-letter">${esc(work.title.slice(0,1))}</span></div><div><h1 id="workDetailTitle" tabindex="-1">${esc(work.title)}</h1><p class="small muted">${esc(work.id)} · ${esc(work.genre||'题材待补充')} · ${esc(work.creatorId||'博主ID未记录')}</p></div></div><div class="row-actions">${btn('补充资料','new-material',work.id)}${p.report?btn('查看报告','work-report',work.id,true):''}</div><div class="work-overview-stats"><div><span>${comic?'总集数':'研究单位'}</span><strong>${comic?esc(work.totalEpisodes??'未知'):'作品'}</strong></div><div><span>已收集${p.partial?' · 含历史汇总':''}</span><strong>${p.collected}<small>${unit}</small></strong></div><div><span>已分析${p.partial?' · 含历史汇总':''}</span><strong>${p.analyzed}<small>${unit}</small></strong></div><div><span>最新报告</span><strong class="work-report-overview">${p.report?'v'+esc(p.report.version):'尚无报告'}</strong><small>${p.report?esc(p.report.status):'尚无可用作品报告'}</small></div><div data-work-metric="views"><span>总观看量</span><strong class="work-performance-value" aria-label="${workPerformanceValue(work,'views')||'未获取'}">${workPerformanceValue(work,'views')||'&nbsp;'}</strong></div><div data-work-metric="interactions"><span>互动量</span><strong class="work-performance-value" aria-label="${workPerformanceValue(work,'interactions')||'未获取'}">${workPerformanceValue(work,'interactions')||'&nbsp;'}</strong></div></div><div class="work-detail-progress"><span>${esc(workProgressText(work,p))}</span><span>${comic?(missing==null?'总集数未知，覆盖范围不代表全剧':`尚未收集 ${missing} 集`):'不同材料版本分别保留判断'}</span></div>${workPerformanceMeta(work)?`<p class="work-performance-meta small muted">${esc(workPerformanceMeta(work))}</p>`:''}</section>`;
 const content=state.workView==='analysis'?workAnalysisPane(work):state.workView==='materials'?workMaterialsPane(work):workEpisodesPane(work);
 return header+`<nav class="work-detail-tabs" aria-label="作品详情分区">${tabs.map(([key,label])=>`<button data-action="work-view" data-id="${key}" aria-current="${state.workView===key?'page':'false'}" class="${state.workView===key?'active':''}">${label}</button>`).join('')}</nav><div id="workDetailContent">${content}</div>`;
}
function workEpisodesPane(work){
 const units=workUnits(work),comic=work.biz?.[0]==='AI漫剧',matches=visibleWorkUnits(work),selected=selectedWorkUnit(work),task=selectedUnitTask(selected),extent=episodeExtent(work);
 const pages=Math.max(1,Math.ceil(extent/100)),page=Math.min(Math.max(1,state.episodeNavPage||1),pages);
 const nav=`<aside class="episode-sidebar"><div class="episode-tools"><h2>${comic?'分集导航':'材料导航'} <span class="small muted">${comic?extent?extent+'集':'集数未知':units.length}</span></h2></div><div class="episode-nav-list" id="episodeNavList">${matches.map(unit=>{const available=!!unit.current,title=unit.current?.title||unit.title||'标题未获取',label=unitLabel(work,unit),status=available?taskPhase(unit.current):'未收集';return `<button class="episode-nav-item ${available?'has-info':'is-missing'} ${selected?.key===unit.key?'active':''}" data-has-info="${available}" data-action="work-unit" data-id="${esc(unit.key)}" aria-current="${selected?.key===unit.key?'true':'false'}" title="${esc(label+' · '+title+' · '+status)}"><span class="episode-nav-number">${comic?unit.number==null?'未标':String(unit.number).padStart(2,'0'):'内容'}</span><span class="episode-row-title">${esc(title)}</span><span class="sr-only">${available?'有资料':'无资料'}</span></button>`}).join('')||'<p class="muted episode-empty">尚无可显示的分集资料。</p>'}</div>${pages>1?`<div class="episode-pages"><button class="btn small" data-action="episode-nav-page" data-id="${page-1}" ${page<=1?'disabled':''}>上一段</button><span>${page} / ${pages}</span><button class="btn small" data-action="episode-nav-page" data-id="${page+1}" ${page>=pages?'disabled':''}>下一段</button></div>`:''}<p class="episode-nav-note small muted"><span class="has-info">有资料</span> · <span class="is-missing">缺资料</span></p></aside>`;
 const missing=selected&&!task?`<section class="unit-section"><h2>${unitLabel(work,selected)}尚无资料</h2><p class="muted">${esc(selected.title||'标题未获取')}</p>${btn('补充该集资料','new-episode-material',String(selected.number))}</section>`:empty(units.length?'没有匹配的材料':'尚无单集资料','补充资料后继续查看。');
 return `<div class="episode-layout">${nav}<section class="episode-detail" id="episodeDetail">${task?unitDetailPane(work,selected,task):missing}</section></div>`;
}
function unitDetailPane(work,unit,task){
 const phase=taskPhase(task),current=task.id===unit.current.id,oldAnalysis=unit.tasks.some(item=>taskPhase(item)==='已分析'),snapshot=task.sourceSnapshot||{},raw=task.input||snapshot.plot||'',video=workMediaUrl(snapshot.mediaUrl||task.mediaUrl),url=workMediaUrl(snapshot.url||''),image=workMediaUrl(snapshot.frameUrl||snapshot.coverUrl||work.frameUrl||work.coverUrl||'');
 const media=video&&(/\.(mp4|webm|mov)(\?|#|$)/i.test(video)||video.startsWith('blob:'))?`<video id="unitVideo" controls preload="metadata" src="${esc(video)}" aria-label="当前材料视频"></video>`:image?`<figure class="unit-media-preview"><img src="${esc(image)}" alt="作品演示参考图" loading="lazy"><figcaption>作品参考图；原视频未获取</figcaption></figure>`:'<p class="muted">原视频未获取，可阅读已保存的文字资料。</p>';
 const versions=`<label class="unit-version-label" for="unitVersion">材料／执行记录<select id="unitVersion">${[...unit.tasks].sort((a,b)=>(b.version||1)-(a.version||1)).map(item=>`<option value="${esc(item.id)}" ${item.id===task.id?'selected':''}>v${item.version||1} · ${taskPhase(item)} · ${esc(item.id)}</option>`).join('')}</select></label>`;
 const status=`${!current?'<span class="tag">历史材料</span>':''}<span class="tag">${esc(phase)}</span>${current&&oldAnalysis&&phase!=='已分析'?`<span class="tag">已有分析 · ${['分析中','解析中'].includes(phase)?'新版处理中':'当前材料待处理'}</span>`:''}`;
 const analysis=task.analysis?.sections?.length?`<p class="small muted">${esc(task.analysis.standard||'标准未记录')} · ${task.analysis.provenance==='demo'?'固定演示分析':'材料分析'}</p>${task.analysis.sections.map(section=>`<div class="unit-analysis-section"><h3>${esc(section.title)}</h3><p>${esc(section.text)}</p><button class="evidence-link" data-action="unit-evidence">查看本集证据 ${icon('out')}</button></div>`).join('')}`:phase==='已分析'?'<p>已有材料分析记录；详细拆解正文未保存，不能补造结论。</p>':notice(phase==='解析失败'||phase==='分析失败'?task.failureReason||'执行失败，尚未得到有效分析。':phase==='需补充'?'必要材料不足，相关维度暂不能判断。':'任务尚未产生有效分析；Demo不自动执行AI任务。');
 const evidence=(task.analysis?.evidence||[]).map(ref=>`<div class="unit-evidence-item"><strong>${esc(ref.start||'段落证据')}${ref.end?'—'+esc(ref.end):''}</strong><blockquote>${esc(ref.quote||'原文证据未记录')}</blockquote></div>`).join('');
 const content=`<div class="unit-detail-heading"><div><span class="small muted">${unitLabel(work,unit)} · ${esc(task.materialType||'材料类型未标明')} · v${task.version||1}</span><h2>${esc(task.title)}</h2><div class="meta">${status}</div></div>${versions}</div><section class="unit-section"><h2>原始内容</h2><div class="unit-source-layout">${media}<div><p class="human-review-text">${esc(raw||'原始正文未获取')}</p><p class="small muted">${esc(task.id)} · ${esc(snapshot.creator||snapshot.creatorId||'来源未记录')}</p>${url?`<a class="evidence-link" href="${esc(url)}" target="_blank" rel="noopener noreferrer">打开来源 ${icon('out')}</a>`:''}</div></div></section>${humanReviewBlock(task)}${researchFeedbackBlock(snapshot.audienceFeedback)}<section class="unit-section"><h2>${work.biz?.[0]==='AI漫剧'?'单集':'内容'}拆解与判断</h2>${analysis}${['解析失败','分析失败'].includes(phase)&&current?btn('重试失败项','retry-work-task',task.id):''}${phase==='需补充'?btn('补充资料','new-material',work.id):''}</section><section id="unitEvidence" class="unit-section" tabindex="-1"><h2>原文证据</h2>${evidence||'<p class="muted">尚无可定位的分析证据。</p>'}</section><section class="unit-section"><h2>知识提炼</h2>${unitKnowledgePane(work,task)}</section>`;
 return content;
}
function relatedKnowledge(work,task=null){const taskIds=new Set(workTasks(work).map(item=>item.id));return db.knowledge.filter(item=>(item.workId===work.id||taskIds.has(item.researchId))&&(!task||item.researchId===task.id))}
function knowledgeState(item){return item.status==='已入库'?'已审核入库':'候选知识 · '+item.status}
function unitKnowledgePane(work,task){
 const existing=relatedKnowledge(work,task),draft=task.analysis?.knowledgeDraft;
 return `${draft?`<article class="knowledge-preview"><h3>${esc(draft.title)}</h3><span class="tag">候选观察 · 演示</span><p>${esc(draft.text)}</p>${existing.some(item=>item.researchId===task.id)?'':btn('提交知识审核','submit-unit-knowledge',task.id)}</article>`:''}${existing.map(item=>`<article class="knowledge-preview"><h3>${esc(item.title)}</h3><span class="tag">${esc(knowledgeState(item))}</span><p>${esc(item.summary)}</p>${btn('查看审核记录','open-work-knowledge',item.id)}</article>`).join('')||(!draft?'<p class="muted">尚未提炼知识。分析完成也不会自动入库。</p>':'')}`;
}
const workReportChapters=[
 {key:'strengths',title:'作品优缺点',legacy:[]},
 {key:'outline',title:'故事大纲',legacy:['故事大纲','题材与核心设定']},
 {key:'emotion',title:'情绪与母题',legacy:['情绪与母题','情绪与爽点']},
 {key:'characters',title:'人物设计',legacy:['人物设计','人物关系与成长']},
 {key:'world',title:'世界观与长线悬念',legacy:['世界观与伏笔回收','世界观与长线悬念']},
 {key:'conflict',title:'情节与冲突',legacy:['情节与冲突']},
 {key:'rhythm',title:'节奏结构',legacy:['主线与跨集节奏','节奏结构']},
 {key:'finale',title:'终局设计',legacy:['终局设计']},
 {key:'curve',title:'剧情发展高潮曲线',legacy:[]},
 {key:'feedback',title:'观众评论反馈总结',legacy:['观众评论反馈总结']}
];
function reportDocumentSection(work,report,chapter){
 const stored=report?.documentSections?.find(section=>section.key===chapter.key);
 if(stored)return stored;
 const legacy=report?.sections?.find(section=>chapter.legacy.includes(section.title));
 if(legacy)return {facts:legacy.text,suggestions:'现有报告未记录本部分的改写建议，待依据原始材料补充。',evidence:legacy.evidence||[]};
 if(chapter.key==='feedback'&&report){
  const feedback=(report.inputRefs||[]).map(ref=>workTasks(work).find(task=>task.id===ref.taskId&&task.version===ref.version)?.sourceSnapshot?.audienceFeedback).filter(Boolean);
  if(feedback.length)return {facts:feedback.map(item=>item.summary||'存在评论快照，尚未形成总结。').join('\n'),suggestions:'将评论反映的困惑、情绪和期待对应到具体场景，再评估调整；不把热评当成全体观众结论。'};
 }
 return {facts:report?'现有报告未记录本部分的有效分析。':'待分析：尚未形成有效作品报告。',suggestions:report?'待结合对应材料与证据提出改写建议。':'待有效分析形成后给出建议。'};
}
function workClimaxCurve(report){
 const points=(report?.climaxCurve||[]).filter(point=>Number.isSafeInteger(point.episode)&&report.coverage?.includes(point.episode)&&typeof point.intensity==='number'&&Number.isFinite(point.intensity)&&point.intensity>=0&&point.intensity<=10).sort((a,b)=>a.episode-b.episode);
 if(points.length<2)return '<p class="muted">尚无可绘制的高潮曲线数据。</p>';
 const max=Math.max(...points.map(point=>point.episode)),coords=points.map(point=>`${40+(point.episode-1)/Math.max(1,max-1)*560},${130-point.intensity*10}`).join(' ');
 return `<figure class="work-climax-curve"><figcaption>剧情发展高潮曲线 · ${report.provenance==='demo'?'演示叙事强度':'叙事强度'}（0—10）</figcaption><svg viewBox="0 0 640 170" role="img" aria-label="覆盖材料中第1至${max}集的高潮曲线"><title>剧情发展高潮曲线</title><desc>${esc(points.map(point=>'第'+point.episode+'集：'+point.intensity).join('；'))}</desc>${[0,5,10].map(score=>`<line x1="40" x2="600" y1="${130-score*10}" y2="${130-score*10}" class="curve-grid"/><text x="10" y="${134-score*10}">${score}</text>`).join('')}<polyline points="${coords}" class="curve-line"/>${points.map(point=>`<circle cx="${40+(point.episode-1)/Math.max(1,max-1)*560}" cy="${130-point.intensity*10}" r="3" class="curve-point"><title>第${point.episode}集：${point.intensity}</title></circle>`).join('')}<text x="40" y="158">第1集</text><text x="600" y="158" text-anchor="end">第${max}集</text></svg><p class="small muted">仅绘制本报告覆盖材料中已记录的点位，未分析集数不外推。</p></figure>`;
}
function renderWorkReportChapters(work,report){return workReportChapters.map((chapter,index)=>{
 const section=reportDocumentSection(work,report,chapter);
 return `<section class="work-report-chapter" data-report-chapter="${chapter.key}"><h2>${index}、${chapter.title}</h2><h3>事实分析</h3><p class="human-review-text">${esc(section.facts||'未记录')}</p>${chapter.key==='curve'?workClimaxCurve(report):''}${report?`<div class="report-evidence-links">${unitEvidenceButtons(section.evidence,report)}</div>`:''}<h3>改写建议</h3><p class="human-review-text">${esc(section.suggestions||'未记录')}</p></section>`;
}).join('')}
function workAnalysisPane(work){
 const reports=workReports(work),report=selectedWorkReport(work);
 const selector=report?`<label class="report-version-label" for="workReportVersion">报告版本<select id="workReportVersion">${reports.map(item=>`<option value="${esc(item.id)}" ${item.id===report.id?'selected':''}>v${esc(item.version)} · ${esc(item.status)} · ${esc(item.createdAt||'时间未记录')}</option>`).join('')}</select></label>`:'';
 const heading=report?`<h1>${esc(reportCoverageText(work,report))}</h1><p class="small muted">${esc(report.status)} · ${esc(report.createdAt||'时间未记录')}${report.provenance==='demo'?' · 演示报告':''}</p>`:'<h1>作品分析尚未形成</h1><p class="small muted">以下为报告结构，尚未生成事实判断和改写建议。</p>';
 const scope=report?`覆盖集号：${report.coverage?.length?esc(report.coverage.join('、')):'未标明，按材料范围阅读'}。报告只对本版本覆盖的材料下结论。`:'有效材料分析完成且本批次结束或阻塞后，才汇总阶段报告。';
 const inputTasks=(report?.inputRefs||[]).map(ref=>workTasks(work).find(task=>task.id===ref.taskId&&(task.version||1)===ref.version)).filter(Boolean);
 const reviews=report?`<h2>报告材料的人工初评</h2>${inputTasks.filter(task=>humanReviewEntries(task).length).map(humanReviewCard).join('')||'<p class="muted">本报告覆盖的材料没有人工初评记录。</p>'}<details class="report-appendix"><summary>其他关联人工初评（不属于本报告输入）</summary>${workTasks(work).filter(task=>!inputTasks.some(item=>item.id===task.id)&&humanReviewEntries(task).length).map(humanReviewCard).join('')||'<p class="muted">暂无其他人工判断。</p>'}</details>`:workHumanReviewBlock(work.id);
 const drafts=(report?.knowledgeDrafts||[]).map((draft,index)=>`<div class="knowledge-preview"><h3>${esc(draft.title)}</h3><span class="tag">作品级候选观察</span><p>${esc(draft.text)}</p><div>${unitEvidenceButtons(draft.evidence,report)}</div>${relatedKnowledge(work).some(item=>item.reportId===report.id&&item.draftId===draft.id)?'':btn('提交知识审核','submit-work-knowledge',String(index))}</div>`).join('');
 const knowledge=report?`<details class="report-appendix"><summary>作品级知识提炼与审核记录</summary>${drafts||'<p class="muted">尚无作品级候选知识。</p>'}${relatedKnowledge(work).filter(item=>item.reportId===report.id).map(item=>`<div class="knowledge-preview"><h3>${esc(item.title)}</h3><span class="tag">${esc(knowledgeState(item))}</span>${btn('查看审核记录','open-work-knowledge',item.id)}</div>`).join('')}</details>`:'';
 const judgment=report?`<details class="report-appendix"><summary>评价与市场预测</summary><h3>内容质量判断</h3><p>${esc(report.quality||'详细质量判断未记录')}</p><h3>市场表现预测</h3><p>暂不可可靠预测：缺少匹配的发布条件与事前预测记录，质量评级不替代市场预测。</p>${report.legacy?btn('查看既有材料报告','research-detail',report.sourceTaskId):''}</details>`:'';
 return `<article class="work-analysis-document work-panel"><header class="report-title-row"><div>${heading}</div>${selector}</header><p class="report-scope">${scope}</p>${renderWorkReportChapters(work,report)}<div class="report-review-records">${reviews}</div>${judgment}${knowledge}</article>`;
}

function demoWorkDocumentSections(report){
 const count=report.coverage.length;
 const texts=[
  ['优点：旧信、姓名与档案构成可追踪的线索，人物关系能随证据变化。缺点：现有覆盖材料尚不足以确认长线回收，部分段落依赖解释。','让关键线索改变人物行动；减少重复说明，并逐项检查已埋伏笔的兑现情况。'],
  [`已覆盖第1—${count}集：返城青年追查旧信，从被动接受解释转向核对证据，在寻找真相与维持家庭关系之间作出选择。未覆盖集数不纳入大纲。`,'按“目标—阻碍—选择—代价”梳理阶段因果，明确每轮调查带来的不可逆变化。'],
  ['已覆盖材料围绕信任、隐瞒与真相展开；日常物件引发对亲密关系的重新判断，母题依托具体线索呈现。','将人物害怕失去的关系落到行动和代价上，避免仅用台词说明情绪。'],
  ['主角逐步获得调查主动性；家人的隐瞒形成关系压力。现有材料不足以确认所有人物的完整成长弧。','明确核心人物各自保护什么、隐瞒什么，让同一证据引发不同选择。'],
  ['旧信和档案是已出现的线索载体；线索背后的完整规则及最终解释尚未确认。','建立线索规则与回收清单，让悬念逐层改变问题，避免不断增加无关谜团。'],
  ['主要冲突来自核对真相与保护关系之间的矛盾，线索发现推动人物立场变化。','让障碍来自人物利益与选择，并使每轮解决问题同时带来新的代价。'],
  ['材料中的日常动作承接调查线索，部分转折形成局部节奏峰值。跨集完整节奏只能在本报告覆盖范围内观察。','检查峰值之间是否有必要的铺垫、喘息和后果，删除不能推进目标或关系的重复段落。'],
  ['本阶段报告尚未覆盖结局，无法判断最终真相、人物选择及伏笔是否完成回收。','补齐终局材料后，核对最终选择是否回应核心情绪，关键伏笔是否有因果闭合。'],
  ['曲线按已记录的演示集数点位展示叙事强度，表达局部峰谷；不是观看量、市场表现或观众评分。','围绕峰值核查铺垫与后果，确保高潮改变目标或关系，而不是只增加信息量。'],
  ['本批次未采集可核验的观众评论，无法形成受欢迎点、困惑点和续集期待的事实总结。','补充评论快照与样本范围，将反馈对应到具体场景；明确区分观众原话与分析推断。']
 ];
 return workReportChapters.map((chapter,index)=>({key:chapter.key,facts:texts[index][0],suggestions:texts[index][1],evidence:index<7?[report.sections[Math.min(index,report.sections.length-1)]?.evidence?.[0]].filter(Boolean):[]}));
}

function workMaterialsPane(work){
 const materials=(db.materials||[]).filter(item=>item.workId===work.id),tasks=workTasks(work),batches=new Map();
 for(const task of tasks){const key=task.batchId||'未记录批次';if(!batches.has(key))batches.set(key,[]);batches.get(key).push(task)}
 return `<section class="work-panel"><div class="report-title-row"><h2>作品级资料与补充材料</h2>${btn('补充资料','new-material',work.id)}</div>${materials.map(item=>`<article class="material-record"><h3>${esc(item.title)}</h3><p class="small muted">${esc(item.id)} · v${item.version||1} · ${item.scope==='episode'?'第'+item.episodeNumber+'集':'作品级资料'} · ${esc(item.status||'状态未记录')}</p><p class="human-review-text">${esc(item.input||'正文未保存')}</p></article>`).join('')||'<p class="muted">尚无作品级补充资料。</p>'}</section><section class="work-panel"><h2>提交批次与执行记录</h2>${[...batches.entries()].map(([id,records])=>`<details class="batch-record"><summary>${esc(id)} · ${records.length}条材料／执行记录</summary>${records.map(task=>`<div class="material-record"><strong>${esc(task.title)}</strong><p class="small muted">${esc(task.id)} · v${task.version||1}${unitNumber(task)?' · 第'+unitNumber(task)+'集':''} · ${esc(taskPhase(task))}</p>${btn('查看材料','work-evidence',task.id)}</div>`).join('')}</details>`).join('')||'<p class="muted">尚无执行记录。</p>'}</section><section class="work-panel"><h2>报告历史</h2>${workReports(work).map(report=>`<div class="material-record"><strong>${esc(reportCoverageText(work,report))}</strong><p class="small muted">${esc(report.status)} · ${esc(report.createdAt||'时间未记录')}</p>${btn('查看此版本','work-report-version',report.id)}</div>`).join('')||'<p class="muted">尚无报告版本。</p>'}</section>`;
}
function openWorkEvidence(taskId,start=''){
 const work=selectedWork(),unit=work&&workUnits(work).find(unit=>unit.tasks.some(task=>task.id===taskId));if(!unit){toast('证据不属于当前作品，或原材料未保存');return}
 state.workView='episodes';state.workUnit=unit.key;state.workTaskId=taskId;state.episodeNavPage=Math.floor(((unit.number||1)-1)/100)+1;updateWorkRoute();render();focusUnitEvidence(start);
}
function focusUnitEvidence(start=''){const evidence=document.getElementById('unitEvidence');evidence?.scrollIntoView({behavior:window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches?'auto':'smooth',block:'start'});evidence?.focus({preventScroll:true});const video=document.getElementById('unitVideo');if(video&&/^(\d+:)?\d+:\d{2}$/.test(start)){const seconds=start.split(':').map(Number).reduce((total,part)=>total*60+part,0);const seek=()=>{try{video.currentTime=Number.isFinite(video.duration)?Math.min(seconds,video.duration):seconds}catch{}};if(video.readyState>=1)seek();else video.addEventListener('loadedmetadata',seek,{once:true})}}
function submitWorkKnowledge(kind,id){
 const work=selectedWork();if(!work)return;
 const report=kind==='work'?selectedWorkReport(work):null,task=kind==='unit'?workTasks(work).find(task=>task.id===id):null,draft=report?.knowledgeDrafts?.[Number(id)]||task?.analysis?.knowledgeDraft;
 if(!draft){toast('没有可提交的候选知识');return}
 const exists=db.knowledge.some(item=>kind==='work'?item.workId===work.id&&item.reportId===report.id&&item.draftId===draft.id:item.researchId===task.id);
 if(exists){toast('此候选已提交审核');return}
 const refs=kind==='work'?(draft.evidence||[]).filter(ref=>report.inputRefs.some(input=>input.taskId===ref.taskId)):[{taskId:task.id,...(task.analysis.evidence?.[0]||{})}];
 db.knowledge.unshift({id:'K-WORK-'+Date.now()+'-'+db.knowledge.length,title:draft.title,summary:draft.text,biz:[...work.biz],stage:'脚本',type:'案例经验',status:'待AI审核',version:1,ai:'待审核',workId:work.id,reportId:report?.id||'',draftId:draft.id||'',researchId:task?.id||'',sourceId:task?.sourceId||'作品报告',evidenceRefs:refs.map(ref=>({...ref,version:workTasks(work).find(item=>item.id===ref.taskId)?.version||1})),evidence:refs.map(ref=>ref.taskId+' · '+(ref.start||'文字材料')).join('；')+'；演示候选，等待AI与人工审核。'});
 save();render();toast('候选知识已送审，尚未正式入库');
}
function retryWorkTask(id){
 const work=selectedWork(),original=work&&workTasks(work).find(task=>task.id===id);if(!original||!['解析失败','分析失败'].includes(taskPhase(original)))return;
 const unit=workUnits(work).find(unit=>unit.tasks.some(task=>task.id===id));if(unit?.current.id!==id){toast('请重试当前材料的失败记录');return}
 const task={...structuredClone(original),id:id+'-retry-'+Date.now(),status:taskPhase(original)==='解析失败'?'待处理':'待分析',retryOf:id,attempt:(original.attempt||0)+1,humanReviews:structuredClone(humanReviewEntries(original)),submittedAt:new Date().toISOString(),analysis:null,failureReason:'',lastAnalyzedAt:''};
 db.research.unshift(task);state.workTaskId=task.id;save();updateWorkRoute();render();toast('已记录重试请求；Demo未接入实际处理服务');
}

function researchDetail(id){const x=db.research.find(r=>r.id===id);let done=x.status==='已完成';openDialog(done?'内容研判报告':'内容研判任务',detailIntro(x)+`<dl class="keyvalues"><dt>评价对象</dt><dd>${x.id} v${x.version}</dd><dt>评价标准</dt><dd>${x.biz[0]==='电商短视频'?'商品表达与事实 v1.1':x.biz[0]==='AI漫剧'?'叙事清晰度 v2.0':'视听表达 v1.3'}（演示）</dd><dt>报告状态</dt><dd>${x.status}</dd></dl>`+humanReviewBlock(x)+workHumanReviewBlock(x.workId,x.id)+researchFeedbackBlock(x.sourceSnapshot?.audienceFeedback)+(done?`<div class="detail-block"><h3>质量评价 · 与市场预测分开</h3>${[['叙事清晰度',82],['情绪递进',76],['声画一致性',88]].map(([n,v])=>`<div class="score-line"><span>${n}</span><span class="bar"><i style="width:${v}%"></i></span><span>${v} / 100</span></div>`).join('')}<p>保留日常动作的重复，减少结尾说明。以上为固定样例评价，不是实际AI推理结果。</p></div>`:notice(x.status==='证据不足'?'缺少商品规格与参考实物，真实性维度返回“证据不足”，不评分。':'任务已接收，等待解析与评价。原型未调用后端，不会自动生成报告。'))+sourceEvidence(x.sourceId,x.sourceSnapshot)+`<div class="detail-block"><h3>市场预测</h3><p>未登记事前预测。该质量评价不能直接替代最终成片的市场预测。</p></div>`,done?btn('提炼为候选知识','extract-knowledge',id,true):btn('补充资料','new-material',x.workId||''),true)}
function workMaterialFields(work){return `${work.biz?.[0]==='AI漫剧'?`<div class="review-intake-row"><div class="field"><label for="materialScope">资料归属</label><select id="materialScope" name="scope"><option value="work">作品级资料</option><option value="episode">单集资料</option></select></div><div class="field" id="materialEpisodeField" hidden><label for="materialEpisode">当前第几集</label><input id="materialEpisode" name="episodeNumber" type="number" min="1" step="1" ${work.totalEpisodes!=null?'max="'+esc(work.totalEpisodes)+'"':''} disabled></div></div>`:'<input type="hidden" name="scope" value="work">'}<input type="hidden" name="biz" value="${esc(work.biz[0])}"><p class="small muted">关联作品：${esc(work.title)} · ${esc(work.id)}</p>`}
function toggleMaterialScope(value){const episode=value==='episode',field=document.getElementById('materialEpisodeField'),input=document.getElementById('materialEpisode');if(field)field.hidden=!episode;if(input){input.disabled=!episode;input.required=episode}}
function submitWorkMaterial(values){
 const work=values.workId?db.works.find(item=>item.id===values.workId&&item.biz?.[0]===state.biz[0]&&item.biz?.[0]===values.biz):null;
 if(values.workId&&!work){document.getElementById('formError').textContent='关联作品不属于当前业务。';return}
 const title=String(values.title||'').trim(),input=String(values.value||'').trim();if(!title||!input){document.getElementById('formError').textContent='请填写资料名称和内容。';return}
 const scope=work?.biz?.[0]==='AI漫剧'&&values.scope==='episode'?'episode':'work';
 let number=null;
 if(scope==='episode'){number=Number(values.episodeNumber);if(!Number.isSafeInteger(number)||number<=0){document.getElementById('formError').textContent='集号须为正整数。';return}if(work.totalEpisodes!=null&&number>work.totalEpisodes){document.getElementById('formError').textContent='集号不能超过已确认的总集数。';return}}
 const unit=scope==='episode'?workUnits(work).find(item=>item.number===number):null,version=unit?(unit.current.version||1)+1:1,stamp=Date.now(),id='M-WORK-'+stamp+'-'+db.materials.length;
 const material={id,workId:work?.id||null,title,biz:[values.biz||state.biz[0]],scope,episodeNumber:number,type:/^https?:\/\//i.test(input)?'外部链接':'文本',version,status:'待处理 · 服务未接入',input};db.materials.unshift(material);
 if(scope==='episode'){
  const task={id:'C-MATERIAL-'+stamp+'-'+db.research.length,workId:work.id,title,biz:[...work.biz],episodeNumber:number,scope:'episode',materialId:id,materialType:material.type,version,status:'待处理',sourceId:'人工提交',input,batchId:'LOCAL-BATCH-'+stamp,submittedAt:new Date().toISOString(),sourceSnapshot:{title,url:material.type==='外部链接'?input:'',evidence:'用户补充的本地资料，尚未解析。'}};
  db.research.unshift(task);work.collectedCount=Math.max(work.collectedCount||0,workUnits(work).filter(item=>item.number!=null).length);state.workUnit='ep:'+number;state.workTaskId=task.id;
 }
 save();draftDirty=false;closeDialog();
 if(work&&state.workId===work.id){state.workView=scope==='episode'?'episodes':'materials';updateWorkRoute();render()}else navigate(1,1);
 toast('资料已记录，等待实际解析服务；未生成新分析或报告');
}

function simpleForm(kind,workId=''){const linkedWork=kind==='material'&&workId?db.works.find(work=>work.id===workId&&work.biz?.[0]===state.biz[0]):null;if(kind==='material'&&workId&&!linkedWork){toast('当前业务内没有这部作品');return}const contents=scoped(db.research);const config={research:['新建研判','资料标题','内容正文或来源链接','提交研判'],material:['提交资料','资料名称','粘贴文本或来源链接','提交处理'],publication:['登记发布','作品名称','发布链接','保存发布记录']}[kind];openDialog(config[0],`<form id="simpleForm" data-kind="${kind}">${kind==='material'&&workId?`<input type="hidden" name="workId" value="${esc(workId)}">`: ''}<div class="field"><label for="st">${config[1]}</label><input id="st" name="title" required maxlength="90"></div><div class="field"><label for="sv">${config[2]}</label><textarea id="sv" name="value" required></textarea></div>${linkedWork?workMaterialFields(linkedWork):kind==='publication'?`<div class="field"><label for="contentRef">关联内容版本</label><select id="contentRef" name="content" required><option value="">请选择当前业务的内容版本</option>${contents.map(x=>`<option value="${x.id}">${esc(x.title)} · ${x.id} v${x.version}</option>`).join('')}</select></div><div class="field"><label for="platform">平台 / 账号</label><input id="platform" name="platform" required placeholder="平台名称 / 发布账号"></div><div class="field"><label for="publishedAt">发布时间</label><input id="publishedAt" name="publishedAt" type="datetime-local" required></div>`:`<div class="field"><label for="sb">业务线</label><select id="sb" name="biz">${businesses.map(b=>`<option ${state.biz[0]===b?'selected':''}>${b}</option>`).join('')}</select></div>`}${kind==='source'?`<div class="field"><label for="sf">采集频率</label><select id="sf" name="freq"><option>每日 09:00</option><option>每 2 小时</option><option>每 4 小时</option></select></div>`:''}${notice('仅记录本地演示输入，不上传、不访问链接、不调用AI或采集服务。')}<p class="form-error" id="formError" role="alert"></p></form>`,btn('取消','close')+`<button class="btn primary" type="submit" form="simpleForm">${config[3]}</button>`)}
function publicationDetail(id){const x=db.publications.find(p=>p.id===id);openDialog('发布对账与实绩',`<h3 class="detail-title">${esc(x.title)}</h3><div class="meta">${x.id} · ${x.content} v${x.version}</div><dl class="keyvalues"><dt>观察窗口</dt><dd>${x.window}</dd><dt>平台 / 账号</dt><dd>${esc(x.platform||'样例平台 / 样例账号')}</dd><dt>事前预测</dt><dd>未登记 · 不纳入盲预测校准</dd><dt>实绩来源</dt><dd>${x.source}</dd></dl><div class="detail-block">${table(['指标','预测','实绩'],[['点赞','未登记',x.likes??'未获取'],['评论','未登记',x.comments??'未获取'],['转发','未登记',x.shares??'未获取'],['收藏','未登记',x.saves??'未获取']])}</div><div class="detail-block"><h3>人工补录 / 更正</h3><form id="performanceForm"><input name="id" type="hidden" value="${id}"><div class="field"><label for="likes">24小时点赞累计数</label><input id="likes" name="likes" type="number" min="0" step="1" value="${x.likes??''}" placeholder="留空表示未获取"></div><div class="field"><label for="perfEvidence">更正依据</label><input id="perfEvidence" name="evidence" required placeholder="如：平台后台24小时截图"></div><p class="form-error" id="formError" role="alert"></p></form><p class="small muted">保留独立快照与更正记录，不与此前累计数相加。</p></div><div class="timeline">${x.history.map(h=>`<div>${esc(h)}</div>`).join('')}</div>`,`<button type="submit" form="performanceForm" class="btn primary">保存补录快照</button>`,true)}

let sparkCapture=null,brainstormContext=null;
function persistIdeas(){try{localStorage.setItem(storageKey,JSON.stringify(db));draftDirty=false;return true}catch{draftDirty=true;toast('浏览器存储不可用，请先复制文本；本次修改仅保留在当前页面');return false}}
function sparkCapsules(actionName,selected=[]){return db.sparks.map(note=>`<button class="idea-capsule ${selected.includes(note.id)?'selected':''}" draggable="true" data-spark-drag="${esc(note.id)}" data-action="${actionName}" data-id="${esc(note.id)}" title="${esc(note.text)}"><span>${esc(note.title)}</span><small>${esc(topicTime(note.updatedAt||note.createdAt))}</small></button>`).join('')||'<p class="small muted">还没有闪念，随手记下第一条。</p>'}
function refreshSparkHistory(){document.getElementById('sparkHistory').innerHTML=sparkCapsules('spark-edit',[sparkCapture?.id])}
function saveSparkText(text){
 if(!sparkCapture)return;
 let note=db.sparks.find(t=>t.id===sparkCapture.id);
 if(!note&&!text.trim()){draftDirty=false;return}
 if(note&&text===sparkCapture.lastText&&!draftDirty)return;
 if(!note){note={id:'S-'+Date.now()+'-'+db.sparks.length,text:'',version:1,createdAt:new Date().toISOString(),versions:[]};db.sparks.unshift(note);sparkCapture.id=note.id}
 else if(!sparkCapture.revised){(note.versions??=[]).push({version:note.version,text:note.text,title:note.title});note.version++;sparkCapture.revised=true}
 note.text=text;note.title=text.split(/\r?\n/).find(line=>line.trim())?.trim().slice(0,90)||'未命名灵感';note.updatedAt=new Date().toISOString();sparkCapture.lastText=text;
 if(persistIdeas()&&!sparkCapture.saved){toast('闪念已自动保存');sparkCapture.saved=true}
 refreshSparkHistory();publish();
}
function sparkDialog(id=''){
 if(draftDirty&&!confirm('当前修改尚未保存，确定切换吗？'))return;
 const note=db.sparks.find(t=>t.id===id),text=note?.text||'';
 openDialog('闪念胶囊',`<div class="spark-layout"><section><div class="idea-heading"><h3>随手记录</h3>${btn('新记录','spark-new')}</div><textarea class="spark-capture" id="sparkBody" aria-label="记录灵感，输入后自动保存" placeholder="任何想法，都可以先放在这里…">${esc(text)}</textarea><p class="small muted">输入后自动保存</p></section><aside><h3>之前的闪念</h3><div class="idea-capsules" id="sparkHistory">${sparkCapsules('spark-edit',[id])}</div></aside></div>`);
 dialog.className='spark-dialog';sparkCapture={id:note?.id||'',lastText:text,revised:!note,saved:false};document.getElementById('sparkBody').focus();
}
function brainstormSignature(context){return JSON.stringify([context.selectedIds.map(id=>{const x=db.sparks.find(n=>n.id===id);return [id,x?.version,x?.text]}),context.instructions])}
function saveBrainstorm(){db.brainstorms[state.biz[0]]=structuredClone(brainstormContext);return persistIdeas()}
function brainstormDialog(){
 openDialog('头脑风暴','<div id="brainstormArea"></div>');dialog.className='brainstorm-dialog';
 brainstormContext=structuredClone(db.brainstorms[state.biz[0]]||{selectedIds:[],instructions:'',result:null});
 brainstormContext.selectedIds=[...new Set(brainstormContext.selectedIds)].filter(id=>db.sparks.some(x=>x.id===id));
 if(brainstormContext.inputSignature!==brainstormSignature(brainstormContext)){brainstormContext.result=null;brainstormContext.savedTopicId=''}
 renderBrainstorm();
}
function renderBrainstorm(){
 const c=brainstormContext,r=c.result;
 document.getElementById('brainstormArea').innerHTML=`<div class="brainstorm-layout"><aside><h3>闪念胶囊</h3><p class="small muted">拖入右侧，或点击添加</p><div class="idea-capsules">${sparkCapsules('brainstorm-add',c.selectedIds)}</div></aside><section><h3>组合你的想法</h3><div class="idea-dropzone" data-idea-drop="true" aria-label="头脑风暴交互区">${c.selectedIds.map(id=>{const n=db.sparks.find(x=>x.id===id);return `<div class="selected-idea"><span>${esc(n.title)}</span><button class="iconbtn" data-action="brainstorm-remove" data-id="${esc(id)}" aria-label="移除${esc(n.title)}">×</button></div>`}).join('')||'<p class="muted">把闪念拖到这里</p>'}</div><label class="idea-field">补充方向（选填）<textarea id="brainstorm-instructions" rows="2">${esc(c.instructions)}</textarea></label><button class="btn primary" data-action="brainstorm-generate" ${c.selectedIds.length?'':'disabled'}>生成一个选题</button>${r?`<section class="brainstorm-result"><div class="idea-heading"><h3>生成结果</h3><span class="tag">演示 · 未调用AI</span></div>${[['title','选题标题'],['logline','Logline'],['characterSettings','角色设定'],['globalRhythm','全局节奏']].map(([key,label])=>`<label class="idea-field">${label}<textarea id="brainstorm-${key}" rows="${key==='title'?1:3}" ${c.savedTopicId?'readonly':''}>${esc(r[key])}</textarea></label>`).join('')}<button class="btn primary" data-action="${c.savedTopicId?'brainstorm-view':'brainstorm-save'}">${c.savedTopicId?'查看已保存选题':'保存为选题卡'}</button></section>`:''}</section></div>`;
}
function brainstormInput(target){const c=brainstormContext,key=target.id.slice('brainstorm-'.length);if(key==='instructions'){c.instructions=target.value;c.result=null;c.savedTopicId='';const result=dialog.querySelector?.('.brainstorm-result');if(result)result.remove()}else if(c.result&&!c.savedTopicId)c.result[key]=target.value;saveBrainstorm()}
function selectBrainstorm(id,remove=false){const c=brainstormContext;if(!db.sparks.some(n=>n.id===id))return;if(!remove&&c.selectedIds.includes(id))return;c.selectedIds=remove?c.selectedIds.filter(x=>x!==id):[...c.selectedIds,id];c.result=null;c.savedTopicId='';saveBrainstorm();renderBrainstorm()}
function generateBrainstorm(){const c=brainstormContext;if(!c.selectedIds.length)return;
 const refs=c.selectedIds.map(id=>{const n=db.sparks.find(x=>x.id===id);return {id,version:n.version,text:n.text,title:n.title}});
 c.ideaRefs=refs;c.result={title:refs.map(n=>n.title).join(' × ').slice(0,90),logline:refs.map(n=>n.text).join('；')+(c.instructions?'\n创作方向：'+c.instructions:''),characterSettings:'主角：围绕“'+refs[0].title+'”设定核心诉求。\n对立人物：让其他闪念中的矛盾阻碍主角，并补充动机与代价。',globalRhythm:'开篇：用首条闪念建立异常与目标。\n推进：让所选想法交汇，逐步增加冲突与代价。\n收束：回收各条闪念的悬念，完成主角选择。'};c.inputSignature=brainstormSignature(c);c.savedTopicId='';saveBrainstorm();renderBrainstorm();
}
function saveBrainstormTopic(){const c=brainstormContext;if(!c.result||c.savedTopicId||c.inputSignature!==brainstormSignature(c))return;if(!c.result.title.trim()||!c.result.logline.trim()){toast('请填写选题标题与Logline');return}
 const topic={...structuredClone(c.result),id:'T-BRAIN-'+Date.now()+'-'+db.topics.length,summary:c.result.logline,biz:[state.biz[0]],audience:'',status:'候选',version:1,evaluation:'未评价',origin:'头脑风暴 · 演示',createdAt:new Date().toISOString(),sourceId:'',ideaRefs:structuredClone(c.ideaRefs),history:['v1 · 由闪念组合生成（演示）']};
 db.topics.unshift(topic);c.savedTopicId=topic.id;
 if(!saveBrainstorm()){db.topics=db.topics.filter(t=>t.id!==topic.id);c.savedTopicId='';db.brainstorms[state.biz[0]]=structuredClone(c);return}
 draftDirty=false;closeDialog();state.topicPage=1;navigate(0,1);topicDetail(topic.id);toast('已保存为选题卡');
}
listen(dialog,'dragstart',e=>{const node=e.target.closest?.('[data-spark-drag]');if(node&&e.dataTransfer){e.dataTransfer.setData('application/x-cip-spark',node.dataset.sparkDrag);e.dataTransfer.effectAllowed='copy'}});
listen(dialog,'dragover',e=>{if(brainstormContext&&e.target.closest?.('[data-idea-drop]')&&Array.from(e.dataTransfer?.types||[]).includes('application/x-cip-spark'))e.preventDefault()});
listen(dialog,'drop',e=>{if(!brainstormContext||!e.target.closest?.('[data-idea-drop]'))return;const id=e.dataTransfer?.getData('application/x-cip-spark');if(db.sparks.some(n=>n.id===id)){e.preventDefault();selectBrainstorm(id)}});
function guide(){openDialog('原型说明与状态预览',`<p>覆盖 4 个一级入口与 15 个二级工作区。布局、详情抽屉和未确认的状态操作均为设计提案。</p><div class="detail-block"><h3>建议体验路径</h3><p>情报流 → 转为选题 → 编辑 → 加入待生产 → 导出<br>研判报告 → 提炼候选 → 审核队列 → 正式知识<br>发布复盘 → 对账与补录 → 查看更正记录</p></div><div class="detail-block"><h3>当前页状态预览</h3><div class="row-actions">${['正常','加载中','空数据','失败','无权限','证据不足','评价过期'].map(x=>btn(x,'preview-state',x)).join('')}</div></div><div class="detail-block"><h3>演示边界</h3><p>所有来源、评分与实绩均为虚构样例。采集、AI、上传、权限、预测冻结与自动清理未连接后端。修改仅保存在当前浏览器。</p></div>`,btn('重置演示数据','reset')+btn('开始浏览','close', '',true))}
function downloadTopic(x){const text=topicText(x),a=document.createElement('a'),url=createDownloadUrl(new Blob([text],{type:'text/markdown;charset=utf-8'}));a.href=url;a.download=`${x.id}-v${x.version}.md`;a.click();setTimeout(()=>revokeDownloadUrl(url),1000);recordHandoff(x,'导出文件');toast('已生成选题文件，并记录交接；不代表生产完成')}
function topicText(x){const a=currentGenreLoadAssessment(x);return `# ${x.title}\n\n> 交互原型演示数据\n\n选题：${x.id} v${x.version}\n主业务线：${x.biz.join('、')}\n目标人群：${x.audience||'未补充'}\n\n## Logline\n${topicLogline(x)}\n\n## 角色设定\n${topicCharactersText(x)||'未补充'}\n\n## 全局节奏\n${x.globalRhythm||'未补充'}\n\n来源：${x.origin==='头脑风暴 · 演示'?'头脑风暴（演示）':x.sourceId||'人工灵感'}${x.ideaRefs?.length?'\n\n来源闪念快照：\n'+x.ideaRefs.map(ref=>ref.title+' · v'+ref.version+'\n'+ref.text).join('\n\n'):''}\n评价：${topicAssessmentStatus(x)}\n${a?'\n承重力总分：'+genreLoadTotal(a)+' / 50（演示）\n'+genreLoadDimensions.map((d,i)=>d.name+'：'+a.dimensions[i].score+' / 5 — '+a.dimensions[i].analysis).join('\n'):''}\n\n此交接不代表内容已制作或发布。\n`}

function recordHandoff(x,type){if(x.status!=='已采用')x.status='已交接';x.history.push(`v${x.version} · ${type} · ${new Date().toLocaleString('zh-CN')}`);db.handoffs.push({topic:x.id,version:x.version,type});save();render();topicDetail(x.id)}
async function action(a,id){switch(a){case 'module':navigate(+id);break;case 'tab':navigate(state.module,+id);break;case 'goto':{const [m,t]=id.split(',').map(Number);if(dialog.open)closeDialog();navigate(m,t);break}case 'biz':if(!businesses.includes(id)||state.biz[0]===id)break;if(dialog.open){closeDialog();if(dialog.open)break}state.biz=[id];state.workId='';state.workTaskId='';state.workUnit='';state.workReportId='';location.hash=`${state.module}/${state.tab}`;state.topicPage=1;state.query='';state.workGenre='全部题材';state.knowledgeCategory='全部';state.status='全部状态';state.stage='全部环节';state.mode='正常';state.hongguoBoard='';state.hongguoGenre='';state.hongguoSubgenre='';try{localStorage.setItem(workspaceStorageKey,id)}catch{}render();toast('已切换至'+id+'业务空间');break;case 'hongguo-board':state.hongguoBoard=id;state.hongguoGenre='';state.hongguoSubgenre='';render();break;case 'hongguo-subgenre':state.hongguoSubgenre=id;render();break;case 'hongguo-genre':state.hongguoGenre=id;state.hongguoSubgenre='';render();break;case 'stage':state.stage=id;render();break;case 'work-status':state.status=id;render();break;case 'work-detail':workDetail(id);break;
case 'work-report':workDetail(id,'analysis');break;
case 'work-back':state.workId='';state.workTaskId='';state.workUnit='';state.workReportId='';location.hash='2/0';render();break;
case 'work-view':if(selectedWork()&&['episodes','analysis','materials'].includes(id)){state.workView=id;updateWorkRoute();render();[...document.querySelectorAll('[data-action=work-view]')].find(button=>button.dataset?.id===id)?.focus({preventScroll:true})}break;
case 'episode-nav-page':{const page=Number(id),work=selectedWork();if(work&&Number.isSafeInteger(page)&&page>0&&page<=Math.ceil(episodeExtent(work)/100)){state.episodeNavPage=page;const unit=workEpisodeEntries(work)[0];state.workUnit=unit?.key||'';state.workTaskId=unit?.current?.id||'';updateWorkRoute();render()}}break;
case 'new-episode-material':{const work=selectedWork(),number=Number(id);if(work&&Number.isSafeInteger(number)&&number>0&&number<=episodeExtent(work)){simpleForm('material',work.id);document.getElementById('materialScope').value='episode';toggleMaterialScope('episode');document.getElementById('materialEpisode').value=String(number)}}break;
case 'work-unit':{const work=selectedWork(),unit=work&&visibleWorkUnits(work).find(unit=>unit.key===id);if(unit){state.episodeNavPage=Math.floor(((unit.number||1)-1)/100)+1;const scroll=document.getElementById('episodeNavList')?.scrollTop||0;state.workUnit=id;state.workTaskId=unit.current?.id||'';updateWorkRoute();render();document.getElementById('episodeNavList').scrollTop=scroll;[...document.querySelectorAll('[data-action=work-unit]')].find(button=>button.dataset?.id===id)?.focus({preventScroll:true})}}break;
case 'unit-version':{const work=selectedWork(),unit=work&&selectedWorkUnit(work);if(unit?.tasks.some(task=>task.id===id)){state.workUnit=unit.key;state.workTaskId=id;updateWorkRoute();render()}}break;
case 'work-report-version':{const work=selectedWork();if(work&&workReports(work).some(report=>report.id===id)){state.workView='analysis';state.workReportId=id;updateWorkRoute();render()}}break;
case 'work-evidence':{let ref;try{ref=JSON.parse(id)}catch{ref={taskId:id}}openWorkEvidence(ref.taskId,ref.start);break}
case 'unit-evidence':focusUnitEvidence();break;
case 'submit-unit-knowledge':submitWorkKnowledge('unit',id);break;
case 'submit-work-knowledge':submitWorkKnowledge('work',id);break;
case 'open-work-knowledge':{const work=selectedWork();if(work&&relatedKnowledge(work).some(item=>item.id===id))knowledgeDetail(id);break}
case 'retry-work-task':retryWorkTask(id);break;case 'review-work-select':chooseIntakeWork(id);break;case 'clear':state.topicPage=1;state.query='';state.workGenre='全部题材';state.knowledgeCategory='全部';state.hongguoBoard='';state.hongguoGenre='';state.hongguoSubgenre='';state.status='全部状态';state.stage='全部环节';render();break;case 'close':closeDialog();break;case 'guide':guide();break;case 'theme':theme=theme==='dark'?'light':'dark';document.documentElement.dataset.theme=theme;try{localStorage.setItem('cip-demo-theme',theme)}catch{}render();toast(`已切换为${theme==='dark'?'深色':'浅色'}主题`);break;case 'brainstorm':brainstormDialog();break;case 'brainstorm-add':selectBrainstorm(id);break;case 'brainstorm-remove':selectBrainstorm(id,true);break;case 'brainstorm-generate':generateBrainstorm();break;case 'brainstorm-save':saveBrainstormTopic();break;case 'brainstorm-view':{const topicId=brainstormContext.savedTopicId;closeDialog();topicDetail(topicId);break}case 'spark':sparkDialog();break;case 'spark-edit':sparkDialog(id);break;case 'spark-new':sparkDialog();break;case 'spark-topics':draftDirty=false;closeDialog();navigate(0,1);break;case 'preview-state':state.mode=id;closeDialog();render();break;case 'normal':state.mode='正常';render();break;case 'reset':if(confirm('重置后将清除本原型的本地修改，恢复演示样例。确定重置吗？')){db=structuredClone(seed);db.rankBoards=structuredClone(defaultRankBoards);db.creators=structuredClone(defaultCreators);prepareIntel();initializeFeedArchive();state.biz=['故事短片'];try{localStorage.setItem(workspaceStorageKey,state.biz[0])}catch{}state.topicPage=1;state.hongguoBoard='';state.hongguoGenre='';state.hongguoSubgenre='';save();closeDialog();navigate(0);toast('已恢复初始演示数据')}break;
case 'intel-detail':{const x=db.intel.find(i=>i.id===id);openDialog('情报详情',detailIntro(x)+`<div class="detail-block"><h3>情报摘要</h3><p>${x.summary}</p></div>`+sourceEvidence(id)+notice(x.failed?'原文获取不完整，请补充资料；不能仅凭标题做完整分析。':'适用业务由AI初标（样例），正式交互可人工修正；研究意图不等于质量结论。'),btn('转为选题','derive-topic',id)+btn('查看 / 发起研判','research-send',id,true),true);break}
case 'derive-topic':topicForm('',id);break;case 'new-topic':topicForm();break;case 'edit-topic':topicForm(id);break;case 'topic-detail':topicDetail(id);break;
case 'topic-page':if(state.module===0&&state.tab===1){state.topicPage=Math.max(1,state.topicPage+Number(id));render()}break;case 'topic-more':{if(state.module!==0||state.tab!==1||state.biz[0]!==id||!topicIdeas[id])break;state.topicPage=1;const round=(db.topicBatchCounts[id]||1)+1;db.topicBatchCounts[id]=round;db.topics.unshift(...topicBatch(id,round));save();render();toast(`已新增5张${id}演示选题卡；未调用AI`);break}
case 'topic-add-production':{const x=db.topics.find(t=>t.id===id);if(!x||x.status!=='候选')break;if(!x.biz.length){topicForm(id);toast('请先明确主业务线');break}if(x.biz[0]==='电商短视频'){toast('电商短视频选题流程暂缓');break}x.status='待生产';x.history.push(`v${x.version} · 人工选择加入待生产${currentGenreLoadAssessment(x)?'（附题材承重力演示评估）':x.evaluation!=='已评价'?'（当前版本暂无有效评价）':''}`);save();draftDirty=false;if(dialog.open)closeDialog();navigate(0,2);toast('选题已加入待生产');break}


case 'copy-topic':{const x=db.topics.find(t=>t.id===id);try{await navigator.clipboard.writeText(topicText(x));recordHandoff(x,'复制交接');toast('已复制选题并记录交接')}catch{openDialog('复制选题',`<p class="muted small">浏览器不允许直接访问剪贴板，请选择以下内容手动复制。</p><textarea style="width:100%;height:280px;margin-top:16px" readonly>${esc(topicText(x))}</textarea>`,btn('已手动复制，记录交接','manual-copy',id));}break}
case 'manual-copy':recordHandoff(db.topics.find(t=>t.id===id),'人工确认复制');break;case 'export-topic':downloadTopic(db.topics.find(t=>t.id===id));break;case 'adopt-topic':{const x=db.topics.find(t=>t.id===id);x.status='已采用';x.history.push('人工标记已采用；不代表生产完成');save();render();topicDetail(id);toast('已记录人工采用状态');break}

case 'feedback-evidence':revealFeedbackEvidence(id);break;

case 'research-send':researchIntake(id);break;
case 'knowledge-category':if(id==='全部'||knowledgeCategories.includes(id)){state.knowledgeCategory=id;render()}break;case 'knowledge-detail':knowledgeDetail(id);break;case 'new-knowledge':knowledgeForm();break;case 'edit-knowledge':knowledgeForm(id);break;
case 'approve-knowledge':{const x=db.knowledge.find(k=>k.id===id);if(x.ai!=='通过'){toast('AI审核尚未通过');break}if(!document.getElementById('reviewConfirm')?.checked){toast('请先勾选人工核实确认');break}x.status='已入库';x.reviewedAt=new Date().toISOString();save();draftDirty=false;closeDialog();navigate(1,0);toast('当前版本已完成双审，进入正式知识');break}
case 'delete-knowledge':if(confirm('将这条演示知识移入回收站？30天清理规则仅展示，原型不会自动永久删除。')){db.knowledge.find(k=>k.id===id).status='回收站';save();closeDialog();render();toast('已移入回收站')}break;
case 'research-detail':researchDetail(id);break;
case 'extract-knowledge':{const x=db.research.find(r=>r.id===id);const exists=db.knowledge.find(k=>k.researchId===id);if(exists){navigate(1,2);knowledgeDetail(exists.id);break}const k={id:'K-'+Date.now(),title:'日常动作的重复与情绪递进',summary:'重复日常动作并改变其细节，可以作为表达人物关系变化的候选方法。当前仅一个样例，不能推广为已验证规律。',biz:x.biz,stage:'脚本',type:'案例经验',status:'待AI审核',version:1,ai:'待审核',sourceId:x.sourceId,researchId:id,evidence:`${x.id} v${x.version} · 片段00:12–00:24；固定演示提炼结果，等待AI与人工审核。`};db.knowledge.unshift(k);save();navigate(1,2);knowledgeDetail(k.id);toast('已创建候选草稿，尚未正式入库');break}
case 'new-research':simpleForm('research');break;case 'new-material':simpleForm('material',id);break;case 'new-publication':simpleForm('publication');break;case 'publication-detail':publicationDetail(id);break;


case 'validation-detail':{const x=scoped(validationSamples).find(r=>r.id===id);if(!x)break;openDialog('候选规律验证',`<h3>${esc(x.title)}</h3><div class="meta">${x.id} · ${esc(x.biz[0])}</div><div class="steps"><span class="done">候选提出</span>→<span>独立样本验证</span>→<span>人工审核</span></div>${notice('样本不足，保留候选；不能自动更新正式知识或评价标准。')}<dl class="keyvalues"><dt>调参 / 观察样本</dt><dd>${x.samples} 个（演示）</dd><dt>独立验证样本</dt><dd>尚未提供</dd><dt>目标指标</dt><dd>${esc(x.target)}</dd><dt>新旧标准</dt><dd>${esc(x.standard)}</dd><dt>市场效果</dt><dd>无可对账数据</dd></dl><div class="detail-block"><h3>下一步</h3><p>补充独立样本与时间范围，按同一口径对比新旧标准，记录人工决策。</p></div>`,btn('查看正式标准','goto','3,2'),true);break;}
case 'new-model':modelConfigForm('',id);break;case 'edit-model':modelConfigForm(id);break;
case 'config-detail':openDialog('处理配置详情',`<h3>${{narrative:'叙事文本拆解',product:'商品事实检查',video:'视频内容解析'}[id]}</h3><dl class="keyvalues"><dt>处理步骤</dt><dd>获取正文 → 解析分段 → 提炼候选 → AI审核</dd><dt>输出要求</dt><dd>内容摘要、证据位置、适用业务、限制说明</dd><dt>模型配置</dt><dd>待正式选型与接入</dd><dt>失败处理</dt><dd>保留原因，允许重试或补充资料</dd></dl>${notice('配置编辑与版本发布将在规则确认后细化；此处为只读结构预览。')}`,btn('关闭','close'),true);break;
case 'rubric-detail':openDialog('评价标准 · 生效版本',`${notice('以下为维度结构示例，不是已确认的正式权重。缺失必要参考时返回证据不足。')}${table(['维度','权重示例','证据要求'],[['内容清晰度','40%','正文或成片对应片段'],['结构与表达','35%','完整内容版本'],['业务适配','25%','业务背景与参考资料']])}<div class="detail-block"><h3>硬性不通过项</h3><p>商品事实冲突、必要参考缺失等单独列出，不能被平均分抵消。历史评价继续使用当时的标准版本。</p></div>`,btn('查看候选验证','goto','2,2'),true);break;

}}
listen(document,'pointerover',e=>{
 if(e.pointerType==='touch')return;
 const box=document.getElementById('feedTextPopover'),source=e.target.closest?.('[data-feed-full-text]');
 if(box.contains(e.target)){clearTimeout(feedTextHideTimer);return}
 if(source&&!source.contains(e.relatedTarget))showFeedFullText(source);
});
listen(document,'pointerout',e=>{
 if(!feedTextSource)return;
 const box=document.getElementById('feedTextPopover');
 if(feedTextSource.contains(e.relatedTarget)||box.contains(e.relatedTarget))return;
 if(feedTextSource.contains(e.target)||box.contains(e.target))deferHideFeedFullText();
});
listen(document,'focusin',e=>{if(e.target.id==='reviewWorkName'){renderIntakeWorkOptions(e.target.value);return}
 const source=e.target.closest?.('[data-feed-full-text]');
 if(source)showFeedFullText(source);else if(document.getElementById('feedTextPopover').contains(e.target))clearTimeout(feedTextHideTimer);
});
listen(document,'focusout',e=>{
 const box=document.getElementById('feedTextPopover');
 if(feedTextSource&&!feedTextSource.contains(e.relatedTarget)&&!box.contains(e.relatedTarget))deferHideFeedFullText();
});
listen(document,'keydown',e=>{if(e.target?.dataset?.workId&&['Enter',' '].includes(e.key)){e.preventDefault();action('work-detail',e.target.dataset.workId);return}if(e.target?.dataset?.topicId&&['Enter',' '].includes(e.key)){e.preventDefault();action('topic-detail',e.target.dataset.topicId);return}if(intakeWorkKeydown(e))return;
 if(e.key==='Escape'&&feedTextSource){if(document.getElementById('feedTextPopover').contains(document.activeElement))feedTextSource.focus({preventScroll:true});hideFeedFullText();e.preventDefault()}
});
listen(window,'resize',hideFeedFullText);
listen(window,'scroll',e=>{if(!document.getElementById('feedTextPopover').contains(e.target))hideFeedFullText()},true);
listen(document,'click',e=>{if(intakeWorkContext&&!e.target.closest('.review-work-combobox'))closeIntakeWorkOptions();const b=e.target.closest('[data-action]');if(b&&!b.disabled){hideFeedFullText();action(b.dataset.action,b.dataset.id||'')}});
listen(document,'input',e=>{if(e.target.id==='reviewWorkName'){document.getElementById('reviewWorkId').value='';document.getElementById('reviewWorkHint').textContent='请选择匹配作品，或使用此名称新建';renderIntakeWorkOptions(e.target.value);return}if(e.target.id==='search'){let pos=e.target.selectionStart;state.query=e.target.value;render();let el=document.getElementById('search');el.focus();el.setSelectionRange(pos,pos)}});
listen(document,'change',e=>{if(e.target.id==='materialScope'){toggleMaterialScope(e.target.value);return}if(e.target.id==='unitVersion'){action('unit-version',e.target.value);return}if(e.target.id==='workReportVersion'){action('work-report-version',e.target.value);return}if(e.target.id==='bizInput'){refreshTopicEditorState();return}if(e.target.id==='reviewBiz'){toggleIntakeComicFields(e.target.value);return}if(e.target.id==='workGenreFilter'){state.workGenre=e.target.value;render();return}if(e.target.id==='statusFilter'){state.status=e.target.value;render()}});
listen(document,'submit',e=>{e.preventDefault();const f=e.target,formData=new FormData(f),values=Object.fromEntries(formData);for(const v of f.querySelectorAll('[required]')){if(!v.value.trim()){document.getElementById('formError').textContent='请补充完整的必填信息。';v.focus();return}}
if(f.getAttribute('id')==='researchIntakeForm'){
 const sourceDate=values.sourceDate||latestFeedDate;
 const video=feedSource(values.sourceId,sourceDate),learningTags=[...new Set(formData.getAll('learningTag').filter(tag=>learningPointOptions.includes(tag)))],learningText=(values.learningText||'').trim(),genre=(values.genre||'').trim();
 const error=document.getElementById('formError');
 if(!video){error.textContent='原始内容不存在，请关闭后重新选择。';return}
 if(!['S','A','B','C'].includes(values.grade)){error.textContent='请选择 S、A、B、C 中的一个人工等级。';return}
 if(!businesses.includes(values.biz)||!genre){error.textContent='请确认业务类型与题材标签。';return}
 if(!learningTags.length&&!learningText){error.textContent='请选择学习点标签，或写下具体学习点。';return}
 const episodeInput=String(values.totalEpisodes??'').trim();
 const totalEpisodes=values.biz==='AI漫剧'&&episodeInput?Number(episodeInput):null;
 if(values.biz==='AI漫剧'&&episodeInput&&(!/^\d+$/.test(episodeInput)||!Number.isSafeInteger(totalEpisodes)||totalEpisodes<1)){error.textContent='总集数请填写正整数，或留空表示未知。';return}
 const episodeNumberInput=String(values.episodeNumber??'').trim();
 const episodeNumber=values.biz==='AI漫剧'&&episodeNumberInput?Number(episodeNumberInput):null;
 if(values.biz==='AI漫剧'&&episodeNumberInput&&(!/^\d+$/.test(episodeNumberInput)||!Number.isSafeInteger(episodeNumber)||episodeNumber<1)){error.textContent='当前第几集请填写正整数，或留空表示未知。';return}
 if(totalEpisodes!=null&&episodeNumber!=null&&episodeNumber>totalEpisodes){error.textContent='当前集数不能超过总集数。';return}
 const workName=values.biz==='AI漫剧'?String(values.workName||'').trim():'';
 let selectedWork=null;
 if(values.biz==='AI漫剧'){
  if(!workName||workName.length>100){error.textContent='请填写作品名称（最多100字），或选择已有作品。';return}
  if(values.workId){selectedWork=db.works.find(work=>work.id===values.workId&&work.biz?.includes('AI漫剧'));if(!selectedWork||selectedWork.title!==workName){error.textContent='作品关联已失效，请重新从下拉菜单选择。';return}}
  else if(db.works.some(work=>work.biz?.includes('AI漫剧')&&normalizedWorkName(work.title)===normalizedWorkName(workName))){error.textContent='已有同名作品，请从下拉菜单选择具体作品。';return}
 }
 let record=db.research.find(r=>r.sourceId===video.id&&(r.sourceDate||latestFeedDate)===sourceDate&&['待研判','待分析'].includes(r.status));
 if(!record)record={id:'C-'+Date.now()+'-'+(db.research.length+1),sourceId:video.id,version:1,history:[]};
 let work=values.biz==='AI漫剧'?selectedWork:db.works.find(item=>item.sourceId===video.id&&item.biz?.[0]===values.biz);
 if(!work){work={id:'WORK-S-'+video.id+'-'+Date.now()+'-'+(db.works.length+1),title:workName||video.title,biz:[values.biz],genre,collectedCount:1,analyzedCount:0,sourceId:video.id,totalEpisodes:null};db.works.unshift(work)}
 const alreadyLinked=work.sourceId===video.id||db.research.some(task=>task.workId===work.id&&task.sourceId===video.id);
 if(!alreadyLinked)work.collectedCount=(work.collectedCount||0)+1;
 if(values.biz==='AI漫剧')work.totalEpisodes=totalEpisodes;
 work.collectedCount=Math.max(work.collectedCount||0,1);
 const submittedAt=new Date().toISOString();
 const initialReviews=humanReviewEntries(record);
 Object.assign(record,{workId:work.id,title:video.title,workName:work.title,episodeNumber,totalEpisodes,sourceDate,sourceSnapshotId:getFeedSnapshot(sourceDate).id,biz:[values.biz],genre,rating:values.grade,learningTags,learningText,status:'待分析',submittedAt,sourceSnapshot:{...(video.sourceType==='novel'?{sourceType:'novel',readers:video.readers??null,board:video.board||''}:{}),id:video.id,evidence:video.evidence,sourceDate,title:video.title,plot:video.plot||video.summary||'',url:video.url||'',coverUrl:video.coverUrl||'',frameUrl:video.frameUrl||'',mediaUrl:video.mediaUrl||'',sourceBiz:video.biz?.[0]||'',sourceGenre:video.genre||'',platform:video.platform||'',creator:video.source||'',creatorId:video.creatorId||'',likes:video.likes??null,comments:video.comments??null,shares:video.shares??null,saves:video.saves??null,collectedAt:video.time||'',audienceFeedback:structuredClone(video.audienceFeedback||null)}});
 record.humanReviews=[...initialReviews,humanReviewSnapshot(record)];
 (record.history??=[]).push(`${submittedAt} · 人工提交研判，评级 ${values.grade}`);
 db.research=db.research.filter(r=>r.id!==record.id);db.research.unshift(record);db.lastSubmittedResearchId=record.id;
 save();draftDirty=false;closeDialog();render();toast('已提交至研判室待分析；当前仍在情报流（演示）');return
}

if(f.getAttribute('id')==='modelConfigForm'){submitModelConfig(values);return}
if(f.getAttribute('id')==='modelBindingsForm'){submitModelBindings(values);return}

if(f.getAttribute('id')==='topicForm'){
 const production=e.submitter?.value==='production';
 if(production&&!values.biz){document.getElementById('formError').textContent='请先选择一条主业务线。';return}
 if(values.biz==='电商短视频'){document.getElementById('formError').textContent='电商短视频选题流程暂缓。';return}
 let x=db.topics.find(topic=>topic.id===values.id);
 const title=String(values.title||'').trim(),logline=String(values.logline??values.summary??'').trim();
 if(!title||!logline){document.getElementById('formError').textContent='请填写选题标题和Logline。';return}
 const patch={title,logline,summary:logline,biz:values.biz?[values.biz]:[],audience:values.audience||'',characterSettings:String(values.characterSettings??(values.protagonist!==undefined||values.antagonist!==undefined?topicCharactersText({characters:{protagonist:values.protagonist||'',antagonist:values.antagonist||''}}):x?topicCharactersText(x):'')).trim(),globalRhythm:String(values.globalRhythm??x?.globalRhythm??'').trim()};
 if(x){
  const changed=comparableTopicContent(x)!==comparableTopicContent(patch);
  if(changed){(x.versions??=[]).push({version:x.version,title:x.title,summary:x.summary,logline:topicLogline(x),characterSettings:topicCharactersText(x),characters:structuredClone(x.characters||{}),globalRhythm:x.globalRhythm||'',biz:[...x.biz],audience:x.audience,evaluation:x.evaluation,genreLoadAssessment:structuredClone(x.genreLoadAssessment||null)});x.version++;Object.assign(x,patch,{evaluation:'待重评',origin:x.origin==='闪念胶囊'?'闪念胶囊':'人工编辑'});if(x.origin==='闪念胶囊')delete x.sparkText;requestTopicScore(x);(x.history??=[]).push(`v${x.version} · 人工修改并请求重新评分（待处理）`)}
 }else{x={id:'T-'+Date.now()+'-'+(db.topics.length+1),...patch,sourceId:values.sourceId||'',status:'候选',version:1,evaluation:'未评价',origin:'手工灵感',createdAt:new Date().toISOString(),history:['v1 · 人工创建草稿']};db.topics.unshift(x)}
 if(production){x.status='待生产';x.history.push(`v${x.version} · 人工确认加入待生产`)}
 state.topicPage=1;save();draftDirty=false;closeDialog();navigate(0,production?2:x.status==='候选'?1:2);toast(production?'选题已加入待生产':pendingTopicScoreRequest(x)?'已保存，重新评分待处理（AI未接入）':'选题已保存')
}

if(f.getAttribute('id')==='knowledgeForm'){if(!knowledgeCategories.includes(values.category)){document.getElementById('formError').textContent='请选择知识分类。';return}let x=db.knowledge.find(k=>k.id===values.id);if(x){(x.versions??=[]).push({version:x.version,title:x.title,summary:x.summary,evidence:x.evidence,ai:x.ai,category:x.category??null,type:x.type,biz:[...x.biz],stage:x.stage});Object.assign(x,{title:values.title,summary:values.summary,evidence:values.evidence,biz:[values.biz],stage:values.stage,category:values.category,version:x.version+1,status:'待AI审核',ai:'待审核'})}else db.knowledge.unshift({id:'K-'+Date.now(),title:values.title,summary:values.summary,evidence:values.evidence,biz:[values.biz],stage:values.stage,category:values.category,type:'方法规则',version:1,status:'待AI审核',ai:'待审核'});save();draftDirty=false;closeDialog();navigate(1,2);toast('候选已提交，当前版本等待AI审核')}
if(f.getAttribute('id')==='simpleForm'){let kind=f.dataset.kind;if(!['research','material','publication'].includes(kind))return;if(kind==='material'){submitWorkMaterial(values);return}if(['source','publication'].includes(kind)){try{const url=new URL(values.value);if(!['https:','http:'].includes(url.protocol))throw Error()}catch{document.getElementById('formError').textContent='请填写有效的 http 或 https 地址。';return}}
if(kind==='publication'){const c=scoped(db.research).find(r=>r.id===values.content);if(!c){document.getElementById('formError').textContent='请选择当前业务空间内的内容版本。';return}db.publications.unshift({id:'P-'+Date.now(),title:values.title,content:c.id,version:c.version,biz:c.biz,likes:null,comments:null,shares:null,saves:null,window:'发布后 24 小时',source:'尚未采集',history:[],url:values.value,publishedAt:values.publishedAt,platform:values.platform})}else{const work={id:'WORK-'+Date.now(),title:values.title.trim(),biz:[values.biz],genre:'',collectedCount:1,analyzedCount:0,totalEpisodes:null};db.works.unshift(work);db.research.unshift({id:'C-'+Date.now(),workId:work.id,title:values.title.trim(),biz:[values.biz],status:'待研判',sourceId:'人工提交',version:1,input:values.value})};save();draftDirty=false;closeDialog();navigate(kind==='source'?3:kind==='material'?1:2,['publication','material'].includes(kind)?1:0);toast(kind==='source'?'来源草稿已保存为暂停状态':kind==='publication'?'发布已登记，实绩未获取':'已记录资料，等待后端解析与研判')}
if(f.getAttribute('id')==='performanceForm'){const x=db.publications.find(p=>p.id===values.id);const count=values.likes.trim()===''?null:Number(values.likes);if(count!==null&&(!Number.isSafeInteger(count)||count<0)){document.getElementById('formError').textContent='累计数须为非负整数；未知请留空。';return}x.history.push(`${new Date().toLocaleString('zh-CN')} · 点赞 ${x.likes??'未获取'} → ${count??'未获取'} · 依据：${values.evidence}`);x.likes=count;x.source='手工补录';save();draftDirty=false;render();publicationDetail(x.id);toast('已保存独立快照与更正依据')}
});
listen(window,'beforeunload',e=>{if(draftDirty){e.preventDefault();e.returnValue=''}});
listen(window,'hashchange',()=>{const before=JSON.stringify([state.module,state.tab,state.workId,state.workView,state.workUnit,state.workTaskId,state.workReportId]);const oldModule=state.module,oldTab=state.tab;if(restoreWorkspaceRoute()){const after=JSON.stringify([state.module,state.tab,state.workId,state.workView,state.workUnit,state.workTaskId,state.workReportId]);if(before===after)return;if(state.module!==oldModule||state.tab!==oldTab){state.query='';state.workGenre='全部题材';state.knowledgeCategory='全部';state.status='全部状态';state.mode='正常'}render()}});
for(const work of [seed.works.find(work=>work.id===demoWorkId),db.works.find(work=>work.id===demoWorkId)].filter(Boolean)){
 if(!Object.hasOwn(work,'performanceSnapshot'))work.performanceSnapshot={id:'DEMO-PERFORMANCE-A080',provenance:'demo',platform:'演示平台',scope:'collected-episodes',coverageEpisodes:Array.from({length:55},(_,index)=>index+1),capturedAt:'2026-10-12 11:00',views:1234800,likes:23400,comments:1870,shares:940,saves:6500};
 for(const report of work.reports||[])if(demoReports.some(sample=>sample.id===report.id&&report.provenance==='demo'&&JSON.stringify(sample.sections)===JSON.stringify(report.sections)&&JSON.stringify(sample.coverage)===JSON.stringify(report.coverage))){
  if(!Object.hasOwn(report,'documentSections'))report.documentSections=demoWorkDocumentSections(report);
  if(!Object.hasOwn(report,'climaxCurve'))report.climaxCurve=[[1,2],[8,6],[10,4],[16,7],[24,8],[25,5],[32,6],[40,9]].filter(([episode])=>report.coverage.includes(episode)).map(([episode,intensity])=>({episode,intensity}));
 }
}
initializeFeedArchive();
restoreWorkspaceRoute();render();

 return {
   action,
   restoreRoute(){restoreWorkspaceRoute();render()},
   dispose(){controller.abort();clearWorkThumbnails();hideFeedFullText();for(const id of pendingTimers)nativeClearTimeout(id);pendingTimers.clear();for(const url of downloadUrls)URL.revokeObjectURL(url);downloadUrls.clear();if(dialog.open)dialog.close()}
 };
}
