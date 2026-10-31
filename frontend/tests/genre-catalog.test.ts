import {readFileSync} from 'node:fs';
import {expect,it} from 'vitest';
import {genreCatalog,genreGroup} from '../src/modules/knowledge/genreCatalog';
import type {KnowledgeItem} from '../src/api/client';
it('11个原文大类在Demo与正式页面一致，未标记或冲突来源不猜分类',()=>{
 const html=readFileSync('../doc/prototypes/index.html','utf8');
 const embedded=html.split('const knowledgeGenreCatalog = ')[1].split(';\n')[0];
 expect(JSON.parse(embedded)).toEqual(genreCatalog);
 expect(genreCatalog).toHaveLength(11);
 expect(new Set(genreCatalog.map(g=>g.source)).size).toBe(11);
 const item=(codes:string[])=>({title:'都市男频',tags:codes.map(code=>({kind:'genre',code}))} as Pick<KnowledgeItem,"tags">);
 expect(genreGroup(item([]))).toBeUndefined();
 expect(genreGroup(item(['未知']))).toBeUndefined();
 expect(genreGroup(item(genreCatalog.slice(0,2).map(g=>g.source)))).toBeUndefined();
 for(const group of genreCatalog)expect(genreGroup(item([group.source]))).toEqual(group);
});
