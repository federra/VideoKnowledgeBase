import { Link } from 'react-router-dom';
import { Icon } from '../components/Icon';
import { businesses, getWorkspace, workspaces } from './workspaces';
import type { DemoSnapshot } from '../demo/types';
export type Dispatch = (action: string, id?: string) => void;

export function Sidebar({snapshot, dispatch, identity}: {snapshot: DemoSnapshot; dispatch: Dispatch; identity?: string}) {
  return <aside className="sidebar">
    <div className="brand"><span className="brand-mark" id="brandIcon"><Icon name="book" /></span>内容智库</div>
    <nav className="nav" id="nav" aria-label="一级导航">{workspaces.map(workspace =>
      <button key={workspace.id} className={snapshot.module === workspace.id ? 'active' : ''}
        aria-current={snapshot.module === workspace.id ? 'page' : undefined}
        onClick={() => dispatch('module', String(workspace.id))}>
        <Icon name={workspace.icon} active={snapshot.module === workspace.id} /><span>{workspace.name}</span>
      </button>)}
    </nav>
    <div className="sidebar-bottom"><div className="side-note">把信息变成判断<br />让经验成为知识</div>
      <div className="profile"><span className="avatar">南</span><div>{identity ?? "南哥"}<div className="small muted">{identity !== undefined ? "本地工作区 · 当前权限" : "全权限演示身份"}</div></div></div>
    </div>
  </aside>;
}
export function Topbar({snapshot, dispatch}: {snapshot: DemoSnapshot; dispatch: Dispatch}) {
  const workspace = getWorkspace(snapshot.module)!;
  const isWork = snapshot.module === 2 && snapshot.tab === 0 && !!snapshot.workTitle;
  const nextTheme = snapshot.theme === 'dark' ? '浅色' : '深色';
  return <header className="topbar"><div className="top-context">
    <nav className="breadcrumb" id="breadcrumb" aria-label="面包屑">
      <Link id="crumb" to={`/${workspace.id}/0`}>{workspace.name}</Link><span className="muted" aria-hidden="true">›</span>
      {isWork ? <><Link id="crumbTab" to={`/${workspace.id}/${snapshot.tab}`}>{workspace.pages[snapshot.tab].name}</Link>
        <span className="muted" aria-hidden="true">›</span><span id="crumbWork" aria-current="page" title={snapshot.workTitle}>{snapshot.workTitle}</span></>
        : <span id="crumbTab" aria-current="page">{workspace.pages[snapshot.tab].name}</span>}
    </nav></div>
    <div className="top-actions"><div className="business-workspace"><span className="workspace-label">业务线</span>
      <div id="businessWorkspace" className="workspace-options" role="group" aria-label="业务线，单选">
        {businesses.map(business => <button key={business} className={snapshot.business === business ? 'active' : ''}
          aria-pressed={snapshot.business === business} onClick={() => dispatch('biz', business)}>{business}</button>)}
      </div></div>
      <button id="themeToggle" className="btn theme-switch" aria-label={`切换${nextTheme}主题`}
        aria-pressed={snapshot.theme === 'dark'} onClick={() => dispatch('theme')}>
        <Icon name={snapshot.theme === 'dark' ? 'sun' : 'moon'} /><span>{nextTheme}主题</span>
      </button>
    </div>
  </header>;
}
export function WorkspaceTabs({snapshot, dispatch, changeDate, feedDate, latestFeedDate}: {
  snapshot: DemoSnapshot; dispatch: Dispatch; changeDate: (date: string) => void; feedDate: string; latestFeedDate: string;
}) {
  const workspace = getWorkspace(snapshot.module)!;
  return <div className="workspace-nav"><nav id="tabs" className="tabs" aria-label="二级工作区">
    {workspace.pages.map((page, index) => <button key={page.name} className={snapshot.tab === index ? 'active' : ''}
      aria-current={snapshot.tab === index ? 'page' : undefined} onClick={() => dispatch('tab', String(index))}>{page.name}</button>)}
    </nav><div id="feedDateTools">{snapshot.module === 0 && snapshot.tab === 0 && <div className="feed-date-filter">
      <label htmlFor="feedDate">日期</label><input id="feedDate" type="date" value={feedDate}
        max={latestFeedDate} aria-label="情报流日期" title="按北京时间查看指定日期的真实快照"
        onChange={event => changeDate(event.target.value)} />
    </div>}</div></div>;
}
