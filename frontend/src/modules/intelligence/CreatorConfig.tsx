import {useState} from 'react';
import {CreatorConfigDialog} from '../../components/CreatorConfigDialog';

export function CreatorConfigButton({business}:{business:string}){
 const [open,setOpen]=useState(false);
 return <div className="creator-config-tools"><button className="btn" onClick={()=>setOpen(true)}>配置博主</button><span className="small muted">配置主页后，点击上方“重新采集”获取更新</span>{open&&<CreatorConfigDialog key={business} business={business} close={()=>setOpen(false)}/>}</div>;
}
