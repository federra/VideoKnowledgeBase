import { useEffect, useLayoutEffect, useRef, useState, useCallback } from 'react';
import { HashRouter, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { IntelligencePage, shanghaiToday, validDate } from '../modules/intelligence/IntelligencePage';
import {RefreshControl} from '../modules/intelligence/RefreshControl';
import { ResearchPage } from '../modules/research/ResearchPage';
import { KnowledgePage } from '../modules/knowledge/KnowledgePage';
import {TopicsPage} from '../modules/topics/TopicsPage';
import {SparkEntry} from '../modules/topics/Sparks';
import {ModelConfigPage} from '../modules/console/ModelConfigPage';
import { ConsolePage } from '../modules/console/ConsolePage';
import type { Session } from '../api/client';
import { ApiProvider } from '../api/provider';
import { createDemoRuntime } from '../demo/runtime.js';
import type { DemoRuntime, DemoSnapshot } from '../demo/types';
import { Icon } from '../components/Icon';
import { Sidebar, Topbar, WorkspaceTabs } from './Navigation';
import { getWorkspace, renderWorkspace } from './workspaces';

const initialSnapshot: DemoSnapshot = {
  module: 0, tab: 0, business: '故事短片', theme: 'light',
  workId: '', workTitle: '', sparkCount: 0,
};

function Application({realTopics=true}:{realTopics?:boolean}) {
  const [snapshot, setSnapshot] = useState(initialSnapshot);
  const runtime = useRef<DemoRuntime | null>(null);
  const location = useLocation();
  const navigate = useNavigate();
  const sourceNavigation = useRef('');
  const [session, setSession] = useState<Session>();
  const sessionChanged = useCallback((value: Session | undefined) => setSession(value), []);
  const [feedDate, setFeedDate] = useState(() => {
    try { const saved=localStorage.getItem('cip-feed-date'); if(saved&&validDate(saved)&&saved<=shanghaiToday())return saved; } catch { /* storage optional */ }
    return shanghaiToday();
  });
  const [researchTitle, setResearchTitle] = useState('');
  const workNameChanged = useCallback((value:string)=>setResearchTitle(value),[]);
  const realResearch = snapshot.module === 2 && snapshot.tab === 0;
  const displaySnapshot = realResearch ? {...snapshot,workTitle:researchTitle} : snapshot;
  const realKnowledge = snapshot.module === 1 && (snapshot.tab === 0 || snapshot.tab === 2 || snapshot.tab === 3);
  const realFeed = snapshot.module === 0 && snapshot.tab === 0;
  const realTopicPage = realTopics && snapshot.module === 0 && (snapshot.tab === 1 || snapshot.tab === 2);
  const realModel = realTopics && snapshot.module === 3 && snapshot.tab === 5;
  const realConsole = snapshot.module === 3 && (snapshot.tab === 0 || snapshot.tab === 4);
  useLayoutEffect(() => {
    const instance = createDemoRuntime({onChange: setSnapshot, renderWorkspace:(module,tab,renderers)=>renderWorkspace(module,tab,renderers,realTopics)});
    runtime.current = instance;
    return () => {instance.dispose();runtime.current = null;};
  }, [realTopics]);
  useEffect(() => {runtime.current?.restoreRoute();}, [location.pathname]);
  useEffect(() => {
    const code=new URLSearchParams(location.search).get('source_business');
    const label=code==='motion_comic'?'AI漫剧':code==='story_short'?'故事短片':code==='ecommerce_video'?'电商短视频':undefined;
    if(!label||!/^\/2\/0\/work\//.test(location.pathname)){sourceNavigation.current='';return;}
    const target=location.pathname+location.search;
    if(snapshot.business===label||sourceNavigation.current===target)return;
    sourceNavigation.current=target;
    void runtime.current?.action('biz',label).then(()=>navigate(target,{replace:true}));
  },[location.pathname,location.search,snapshot.business,navigate]);
  const dispatch = (action: string, id = '') => {
    void runtime.current?.action(action, id).catch(() => {
      const toast = document.getElementById('toast');
      if (toast) {toast.textContent = '页面操作未完成，请刷新后重试。';toast.classList.add('show');}
    });
  };
  return <>
    <div className="app"><Sidebar snapshot={snapshot} dispatch={dispatch} /><main className="main">
      <Topbar snapshot={displaySnapshot} dispatch={dispatch} />
      <div className="workspace"><WorkspaceTabs snapshot={snapshot} feedDate={feedDate} latestFeedDate={shanghaiToday()} dispatch={dispatch} feedAction={<RefreshControl key={snapshot.business} business={snapshot.business==='AI漫剧'?'motion_comic':snapshot.business==='故事短片'?'story_short':'ecommerce_video'} allowed={!!session?.actions.includes('collection.run')&&!!session?.actions.includes('source.configure')} onDateChange={date=>{setFeedDate(date);try{localStorage.setItem('cip-feed-date',date);}catch{/* storage optional */}}}/> }
        changeDate={date => {if(validDate(date)&&date<=shanghaiToday()){setFeedDate(date);try{localStorage.setItem('cip-feed-date',date);}catch{/* storage optional */}}}} />
        {/* This bounded DOM island is the temporary, removable Demo page adapter. */}
        <section id="page" aria-label="当前工作区" hidden={realModel || realTopicPage || realConsole || realFeed || realResearch || realKnowledge} />
        {realTopicPage && <section data-real-workspace aria-label="真实选题"><TopicsPage business={snapshot.business} tab={snapshot.tab} onSession={sessionChanged}/></section>}
        {realModel && <section data-real-workspace aria-label="真实模型配置"><ModelConfigPage business={snapshot.business} onSession={sessionChanged}/></section>}
        {realKnowledge && <section data-real-workspace aria-label="真实知识库"><KnowledgePage business={snapshot.business} tab={snapshot.tab} onSession={sessionChanged}/></section>}
        {realResearch && <section data-real-workspace aria-label="真实内容研判"><ResearchPage business={snapshot.business} onSession={sessionChanged} onWorkName={workNameChanged}/></section>}
        {realFeed && <section data-real-workspace aria-label="真实情报流"><IntelligencePage business={snapshot.business} date={feedDate} onSession={sessionChanged}/></section>}
        {realConsole && <section data-real-workspace aria-label="真实控制台"><ConsolePage key={`${snapshot.business}:${snapshot.tab}`} business={snapshot.business} tab={snapshot.tab} onSession={sessionChanged} /></section>}
        <footer className="footer"><span>{realTopicPage ? "选题与版本交接 · 真实服务" : realModel ? "模型配置 · 真实服务" : realKnowledge ? "知识候选与双审发布 · 真实服务" : realFeed ? "情报流 · 真实快照 · Asia/Shanghai" : realResearch ? "研判导入与文本解析 · 真实服务" : realConsole ? "控制台采集与运行 · 真实服务" : "工程基础 v0.1 · Demo样例，不连接真实业务服务"}</span></footer>
      </div>
    </main></div>
    {realTopics ? <SparkEntry/> : <button id="sparkFloat" className="spark-float" aria-label="打开闪念胶囊" onClick={() => dispatch('spark')}>
      <Icon name="spark" /><span>闪念胶囊</span><span className="spark-count">{snapshot.sparkCount}</span>
    </button>}
    <dialog id="dialog" aria-labelledby="dialogTitle" />
    <div id="feedTextPopover" role="tooltip" tabIndex={0} hidden />
    <div id="toast" className="toast" role="status" aria-live="polite" />
  </>;
}
function WorkspaceRoute({realTopics}:{realTopics:boolean}) {
  const {pathname} = useLocation();
  const [, module, tab] = pathname.split('/');
  const workspace = /^\d+$/.test(module ?? '') ? getWorkspace(Number(module)) : undefined;
  if (!workspace || !/^\d+$/.test(tab ?? '') || !workspace.pages[Number(tab)]) return <Navigate to="/0/0" replace />;
  return <Application realTopics={realTopics} />;
}
export function App({realTopics=true}:{realTopics?:boolean}={}) {
  const [queryClient] = useState(() => new QueryClient({defaultOptions: {queries: {retry: false, staleTime: 30_000}}}));
  return <QueryClientProvider client={queryClient}><ApiProvider><HashRouter>
    <Routes><Route path="*" element={<WorkspaceRoute realTopics={realTopics} />} /></Routes>
  </HashRouter></ApiProvider></QueryClientProvider>;
}
