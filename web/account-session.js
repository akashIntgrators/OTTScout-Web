// Keep a single writer for each UID's local queue across browser tabs.
export class AccountSession {
  constructor(sync, adapterFor, locks) {this.sync=sync;this.adapterFor=adapterFor;this.locks=locks;this.generation=0;this.release=null;this.request=null;}
  async bind(user) {
    const generation=++this.generation, previous=this.request;
    this.release?.();this.release=null;
    if(!user){this.sync.setUser(null);return;}
    const uid=user.uid;
    const readOnly=reason=>{if(generation===this.generation)this.sync.setUser(uid,this.adapterFor(uid),{readOnly:true,reason});};
    this.sync.setUser(uid,null,{readOnly:true,reason:'Preparing saved-title sync…'});
    if(previous)await previous.catch(()=>{});
    if(generation!==this.generation)return;
    if(!this.locks?.request){readOnly('This browser cannot safely sync saved titles. Use a current browser, or sign out to save as a guest.');return;}
    try {
      this.request=this.locks.request('ottscout-watchlist-v1:'+uid,{mode:'exclusive',ifAvailable:true},async lock=>{
        if(generation!==this.generation)return;
        if(!lock){readOnly();return;}
        this.sync.setUser(uid,this.adapterFor(uid));
        await new Promise(resolve=>{this.release=resolve;});
      }).catch(()=>readOnly('This browser could not protect saved-title storage. Retry sync or sign out to save as a guest.'));
    } catch {readOnly('This browser could not protect saved-title storage. Retry sync or sign out to save as a guest.');}
  }
}
