import {readFileSync} from 'node:fs';
import {expect,it,vi} from 'vitest';

it('Demo retains its keyboard cursor after asynchronous rebinding and never selects a future date',()=>{
 vi.useFakeTimers();
 const html=readFileSync('../doc/prototypes/index.html','utf8');
 const functions=html.slice(html.indexOf('let feedCalendarDemo='),html.indexOf('function feedDateFilter()'));
 const root=document.createElement('div');document.body.append(root);
 // Run the actual prototype calendar functions against its local snapshot boundary.
 const boot=new Function('document','setTimeout','root',`
 const latestFeedDate='2026-10-04',state={feedDate:'2026-10-04'};
 const getFeedSnapshot=day=>day==='2026-10-03'?{intel:[{}]}:null;
 const inWorkspace=()=>true;
 ${functions}
 function render(){root.innerHTML='<div data-demo-calendar>'+demoCalendar()+'</div>';}
 feedCalendarDemo.open=true;render();
 return {move:()=>demoCalendarMonth(1),close:()=>{demoCalendarClose(false);demoCalendarCleanup?.();}};
 `);
 const app=boot(document,setTimeout,root);
 try{
  vi.runOnlyPendingTimers();
  expect(document.activeElement?.getAttribute('data-day')).toBe('2026-10-04');
  document.activeElement?.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}));
  vi.runOnlyPendingTimers();
  expect(document.activeElement?.getAttribute('data-day')).toBe('2026-10-03');
  document.activeElement?.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}));
  vi.runOnlyPendingTimers();
  expect(document.activeElement?.getAttribute('data-day')).toBe('2026-10-02');
  expect(root.querySelector('[data-day="2026-10-03"]')?.classList.contains('has-data')).toBe(true);
  expect((root.querySelector('[data-day="2026-10-05"]') as HTMLButtonElement).disabled).toBe(true);
 }finally{app.close();root.remove();vi.clearAllTimers();vi.useRealTimers();}
});

it('Demo pads October with real September and November dates while preserving future disabling',()=>{
 vi.useFakeTimers();
 const html=readFileSync('../doc/prototypes/index.html','utf8');
 const functions=html.slice(html.indexOf('let feedCalendarDemo='),html.indexOf('function feedDateFilter()'));
 const root=document.createElement('div');document.body.append(root);
 const boot=new Function('document','setTimeout','root',`
 const latestFeedDate='2026-10-30',state={feedDate:'2026-10-30'};
 const getFeedSnapshot=day=>day==='2026-09-30'?{intel:[{}]}:null;
 const inWorkspace=()=>true;
 ${functions}
 function render(){root.innerHTML='<div data-demo-calendar>'+demoCalendar()+'</div>';}
 feedCalendarDemo.open=true;feedCalendarDemo.month='2026-10';render();
 return ()=>{demoCalendarClose(false);demoCalendarCleanup?.();};
 `);
 const close=boot(document,setTimeout,root);
 try{
  vi.runOnlyPendingTimers();
  const dates=root.querySelectorAll('[data-day]');expect(dates).toHaveLength(35);
  expect(dates[0].getAttribute('data-day')).toBe('2026-09-28');
  expect(dates[34].getAttribute('data-day')).toBe('2026-11-01');
  expect(root.querySelector('[data-day="2026-09-30"]')?.classList.contains('has-data')).toBe(true);
  expect((dates[34] as HTMLButtonElement).disabled).toBe(true);
 }finally{close();root.remove();vi.clearAllTimers();vi.useRealTimers();}
});
