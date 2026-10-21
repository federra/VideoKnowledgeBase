import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { ReactNode } from 'react';
import type { ConsoleCreate, FeedItem, Session } from '../../api/client';
import { feedback, useApi, useApiQuery } from '../../api/provider';
import { Icon } from '../../components/Icon';
import { IntelligenceIntakeDrawer } from '../research/IntelligenceIntakeDrawer';
import { FeedbackDrawer } from './FeedbackDrawer';
import {NovelFeed} from './NovelFeed';
const codes: Record<string,ConsoleCreate['business_code']>={AI漫剧:'motion_comic',故事短片:'story_short',电商短视频:'ecommerce_video'};
export function shanghaiToday(){return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());}
export function validDate(value:string){const parsed=new Date(value+'T00:00:00Z');return /^\d{4}-\d\d-\d\d$/.test(value)&&Number.isFinite(parsed.getTime())&&parsed.toISOString().slice(0,10)===value;}
export function compact(value:string|null){
 if(value===null)return '未获取';const n=BigInt(value);
 if(n>=10000n){const tenths=n/1000n;return `${tenths/10n}${tenths%10n?'.'+tenths%10n:''}万`;}
 return n.toLocaleString('zh-CN');
}
function safeLink(value:string|null){try{const url=new URL(value??'');return url.protocol==='https:'&&!url.username&&!url.password?url.href:null;}catch{return null;}}
function Notice({children}:{children:ReactNode}){return <div className="notice"><Icon name="info"/><p>{children}</p></div>;}
/** Full text only opens for actual overflow; evidence stays escaped React text. */
export function FullText({children,className,href}:{children:string;className:string;href?:string|null}){
 const ref=useRef<HTMLSpanElement & HTMLAnchorElement>(null), popup=useRef<HTMLSpanElement>(null);
 const timer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined),description=useId();
 const [position,setPosition]=useState<{left:number;top:number;maxHeight:number;below:boolean;anchorTop:number}|null>(null);
 const keep=()=>clearTimeout(timer.current);
 const hide=()=>{keep();setPosition(null);};
 const show=()=>{keep();const el=ref.current;if(!el||!(el.scrollHeight>el.clientHeight||el.scrollWidth>el.clientWidth))return;
  const rect=el.getBoundingClientRect(),below=Math.max(0,window.innerHeight-rect.bottom-20),above=Math.max(0,rect.top-20),down=below>=Math.min(360,above);
  setPosition({left:Math.max(12,Math.min(rect.left,window.innerWidth-Math.min(480,window.innerWidth-24)-12)),top:rect.bottom+8,maxHeight:Math.min(360,Math.max(1,down?below:above)),below:down,anchorTop:rect.top});
 };
 const deferHide=()=>{keep();timer.current=setTimeout(()=>{if(document.activeElement!==ref.current&&!popup.current?.contains(document.activeElement))setPosition(null);},150);};
 useLayoutEffect(()=>{if(position&&!position.below&&popup.current){const top=Math.max(12,position.anchorTop-8-popup.current.offsetHeight);if(top!==position.top)setPosition({...position,top});}},[position]);
 useEffect(()=>{const close=()=>setPosition(null);window.addEventListener('resize',close);window.addEventListener('scroll',close,true);return()=>{clearTimeout(timer.current);window.removeEventListener('resize',close);window.removeEventListener('scroll',close,true);};},[]);
 const props={ref,className,'aria-describedby':position?description:undefined,onMouseEnter:show,onMouseLeave:deferHide,onFocus:show,onBlur:deferHide,onKeyDown:(e:React.KeyboardEvent)=>{if(e.key==='Escape')hide();}};
 return <span className="feed-fulltext-wrap">{href?<a {...props} href={href} target="_blank" rel="noopener noreferrer">{children} <Icon name="out"/></a>:<span {...props} tabIndex={0}>{children}</span>}
 {position&&createPortal(<span ref={popup} id={description} className="feed-real-popover" role="tooltip" tabIndex={0} style={{left:position.left,top:position.top,maxHeight:position.maxHeight}} onMouseEnter={keep} onMouseLeave={deferHide} onFocus={keep} onBlur={deferHide} onKeyDown={e=>{if(e.key==='Escape')hide();}}>{children}</span>,document.body)}</span>;
}

export function VideoMetrics({item,hongguo=false}:{item:FeedItem;hongguo?:boolean}){
 const o=item.entry.observation;
 const metrics=hongguo?[['热','红果热度',item.heat_display?.replace(/热度$/,'')??'未获取'],['分','评分',item.score_display??'未获取'],['赞','点赞',compact(o.like_count)],['藏','收藏',compact(o.collect_count)]]:[['赞','点赞',compact(o.like_count)],['转','转发',compact(o.share_count)],['评','评论',compact(o.comment_count)],['藏','收藏',compact(o.collect_count)]];
 return <div className="rank-stats" aria-label={hongguo?'红果指标，热度、评分、点赞、收藏':'互动指标，真实快照'}>{metrics.map(([short,label,value])=><span key={short} title={`${label}：${short==='热'?item.heat_display??value:value}`}><b>{short}</b><strong>{value}</strong></span>)}</div>;
}
function Card({item,position,onUnavailable,onFeedback,hongguo=false}:{hongguo?:boolean;item:FeedItem;position:number;onUnavailable:()=>void;onFeedback:()=>void}){
 const o=item.entry.observation,link=safeLink(o.original_url),title=o.display_name||o.description||`抖音作品 ${o.platform_id}`;
 return <article className="rank-card"><div className="feed-card-copy"><div className="rank-main"><span className="rank-number" title="当前列表序号，非平台排名">{String(position).padStart(2,'0')}</span><FullText className="rank-title" href={link}>{title}</FullText><div className="feed-card-context"><div className="feed-meta" aria-label="平台、博主"><span title={item.source_name}>{hongguo?'红果':'抖音'} · {item.source_name}</span><span>{item.author??'博主未记录'}</span></div><div className="feed-card-tags" aria-label="题材">{hongguo?<><span className="genre-tag" title="题材：来源标签第一个词">{item.genre_tags?.[0]??'题材：—'}</span><span className="genre-tag" title="二级题材：来源标签第二个词">{item.genre_hierarchy?.[0]?.subgenres?.[0]??'二级题材：—'}</span></>:<span className="genre-tag">待标注</span>}</div></div></div>
 <FullText className="rank-plot">{`原始描述：${o.description??'未获取'}${link?'':' · 原视频链接未获取或不可用'}`}</FullText></div><div className="feed-card-side"><VideoMetrics item={item} hongguo={hongguo}/><div className="feed-card-actions"><div className="feedback-preview"><button className="feedback-open" aria-label={`查看${title}的观众反馈`} onClick={onFeedback}>观众反馈 ›</button>{item.comment_sample_count!==null&&item.comment_sample_count!==undefined?<span className="feedback-status">已采集 {item.comment_sample_count} 条评论</span>:item.entry.feedback_id?(item.feedback_emotions??[]).map(name=><span className="emotion-tag" key={name} title={name}>{name}</span>):<span className="feedback-status">该日期评论未获取</span>}</div><button className="rank-research" aria-label={`研判：${title}`} onClick={()=>onUnavailable()}>研判</button></div></div></article>;
}
export function IntelligencePage({business,date,onSession,onDateChange}:{business:string;date:string;onDateChange?:(date:string)=>void;onSession?:(value:Session|undefined)=>void}){
 const api=useApi();const [ready,setReady]=useState(false),[error,setError]=useState<unknown>(),[attempt,setAttempt]=useState(0);
 useEffect(()=>{const controller=new AbortController();let active=true;api.getSession(controller.signal).then(s=>{if(active){setReady(true);setError(undefined);onSession?.(s);}}).catch(e=>{if(active){setError(e);setReady(false);onSession?.(undefined);}});return()=>{active=false;controller.abort();};},[api,attempt,onSession]);
 useEffect(()=>api.onBoundary(()=>{setReady(false);setError(api.accessError);onSession?.(undefined);}),[api,onSession]);
 return <><h1 className="sr-only">情报流</h1>{ready?<FeedBody business={business} date={date} onDateChange={onDateChange}/>:<div className="empty" role={error?'alert':'status'}><h2>{error?feedback(error).message:'正在连接本地工作区…'}</h2>{Boolean(error)&&<button className="btn" onClick={()=>setAttempt(x=>x+1)}>重试</button>}</div>}</>;
}
type OverviewState={scope:string;videos:string|null;creators:string|null};
function FeedOverview({business,videos=null,creators=null,novels=null}:{business:string;videos?:string|null;creators?:string|null;novels?:string|null}){
 return <div className="metric-grid feed-overview" aria-label={`${business}监测概览`}>{([['视频',videos],['博主',creators],['小说',novels]] as const).map(([label,value])=><div className="metric-card" key={label}><span>{label}</span><strong>{compact(value)}</strong></div>)}</div>;
}
function FeedBody({business,date,onDateChange}:{business:string;date:string;onDateChange?:(date:string)=>void}){
 const [lane,setLane]=useState<'board'|'creator'|'novel'>('board');const [insight,setInsight]=useState(true);const [overview,setOverview]=useState<OverviewState|null>(null);
 const api=useApi();const novels=useApiQuery(['novels',codes[business],date,'all','','','',1,''],signal=>api.novelFeed(codes[business],date,{},signal),data=>data.items.length===0);
 if(lane==='novel')return <NovelFeed key={business+':'+date} business={business} code={codes[business]} date={date} onLane={setLane} overview={<FeedOverview business={business} videos={overview?.scope===business+':'+date?overview.videos:null} creators={overview?.scope===business+':'+date?overview.creators:null} novels={novels.data?.novel_count}/>}/>;
 return <FeedContents onDateChange={onDateChange} novels={novels.data?.novel_count??null} onOverview={setOverview} selectNovel={()=>setLane('novel')} key={business} business={business} date={date} lane={lane} setLane={setLane} insight={insight} setInsight={setInsight}/>;
}
function FeedContents({onDateChange,novels,business,date,lane,setLane,insight,setInsight,selectNovel,onOverview}:{onDateChange?:(date:string)=>void;novels:string|null;business:string;date:string;lane:'board'|'creator';setLane:(v:'board'|'creator')=>void;insight:boolean;setInsight:(v:boolean)=>void;selectNovel:()=>void;onOverview:(value:OverviewState)=>void}){
 const [hongguoBoard,setHongguoBoard]=useState(''),[hongguoGenre,setHongguoGenre]=useState(''),[hongguoSubgenre,setHongguoSubgenre]=useState('');
 const api=useApi();const [q,setQ]=useState(''),[source,setSource]=useState('hongguo'),[accounts,setAccounts]=useState<string[]>([]),[menu,setMenu]=useState(false),[notice,setNotice]=useState('');
 const [selectedFeedback,setSelectedFeedback]=useState<FeedItem|null>(null);
 const [selectedResearch,setSelectedResearch]=useState<FeedItem|null>(null);
 const [pages,setPages]=useState({board:1,creator:1});const [pageDate,setPageDate]=useState(date);
 // Reset synchronously before reading a new date, avoiding one request for an old page.
 if(pageDate!==date){setPageDate(date);setHongguoGenre('');setHongguoSubgenre('');setSelectedFeedback(null);setSelectedResearch(null);setPages({board:1,creator:1});setMenu(false);}
 const query=useApiQuery(['intelligence',codes[business],date,lane,pages[lane],q,source,accounts.join(','),hongguoBoard,hongguoGenre,hongguoSubgenre],signal=>api.intelligenceFeed(codes[business],date,{lane,page:pages[lane],q,source:lane==='board'&&!['hongguo','tikhub'].includes(source)?source:undefined,videoCatalog:lane==='board'&&['hongguo','tikhub'].includes(source)?source as 'hongguo'|'tikhub':undefined,videoBoard:lane==='board'&&source==='hongguo'?hongguoBoard:undefined,videoGenre:lane==='board'&&source==='hongguo'?hongguoGenre:undefined,videoSubgenre:lane==='board'&&source==='hongguo'?hongguoSubgenre:undefined,accounts:lane==='creator'?accounts:undefined},signal),data=>data.items.length===0);
 const data=query.data;
 useEffect(()=>{if(data)onOverview({scope:business+':'+date,videos:data.metrics.videos,creators:data.metrics.creators});},[data,business,date,onOverview]);
 const total=BigInt(data?.total??'0');const maxPages=total>0n?(total+9n)/10n:1n;
 useEffect(()=>{
  if(!data)return;
  if(source&&!['hongguo','tikhub'].includes(source)&&!data.boards.some(b=>b.id===source))setSource('hongguo');
  const retained=accounts.filter(id=>data.creators.some(c=>c.id===id));
  if(retained.length!==accounts.length)setAccounts(retained);
 },[data,source,accounts]);
 const reset=()=>setPages({board:1,creator:1});
 const isHongguo=lane==='board'&&source==='hongguo';
 return <>
 {!isHongguo&&data?.keyword_ranking_status==='series_order'&&<Notice>当前暂用TikHub短剧热榜（content_type=0），保留首屏返回顺序；简介来自series.desc。可获取整剧累计播放量和收藏量，未返回作品级点赞、评论、分享，保持未获取。播放量已保存，当前卡片沿用赞／转／评／藏四项布局。右侧洞察属于此前其他作品，未对本榜单重新分析。</Notice>}
 {!isHongguo&&data?.keyword_ranking_status==='provider_order'&&<Notice>当前采用{data.boards[0]?.name??'红狐“小剧场”每日热门作品榜'}，保留接口返回顺序展示前10条。该接口每日10点后更新昨日数据，具体排序算法未公开；不按“漫剧”关键词过滤，不称播放量榜。{data.insight?'右侧洞察沿用当日其他作品的已封存评论样本，未对本榜单重新分析。':''}</Notice>}
 {!isHongguo&&data&&!['provider_order','series_order'].includes(data.keyword_ranking_status??'')&&BigInt(data.keyword_works_count??'0')>0n&&<Notice>已保存 {data.keyword_works_count} 条“漫剧”关键词候选；{data.keyword_ranking_status==='default_order'?'当前播放量不可得，采用默认相关性排序（红狐接口），保留返回顺序取前10条。相关性、时效性等因素影响搜索结果，具体权重未公开；与登录抖音后的个性化结果可能不同。':'播放量齐全时按播放量降序；缺失时使用已明确采集的默认相关性顺序。'}{data.keyword_ranking_status==='insufficient_metrics'?'当前尚无可用默认排序批次。':''}仅展示已采集样本，关键词候选不计作达人监测更新。</Notice>}
 {!isHongguo&&data&&!data.has_snapshot&&<Notice>暂无历史数据：该日期未保存可访问的情报快照，指标与洞察不使用最新数据替代。</Notice>}
 {isHongguo&&data?.has_snapshot&&<Notice>每榜最多20部，全部榜单按红果热度数值降序、跨榜去重；热度为综合指标，非播放量。评论为公开播放页预载样本，每部最多15条，未执行AI分析。</Notice>}
 {source==='tikhub'&&data&&<Notice>当前查看TikHub抖音短剧热榜，快照日期 {date}；{data.total==='0'?`该日期暂无快照，最近已保存日期为 ${data.video_latest_dates?.tikhub??'暂无'}，请切换顶部日期。`:'保留原始返回顺序，历史数据未重新采集。'}</Notice>}
 <FeedOverview business={business} novels={novels} videos={data?.metrics.videos} creators={data?.metrics.creators}/>
 <div className="feed-controls"><div className="feed-view-filter" role="group" aria-label="情报类型">{(['board','creator'] as const).map(v=><button key={v} className={v===lane?'active':''} aria-pressed={v===lane} onClick={()=>{setLane(v);setSelectedFeedback(null);setMenu(false);setNotice('');}}>{v==='board'?'视频':'博主'}</button>)}<button aria-pressed={false} onClick={selectNovel}>小说</button></div>
 <div className="feed-specific-filter">{lane==='board'?<div className="rank-filter"><label htmlFor="rankBoardFilter">榜单类型</label><select id="rankBoardFilter" aria-label="榜单类型" value={source} onChange={e=>{setSource(e.target.value);if(data?.video_latest_dates?.[e.target.value]&&date!==data.video_latest_dates[e.target.value])onDateChange?.(data.video_latest_dates[e.target.value]);setHongguoBoard('');setHongguoGenre('');setHongguoSubgenre('');reset();}}><option value="hongguo">红果榜单</option><option value="tikhub">TikHub抖音短剧热榜</option>{data?.boards.filter(b=>!b.name.includes("TikHub")).map(b=><option key={b.id} value={b.id}>{b.name}</option>)}</select></div>:<div className="creator-tools"><div className="creator-dropdown"><button className="creator-trigger" aria-expanded={menu} aria-controls="creatorOptions" onClick={()=>setMenu(!menu)}>{accounts.length?`${accounts.length} 位达人`:'全部达人'} <span aria-hidden="true">⌄</span></button>{menu&&<div className="creator-options" id="creatorOptions" role="group" aria-label="达人筛选，可多选" onKeyDown={e=>{if(e.key==='Escape')setMenu(false);}}><button aria-pressed={!accounts.length} onClick={()=>{setAccounts([]);reset();}}>全部达人</button>{data?.creators.map(c=><button key={c.id} aria-pressed={accounts.includes(c.id)} onClick={()=>{setAccounts(accounts.includes(c.id)?accounts.filter(x=>x!==c.id):[...accounts,c.id]);reset();}}><span className="option-check">{accounts.includes(c.id)?'✓':''}</span><span>{c.name}</span></button>)}{!data?.creators.length&&<p className="muted small">暂无当日达人数据</p>}</div>}</div></div>}</div>
 <label className="search feed-search"><Icon name="search"/><span className="sr-only">搜索当前工作区</span><input id="search" placeholder="搜索视频、博主或剧情简介" value={q} maxLength={100} autoComplete="off" onChange={e=>{setQ(e.target.value);reset();}} /></label></div>
 {lane==='board'&&source==='hongguo'&&<><div className="novel-filters hongguo-filters">{[['榜单类型',hongguoBoard,[['hot-drama','红果热播榜'],['hot-real-drama','真人剧热播榜'],['hot-ai-drama','AI剧热播榜'],['hot-comic-drama','漫剧热播榜']]],['题材',hongguoGenre,(data?.video_genres??[]).map(g=>[g,g])],['二级题材',hongguoSubgenre,(data?.video_subgenres??[]).map(g=>[g,g])]].map(([label,value,options])=><div className="novel-filter-row" role="group" aria-label={'红果'+label} key={label as string}><span className="filter-label">{label as string}</span>{[['','全部'],...(options as string[][])].map(([key,name])=><button className={`chip ${value===key?'active':''}`} aria-pressed={value===key} key={key} onClick={()=>{if(label==='榜单类型'){setHongguoBoard(key);setHongguoGenre('');setHongguoSubgenre('');}else if(label==='题材'){setHongguoGenre(key);setHongguoSubgenre('');}else setHongguoSubgenre(key);reset();}}>{name}</button>)}{label!=='榜单类型'&&!(options as string[][]).length&&<span className="small muted">暂无已采集{label as string}</span>}</div>)}</div>{data?.total==='0'&&<Notice>{data.has_snapshot?'当前筛选暂无红果作品。':'红果榜单尚无已入库快照；题材将按该日期、业务与榜单的实际采集标签展示。'}</Notice>}</>}
 {notice&&<p className="notice" role="status">{notice}<button className="btn small" onClick={()=>setNotice('')}>关闭</button></p>}
 <div className={`feed-columns feed-single ${insight&&!isHongguo?'':'insight-collapsed'}`}><section className={`feed-lane ${lane==='board'?'rank':'creator'}-lane`}><div className="lane-head"><div><h2>{lane==='board'?'榜单':'达人'}</h2><span>{data?`${data.total} 条${lane==='creator'?'作品':''} · 真实快照`:'正在读取'}</span></div></div>
 {query.error?<div className="lane-empty" role="alert"><strong>{query.message}</strong><p>未使用演示数据替代。</p><button className="btn" onClick={()=>void query.refetch()}>重试</button></div>:!data?<div className="lane-empty" role="status"><p>正在获取内容…</p><div className="skeleton"/></div>:<div className={lane==='board'?'rank-list':'creator-list'}>{data.items.map((item,index)=><Card hongguo={lane==='board'&&source==='hongguo'} key={item.entry.id} item={item} position={(pages[lane]-1)*10+index+1} onUnavailable={()=>setSelectedResearch(item)} onFeedback={()=>setSelectedFeedback(item)}/>)}{!data.items.length&&<div className="lane-empty"><strong>{lane==='board'?'暂无榜单数据':'暂无匹配的达人更新'}</strong><p>{q||source||accounts.length?'没有符合当前筛选的当日记录。':lane==='board'?data.keyword_ranking_status==='series_order'?'当前未返回可展示的短剧热榜作品。':data.keyword_ranking_status==='provider_order'?'该请求日期未返回可展示的小剧场视频。':data.keyword_ranking_status==='insufficient_metrics'?'缺少播放量及可核验默认顺序批次，暂未取得对应数据。':'尚无符合关键词和播放量排序要求的数据。':'该日期未保存达人作品，不展示最新数据。'}</p></div>}</div>}
 <div className="feed-pager" aria-label={`${lane==='board'?'榜单':'达人'}翻页`}><span>每页最多10条 · 第 {pages[lane]} / {String(maxPages)} 页 · 共 {data?.total??'未获取'} 条</span><div className="pager-actions"><button aria-label={`${lane==='board'?'榜单':'达人'}上一页`} disabled={!data||pages[lane]===1} onClick={()=>setPages({...pages,[lane]:pages[lane]-1})}>上一页</button><button aria-label={`${lane==='board'?'榜单':'达人'}下一页`} disabled={!data||BigInt(pages[lane])>=maxPages} onClick={()=>setPages({...pages,[lane]:pages[lane]+1})}>下一页</button></div></div></section>
 {insight&&!isHongguo&&<aside className="insight-aside"><div className="lane-head"><div><h2>洞察报告</h2></div><button className="insight-hide" aria-label="收起洞察报告" aria-expanded="true" onClick={()=>setInsight(false)}>收起 ›</button></div><section className="insight-card"><span className="feed-snapshot-date">{date} · 当日快照</span>{data?.insight?<><p className="brief">{data.insight.sample_count} 条评论 · 情绪分类 {data.insight.classified_count} 条（情绪可重叠，占比不相加）。{data.insight.coverage_note}</p>{[['市场情绪',data.insight.emotions.map(e=>`${e.name} ${e.percent}%（${e.count}条）`).join('、')||'证据不足'],['高频母题',data.insight.motif??'证据不足'],['主要题材',data.insight.genre??'证据不足']].map(([label,text])=><div className="insight-item" key={label}><span className="small muted">{label}</span><h3>{text}</h3></div>)}<div className="insight-item"><span className="small muted">建议选题方向</span>{data.insight.suggestions.length?<ul className="insight-directions">{data.insight.suggestions.map((text,i)=><li key={i}>{text}</li>)}</ul>:<h3>证据不足</h3>}</div></>:<p className="brief">{!data?'正在读取该日期洞察…':data.has_snapshot?'该日期尚未生成洞察报告，建议选题方向未获取。':'暂无历史数据，未保存该日期的洞察报告。'}</p>}</section></aside>}</div>
 {selectedFeedback&&<FeedbackDrawer key={selectedFeedback.entry.id} entryId={selectedFeedback.entry.id} business={codes[business]} date={date} title={selectedFeedback.entry.observation.display_name??selectedFeedback.entry.observation.description??'未命名内容'} url={selectedFeedback.entry.observation.original_url} close={()=>setSelectedFeedback(null)}/>}
 {!insight&&!isHongguo&&<button className="insight-restore" aria-label="展开洞察报告" aria-expanded="false" onClick={()=>setInsight(true)}>洞察报告 ‹</button>}
 {selectedResearch&&<IntelligenceIntakeDrawer item={selectedResearch} business={business} date={date} close={()=>setSelectedResearch(null)}/>}</>;
}
