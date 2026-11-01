import {parseSpark,parseTopic} from '../topics/contracts';
import type {Spark,Topic} from '../topics/contracts';
export type Access={enabled:boolean;setup_required:boolean;org_id:string|null};
export type User={id:string;login_name:string;display_name:string;role:'administrator'|'user';enabled:boolean;lock_version:string;created_at:string};
export type Space={member:User;sparks:Spark[];topics:Topic[]};
const object=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v);
const uuid=(v:unknown):v is string=>typeof v==='string'&&/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(v);
export function parseAccess(v:unknown):Access{if(!object(v)||typeof v.enabled!=='boolean'||typeof v.setup_required!=='boolean'||!(v.org_id===null||uuid(v.org_id)))throw Error('shape');return v as Access;}
export function parseUser(v:unknown):User{if(!object(v)||!uuid(v.id)||typeof v.login_name!=='string'||typeof v.display_name!=='string'||!['administrator','user'].includes(String(v.role))||typeof v.enabled!=='boolean'||typeof v.lock_version!=='string'||!/^[1-9][0-9]*$/.test(v.lock_version)||typeof v.created_at!=='string'||!Number.isFinite(Date.parse(v.created_at)))throw Error('shape');return v as User;}
export function parseUsers(v:unknown):{items:User[]}{if(!object(v)||!Array.isArray(v.items))throw Error('shape');return {items:v.items.map(parseUser)};}
export function parseSpace(v:unknown):Space{if(!object(v)||!Array.isArray(v.sparks)||!Array.isArray(v.topics))throw Error('shape');return {member:parseUser(v.member),sparks:v.sparks.map(parseSpark),topics:v.topics.map(parseTopic)};}
