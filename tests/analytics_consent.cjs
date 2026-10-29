const vm=require('node:vm'), fs=require('node:fs'), assert=require('node:assert/strict');
const code=fs.readFileSync('analytics.js','utf8');
function run(choice){
  const storage=new Map(choice?[['ottscout-analytics-consent',choice]]:[]), nodes=[],scripts=[];
  const document={title:'Test',cookie:'',activeElement:null};
  const main={focus(){document.activeElement=main}};
  const body={append(n){nodes.push(n)}};
  Object.assign(document,{body,head:{append(n){scripts.push(n)}},querySelector(selector){return selector==='main'?main:body},createElement(tag){
    return {tag,style:{},attributes:{},setAttribute(k,v){this.attributes[k]=String(v)},addEventListener(ev,cb){this[ev]=cb},remove(){this.removed=true},focus(){document.activeElement=this},querySelector(){return {focus:()=>{this.childFocused=true}}}};
  }});
  const ctx={window:{},document,localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},location:{hostname:'ottscout.techiwithhelmet.com',origin:'https://ottscout.techiwithhelmet.com',pathname:'/test/',search:'?private=search'},navigator:{}};
  ctx.window=ctx;vm.runInNewContext(code,ctx);return {ctx,nodes,scripts,storage,main};
}
let s=run();assert.equal(s.scripts.length,0);
s.nodes.find(n=>n.className==='analytics-choice').click({target:{dataset:{choice:'declined'}}});assert.equal(s.scripts.length,0);assert.equal(s.ctx.document.activeElement,s.main);
s=run();const panel=s.nodes.find(n=>n.className==='analytics-choice');
panel.click({target:{dataset:{choice:'accepted'}}});assert.equal(s.scripts.length,1);
const event=s.ctx.dataLayer.find(a=>a[0]==='event');assert.equal(event[2].page_location,'https://ottscout.techiwithhelmet.com/test/');assert.equal(event[2].page_referrer,'');
panel.click({target:{dataset:{choice:'declined'}}});assert.equal(s.ctx['ga-disable-G-LV97MSZYW1'],true);assert.equal(s.storage.get('ottscout-analytics-consent'),'declined');
panel.click({target:{dataset:{choice:'accepted'}}});assert.equal(s.ctx['ga-disable-G-LV97MSZYW1'],false);assert.equal(s.ctx.dataLayer.at(-1)[2].analytics_storage,'granted');assert.equal(s.scripts.length,1);
s=run('declined');assert.equal(s.scripts.length,0);
const choices=s.nodes.find(n=>n.tag==='button');choices.click();const reopened=s.nodes.find(n=>n.className==='analytics-choice');
assert.equal(reopened.childFocused,true);assert.equal(choices.attributes['aria-expanded'],'true');
reopened.keydown({key:'Escape'});assert.equal(s.ctx.document.activeElement,choices);assert.equal(choices.attributes['aria-expanded'],'false');assert.equal(s.storage.get('ottscout-analytics-consent'),'declined');assert.equal(s.scripts.length,0);
choices.click();reopened.click({target:{dataset:{choice:'accepted'}}});assert.equal(s.ctx.document.activeElement,choices);assert.equal(s.scripts.length,1);
s=run('accepted');assert.equal(s.scripts.length,1);
console.log('Analytics consent, URL privacy, withdrawal and keyboard focus scenarios passed.');
