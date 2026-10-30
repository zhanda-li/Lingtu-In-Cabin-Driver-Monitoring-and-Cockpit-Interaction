/* Run with agent-browser eval --stdin on an isolated :8817/nav.html test page.
   These are labelled fixtures, never production route results. Reload afterwards. */
(async () => {
  if (location.hostname !== '127.0.0.1' || location.port !== '8817'
      || sessionStorage.getItem('xq.wake.want') !== 'off') {
    throw new Error('Use isolated localhost:8817 with microphone off.');
  }
  const results = [];
  const check = (condition, name) => {
    if (!condition) throw new Error(name);
    results.push(name);
  };
  const originalFetch = window.fetch, originalGeo = XQ.geo.ask;
  const savedOrigin = localStorage.getItem('xq.nav.org'), savedGeo = XQ.geo.last;
  const pending = [];
  const json = value => new Response(JSON.stringify(value), {status:200,
    headers:{'Content-Type':'application/json'}});
  const point = (name, lat, lng) => ({name,lat,lng,address:'TEST FIXTURE'});
  const a = point('TEST START',39.13,117.20);
  const b = point('TEST DEST B',39.14,117.21);
  const c = point('TEST DEST C',39.15,117.22);
  const response = target => ({ok:true,by:'drive',has_route:true,name:target.name,
    poi_lat:target.lat,poi_lng:target.lng,km:1,min:2,
    routes:[{drive_m:1000,drive_s:120,min:2,km:1,tolls:0,lights:2,
      polyline:['117.20,39.13',target.lng+','+target.lat],steps:1,
      step_list:[{m:1000,s:120,tx:'TEST INSTRUCTION',road:'TEST ROAD',
        poly:['117.20,39.13',target.lng+','+target.lat]}]}]});
  try {
    window.fetch = (url,options={}) => {
      if (String(url).startsWith('/amap/route')) {
        return new Promise(resolve => pending.push({resolve,signal:options.signal}));
      }
      return originalFetch(url,options);
    };
    await takePlace(a,'org'); await takePlace(b,'dest');
    check(pending.length===0 && XQ.nav.state().routes===0,
      'selecting endpoints does not issue premature route requests');
    const older = routeTo();
    check($('navStart').disabled && $('dstGo').disabled,'loading disables navigation and duplicate clicks');
    await takePlace(c,'dest');
    check(pending[0].signal.aborted,'changing destination cancels the previous request');
    const newer = routeTo();
    pending[1].resolve(json(response(c))); await newer;
    pending[0].resolve(json(response(b))); await older;
    check(XQ.nav.state().dest.name===c.name && $('nbName').textContent===c.name,
      'late old route cannot overwrite the new destination');
    check(!$('navStart').disabled && !$('dstGo').disabled,'new route unlocks navigation');
    $('dstIn').value='UNCONFIRMED EDIT';
    $('dstIn').dispatchEvent(new Event('input',{bubbles:true}));
    clearTimeout(TYPING.timer);
    check($('navStart').disabled && XQ.nav.state().routes===0,'typing clears stale routes immediately');

    window.fetch = url => String(url).startsWith('/amap/search')
      ? Promise.resolve(json({ok:true,list:[point('SAME NAME',39.1,117.1),point('SAME NAME',39.2,117.2)]}))
      : originalFetch(url);
    $('dstIn').value='SAME NAME';
    const resolved = await resolveBox('dest');
    check(!resolved && $('dstList').querySelectorAll('button').length===2,
      'same-name places require explicit address selection');
    $('dstIn').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}));
    check($('dstIn').getAttribute('aria-activedescendant')==='navPlaceOption0',
      'arrow keys highlight a candidate without changing the destination');
    $('dstIn').dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
    check($('dstList').hidden,'escape closes candidates');

    let searchDone;
    window.fetch=()=>new Promise(resolve=>{searchDone=resolve;});
    $('dstIn').value='LATE SEARCH FIXTURE';
    TYPING.which='dest';
    const searching=runType('dest');
    hideList();
    searchDone(json({ok:true,list:[c]})); await searching;
    check($('dstList').hidden,'late suggestions cannot reopen a dismissed list');

    let attempts=0;
    window.fetch=()=>Promise.resolve(json(++attempts===1
      ? {ok:false,why:'TEST TEMPORARY FAILURE',list:[]}
      : {ok:true,list:[c]}));
    await lookup('RETRY FIXTURE',false);
    const retried=await lookup('RETRY FIXTURE',false);
    check(attempts===2 && retried.ok,'temporary search failures are not cached');

    await takePlace(b,'dest');
    window.fetch = url => String(url).startsWith('/amap/route')
      ? Promise.resolve(new Response('',{status:503})) : originalFetch(url);
    await routeTo();
    check($('navStart').disabled && XQ.nav.state().routes===0
      && $('rtWhy').textContent.includes('503'),'HTTP failures cannot leave a usable old route');

    let geoDone;
    XQ.geo.ask=()=>new Promise(resolve=>{geoDone=resolve;});
    const locating=tryGeo();
    await takePlace(a,'org');
    geoDone({lat:40,lng:118}); await locating;
    check(XQ.nav.state().origin.label===a.name,'late geolocation cannot replace a manual origin');
    return {passed:results.length,checks:results,fixture_data:true};
  } finally {
    window.fetch=originalFetch; XQ.geo.ask=originalGeo;
    clearTimeout(TYPING.timer);
    invalidateRoutes();
    if (savedOrigin === null) localStorage.removeItem('xq.nav.org');
    else localStorage.setItem('xq.nav.org', savedOrigin);
    XQ.geo.last = savedGeo;
  }
})()
