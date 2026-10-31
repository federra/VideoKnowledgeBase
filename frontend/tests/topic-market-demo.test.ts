import {readFileSync} from 'node:fs';
import {expect,it} from 'vitest';

function demoScore(){
 const html=readFileSync('../doc/prototypes/index.html','utf8');
 const start=html.indexOf('const genreLoadDimensions='),end=html.indexOf('let topicEditContext=null;');
 return new Function(`${html.split('\n').find(line=>line.startsWith('const esc='))}\n${html.slice(start,end)};return {sample:sampleGenreLoadAssessment,render:renderGenreLoadAssessment,valid:validGenreLoadAssessment};`)();
}
it('Demo新样例显示AI推断演示标识及数值总分；旧量表不改成新推断',()=>{
 const app=demoScore(),sample=app.sample({version:1,title:'方向',audience:'观众',logline:'文本',characterSettings:'角色',globalRhythm:'节奏'},0);
 expect(sample.provenance).toBe('demo');
 const root=document.createElement('div');root.innerHTML=app.render(sample);
 expect(root.textContent).toContain('市场：AI推断（演示）');
 expect(root.textContent).toContain('32 / 50');
 expect(root.querySelectorAll('[role=meter]')).toHaveLength(10);
 expect(root.textContent).not.toContain('目标人群为');
 const legacy={...sample,schemaVersion:'genre-load-v2',marketBasis:undefined};
 expect(app.valid(legacy)).toBe(true);
 root.innerHTML=app.render(legacy);expect(root.textContent).not.toContain('AI推断');
});
