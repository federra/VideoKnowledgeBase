import {readFileSync} from 'node:fs';
import {expect,it} from 'vitest';
import {getWorkspace} from '../src/app/workspaces';

it('暂隐藏入口保留全部模块和知识页原始路由编号',()=>{
 expect([0,1,2,3].map(id=>getWorkspace(id)?.name)).toEqual(['情报局','藏经阁','研判室','控制台']);
 expect(getWorkspace(1)?.pages.map(page=>page.name)).toEqual(['知识浏览','入库处理','审核队列','回收站']);
 expect(getWorkspace(2)?.pages[0].name).toBe('内容研判');
});

it('单HTML Demo同样隐藏入口且回收站仍使用tab=3',()=>{
 const html=readFileSync('../doc/prototypes/index.html','utf8');
 const config=html.split('\n').filter(line=>line.startsWith('const modules=')||line.startsWith('const navOrder=')).join('\n');
 const navigation=new Function(config+';return {modules,navOrder};')();
 expect(navigation.navOrder).toEqual([0,1,3]);
 expect(navigation.modules[2].name).toBe('研判室');
 const start=html.indexOf("modules[state.module].tabs.map((t,i)=>"),end=html.indexOf(".join('');if(state.mode",start);
 expect(start).toBeGreaterThan(0);expect(end).toBeGreaterThan(start);
 const tabs=new Function('modules','state','return '+html.slice(start,end)+".join('');")(navigation.modules,{module:1,tab:3});
 const root=document.createElement('div');root.innerHTML=tabs;
 expect(Array.from(root.querySelectorAll('button'),button=>[button.textContent,button.dataset.id])).toEqual([['知识浏览','0'],['回收站','3']]);
 expect(root.querySelector('[data-id="3"]')?.getAttribute('aria-current')).toBe('page');
});
