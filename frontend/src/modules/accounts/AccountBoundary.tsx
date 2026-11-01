import {createContext,useCallback,useContext,useEffect,useRef,useState} from 'react';
import type {ReactNode,FormEvent} from 'react';
import {ApiError} from '../../api/client';
import type {Session} from '../../api/client';
import {feedback,useApi} from '../../api/provider';
import {Icon} from '../../components/Icon';
import {parseAccess} from './contracts';
import type {Access} from './contracts';
import './accounts.css';
import {clearAllTopicSessionState} from '../topics/scope';
const Context=createContext<{session?:Session;logout:()=>Promise<void>}>({logout:async()=>{}});
export const useAccount=()=>useContext(Context);
export const accountsEnabled=(session?:Session)=>!!session&&'user_accounts_enabled' in session&&session.user_accounts_enabled===true;
export const administrator=(session?:Session)=>!!session?.actions.includes('member.manage');
function clearPersonalDrafts(){clearAllTopicSessionState();}
function announce(){try{localStorage.setItem('cip-account-change',crypto.randomUUID());}catch{/* cross-tab revalidation also occurs on focus */}}
export function AccountBoundary({children}:{children:ReactNode}){
 const api=useApi();const [session,setSession]=useState<Session>();const [access,setAccess]=useState<Access>();const [error,setError]=useState('');const [loading,setLoading]=useState(true);const [attempt,setAttempt]=useState(0);const logoutInProgress=useRef(false);const lastVerified=useRef(0);const focusReading=useRef(false);const activeSession=useRef<Session|undefined>(undefined);activeSession.current=session;
 const discover=useCallback(async(signal?:AbortSignal)=>{const entry=await api.get('/api/v1/access',parseAccess,signal);setAccess(entry);setLoading(false);},[api]);
 useEffect(()=>{let alive=true;const c=new AbortController();setLoading(true);api.getSession(c.signal).then(value=>{if(alive){lastVerified.current=Date.now();setSession(value);setLoading(false);setError('');}}).catch(async e=>{if(!alive)return;setSession(undefined);try{if(e instanceof ApiError&&e.status===401){await discover(c.signal);if(alive)setError('');}else if(alive){setError(feedback(e).message);setLoading(false);}}catch(x){if(alive){setError(feedback(x).message);setLoading(false);}}});return()=>{alive=false;c.abort();};},[api,attempt,discover]);
 useEffect(()=>api.subscribe(()=>{if(logoutInProgress.current)return;const current=api.currentSession;if(current&&!api.accessBlocked){lastVerified.current=Date.now();setSession(current);setLoading(false);setError('');}else if(api.accessBlocked){setSession(undefined);}}),[api]);
 useEffect(()=>api.onBoundary(()=>{const problem=api.accessError;if(logoutInProgress.current)return;if(!problem){if(activeSession.current)clearPersonalDrafts();return;}setSession(undefined);clearPersonalDrafts();if(problem.status===401){setLoading(true);void discover().catch(e=>{setError(feedback(e).message);setLoading(false);});}else{setError(problem.message);setLoading(false);}}),[api,discover]);
 useEffect(()=>{
  const controller=new AbortController();
  const changed=(event:StorageEvent)=>{if(event.key!=='cip-account-change')return;api.invalidateIdentity();setSession(undefined);clearPersonalDrafts();setAttempt(n=>n+1);};
  const focused=()=>{
   // Window focus is only a reason to check, never evidence of an identity change.
   if(!accountsEnabled(activeSession.current)||focusReading.current||Date.now()-lastVerified.current<60_000)return;
   focusReading.current=true;lastVerified.current=Date.now();
   // A real 401 or changed principal is handled by the shared client boundary.
   // Network failures leave the current editor intact; every API still checks auth.
   void api.getSession(controller.signal).catch(()=>{}).finally(()=>{focusReading.current=false;});
  };
  window.addEventListener('storage',changed);window.addEventListener('focus',focused);
  return()=>{controller.abort();window.removeEventListener('storage',changed);window.removeEventListener('focus',focused);};
 },[api]);
 const logout=async()=>{logoutInProgress.current=true;setSession(undefined);setLoading(true);clearPersonalDrafts();try{await api.logout();setError('');}catch(e){setError('退出结果尚未确认，请重试退出。'+feedback(e).message);}finally{logoutInProgress.current=false;announce();try{await discover();}catch(e){setError(feedback(e).message);setLoading(false);}}};
 if(session&&!loading)return <Context.Provider key={`${session.org_id}:${session.member_id}`} value={{session,logout}}>{children}</Context.Provider>;
 if(loading)return <main className="account-screen"><div className="card account-form" role="status">正在确认用户身份…</div></main>;
 if(access?.enabled)return <LoginForm access={access} initialError={error} accepted={value=>{if(!administrator(value)&&/^#\/?3(?:\/|$)/.test(window.location.hash))window.location.hash="/0/0";clearPersonalDrafts();setSession(value);setError('');announce();}} retry={()=>setAttempt(n=>n+1)}/>;
 return <main className="account-screen"><section className="card account-form"><h1>暂时无法进入工作区</h1><p role="alert">{error||'请确认服务配置后重试。'}</p><button className="btn" onClick={()=>setAttempt(n=>n+1)}>重试</button></section></main>;
}
function LoginForm({access,initialError,accepted,retry}:{access:Access;initialError:string;accepted:(s:Session)=>void;retry:()=>void}){
 const api=useApi();const [register,setRegister]=useState(false);const [email,setEmail]=useState('');const [password,setPassword]=useState('');const [confirm,setConfirm]=useState('');const [busy,setBusy]=useState(false);const [error,setError]=useState('');
 async function submit(e:FormEvent){e.preventDefault();if(busy||access.setup_required)return;if(register&&password!==confirm){setError('两次密码不一致。');return;}if(register&&[...password].length<8){setError('密码至少需要8个字符。');return;}setBusy(true);setError('');try{const result=register?await api.registerAccount({email:email.trim().toLowerCase(),password}):await api.login({org_id:access.org_id!,login_name:email.trim().toLowerCase(),password});setPassword('');setConfirm('');accepted(result);}catch(x){setPassword('');setConfirm('');setError(register&&x instanceof ApiError&&x.code==='VERSION_CONFLICT'?'此邮箱已注册，请直接登录或使用其他邮箱。':feedback(x).message);}finally{setBusy(false);}}
 return <main className="account-screen"><div className={"account-login-layout"+(!register&&!access.setup_required?" with-test-accounts":"")}><section className="card account-form"><div className="account-brand"><span className="brand-mark"><Icon name="book"/></span><span>内容智库</span></div><h1>{access.setup_required?'用户系统正在初始化':register?'注册账号':'登录内容智库'}</h1><p className="muted">{access.setup_required?'请等待本地管理员初始化完成后，重新读取入口。':register?'使用邮箱创建个人账号，闪念和选题仅自己与管理员可见。':'登录后进入自己的创作空间，榜单和知识库由团队共享。'}</p>{access.setup_required?<button className="btn" onClick={retry}>重新读取入口</button>:<form onSubmit={e=>void submit(e)}><label>邮箱<input type="email" autoComplete="username" value={email} required maxLength={254} onChange={e=>setEmail(e.target.value)} disabled={busy}/></label><label>密码<input type="password" autoComplete={register?'new-password':'current-password'} value={password} required minLength={register?8:undefined} maxLength={1024} onChange={e=>setPassword(e.target.value)} disabled={busy}/></label>{register&&<><label>确认密码<input type="password" autoComplete="new-password" value={confirm} required minLength={8} maxLength={1024} onChange={e=>setConfirm(e.target.value)} disabled={busy}/></label><p className="small muted">密码8～1024个字符，可使用密码管理器。</p></>}{(error||initialError)&&<p className="form-error" role="alert">{error||initialError}</p>}<button className="btn primary" disabled={busy} type="submit">{busy?'正在提交…':register?'注册并登录':'登录'}</button><button className="btn quiet" disabled={busy} type="button" onClick={()=>{setRegister(v=>!v);setPassword('');setConfirm('');setError('');}}>{register?'返回登录':'邮箱注册'}</button>{initialError&&<button className="btn" type="button" onClick={retry}>重新确认身份</button>}</form>}</section>{!register&&!access.setup_required&&<aside className="card account-test-accounts"><h2>内部测试账号</h2><p className="muted">管理员可进入控制台；普通用户使用自己的个人空间。</p><textarea aria-label="内部测试账号" readOnly rows={8} value={"管理员\n账号：admin@admin.com\n密码：admin123\n\n普通用户\n账号：user1@user.com\n密码：user1#123"}/></aside>}</div></main>;
}
