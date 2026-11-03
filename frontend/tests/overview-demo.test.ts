import {readFileSync} from 'node:fs';
import {expect,it} from 'vitest';
const html=readFileSync('../doc/prototypes/index.html','utf8');
const overview=html.slice(html.indexOf('function feedOverview('),html.indexOf('function feedBrowserStart('));
it.each([['加载中',['加载中','加载中','加载中']],['失败',['加载失败','加载失败','加载失败']],['正常',['未获取','未获取','未获取']]])('Demo的%s预览区分请求状态和确认缺失', (mode,expected)=>{
 const run=new Function('mode',`const state={biz:['AI漫剧'],mode,feedDate:'2026-10-17',feedView:'rank'},latestFeedDate='2026-10-17';const getFeedSnapshot=()=>null,esc=s=>s,scoped=s=>s,compactNum=v=>v==null?'未获取':String(v);${overview};return feedOverview();`);
 const root=document.createElement('div');root.innerHTML=run(mode);
 expect(Array.from(root.querySelectorAll('strong')).map(x=>x.textContent)).toEqual(expected);
});
