const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const source = fs.readFileSync('static/landing/landing.js', 'utf8');

function environment({width=1440, reduced=false, fine=true}={}) {
  const queue=new Map(), observers=[]; let next=0, time=0;
  function element(rect={left:0,top:80,width:1440,height:800}) {
    const classes=new Set(), values=new Map(), listeners=new Map();
    return {offsetWidth:rect.width,offsetHeight:rect.height, listeners, values, classes,
      classList:{add(...names){names.forEach(x=>classes.add(x));},remove(...names){names.forEach(x=>classes.delete(x));},toggle(name,on){if(on)classes.add(name);else classes.delete(name);}},
      style:{setProperty(k,v){values.set(k,v);},removeProperty(k){values.delete(k);}},
      getBoundingClientRect(){return {...rect};},
      addEventListener(name,cb){listeners.set(name,cb);}, removeEventListener(name){listeners.delete(name);},
      contains(){return false;}, closest(){return null;}, matches(){return false;}};
  }
  const body=element(), hero=element(), card=element({left:80,top:100,width:1280,height:540});
  const photo=element({left:80,top:200,width:620,height:440});
  photo.closest=()=>card;
  const media={reduced:{matches:reduced,addEventListener(_name,cb){this.changed=cb;}},fine:{matches:fine,addEventListener(_name,cb){this.changed=cb;}}};
  const win={innerWidth:width,innerHeight:900,scrollY:0,listeners:new Map(),
    matchMedia(query){return query.includes('reduced')?media.reduced:media.fine;},
    addEventListener(name,cb){this.listeners.set(name,cb);},removeEventListener(name){this.listeners.delete(name);}};
  const doc={body,querySelector(selector){return selector==='[data-hero]'?hero:null;},getElementById(){return null;},
    querySelectorAll(selector){
      if(selector==='[data-tilt]')return [card];
      if(selector==='[data-depth]')return [photo];
      if(selector.startsWith('.is-pending'))return [hero,card,photo];
      return [];
    },addEventListener(){},removeEventListener(){}};
  const ctx={window:win,document:doc,Set,Map,console,
    requestAnimationFrame(cb){const id=++next;queue.set(id,cb);return id;},cancelAnimationFrame(id){queue.delete(id);},
    IntersectionObserver:class{constructor(cb){this.cb=cb;observers.push(this);}observe(){}unobserve(){}disconnect(){}}};
  win.IntersectionObserver=ctx.IntersectionObserver;
  vm.runInNewContext(source,ctx);
  function flush(){let frames=0;while(queue.size){const entries=[...queue];queue.clear();time+=16;entries.forEach(([,cb])=>cb(time));assert(++frames<150,'RAF must stop after settling');}return frames;}
  function visible(){observers[0].cb([{target:hero,isIntersecting:true},{target:photo,isIntersecting:true},{target:card,isIntersecting:true}]);flush();}
  return {win,hero,card,photo,body,media,queue,flush,visible};
}
const env=environment();env.visible();
env.hero.listeners.get('pointerenter')({clientX:1296,clientY:160,pointerType:'mouse'});
env.hero.listeners.get('pointermove')({clientX:1440,clientY:80,pointerType:'mouse'});
assert.equal(env.queue.size,1,'one RAF for all mouse events');
env.flush();
assert.equal(Number(env.hero.values.get('--hero-x')),1);
assert.equal(Number(env.hero.values.get('--hero-y')),-1);
env.card.listeners.get('pointerenter')({clientX:1360,clientY:100,pointerType:'mouse'});env.flush();
assert.equal(env.card.values.get('--card-rx'),'6.000deg');
assert.equal(env.card.values.get('--card-ry'),'8.000deg');
assert.equal(env.card.values.get('--card-scale'),'1.01800');
assert.equal(env.card.values.get('--card-lift'),'-12.000px');
assert(env.card.classes.has('is-tilting'));
env.card.listeners.get('pointerleave')();env.hero.listeners.get('pointerleave')();env.flush();
assert(!env.card.classes.has('is-tilting'));
assert.equal(Number(env.hero.values.get('--hero-x')),0);
assert.equal(env.queue.size,0,'idle JavaScript does not animate forever');

env.media.reduced.matches=true;env.media.reduced.changed();
assert(env.body.classes.has('motion-reduced'));
assert(!env.body.classes.has('motion-enabled'));
assert.equal(env.hero.values.size,0,'preference change removes motion styles');
assert.equal(env.queue.size,0);
env.media.reduced.matches=false;env.media.reduced.changed();env.visible();
assert(env.body.classes.has('motion-enabled'),'normal preference re-enables animation');

const phone=environment({width:390,fine:false});phone.visible();
phone.hero.listeners.get('pointerenter')({clientX:300,clientY:120,pointerType:'touch'});
phone.card.listeners.get('pointermove')({clientX:300,clientY:120,pointerType:'touch'});
assert.equal(phone.queue.size,0,'coarse/touch pointer has no tilt loop');
assert.equal(Number(phone.hero.values.get('--hero-x')),0);
assert(!phone.card.classes.has('is-tilting'));
const quiet=environment({reduced:true});
assert.equal(quiet.queue.size,0);
assert(!quiet.body.classes.has('motion-enabled'));
for (const [width,factor] of [[1440,1],[1024,.75],[820,.55],[390,0]]) {
  const sized=environment({width});sized.visible();
  sized.hero.listeners.get('pointerenter')({clientX:1440,clientY:80,pointerType:'mouse'});
  sized.card.listeners.get('pointerenter')({clientX:1360,clientY:100,pointerType:'mouse'});
  sized.flush();
  assert.equal(Number(sized.hero.values.get('--hero-x')),factor);
  assert.equal(parseFloat(sized.card.values.get('--card-ry')),8*factor);
}
const hybrid=environment();hybrid.visible();
hybrid.card.listeners.get('pointerenter')({clientX:1360,clientY:100,pointerType:'touch'});
assert.equal(hybrid.queue.size,0,'touch input stays static even on a hybrid fine-pointer device');
assert(!/setInterval|Three\.|gsap|style\.(top|left)\s*=/.test(source));
console.log('Landing motion: amplitudes, RAF coalescé/arrêté, reset, touch et reduced-motion dynamique OK');
