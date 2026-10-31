import {afterEach,expect,it} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {ApiProvider} from '../src/api/provider';
import {ApiClient} from '../src/api/client';
import {TopicEditor} from '../src/modules/topics/TopicEditor';
import {parseTopic,parseAssessment} from '../src/modules/topics/contracts';
const id='11111111-1111-4111-8111-111111111111',time='2026-10-31T00:00:00Z';
const fields={title:'测试方向',audience:'读者',logline:'冲突',character_settings:'角色',global_rhythm:'节奏'};
const assessment={id,topic_version:1,rubric_version:'genre-load-v2',dimensions:['emotion','conflict','contrast','antagonist','twist','audience','platform','acquisition','sequel','differentiation'].map((key,i)=>({key,score:i<5?4:null,analysis:i<5?'有文本依据':'缺少市场证据'})),content_total:20,market_total:null,total:null,limitations:['缺少市场证据'],created_at:time};
const base={id,business_code:'motion_comic',version:1,status:'candidate',fields,origin:'manual',created_at:time,updated_at:time,evaluation_status:'insufficient_evidence',source_refs:{},history:[],assessment,evaluation_task:null,score_model_ready:true};
afterEach(()=>{cleanup();sessionStorage.clear();});
async function editor(overrides={},fail=false){const writes:{path:string;key:string|null;body:unknown}[]=[];let reads=0;const task={id,task_id:id,state:'queued',safe_error_code:null,topic_id:id,topic_version:1,assessment:null};const response=(data:unknown)=>new Response(JSON.stringify({request_id:id,data}),{headers:{'Content-Type':'application/json'}});const client=new ApiClient({fetcher:async(path,init)=>{const url=String(path);if(url.endsWith('/session'))return response({org_id:id,member_id:id,authz_version:'9876',display_name:'成员',actions:[],csrf_token:'a'.repeat(64),expires_at:'2030-01-01T00:00:00Z'});if(init?.method){writes.push({path:url,key:new Headers(init.headers).get('Idempotency-Key'),body:JSON.parse(String(init.body))});if(fail)throw Error('network');if(init.method==='PATCH')return response({...base,fields:{...fields,title:'已改'},version:2,assessment:null,evaluation_status:'needs_review'});return response({...task,topic_version:writes.some(w=>w.path===url.replace('/evaluate',''))?2:1});}reads++;return response({...task,state:'succeeded',assessment});}});await client.getSession();const view=render(<QueryClientProvider client={new QueryClient()}><ApiProvider client={client}><TopicEditor initial={parseTopic({...base,...overrides})} business={(overrides as {business_code?:'story_short'}).business_code??'motion_comic'} businessLabel="AI漫剧" close={()=>{}} changed={()=>{}} scope="score-test"/></ApiProvider></QueryClientProvider>);return {writes,reads:()=>reads,unmount:view.unmount};}
it('缺市场证据保留20内容分，市场和总分未知且仅五个有效比例条；编辑立即隐藏旧评分',async()=>{await editor();expect(screen.getAllByRole('meter')).toHaveLength(5);expect(screen.getByText('20 / 25')).toBeTruthy();expect(screen.getByText('— / 50')).toBeTruthy();fireEvent.change(screen.getByRole('textbox',{name:'选题标题'}),{target:{value:'已改'}});expect(screen.queryAllByRole('meter')).toHaveLength(0);expect(screen.queryByText('20 / 25')).toBeNull();});
it('拒绝非法总分、越界维度及旧版本评分',()=>{expect(()=>parseTopic({...base,assessment:{...assessment,total:20}})).toThrow();expect(()=>parseTopic({...base,assessment:{...assessment,dimensions:assessment.dimensions.map((d,i)=>i===0?{...d,score:6}:d)}})).toThrow();expect(()=>parseTopic({...base,version:2})).toThrow();});
it('读取不调用模型，显式评分防双击并轮询到结果',async()=>{const f=await editor({assessment:null,evaluation_status:'not_evaluated'});expect(f.writes).toHaveLength(0);const score=screen.getByRole('button',{name:'评分'});fireEvent.click(score);fireEvent.click(score);await waitFor(()=>expect(f.writes).toHaveLength(1));expect(f.writes[0].body).toEqual({expected_version:1});await waitFor(()=>expect(f.reads()).toBe(1),{timeout:2500});expect(await screen.findByText('20 / 25')).toBeTruthy();expect(f.writes).toHaveLength(1);});
it('保存并重新评分用保存返回的新版本执行，修改前分数不回填',async()=>{const f=await editor();fireEvent.change(screen.getByRole('textbox',{name:'选题标题'}),{target:{value:'已改'}});fireEvent.click(screen.getByRole('button',{name:'保存并重新评分'}));await waitFor(()=>expect(f.writes).toHaveLength(2));expect(f.writes[1]).toMatchObject({path:'/api/v1/topics/'+id+'/evaluate',body:{expected_version:2}});});
it('评分响应未知后只显式恢复同幂等键，关闭重开保留原提交',async()=>{const f=await editor({assessment:null},true);fireEvent.click(screen.getByRole('button',{name:'评分'}));await screen.findByRole('alert');expect(f.writes).toHaveLength(1);expect(screen.getByRole('button',{name:'评分'})).toHaveProperty('disabled',true);fireEvent.click(screen.getByRole('button',{name:'恢复原评分提交'}));await waitFor(()=>expect(f.writes).toHaveLength(2));expect(f.writes[1].key).toBe(f.writes[0].key);f.unmount();const restored=await editor({assessment:null});expect(restored.writes).toHaveLength(0);fireEvent.click(screen.getByRole('button',{name:'恢复原评分提交'}));await waitFor(()=>expect(restored.writes).toHaveLength(1));expect(restored.writes[0].key).toBe(f.writes[0].key);});
it('故事短片明确无适用量表，未配置评分模型给配置入口而非调用',async()=>{const f=await editor({business_code:'story_short',assessment:null,score_model_ready:false});expect(screen.queryAllByRole('meter')).toHaveLength(0);expect(screen.getByText(/故事短片暂无适用评分量表/)).toBeTruthy();expect(screen.queryByRole('button',{name:'评分'})).toBeNull();expect(f.writes).toHaveLength(0);});

it('未知评分模型配置只给入口；保存配置不触发页面评分',async()=>{const f=await editor({assessment:null,score_model_ready:false});expect(screen.getByRole('button',{name:'评分'})).toHaveProperty('disabled',true);expect(screen.getByRole('link',{name:'前往评分模型配置'}).getAttribute('href')).toBe('#/3/5');expect(f.writes).toHaveLength(0);});
it('损坏待核验记录禁止付费请求，旧评分任务不能绑定新版',async()=>{sessionStorage.setItem('cip-topic-score:score-test:'+id,'broken');const f=await editor({assessment:null});fireEvent.click(screen.getByRole('button',{name:'恢复原评分提交'}));expect(await screen.findByRole('alert')).toBeTruthy();expect(f.writes).toHaveLength(0);fireEvent.change(screen.getByRole('textbox',{name:'选题标题'}),{target:{value:'已改'}});fireEvent.submit(screen.getByRole('textbox',{name:'选题标题'}).closest('form')!);await new Promise(resolve=>setTimeout(resolve,0));expect(f.writes).toHaveLength(0);expect(()=>parseTopic({...base,evaluation_task:{id,task_id:id,topic_id:id,topic_version:2,state:'succeeded',safe_error_code:null,assessment:null}})).toThrow();});

it('遵循Demo紧凑评分行，不展开模型长分析与限制原文',async()=>{await editor();expect(screen.queryByText(/AI漫剧 · 国内80集 · genre-load-v2/)).toBeNull();expect(screen.queryAllByText('有文本依据')).toHaveLength(0);expect(screen.queryAllByText('缺少市场证据')).toHaveLength(0);expect(screen.getAllByRole('meter')).toHaveLength(5);});

const inferred={...assessment,rubric_version:'genre-load-v3-inferred',market_basis:'ai_inference',dimensions:assessment.dimensions.map((d,i)=>({...d,score:i<5?4:[0,5,2,3,4][i-5]})),content_total:20,market_total:14,total:34};
it('新量表接收市场整数及十维总分，展示紧凑市场AI推断标签和全部分数条',async()=>{
 expect(parseAssessment(inferred).total).toBe(34);
 await editor({assessment:inferred,evaluation_status:'scored'});
 expect(screen.getByText('市场：AI推断')).toBeTruthy();
 expect(screen.getByText('14 / 25')).toBeTruthy();
 expect(screen.getByText('34 / 50')).toBeTruthy();
 expect(screen.getAllByRole('meter')).toHaveLength(10);
 expect(screen.getByRole('meter',{name:'用户基数评分'}).getAttribute('aria-valuenow')).toBe('0');
 expect(screen.queryByText('缺少市场证据')).toBeNull();
 fireEvent.change(screen.getByRole('textbox',{name:'选题标题'}),{target:{value:'已改'}});
 expect(screen.queryByText('市场：AI推断')).toBeNull();
});
it('新量表未知维度不当零分，全未知市场仍属于AI推断政策',()=>{
 const unknown={...inferred,dimensions:assessment.dimensions,market_total:null,total:null};
 expect(parseAssessment(unknown).total).toBeNull();
 expect(()=>parseAssessment({...unknown,market_total:0,total:20})).toThrow();
});
it('严格拒绝新量表错漏依据、非法维度、伪造总分及未知量表',()=>{
 for(const market_basis of [undefined,null,'unavailable','measured'])expect(()=>parseAssessment({...inferred,market_basis})).toThrow();
 for(const score of ['4',true,1.5,-1,6])expect(()=>parseAssessment({...inferred,dimensions:inferred.dimensions.map((d,i)=>i===8?{...d,score}:d)})).toThrow();
 for(const totals of [{total:35},{market_total:15},{content_total:19},{total:'34'}])expect(()=>parseAssessment({...inferred,...totals})).toThrow();
 expect(()=>parseAssessment({...inferred,rubric_version:'genre-load-v4'})).toThrow();
});
it('旧评分兼容缺省或unavailable依据且市场仍未知，不冒充AI推断',async()=>{
 expect(parseAssessment(assessment).market_total).toBeNull();
 expect(parseAssessment({...assessment,market_basis:'unavailable'}).total).toBeNull();
 expect(()=>parseAssessment({...assessment,market_basis:'ai_inference'})).toThrow();
 expect(()=>parseAssessment({...inferred,rubric_version:'genre-load-v2',market_basis:'unavailable'})).toThrow();
 await editor();expect(screen.queryByText('市场：AI推断')).toBeNull();
});
