// No Firebase dependency: the same rules apply to cached, guest and remote IDs.
export const validTitleId = value => typeof value === 'string' && value.length <= 160 && /^motn:[A-Za-z0-9-]+$/.test(value);
const validUid = value => typeof value === 'string' && value.length > 0 && value.length <= 128 && !value.includes('/');
const exact = (value, keys) => value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).sort().join(',') === [...keys].sort().join(',');
export function validCloudRecord(id, value) {
  return Boolean(validTitleId(id) && exact(value, ['titleId','saved','updatedAt']) && value.titleId === id && typeof value.saved === 'boolean'
    && value.updatedAt && Number.isInteger(value.updatedAt.seconds) && value.updatedAt.seconds > 0
    && Number.isInteger(value.updatedAt.nanoseconds) && value.updatedAt.nanoseconds >= 0 && value.updatedAt.nanoseconds < 1e9);
}
export class WatchlistSync {
  constructor(storage, onChange = () => {}) {
    this.storage=storage;this.onChange=onChange;this.uid=null;this.generation=0;this.unsubscribe=null;
    this.records=new Map();this.pending=new Map();this.imported=false;this.ready=false;this.status='guest';this.error='';this.busy=false;this.revision=0;this.guestError='';this.accountError='';this.lastGuest=new Set();this.writeError='';this.deletionPending=false;this.readOnly=false;this.readOnlyReason='';
  }
  read(key) { const raw=this.storage.getItem(key);if(raw===null)return null;if(typeof raw!=='string'||raw.length>4000000)throw new Error('Invalid local data');return JSON.parse(raw); }
  write(key,value) { try { this.storage.setItem(key,JSON.stringify(value));this.writeError='';return true; } catch { this.writeError='Device storage is unavailable. Keep this page open until changes sync.';return false; } }
  key(uid=this.uid) { return 'ottscout-account-watchlist-v1:'+encodeURIComponent(uid); }
  guest() { try {const value=this.read('ottscout-watchlist');if(value!==null&&(!Array.isArray(value)||value.length>10000||!value.every(id=>Number.isSafeInteger(id)&&id>=0||validTitleId(id))))throw new Error('Invalid guest watchlist');this.lastGuest=new Set(value||[]);this.guestError='';}catch{this.guestError='Your guest watchlist could not be read. Saving is paused to protect it. Clear this site’s data only if you no longer need those device saves.';}return new Set(this.lastGuest); }
  ids() {
    if(!this.uid)return this.guest();
    const records=new Map(this.records);for(const [id,change] of this.pending)records.set(id,change.saved);
    return new Set([...records].filter(([,value])=>value).map(([id])=>id));
  }
  emit() { const ids=this.ids();this.onChange({uid:this.uid,ids,status:this.deletionPending?'deletion-pending':this.readOnly?'read-only':this.accountError||((!this.uid||!this.imported)&&this.guestError)?'storage-error':this.status,error:this.deletionPending?'Account deletion has started. Finish deleting your account; new saves and imports are disabled.':this.readOnly?this.readOnlyReason:this.accountError||((!this.uid||!this.imported)&&this.guestError)||this.writeError||this.error,pending:this.pending.size,ready:this.ready,canSave:!this.deletionPending&&!this.readOnly&&!this.accountError&&!((!this.uid||!this.imported)&&this.guestError)&&!this.writeError}); }
  cache() { if(this.uid&&!this.accountError&&!this.readOnly)return this.write(this.key(),{version:1,uid:this.uid,deleting:this.deletionPending,records:[...this.records].map(([titleId,saved])=>({titleId,saved})),pending:[...this.pending].map(([titleId,value])=>({titleId,...value})),imported:this.imported}); }
  load(uid) {
    this.records=new Map();this.pending=new Map();this.imported=false;this.accountError='';this.deletionPending=false;
    let value;try{value=this.read(this.key(uid));}catch{this.accountError='Device account saves could not be read. Saving and sync are paused to protect pending changes. Clear this site’s data only if you no longer need unsynced changes.';return;}if(value===null)return;
    if(!exact(value,['version','uid','records','pending','imported','deleting'])||value.version!==1||value.uid!==uid||!Array.isArray(value.records)||!Array.isArray(value.pending)||typeof value.imported!=='boolean'||typeof value.deleting!=='boolean'||value.records.length>10000||value.pending.length>10000){this.accountError='Device account saves are unreadable. Saving and sync are paused to protect pending changes.';return;}
    if(!value.records.every(v=>exact(v,['titleId','saved'])&&validTitleId(v.titleId)&&typeof v.saved==='boolean')||!value.pending.every(v=>exact(v,['titleId','saved','revision'])&&validTitleId(v.titleId)&&typeof v.saved==='boolean'&&Number.isSafeInteger(v.revision)&&v.revision>0)||new Set(value.records.map(v=>v.titleId)).size!==value.records.length||new Set(value.pending.map(v=>v.titleId)).size!==value.pending.length){this.accountError='Device account saves are unreadable. Saving and sync are paused to protect pending changes.';return;}
    this.records=new Map(value.records.map(v=>[v.titleId,v.saved]));this.pending=new Map(value.pending.map(v=>[v.titleId,{saved:v.saved,revision:v.revision}]));
    this.revision=Math.max(this.revision,...value.pending.map(v=>v.revision));this.imported=value.imported;this.deletionPending=value.deleting;
  }
  setUser(uid, adapter=null, options={}) {
    this.generation++;this.unsubscribe?.();this.unsubscribe=null;this.adapter=null;this.busy=false;this.ready=false;this.error='';this.readOnly=Boolean(options.readOnly);this.readOnlyReason=options.reason||'Your account is open in another tab. Save there, or close it and retry sync here.';
    if(!validUid(uid)){this.uid=null;this.accountError='';this.deletionPending=false;this.readOnly=false;this.records.clear();this.pending.clear();this.status='guest';this.ready=true;this.emit();return;}
    this.uid=uid;this.load(uid);this.adapter=adapter;this.status=this.deletionPending?'deletion-pending':'connecting';this.emit();
    const generation=this.generation;
    if(!adapter)return;
    this.unsubscribe=adapter.subscribe(rows=>{
      if(generation!==this.generation||this.deletionPending)return;
      if(!Array.isArray(rows)||rows.length>10000)return;
      const valid=rows.filter(row=>row&&validCloudRecord(row.id,row.data));
      // Invalid remote documents are ignored rather than promoted to saved titles.
      this.records=new Map(valid.map(row=>[row.id,row.data.saved]));this.ready=true;this.status='syncing';this.error='';this.cache();this.emit();this.flush();
    },()=>{if(generation===this.generation){this.status='offline';this.error='Saved titles are on this device. Sync will retry when the connection returns.';this.emit();}});
  }
  toggle(id) {
    if(!this.uid){const ids=this.guest();if(this.guestError||!(validTitleId(id)||Number.isSafeInteger(id)&&id>=0)){this.emit();return false;}ids.has(id)?ids.delete(id):ids.add(id);if(!this.write('ottscout-watchlist',[...ids])){this.emit();return false;}this.emit();return true;}
    if(this.accountError||this.deletionPending||this.readOnly||!validTitleId(id))return false;
    const previous=this.pending.get(id);this.pending.set(id,{saved:!this.ids().has(id),revision:++this.revision});
    if(!this.cache()){previous?this.pending.set(id,previous):this.pending.delete(id);this.emit();return false;}
    this.status='syncing';this.emit();this.flush();return true;
  }
  async flush() {
    if(!this.uid||!this.adapter||!this.ready||this.busy||this.accountError||this.deletionPending||this.readOnly)return;
    this.busy=true;const generation=this.generation;const adapter=this.adapter;const current=()=>generation===this.generation;
    try {
      if(!this.imported){
        const guestIds=[...this.guest()].filter(validTitleId);
        if(this.guestError)throw new Error('Guest saves unreadable');
        await adapter.importMissing(guestIds,current);
        if(!current())return;
        this.imported=true;if(!this.cache()){this.imported=false;throw new Error('Device storage unavailable');}
      }
      while(current()&&this.pending.size){
        const [id,change]=this.pending.entries().next().value;
        await adapter.write(id,change.saved,current);
        if(!current())return;
        if(this.pending.get(id)?.revision===change.revision)this.pending.delete(id);
        this.cache();this.emit();
      }
      if(current()){this.status='synced';this.error='';}
    } catch {if(current()){this.status='offline';this.error='Changes are waiting on this device. Reconnect and retry sync.';}}
    finally {if(current()){this.busy=false;this.emit();}}
  }
  markDeletionPending(){
    this.generation++;this.unsubscribe?.();this.unsubscribe=null;this.adapter=null;this.busy=false;this.deletionPending=true;this.ready=false;this.pending.clear();this.records.clear();this.imported=true;this.status='deletion-pending';this.error='Account deletion has started. Finish deleting your account; new saves and imports are disabled.';this.cache();this.emit();
  }
  networkOffline(){if(this.uid&&!this.deletionPending){this.status='offline';this.error='Saved titles and pending changes remain on this device. Reconnect to sync.';this.emit();}}
  retry(){ this.flush(); }
}
