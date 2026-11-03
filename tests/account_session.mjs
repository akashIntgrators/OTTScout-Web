import assert from 'node:assert/strict';
import test from 'node:test';
import {AccountSession} from '../web/account-session.js';
import {WatchlistSync} from '../web/watchlist-sync.js';
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
function fakeLocks(){const held=new Set();return {request(name,options,callback){assert.equal(options.ifAvailable,true);return Promise.resolve().then(async()=>{if(held.has(name))return callback(null);held.add(name);try{return await callback({name});}finally{held.delete(name);}});}};}
function fixture(){
 const values=new Map();const storage={getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value)};
 const transports=[];const adapter=()=>{let next;const result={subscribe(fn){next=fn;return ()=>{};},emit(){next?.([]);},async importMissing(){throw Error('offline');},async write(){throw Error('offline');}};transports.push(result);return result;};
 return {values,storage,adapter,transports};
}
test('one tab owns all account cache writes; a read-only tab cannot erase pending changes and can take over',async()=>{
 const f=fixture(),locks=fakeLocks(),a=new WatchlistSync(f.storage),b=new WatchlistSync(f.storage);
 const one=new AccountSession(a,f.adapter,locks),two=new AccountSession(b,f.adapter,locks);
 await one.bind({uid:'A'});await tick();await two.bind({uid:'A'});await tick();
 assert.equal(a.readOnly,false);assert.equal(b.readOnly,true);
 assert.equal(a.toggle('motn:one'),true);const durable=f.values.get(a.key());
 f.transports.at(-1).emit();assert.equal(b.toggle('motn:two'),false);assert.equal(f.values.get(a.key()),durable);
 await one.bind(null);await tick();await two.bind({uid:'A'});await tick();
 assert.equal(b.readOnly,false);assert.equal(b.ids().has('motn:one'),true);assert.equal(b.pending.size,1);
 await two.bind(null);await tick();
});
test('rapid auth switching while a lock request is pending never installs the old UID',async()=>{
 const f=fixture(),model=new WatchlistSync(f.storage),session=new AccountSession(model,f.adapter,fakeLocks());
 const a=session.bind({uid:'A'}),b=session.bind({uid:'B'});await Promise.all([a,b]);await tick();
 assert.equal(model.uid,'B');assert.equal(model.readOnly,false);await session.bind(null);await tick();assert.equal(model.uid,null);
});
test('a browser without Web Locks refuses account saves without touching existing durable data',async()=>{
 const f=fixture(),model=new WatchlistSync(f.storage),session=new AccountSession(model,f.adapter,null);
 await session.bind({uid:'A'});assert.equal(model.readOnly,true);assert.equal(model.toggle('motn:one'),false);assert.equal(f.values.size,0);
 await session.bind(null);assert.equal(model.toggle('motn:guest'),true);assert.equal(JSON.parse(f.values.get('ottscout-watchlist'))[0],'motn:guest');
});
