/** Remove migrated UI paths from extracted Demo; preserve the approved source. */
import ts from '../frontend/node_modules/typescript/lib/typescript.js';
const obsoleteState = new Set(['feedDate','rankPage','creatorPage','feedView','insightOpen','creatorMenuOpen','rankBoard','creators','novelPage','novelPlatform']);
const obsoleteActions = new Set(['feed-latest','feed-view','creator-menu','creator-all','creator-select','insight-toggle','feed-page','rank-board-manage','rank-board-remove','creator-manage','creator-remove','feedback-open','feedback-research','new-source','toggle-source','retry-job','job-detail']);
const obsoleteFunctions = new Set(['feed','feedOverview','novelFeed','feedPage','feedPager','feedDateFilter','changeFeedDate','audienceFeedbackDialog','rankBoardFilter','creatorFilter','insightAside','rankBoardDialog','creatorDialog']);
export function pruneMigratedDemo(source) {
  let file = ts.createSourceFile('demo.js',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.JS);
  const edits=[];
  const remove = node => edits.push([node.getStart(file),node.end,'']);
  function walk(node,owner='') {
    if(ts.isFunctionDeclaration(node)) {
      owner=node.name?.text??owner;
      if(obsoleteFunctions.has(owner)){remove(node);return;}
    }
    if(ts.isCaseClause(node)&&((owner==='action'&&obsoleteActions.has(node.expression.text))||(owner==='consolePage'&&['0','4'].includes(node.expression.getText(file))))){remove(node);return;}
    if(ts.isTryStatement(node)&&node.getText(file).includes('feedDateStorageKey')){remove(node);return;}
    if(ts.isIfStatement(node)&&/^f\.getAttribute\('id'\)\s*===\s*'(rankBoardForm|creatorForm)'$/.test(node.expression.getText(file))){remove(node);return;}
    if(ts.isIfStatement(node)&&node.expression.getText(file)==="kind==='source'"&&node.elseStatement){edits.push([node.getStart(file),node.elseStatement.getStart(file),'']);return;}
    if(ts.isIfStatement(node)&&node.expression.getText(file).match(/^e\.target\.id\s*===\s*'(rankBoardFilter|rankBoardBiz|creatorBiz|novelBoardFilter)'$/)){remove(node);return;}
    if(ts.isPropertyAssignment(node)&&ts.isObjectLiteralExpression(node.parent)&&ts.isVariableDeclaration(node.parent.parent)&&node.parent.parent.name.getText(file)==='state'&&obsoleteState.has(node.name.getText(file))){
      let end=node.end;while(/[\s]/.test(source[end]??'')&&end<source.length)end++;if(source[end]===',')end++;edits.push([node.getStart(file),end,'']);return;
    }
    if(ts.isExpressionStatement(node)&&ts.isBinaryExpression(node.expression)){
      const left=node.expression.left.getText(file);
      if(left.startsWith('state.')&&obsoleteState.has(left.slice(6))){remove(node);return;}
    }
    ts.forEachChild(node,child=>walk(child,owner));
  }
  walk(file);
  for(const [start,end,replacement] of edits.sort((a,b)=>b[0]-a[0]))source=source.slice(0,start)+replacement+source.slice(end);
  source=source.replace(/const feedDateStorageKey=.*\nlet selectedFeedDate=.*\n/,'')
    .replaceAll('state.feedDate','latestFeedDate')
    .replace('let kind=f.dataset.kind;',"let kind=f.dataset.kind;if(!['research','material','publication'].includes(kind))return;")
    .replace('let feedbackContext=null;','').replace('const feedPageSize=10;','')
    .replace("source:['新增采集来源','来源名称','来源地址','保存来源'],",'');
  // No migrated render callback or duplicate date API is exposed to the shell.
  source=source.replace('feed,topicPage,knowledgePage','topicPage,knowledgePage');
  // Drop now unreachable helper functions. Identifier counting includes callback references.
  let changed=true;
  while(changed){
    changed=false;file=ts.createSourceFile('demo.js',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.JS);
    const counts=new Map(),functions=[];
    function count(node){if(ts.isIdentifier(node))counts.set(node.text,(counts.get(node.text)??0)+1);if(ts.isFunctionDeclaration(node)&&node.name)functions.push(node);ts.forEachChild(node,count);}count(file);
    for(const node of functions.sort((a,b)=>b.pos-a.pos))if(counts.get(node.name.text)===1){source=source.slice(0,node.getStart(file))+source.slice(node.end);changed=true;}
  }
  // The approved seed remains for unconverted research/topic demonstrations only.
  return source;
}
