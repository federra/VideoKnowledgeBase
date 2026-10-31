import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {expect,it,vi} from 'vitest';
import {ApiClient} from '../src/api/client';
import {ApiProvider} from '../src/api/provider';
import {FeedDatePicker} from '../src/components/FeedDatePicker';
const id='11111111-1111-4111-8111-111111111111';
const reply=(data:unknown)=>new Response(JSON.stringify({request_id:id,data}),{status:200,headers:{'Content-Type':'application/json'}});
function mount(fetcher:typeof fetch){
 const onChange=vi.fn();
 const client=new ApiClient({fetcher});
 const wrapper=({children}:{children:React.ReactNode})=><QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><ApiProvider client={client}>{children}</ApiProvider></QueryClientProvider>;
 const view=render(<FeedDatePicker business="motion_comic" value="2026-10-30" today="2026-10-30" onChange={onChange}/>,{wrapper});
 return {view,onChange};
}
it('opens lazily, classifies actual dates and today, disables future, selects past once',async()=>{
 const fetcher=vi.fn(async()=>reply({business_code:'motion_comic',month:'2026-10',today:'2026-10-30',dates:['2026-10-29','2026-10-30']}));
 const {onChange}=mount(fetcher as typeof fetch);expect(fetcher).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'情报流日期'}));
 const saved=await screen.findByRole('button',{name:'2026-10-29，已采集'});
 expect(saved.classList.contains('has-data')).toBe(true);
 expect(screen.getByRole('button',{name:'2026-10-28，无采集数据'}).classList.contains('no-data')).toBe(true);
 expect(screen.getByRole('button',{name:'2026-10-30，已采集，今天'}).getAttribute('aria-pressed')).toBe('true');
 const future=screen.getByRole('button',{name:'2026-10-31，未来日期'});expect((future as HTMLButtonElement).disabled).toBe(true);
 fireEvent.click(future);expect(onChange).not.toHaveBeenCalled();fireEvent.click(saved);
 expect(onChange).toHaveBeenCalledExactlyOnceWith('2026-10-29');expect(screen.queryByRole('dialog')).toBeNull();
 expect(document.activeElement).toBe(screen.getByRole('button',{name:'情报流日期'}));
});
it('never mislabels a pending or failed read as no data; retries without collecting',async()=>{
 let fail=true;
 const fetcher=vi.fn(async()=>fail?new Response('',{status:503}):reply({business_code:'motion_comic',month:'2026-10',today:'2026-10-30',dates:[]}));
 mount(fetcher as typeof fetch);fireEvent.click(screen.getByRole('button',{name:'情报流日期'}));
 await screen.findByText('采集状态暂不可用');expect(screen.getByRole('button',{name:'2026-10-29，状态待确认'})).toBeTruthy();
 expect(screen.queryByRole('button',{name:'2026-10-29，无采集数据'})).toBeNull();
 fail=false;fireEvent.click(screen.getByRole('button',{name:'重试'}));await screen.findByRole('button',{name:'2026-10-29，无采集数据'});
 expect(fetcher.mock.calls.every(call=>(call as unknown as [unknown,RequestInit?])[1]?.method!=='POST')).toBe(true);
});
it('month, business and response scope are isolated; keyboard and Escape preserve selection',async()=>{
 const fetcher=vi.fn(async(url:RequestInfo|URL)=>{const q=new URL(String(url),'http://local').searchParams;return reply({business_code:q.get('business_code'),month:q.get('month'),today:'2026-10-30',dates:q.get('business_code')==='motion_comic'&&q.get('month')==='2026-10'?['2026-10-29']:[]});});
 const {view,onChange}=mount(fetcher as typeof fetch);
 fireEvent.click(screen.getByRole('button',{name:'情报流日期'}));await screen.findByRole('button',{name:'2026-10-29，已采集'});
 fireEvent.click(screen.getByRole('button',{name:'上个月'}));await screen.findByRole('button',{name:'2026-09-30，无采集数据'});
 fireEvent.click(screen.getByRole('button',{name:'下个月'}));const day=await screen.findByRole('button',{name:'2026-10-29，已采集'});
 day.focus();fireEvent.keyDown(day,{key:'ArrowLeft'});await waitFor(()=>expect(document.activeElement).toBe(screen.getByRole('button',{name:'2026-10-28，无采集数据'})));
 fireEvent.keyDown(document.activeElement!,{key:'Escape'});expect(screen.queryByRole('dialog')).toBeNull();expect(onChange).not.toHaveBeenCalled();
 view.rerender(<FeedDatePicker business="story_short" value="2026-10-30" today="2026-10-30" onChange={onChange}/>);
 fireEvent.click(screen.getByRole('button',{name:'情报流日期'}));await screen.findByRole('button',{name:'2026-10-29，无采集数据'});
});
it('rejects another business or impossible dates returned by the calendar endpoint',async()=>{
 const client=new ApiClient({fetcher:(async()=>reply({business_code:'story_short',month:'2026-10',today:'2026-10-30',dates:['2026-10-29']})) as typeof fetch});
 await expect(client.feedCalendar('motion_comic','2026-10')).rejects.toMatchObject({code:'INVALID_RESPONSE'});
});
