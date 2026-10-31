import {expect,it} from 'vitest';
import {quoteGroups} from '../src/modules/knowledge/quoteCatalog';
const item=(codes:string[])=>({tags:codes.map(code=>({kind:'genre' as const,code}))});
it('keeps both themes of a deduplicated quote and maps approved B groups',()=>{
 const groups=quoteGroups(item(['男频 · 仇恨/复仇主题（20条）','男频 · 怜悯/守护主题（20条）']));
 expect(groups.map(g=>g.label)).toEqual(['仇恨/复仇','怜悯/守护']);
 expect(groups.every(g=>g.line==='A'&&g.gender==='男频')).toBe(true);
 expect(quoteGroups(item(['B线 · Werewolf/Supernatural (10)']))[0]).toMatchObject({line:'B',gender:'女频',mapped:true});
 expect(quoteGroups(item(['B线 · Marriage of Convenience/Sweet (10)']))[0]).toMatchObject({line:'B',gender:'女频',mapped:true});
 expect(quoteGroups(item(['未知女频主题']))).toEqual([]);
});
