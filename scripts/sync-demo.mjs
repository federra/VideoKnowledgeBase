/** Deterministic extraction only. Never modifies the approved prototype. */
import { readFileSync, writeFileSync, mkdirSync, cpSync, readdirSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { pruneMigratedDemo } from './prune-migrated-demo.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const source = readFileSync(path.join(root, 'doc/prototypes/index.html'), 'utf8');
const hash = createHash('sha256').update(source).digest('hex');
const assetsRoot = path.join(root, 'doc/prototypes/assets');
function assetHashes(directory, prefix = '') {
  return Object.fromEntries(readdirSync(directory, {withFileTypes: true}).sort((a,b) => a.name.localeCompare(b.name)).flatMap(entry => {
    const name = prefix + entry.name;
    return entry.isDirectory()
      ? Object.entries(assetHashes(path.join(directory, entry.name), name + '/'))
      : [[name, createHash('sha256').update(readFileSync(path.join(directory, entry.name))).digest('hex')]];
  }));
}
const assets = assetHashes(assetsRoot);
if (process.argv.includes('--check')) {
  const copied = assetHashes(path.join(root, 'frontend/public/assets'));
  if (JSON.stringify(assets) !== JSON.stringify(copied)) throw new Error('Demo asset drift; review required');
}
const css = source.match(/<style>([\s\S]*?)<\/style>/)[1];
let js = source.match(/<script>([\s\S]*?)<\/script>/)[1];
const icons = js.match(/const icons=(.*);\nconst icon=/)[1];
const solid = js.match(/const navSolidIcons=([\s\S]*?);\nconst navIcon=/)[1];
// Trusted local SVG constants, parsed at build time, never third-party content.
const iconData = Function('return (' + icons + ')')();
const solidData = Function('return (' + solid + ')')();
js = js.replaceAll('content-ui-qa-v1', 'cip-demo-qa-v1')
  .replaceAll('content-ui-v1', 'cip-demo-v1').replaceAll('content-ui-theme', 'cip-demo-theme');
js = js.replace("location.hash.slice(1).split('/')", "location.hash.slice(1).replace(/^\\//,'').split('/')");
const renderStart = js.indexOf('function render(){');
const renderEnd = js.indexOf('\nfunction stateView()', renderStart);
if (renderStart < 0 || renderEnd < 0) throw new Error('Demo render boundary changed; review before syncing.');
js = js.slice(0, renderStart) + `function render(){
 clearWorkThumbnails();hideFeedFullText();
 publish();
 if(state.mode!=='正常'){page.innerHTML=heading(modules[state.module].tabs[state.tab],'')+stateView();return}
 page.innerHTML=renderWorkspace(state.module,state.tab,{
   feed,topicPage,knowledgePage,intake,researchPage,publicationPage,validationPage,consolePage
 });
 hydrateWorkThumbnails();
}` + js.slice(renderEnd);
// The shell is owned exclusively by React, including the capsule badge.
js = js.replace("document.getElementById('sparkFloat').innerHTML=sparkFloatLabel();", 'publish();');
// Date input belongs to the React shell; do not process its bubbling event twice.
js = js.replace("if(e.target.id==='feedDate'){changeFeedDate(e.target.value);return}", '');
// Keep download URLs accountable even if unmount cancels their delayed revocation.
js = js.replace('URL.createObjectURL(new Blob([text]', 'createDownloadUrl(new Blob([text]')
  .replace('setTimeout(()=>URL.revokeObjectURL(url),1000)', 'setTimeout(()=>revokeDownloadUrl(url),1000)');
// Limit all runtime listener lifetimes to its mount, including dialog listeners.
js = js.replace(/\b(document|window|dialog)\.addEventListener\(/g, 'listen($1,');
js = pruneMigratedDemo(js);
const header = `// Generated from approved Demo. SHA-256: ${hash}
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
`;
const footer = `
 return {
   action,
   restoreRoute(){restoreWorkspaceRoute();render()},
   dispose(){controller.abort();clearWorkThumbnails();hideFeedFullText();for(const id of pendingTimers)nativeClearTimeout(id);pendingTimers.clear();for(const url of downloadUrls)URL.revokeObjectURL(url);downloadUrls.clear();if(dialog.open)dialog.close()}
 };
}
`;
const outputs = new Map([
  ['frontend/src/styles/demo.css', `/* Approved Demo stylesheet. SHA-256: ${hash} */\n${css}\n`],
  ['frontend/src/demo/runtime.js', header + js + footer],
  ['frontend/src/demo/icons.json', JSON.stringify({ outline: iconData, solid: solidData }, null, 2) + '\n'],
  ['frontend/src/demo/baseline.json', JSON.stringify({ source: 'doc/prototypes/index.html', sha256: hash, assets }, null, 2) + '\n'],
]);
for (const [name, content] of outputs) {
  const filename = path.join(root, name);
  if (process.argv.includes('--check')) {
    if (readFileSync(filename, 'utf8') !== content) throw new Error(`${name}: baseline drift; review required`);
  } else {
    mkdirSync(path.dirname(filename), { recursive: true });
    writeFileSync(filename, content);
  }
}
if (!process.argv.includes('--check')) cpSync(path.join(root,'doc/prototypes/assets'),path.join(root,'frontend/public/assets'),{recursive:true});
console.log(`${process.argv.includes('--check')?'Verified':'Extracted'} Demo baseline ${hash.slice(0,12)}; original unchanged.`);
