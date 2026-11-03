import {initializeApp} from 'firebase/app';
import {getAuth, connectAuthEmulator, setPersistence, browserLocalPersistence, onAuthStateChanged, GoogleAuthProvider, signInWithPopup, createUserWithEmailAndPassword, signInWithEmailAndPassword, sendPasswordResetEmail, sendEmailVerification, reload, signOut, EmailAuthProvider, reauthenticateWithCredential, reauthenticateWithPopup, deleteUser} from 'firebase/auth';
import {initializeFirestore, memoryLocalCache, connectFirestoreEmulator, collection, doc, onSnapshot, runTransaction, serverTimestamp, getDocsFromServer, writeBatch} from 'firebase/firestore';
import {WatchlistSync} from './watchlist-sync.js';
import {AccountSession} from './account-session.js';
const $=selector=>document.querySelector(selector);
const dialog=$('#account-dialog');
const accountButton=$('#account-button');
let auth, db, currentUser=null, initialized=false, initializing=false, busy=false, deleting=false, mode='signin';
let latest={uid:null,ids:new Set(),status:'guest',error:'',pending:0,ready:false};
// Failure to read existing storage must never be mistaken for an empty watchlist.
const memory=new Map();
const storage={getItem(key){return localStorage.getItem(key);},setItem(key,value){memory.set(key,value);localStorage.setItem(key,value);},removeItem(key){memory.delete(key);localStorage.removeItem(key);}};
const sync=new WatchlistSync(storage,state=>{
  latest=state;
  window.dispatchEvent(new CustomEvent('ottscout:watchlist',{detail:state}));
  paint();
});
window.OTTScoutAccount={toggle:id=>sync.toggle(id),state:()=>latest};
window.addEventListener('ottscout:watchlist-request',()=>sync.emit());
function message(text,error=false){$('#account-feedback').textContent=text;$('#account-feedback').setAttribute('role',error?'alert':'status');}
function paint(){
  if(!dialog)return;
  accountButton.textContent=currentUser?'Account':'Sign in';
  accountButton.setAttribute('aria-label',currentUser?'Your OTTScout account':'Sign in to sync saved titles');
  $('#account-guest').hidden=Boolean(currentUser);$('#account-member').hidden=!currentUser;
  $('#account-unavailable').hidden=initialized;$('#account-options').hidden=!initialized;
  $('#account-storage-status').hidden=Boolean(currentUser)||!latest.error;$('#account-storage-status').textContent=latest.error||'';
  $('#account-title').textContent=currentUser?'Your account':'Save across devices';
  $('#account-continue').textContent=currentUser?'Continue browsing':'Continue as guest';
  if(currentUser){
    $('#account-email').textContent=currentUser.email||'Signed in with Google';
    $('#account-verification').textContent=currentUser.emailVerified?'Email verified':'Email not verified';
    $('#account-verify').hidden=currentUser.emailVerified;$('#account-check-verification').hidden=currentUser.emailVerified;
    $('#account-sync').textContent=deleting?'Deleting account…':latest.error||({connecting:'Connecting to your saved titles…',syncing:'Syncing saved titles…',synced:'Saved titles are synced.','deletion-pending':'Account deletion has started. Finish deleting your account; new saves are disabled.',offline:'Changes are waiting on this device.'}[latest.status]||'Saved titles stay on this device until connected.');
    $('#account-retry').hidden=latest.status==='deletion-pending'||latest.status==='synced'&&!latest.pending;
    if(latest.status==='deletion-pending'){$('#account-delete').open=true;$('#account-delete-submit').textContent='Finish account deletion';}else{$('#account-delete-submit').textContent='Confirm account deletion';}
    const password=currentUser.providerData.some(provider=>provider.providerId==='password');
    $('#delete-password-label').hidden=!password;
  }
  dialog.querySelectorAll('button:not(#account-close):not(#account-continue)').forEach(button=>{button.disabled=busy;});
  $('#account-form').hidden=mode==='reset';$('#account-reset-form').hidden=mode!=='reset';
  $('#account-switch').hidden=mode==='reset';$('#account-forgot').hidden=mode==='reset';
  $('#account-password').autocomplete=mode==='signup'?'new-password':'current-password';
  $('#account-password').minLength=mode==='signup'?8:1;
  $('#account-submit').textContent=mode==='signup'?'Create account':'Sign in';
  $('#account-switch').textContent=mode==='signup'?'Already have an account? Sign in':'New here? Create an account';
}
function setMode(value){mode=value;message('');paint();}
function readable(error){
  const code=error?.code||'';
  if(code.includes('popup-closed-by-user')||code.includes('cancelled-popup-request'))return 'Sign-in was cancelled. You can keep browsing as a guest.';
  if(code.includes('popup-blocked'))return 'Your browser blocked Google sign-in. Allow the pop-up, or use email and password.';
  if(code.includes('unauthorized-domain'))return 'Sign-in is not enabled for this website address yet. Guest browsing still works.';
  if(code.includes('operation-not-allowed'))return 'This sign-in method is not enabled yet. Guest browsing still works.';
  if(code.includes('network-request-failed')||code.includes('unavailable'))return 'Cannot connect right now. Check your connection and try again.';
  if(code.includes('too-many-requests'))return 'Too many attempts. Please wait a while before trying again.';
  if(code.includes('weak-password'))return 'Choose a password with at least eight characters.';
  if(code.includes('invalid-email'))return 'Enter a valid email address.';
  if(code.includes('account-exists-with-different-credential')||code.includes('credential-already-in-use'))return 'This email uses another sign-in method. Sign in with the method you used before.';
  if(code.includes('user-disabled'))return 'This account is disabled. You can continue browsing as a guest.';
  if(code.includes('email-already-in-use'))return 'An account already uses this email. Sign in or reset its password.';
  if(code.includes('requires-recent-login')||code.includes('invalid-credential')||code.includes('wrong-password')||code.includes('user-not-found'))return 'Check your sign-in details and try again. You can also reset your password.';
  return 'This action could not finish. Please try again.';
}
async function perform(action){if(busy||!initialized)return;busy=true;message('');paint();try{await action();}catch(error){message(readable(error),true);}finally{busy=false;paint();}}
function adapterFor(uid){
  let alive=true;
  const active=check=>alive&&!deleting&&auth.currentUser?.uid===uid&&(!check||check());
  const ref=id=>doc(db,'users',uid,'watchlist',id);
  return {
    subscribe(next,error){
      let stopWatch=null;
      const waiting=setTimeout(()=>{if(active())error(new Error('Account sync is waiting for a connection'));},10000);
      const stopMarker=onSnapshot(doc(db,'users',uid,'accountState','deletion'),{includeMetadataChanges:true},snapshot=>{
        if(!active()||snapshot.metadata.fromCache||snapshot.metadata.hasPendingWrites)return;
        if(snapshot.exists()){clearTimeout(waiting);sync.markDeletionPending();return;}
        if(!stopWatch)stopWatch=onSnapshot(collection(db,'users',uid,'watchlist'),{includeMetadataChanges:true},watchlist=>{
          if(!active()||watchlist.metadata.fromCache||watchlist.metadata.hasPendingWrites)return;
          clearTimeout(waiting);next(watchlist.docs.map(item=>({id:item.id,data:item.data()})));
        },error);
      },error);
      return ()=>{alive=false;clearTimeout(waiting);stopMarker();stopWatch?.();};
    },
    async write(id,saved,check){
      if(!active(check))throw new Error('Session changed');
      await runTransaction(db,async transaction=>{await transaction.get(ref(id));if(!active(check))throw new Error('Session changed');transaction.set(ref(id),{titleId:id,saved,updatedAt:serverTimestamp()});});
    },
    async importMissing(ids,check){
      for(let index=0;index<ids.length;index+=10){
        const chunk=ids.slice(index,index+10);
        await runTransaction(db,async transaction=>{
          if(!active(check))throw new Error('Session changed');
          const found=await Promise.all(chunk.map(id=>transaction.get(ref(id))));
          if(!active(check))throw new Error('Session changed');
          chunk.forEach((id,i)=>{if(!found[i].exists())transaction.set(ref(id),{titleId:id,saved:true,updatedAt:serverTimestamp()});});
        });
      }
    }
  };
}
const session=new AccountSession(sync,adapterFor,navigator.locks);
const bindAccount=user=>session.bind(user);
accountButton?.addEventListener('click',()=>{if(!initialized)start();message('');$('#account-delete').open=false;paint();dialog.showModal();});
$('#account-close')?.addEventListener('click',()=>dialog.close());
$('#account-continue')?.addEventListener('click',()=>dialog.close());
dialog?.addEventListener('close',()=>{ $('#account-password').value='';$('#delete-password').value='';$('#delete-confirm').checked=false;accountButton.focus(); });
$('#account-google')?.addEventListener('click',()=>perform(async()=>{await signInWithPopup(auth,new GoogleAuthProvider());dialog.close();}));
$('#account-switch')?.addEventListener('click',()=>setMode(mode==='signup'?'signin':'signup'));
$('#account-forgot')?.addEventListener('click',()=>{ $('#reset-email').value=$('#account-email-input').value;setMode('reset');$('#reset-email').focus(); });
$('#account-reset-back')?.addEventListener('click',()=>setMode('signin'));
$('#account-form')?.addEventListener('submit',event=>{event.preventDefault();perform(async()=>{
  const email=$('#account-email-input').value.trim(),password=$('#account-password').value;
  if(mode==='signup'){
    const result=await createUserWithEmailAndPassword(auth,email,password);
    try{await sendEmailVerification(result.user);message('Account created. Check your inbox for the verification link.');}catch{message('Account created. Use Send verification email to verify your address.');}
  }else{await signInWithEmailAndPassword(auth,email,password);dialog.close();}
  $('#account-password').value='';
});});
$('#account-reset-form')?.addEventListener('submit',event=>{event.preventDefault();perform(async()=>{await sendPasswordResetEmail(auth,$('#reset-email').value.trim());message('If an account uses this address, a reset email has been sent. Check your inbox and spam folder.');});});
$('#account-verify')?.addEventListener('click',()=>perform(async()=>{await sendEmailVerification(currentUser);message('Verification email sent. Check your inbox and spam folder.');}));
$('#account-check-verification')?.addEventListener('click',()=>perform(async()=>{await reload(currentUser);currentUser=auth.currentUser;message(currentUser.emailVerified?'Your email is verified.':'Not verified yet. Open the email link, then check again.');}));
$('#account-signout')?.addEventListener('click',()=>perform(async()=>{await signOut(auth);message('Signed out. Your guest watchlist is back on this device.');}));
$('#account-retry')?.addEventListener('click',()=>{if(currentUser){bindAccount(currentUser);}});
window.addEventListener('offline',()=>sync.networkOffline());
window.addEventListener('online',()=>{if(!initialized)start();else if(currentUser&&!deleting)bindAccount(currentUser);});
$('#account-delete-form')?.addEventListener('submit',event=>{event.preventDefault();perform(async()=>{
  const user=currentUser;if(!user||!$('#delete-confirm').checked)return;
  const uid=user.uid;
  if(user.providerData.some(provider=>provider.providerId==='password'))await reauthenticateWithCredential(user,EmailAuthProvider.credential(user.email,$('#delete-password').value));
  else await reauthenticateWithPopup(user,new GoogleAuthProvider());
  if(auth.currentUser?.uid!==uid)throw new Error('Session changed');
  deleting=true;paint();
  try{
    const marker=doc(db,'users',uid,'accountState','deletion');
    await runTransaction(db,async transaction=>{
      const existing=await transaction.get(marker);
      if(auth.currentUser?.uid!==uid)throw new Error('Session changed');
      if(!existing.exists())transaction.set(marker,{deleting:true,updatedAt:serverTimestamp()});
    });
    sync.markDeletionPending();
    // The immutable marker prevents other devices from recreating saves during cleanup.
    const records=await getDocsFromServer(collection(db,'users',uid,'watchlist'));
    for(let index=0;index<records.docs.length;index+=400){
      if(auth.currentUser?.uid!==uid)throw new Error('Session changed');
      const batch=writeBatch(db);records.docs.slice(index,index+400).forEach(item=>batch.delete(item.ref));await batch.commit();
    }
    await deleteUser(user);storage.removeItem('ottscout-account-watchlist-v1:'+encodeURIComponent(uid));message('Account and cloud watchlist deleted. Your separate guest saves remain on this device.');
  } finally {deleting=false;bindAccount(auth.currentUser);$('#delete-password').value='';}
});});
async function start(){
  if(initialized||initializing)return;initializing=true;
  $('#account-unavailable').textContent='Connecting to account services…';
  paint();sync.emit();
  try{
    const emulator=__OTTSCOUT_EMULATOR__&&['localhost','127.0.0.1'].includes(location.hostname)&&new URL(location.href).searchParams.get('auth-emulator')==='1';
    const response=await fetch(emulator?'/firebase-config.local.json':'/firebase-config.json',{cache:'no-store'});if(!response.ok)throw new Error('Not configured');
    const config=await response.json();
    if(!config||!['apiKey','authDomain','projectId','appId'].every(key=>typeof config[key]==='string'&&config[key].length>0))throw new Error('Not configured');
    if(emulator&&config.projectId!=='demo-ottscout')throw new Error('Emulator requires demo project');
    const app=initializeApp(config);auth=getAuth(app);db=initializeFirestore(app,{localCache:memoryLocalCache()});
    if(emulator){connectAuthEmulator(auth,'http://127.0.0.1:9099',{disableWarnings:true});connectFirestoreEmulator(db,'127.0.0.1',8085);}
    await setPersistence(auth,browserLocalPersistence);initialized=true;
    onAuthStateChanged(auth,user=>{currentUser=user;if(!deleting)bindAccount(user);paint();},()=>{message('Could not restore your sign-in. Guest browsing is available.',true);});
  }catch{ $('#account-unavailable').textContent=navigator.onLine===false?'You’re offline. Continue as a guest, or reconnect to sign in.':'Sign-in is unavailable. You can browse and save titles as a guest, and retry by opening Sign in again.'; }
  initializing=false;paint();
}
start();
