import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, it } from 'vitest';
import { App } from '../src/app/App';
beforeEach(()=>{localStorage.clear();window.location.hash='#3/5';});
function addSource(kind:'单文本'|'多模态',name:string){
 fireEvent.click(screen.getByRole('button',{name:`新增${kind}模型源`}));
 expect((screen.getByLabelText('模型类型') as HTMLSelectElement).selectedOptions[0].textContent).toBe(kind);
 const fields={'模型源名称':name,'API地址':'https://example.com/v1','模型名称':`example-${name}`,'服务端密钥引用':'TEST_MODEL_KEY'};
 for(const [label,value] of Object.entries(fields))fireEvent.input(screen.getByLabelText(label),{target:{value}});
 fireEvent.submit(document.querySelector('#modelConfigForm')!);
}
it('两类各支持多个来源，脚本、报告、评论与视频环节独立选择相应模型源',async()=>{
 render(<App/>);await screen.findByRole('heading',{name:'模型配置'});
 addSource('单文本','文本一');addSource('单文本','文本二');addSource('多模态','视频一');addSource('多模态','视频二');
 const sources=JSON.parse(localStorage.getItem('cip-demo-v1')!).modelConnections;
 expect(sources).toHaveLength(4);
 const chosen={'脚本分析':sources[0].id,'输出分析报告':sources[1].id,'用户评论分析':sources[0].id,'视频分析':sources[2].id};
 for(const [label,id] of Object.entries(chosen))fireEvent.change(screen.getByLabelText(label),{target:{value:id}});
 expect(screen.getByLabelText('视频分析').textContent).toContain('视频二');
 expect(screen.getByLabelText('视频分析').textContent).not.toContain('文本一');
 expect(screen.getByLabelText('脚本分析').textContent).not.toContain('视频一');
 fireEvent.submit(document.querySelector('#modelBindingsForm')!);
 const db=JSON.parse(localStorage.getItem('cip-demo-v1')!);
 expect(db.modelBindings['故事短片']).toMatchObject({decompose:sources[0].id,report:sources[1].id,feedback:sources[0].id,visual:sources[2].id});
 expect(screen.queryByLabelText('语音转写')).toBeNull();expect(screen.queryByLabelText('向量检索')).toBeNull();
});
it('模型源跨业务共用，环节分配隔离保存且不显示真实启用成功',async()=>{
 render(<App/>);await screen.findByRole('heading',{name:'模型配置'});addSource('单文本','共享源');
 const source=JSON.parse(localStorage.getItem('cip-demo-v1')!).modelConnections[0];
 fireEvent.change(screen.getByLabelText('用户评论分析'),{target:{value:source.id}});fireEvent.submit(document.querySelector('#modelBindingsForm')!);
 fireEvent.click(screen.getByRole('button',{name:'AI漫剧'}));
 expect(screen.getByText('共享源',{exact:true})).toBeTruthy();
 expect((screen.getByLabelText('用户评论分析') as HTMLSelectElement).value).toBe('');
 expect(screen.getByText('本地草稿 · 未验证')).toBeTruthy();
});
