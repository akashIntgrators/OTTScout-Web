import assert from 'node:assert/strict';
import {WatchlistSync,validCloudRecord,validTitleId} from '../web/watchlist-sync.js';
const timestamp={seconds:1793650000,nanoseconds:0};
const row=(id,saved=true)=>({id,data:{titleId:id,saved,updatedAt:timestamp}});
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
function storage(seed={}){const map=new Map(Object.entries(seed));return {map,getItem:key=>map.get(key)??null,setItem:(key,value)=>map.set(key,value),removeItem:key=>map.delete(key)};}
function remote(initial=[]){
  const records=new Map(initial.map(v=>[v.id,v.data]));let next,error;let fail=false;let blocked=null;
  const adapter={subscribe(n,e){next=n;error=e;return ()=>{};},async importMissing(ids,current){if(fail)throw Error('offline');for(const id of ids){if(!current())throw Error('stale');if(!records.has(id))records.set(id,row(id).data);}adapter.emit();},async write(id,saved,current){if(blocked)await blocked;if(fail)throw Error('offline');if(!current())throw Error('stale');records.set(id,row(id,saved).data);adapter.emit();},emit(){next?.([...records].map(([id,data])=>({id,data})));},error(){error?.(Error('offline'));},set fail(v){fail=v;},set blocked(v){blocked=v;},records};return adapter;
}
assert.equal(validTitleId('motn:A-123'),true);assert.equal(validTitleId('motn:../secret'),false);assert.equal(validTitleId('motn:'+'a'.repeat(160)),false);
assert.equal(validCloudRecord('motn:1',row('motn:1').data),true);
for(const value of [{...row('motn:1').data,extra:true},{...row('motn:1').data,titleId:'motn:2'},{...row('motn:1').data,updatedAt:null},{...row('motn:1').data,saved:'true'}])assert.equal(validCloudRecord('motn:1',value),false);
// Guest saves import only if absent. False cloud tombstones survive first sign-in.
{
 const local=storage({'ottscout-watchlist':JSON.stringify(['motn:1','motn:2',0])});const api=remote([row('motn:1',false)]);const model=new WatchlistSync(local);
 model.setUser('A',api);api.emit();await tick();assert.deepEqual([...model.ids()],['motn:2']);assert.equal(api.records.get('motn:1').saved,false);assert.equal(api.records.has('0'),false);
 model.toggle('motn:2');await tick();assert.equal(api.records.get('motn:2').saved,false);
 model.setUser(null);assert.deepEqual([...model.ids()],['motn:1','motn:2',0]);assert.equal(JSON.parse(local.map.get('ottscout-watchlist')).length,3);
 model.setUser('A',api);api.emit();await tick();assert.equal(model.ids().has('motn:2'),false,'Removed imports must not reappear');
}
// Existing account cache is displayed before a server snapshot; no empty SDK memory snapshot enters core.
{
 const local=storage();const api=remote([row('motn:4')]);let model=new WatchlistSync(local);model.setUser('A',api);api.emit();await tick();
 model.setUser(null);model=new WatchlistSync(local);api.fail=true;model.setUser('A',api);api.error();assert.equal(model.ids().has('motn:4'),true);
 assert.equal(model.toggle('motn:4'),true);assert.equal(model.ids().has('motn:4'),false);assert.equal(model.pending.size,1);assert.equal(JSON.parse(local.map.get(model.key())).pending[0].saved,false);
 // Restart offline, then receive the authoritative old server list: pending removal still wins.
 model=new WatchlistSync(local);model.setUser('A',api);assert.equal(model.ids().has('motn:4'),false);api.fail=false;api.emit();await tick();assert.equal(api.records.get('motn:4').saved,false);assert.equal(model.pending.size,0);
}
// A late callback or write from account A cannot change B or the guest key.
{
 const local=storage({'ottscout-watchlist':'["motn:guest"]'});const a=remote([row('motn:A')]),b=remote([row('motn:B')]);const model=new WatchlistSync(local);
 model.setUser('A',a);a.emit();await tick();let unblock;a.blocked=new Promise(resolve=>unblock=resolve);model.toggle('motn:newA');model.setUser('B',b);b.emit();await tick();a.emit();unblock();await tick();
 assert.equal(model.ids().has('motn:A'),false);assert.equal(model.ids().has('motn:newA'),false);assert.equal(model.ids().has('motn:B'),true);assert.equal(a.records.has('motn:newA'),false);assert.equal(local.map.get('ottscout-watchlist'),'["motn:guest"]');
}
// Toggling a title while its earlier write is in flight keeps the newest revision queued.
{
 const local=storage();const api=remote();const model=new WatchlistSync(local);model.setUser('A',api);api.emit();await tick();let unblock;api.blocked=new Promise(resolve=>unblock=resolve);
 model.toggle('motn:rapid');model.toggle('motn:rapid');unblock();await tick();await tick();assert.equal(api.records.get('motn:rapid').saved,false);assert.equal(model.pending.size,0);assert.equal(model.ids().has('motn:rapid'),false);
}
// Corrupt stored records are never silently erased or imported; a failed durable write is rejected.
{
 const local=storage({'ottscout-watchlist':'{broken'});let state;const model=new WatchlistSync(local,value=>state=value);model.emit();assert.equal(model.toggle('motn:1'),false);assert.equal(local.map.get('ottscout-watchlist'),'{broken');assert.equal(state.status,'storage-error');
 const bad=storage({'ottscout-account-watchlist-v1:A':'{"version":1,"uid":"B"}'});const api=remote([row('motn:1')]);const account=new WatchlistSync(bad);account.setUser('A',api);api.emit();await tick();assert.equal(account.toggle('motn:2'),false);assert.equal(api.records.has('motn:2'),false);assert.equal(bad.map.get(account.key()),'{"version":1,"uid":"B"}');
 const unavailable=storage();const failed=new WatchlistSync(unavailable);const cloud=remote();failed.setUser('A',cloud);cloud.emit();await tick();unavailable.setItem=()=>{throw Error('quota');};assert.equal(failed.toggle('motn:1'),false);assert.equal(failed.pending.size,0);assert.equal(cloud.records.has('motn:1'),false);
}
console.log('Watchlist account isolation, tombstones, offline restart, rapid-toggle and corrupt-storage tests passed.');

// A secondary read-only tab cannot erase the owner's pending queue, even with a snapshot.
{
 const local=storage();const ownerApi=remote(),readerApi=remote();let readerState;
 const owner=new WatchlistSync(local),reader=new WatchlistSync(local,value=>readerState=value);
 owner.setUser('A',ownerApi);reader.setUser('A',readerApi,{readOnly:true});
 assert.equal(owner.toggle('motn:one'),true);const before=local.map.get(owner.key());
 readerApi.emit();await tick();assert.equal(reader.toggle('motn:two'),false);assert.equal(local.map.get(owner.key()),before);assert.equal(readerState.status,'read-only');assert.equal(readerState.canSave,false);
 const reopened=new WatchlistSync(local);reopened.setUser('A',remote());assert.equal(reopened.ids().has('motn:one'),true);assert.equal(reopened.pending.size,1);assert.equal(readerApi.records.size,0);
}
console.log('Read-only secondary tabs preserve the owner’s durable queue.');
