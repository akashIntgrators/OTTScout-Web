import assert from 'node:assert/strict';
import {test} from 'node:test';
import {parseRecommendationRequest, recommendationAppLink, resolveRecommendation, approveRecommendation, mountRecommendation} from '../web/recommendation-links.js';
import {WatchlistSync} from '../web/watchlist-sync.js';

const movie={id:'motn:42',title:'A shared film',type:'Movie',year:2024,originalLanguage:'Hindi',poster:'https://image.tmdb.org/t/p/w342/movie.jpg'};
const request={kind:'title',id:movie.id};
function fixture(options={}) {
  const doc={body:{},activeElement:null};doc.activeElement=doc.body;
  const nodes=new Map();
  for(const name of ['title','description','meta','poster','approve','decline','app','feedback'])nodes.set('recommendation-'+name,{
    hidden:false,disabled:false,textContent:'',attrs:{},setAttribute(name,value){this.attrs[name]=value;},focus(){doc.activeElement=this;},
  });
  const root={ownerDocument:doc,hidden:true,querySelector(selector){return nodes.get(selector.slice(1));}};
  let state={uid:null,ids:new Set(),canSave:true,reason:''};
  const writes=[];let closes=0,saves=0;
  const ports={url:'https://ottscout.techiwithhelmet.com/?recommend=motn%3A42',getCatalogue:()=>({ready:true,catalogue:{titles:[movie]}}),getState:()=>state,
    write:(id,uid)=>{writes.push({id,uid});state.ids.add(id);return true;},onClose(){closes++;},onSaved(){saves++;},...options};
  const receiver=mountRecommendation(root,ports);
  return {root,ports,writes,receiver,get state(){return state;},set state(value){state=value;},get closes(){return closes;},get saves(){return saves;},field:name=>nodes.get('recommendation-'+name)};
}
test('recommendation links contain one bounded catalogue ID, never a destination or account',()=>{
  assert.deepEqual(parseRecommendationRequest('https://ottscout.techiwithhelmet.com/'),{kind:'none'});
  assert.deepEqual(parseRecommendationRequest('https://ottscout.techiwithhelmet.com/?recommend=motn%3A42'),request);
  for(const value of ['', 'motn:../42','https://evil.test','motn:42/extra','motn:42?uid=another','motn:42\n','motn:'+ 'x'.repeat(156)]){
    assert.deepEqual(parseRecommendationRequest('https://ottscout.techiwithhelmet.com/?recommend='+encodeURIComponent(value)),{kind:'invalid'});
    assert.equal(recommendationAppLink(value),null);
  }
  assert.deepEqual(parseRecommendationRequest('https://ottscout.techiwithhelmet.com/?recommend=motn%3A42&recommend=motn%3A43'),{kind:'invalid'});
  assert.deepEqual(parseRecommendationRequest('https://ottscout.techiwithhelmet.com/?recommend=motn%253A42'),{kind:'invalid'});
  for(const url of ['http://ottscout.techiwithhelmet.com/?recommend=motn%3A42','https://evil.test/?recommend=motn%3A42','https://ottscout.techiwithhelmet.com/titles/42/?recommend=motn%3A42','https://name@ottscout.techiwithhelmet.com/?recommend=motn%3A42','https://ottscout.techiwithhelmet.com/?recommend=motn%3A42#other'])assert.deepEqual(parseRecommendationRequest(url),{kind:'invalid'});
  assert.deepEqual(parseRecommendationRequest('http://localhost:5174/?recommend=motn%3A42',true),request);
  assert.equal(recommendationAppLink('motn:42'),'ottscout://recommend/motn%3A42');
});
test('loading and an unknown ID never substitute a similar name or sample title',()=>{
  assert.equal(resolveRecommendation(request,{ready:false,catalogue:null}).status,'loading');
  assert.equal(resolveRecommendation(request,{ready:true,catalogue:{titles:[{...movie,id:'motn:other'}]}}).status,'unavailable');
  assert.equal(resolveRecommendation(request,{ready:true,catalogue:null}).status,'unavailable');
});
test('opening shows the exact title without saving or launching another application',()=>{
  const view=fixture();
  assert.equal(view.root.hidden,false);assert.equal(view.field('title').textContent,movie.title);
  assert.equal(view.field('poster').src,movie.poster);assert.equal(view.field('app').href,'ottscout://recommend/motn%3A42');
  assert.equal(view.field('app').onclick,undefined);assert.equal(view.writes.length,0);assert.equal(view.state.ids.size,0);
});
test('explicit approval saves once and cannot toggle a title off',async()=>{
  const view=fixture();await view.field('approve').onclick();
  assert.deepEqual(view.writes,[{id:'motn:42',uid:null}]);assert.equal(view.state.ids.has('motn:42'),true);
  assert.equal(view.field('approve').disabled,true);assert.match(view.field('feedback').textContent,/guest watchlist/);
  await view.field('approve').onclick();assert.equal(view.writes.length,1);assert.equal(view.state.ids.has('motn:42'),true);
});
test('already-saved decisions are idempotent even through the decision API',async()=>{
  const state={uid:'receiver',ids:new Set(['motn:42']),canSave:true,reason:''};let writes=0;
  assert.deepEqual(await approveRecommendation('motn:42',{getState:()=>state,write:()=>{writes++;return true;}}),{status:'already-saved',uid:'receiver'});
  assert.equal(writes,0);assert.equal(state.ids.has('motn:42'),true);
});
test('declining closes the review without changing the watchlist',()=>{
  const view=fixture();view.field('decline').onclick();view.receiver.refresh();
  assert.equal(view.root.hidden,true);assert.equal(view.closes,1);assert.equal(view.writes.length,0);assert.equal(view.state.ids.size,0);
});
test('storage failure keeps the review open without a success claim',async()=>{
  const view=fixture({write:()=>false});await view.field('approve').onclick();
  assert.equal(view.root.hidden,false);assert.equal(view.field('feedback').attrs.role,'alert');
  assert.match(view.field('feedback').textContent,/could not be saved/);assert.equal(view.saves,0);assert.equal(view.field('approve').disabled,false);
});
test('an account switch during approval cannot report a save for the new account',async()=>{
  const completion=Promise.withResolvers(),view=fixture({write:()=>completion.promise});
  view.state={uid:'A',ids:new Set(),canSave:true,reason:''};const pending=view.field('approve').onclick();
  assert.equal(view.field('decline').disabled,true);view.state={uid:'B',ids:new Set(),canSave:true,reason:''};
  completion.resolve(true);await pending;
  assert.equal(view.root.hidden,false);assert.match(view.field('feedback').textContent,/account changed/);assert.equal(view.state.ids.size,0);assert.equal(view.saves,0);
});
test('deletion and storage guards stop approval with an explanation',async()=>{
  const view=fixture();view.state={uid:'receiver',ids:new Set(),canSave:false,reason:'Account deletion has started.'};view.receiver.refresh();
  assert.equal(view.field('approve').disabled,true);assert.match(view.field('feedback').textContent,/deletion/);
  assert.equal((await approveRecommendation('motn:42',view.ports)).status,'blocked');assert.equal(view.writes.length,0);
});
test('unknown titles expose no approval or app-opening action',()=>{
  const view=fixture({url:'https://ottscout.techiwithhelmet.com/?recommend=motn%3Aunknown'});
  assert.equal(view.field('title').textContent,'Title not available');assert.equal(view.field('approve').hidden,true);
  assert.equal(view.field('app').hidden,true);assert.equal(view.writes.length,0);
});
test('real guest storage quota failure is not promoted to approval success',async()=>{
  const values=new Map([['ottscout-watchlist','["motn:old"]']]);let state;
  const model=new WatchlistSync({getItem:key=>values.get(key)??null,setItem(){throw new Error('Quota exceeded');}},value=>{state=value;});
  model.setUser(null);
  const ports={getState:()=>({uid:state.uid,ids:state.ids,canSave:state.canSave,reason:state.canSave?'':state.error}),
    write:(id,uid)=>state.uid===uid&&(state.ids.has(id)||model.toggle(id))};
  const view=fixture(ports);await view.field('approve').onclick();
  assert.equal(view.saves,0);assert.equal(view.root.hidden,false);assert.equal(view.field('feedback').attrs.role,'alert');
  assert.equal(state.ids.has('motn:42'),false);assert.equal(values.get('ottscout-watchlist'),'["motn:old"]');
});
test('real guest save is durable and repeat decisions never remove an existing title',async()=>{
  const values=new Map();let state;
  const model=new WatchlistSync({getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value)},value=>{state=value;});
  model.setUser(null);
  const ports={getState:()=>({uid:state.uid,ids:state.ids,canSave:state.canSave,reason:state.canSave?'':state.error}),
    write:(id,uid)=>state.uid===uid&&(state.ids.has(id)||model.toggle(id))};
  const view=fixture(ports);await view.field('approve').onclick();
  assert.equal(view.saves,1);assert.deepEqual(JSON.parse(values.get('ottscout-watchlist')),['motn:42']);
  assert.equal((await approveRecommendation('motn:42',ports)).status,'already-saved');
  assert.deepEqual(JSON.parse(values.get('ottscout-watchlist')),['motn:42']);
  assert.match(view.field('feedback').textContent,/guest watchlist in this browser/);
  assert.equal(view.field('decline').textContent,'Close recommendation');
});
