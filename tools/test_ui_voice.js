// Behavioral tests for the real browser scripts; no microphone or sound output.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const path = require('path');
const root = path.resolve(__dirname, '..');
const read = f => fs.readFileSync(path.join(root, 'ui/web', f), 'utf8');
function env() {
  const storage = new Map();
  const context = {console, setTimeout, clearTimeout, Float32Array, Int16Array,
    Uint8Array, Promise, URLSearchParams,
    location:{pathname:'/media.html',search:''},
    sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},
    localStorage:{getItem:()=>null},
    document:{readyState:'loading',head:{appendChild(){}},
      createElement:()=>({}), addEventListener(){}},
    navigator:{mediaDevices:{}}, XQ:{flash(){},NAV:[['media','音乐','media.html']]},
    addEventListener(){}};
  context.window = context;
  return vm.createContext(context);
}
async function main() {
  const t=env();
  const memory=new Map([['xq.tts.on','0']]);
  t.localStorage={getItem:k=>memory.get(k),setItem:(k,v)=>memory.set(k,v)};
  t.document.visibilityState='visible';
  const live=read('live.js');
  const tb=live.indexOf('XQ.tts = {');
  vm.runInContext(live.slice(tb,live.indexOf('XQ.tts._init();',tb)),t);
  const sb=live.indexOf('XQ.speak = function');
  vm.runInContext(live.slice(sb,live.indexOf('\n};',sb)+4),t);
  t.XQ.tts.attach(null,{default_on:true,enable_revision:'reply-audible-v1'});
  assert.equal(t.XQ.tts.on,true,'explicit voice restoration must clear old mute once');
  t.XQ.tts.set(false);
  t.XQ.tts.attach(null,{default_on:true,enable_revision:'reply-audible-v1'});
  assert.equal(t.XQ.tts.on,false,'later manual mute must remain effective');
  assert.equal(t.XQ.speak('reply'),false);
  assert.match(t.XQ.tts.lastError,/静音/);
  t.XQ.tts.on=true;t.document.visibilityState='hidden';
  assert.equal(t.XQ.speak('reply'),false);
  assert.match(t.XQ.tts.lastError,/后台/);
  console.log('PASS one-time audible restoration, later mute, and visible failure reasons');

  const c=env(); vm.runInContext(read('player.js'),c);
  let calls=0;
  const au={addEventListener(){}};
  c.XQP.bind(au,()=>null,async()=>{calls++;return {ok:true,file:'real.mp3'};});
  assert.equal((await c.XQP.playCalm()).ok,true,'native player must receive the request');
  assert.equal(calls,1);
  c.XQP.bind(au,()=>null,async()=>({ok:false,why:'blocked'}));
  assert.equal((await c.XQP.playCalm()).why,'blocked');
  console.log('PASS native playback delegation and truthful failure');

  const w=env(); vm.runInContext(read('wake.js'),w);
  let grant,stopped=0;
  w.navigator.mediaDevices.getUserMedia=()=>new Promise(r=>grant=r);
  w.XQ.wake.attach({online:true,send(){}},{kws_model:'test'});
  const starting=w.XQ.wake.start();
  w.XQ.wake.stop('manual');
  grant({getTracks:()=>[{stop(){stopped++;}}]});
  await starting;
  assert.equal(stopped,1,'late permission must release the microphone');
  assert.equal(w.XQ.wake.state,'off');
  console.log('PASS cancelled microphone request cannot reopen capture');

  let messages=[];
  w.XQ.wake.link={online:true,send:m=>messages.push(m)};
  w.XQ.wake._stream={};
  w.XQ.wake.state='listening';
  w.XQ.wake._serverReady=true;
  w.XQ.wake.disconnected();
  assert.equal(w.XQ.wake.state,'starting');
  w.XQ.wake._send(new Float32Array(1600));
  assert.equal(messages.length,0,'disconnected capture must not claim PCM sent');
  w.XQ.wake.attach(w.XQ.wake.link,{kws_model:'test'});
  assert.equal(messages.length,1);
  assert.equal(messages[0].type,'voice_start');
  w.XQ.wake.onMsg({ev:'ready'});
  assert.equal(w.XQ.wake.state,'listening');
  assert.equal(w.XQ.wake._serverReady,true);
  assert.equal(w.sessionStorage.getItem(w.XQ.wake.WANT_KEY),'on');
  console.log('PASS reconnect re-registers capture and waits for server ready');

  const m=env(); vm.runInContext(read('wake.js'),m);
  messages=[];
  m.XQ.wake.link={online:true,send:r=>messages.push(r)};
  m.XQP={playCalm:async()=>({ok:false,why:'blocked'})};
  m.XQ.wake.onMsg({ev:'do',id:'music',seq:3});
  await new Promise(r=>setTimeout(r,0));
  assert.equal(messages[0].ok,false);
  assert.equal(messages[0].why,'blocked');
  assert.equal(messages[0].seq,3);
  messages=[];
  m.XQ.wake.onMsg({ev:'do',id:'go:media',seq:4});
  assert.equal(messages[0].same,true);
  assert.equal(messages[0].ok,true);
  console.log('PASS music failure acknowledgement and same-page navigation');
  messages=[];
  m.XQ.tts={lastError:'已静音'};
  m.XQ.speak=()=>false;
  m.XQ.wake.onMsg({ev:'reply',text:'test reply',round:7});
  assert.equal(messages[0].played,false);
  assert.equal(messages[0].round,7);
  assert.match(m.XQ.wake.playbackWhy,/静音/);
  messages=[];
  let completed;
  m.XQ.speak=(_,opts)=>{completed=opts.done;return true;};
  m.XQ.wake.onMsg({ev:'reply',text:'test reply',round:8});
  m.XQ.wake.round=9;
  completed();
  assert.equal(messages[0].round,8,'completion must retain its original round');
  assert.equal(messages[0].played,true);
  console.log('PASS unplayed reply reports failure and completion retains its round');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
