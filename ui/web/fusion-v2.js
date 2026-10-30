/* Additive view: reuses the page's existing socket and design tokens. */
(() => {
  const host = document.getElementById('fusionV2Mount');
  const badge = document.getElementById('fusionModeBadge');
  let latest = null, disconnected = true, requested = null;
  const text = (id,value) => { const e=document.getElementById(id); if(e)e.textContent=value??'—'; };
  const number = (x,unit='') => typeof x==='number' && Number.isFinite(x)?`${x.toFixed(2)}${unit}`:'—';
  const probability = x => typeof x==='number' && Number.isFinite(x)?`${(x*100).toFixed(1)}%`:'—';
  if (host) {
    const tile = (label,id) => `<div class="mt"><div class="k">${label}</div><div class="v na" id="${id}">—</div></div>`;
    host.innerHTML = `<div class="mon-sec-h"><h2>多模型融合监测</h2><span class="note" id="fvConnection">等待真实数据</span></div>
      <div class="three fusion-grid">
        <section class="card card-pad span-all"><div class="card-h"><h3>当前疲劳风险</h3><span class="note" id="fvMode">Legacy</span></div>
          <div class="mtiles">${tile('最终等级 · 沿用原有 L0–L3','fvFinal')}${tile('变化趋势','fvTrend')}${tile('Legacy / V2 对照','fvCompare')}${tile('主要原因','fvReason')}</div>
          <label class="fusion-control" id="fvControl" hidden>融合模式 <select id="fvSelect" aria-label="融合模式"><option value="legacy">Legacy</option><option value="v2">Fusion V2</option></select><span class="note" id="fvAck"></span></label></section>
        <section class="card card-pad"><div class="card-h"><h3>眼部智能监测</h3><span class="note" id="fvEyeStatus">INVALID</span></div><div class="mtiles">
          ${tile('左眼状态 / 睁眼概率','fvLeft')}${tile('右眼状态 / 睁眼概率','fvRight')}${tile('EAR / PERCLOS','fvEar')}${tile('当前闭眼时长','fvEyeDuration')}${tile('YOLO Eye 耗时','fvEyeMs')}${tile('几何与分类一致性','fvEyeAgreement')}</div></section>
        <section class="card card-pad"><div class="card-h"><h3>嘴部哈欠监测</h3><span class="note" id="fvMouthStatus">INVALID</span></div><div class="mtiles">
          ${tile('分类概率 · 非疲劳程度','fvMouthProb')}${tile('MAR','fvMar')}${tile('候选持续时长','fvMouthDuration')}${tile('候选事件数','fvMouthCount')}${tile('YOLO Mouth 耗时','fvMouthMs')}${tile('模型冲突','fvMouthConflict')}</div></section>
        <section class="card card-pad"><div class="card-h"><h3>头部姿态</h3><span class="note" id="fvHeadStatus">INVALID</span></div><div class="mtiles">
          ${tile('Pitch / Yaw / Roll','fvAngles')}${tile('相对下探 / 持续时间','fvHeadDown')}${tile('原 nod 统计 · 次/分','fvNod')}${tile('独立点头周期','fvNodEvent')}</div></section>
        <section class="card card-pad span-all"><details open><summary>融合判定依据</summary><div class="fusion-evidence" id="fvEvidence"></div><p class="note" id="fvConflicts">等待证据</p><p class="note" id="fvDegraded"></p></details></section>
        <section class="card card-pad span-all"><details><summary>模型运行状态与最近事件</summary><div class="fusion-runtime" id="fvRuntime"></div><p class="note" id="fvUpdated">—</p><ul id="fvEvents"></ul></details></section>
      </div>`;
    document.getElementById('fvSelect').addEventListener('change',e => {
      const link=window.XQ&&XQ.fusionTransport;
      if (!link || !link.online) { text('fvAck','连接异常，未发送');return; }
      requested=e.target.value;e.target.disabled=true;text('fvAck','等待后端确认…');
      link.send({type:'fusion_mode',mode:requested});
    });
  }
  const label = g => !g?'INVALID':g.stale?'STALE':g.warmup?'WARMUP':!g.valid?'INVALID':g.conflict?'CONFLICT':g.state?.toUpperCase()||'VALID';
  function paint() {
    const f=latest?.fusion_v2;
    const stale=!!f && Date.now()/1000-f.last_update_wall>1.5;
    const status=disconnected?'连接异常':stale?'STALE · 数据已过期':f?'实时后端数据':'未开启 Fusion V2 对照';
    if(badge)badge.textContent=f?`Fusion ${f.mode==='v2'?'V2':'Legacy'} · ${status}`:status;
    if(!host)return;
    text('fvConnection',status);host.dataset.valid=disconnected||stale?'false':'true';
    if (!f || disconnected || stale) {
      ['fvEyeStatus','fvMouthStatus','fvHeadStatus'].forEach(id=>text(id,stale?'STALE':'INVALID'));
      ['fvFinal','fvReason','fvCompare','fvTrend','fvLeft','fvRight','fvEar','fvEyeDuration','fvMouthProb','fvMar','fvMouthDuration','fvAngles','fvHeadDown','fvEyeMs','fvMouthMs','fvNod','fvMouthCount'].forEach(id=>text(id,'—'));
      text('fvEyeAgreement',stale?'STALE':'INVALID');text('fvMouthConflict',stale?'STALE':'INVALID');
      text('fvEvidence',stale?'STALE · 等待新证据':'INVALID · 无当前证据');
      text('fvRuntime',disconnected?'连接异常':stale?'STALE · 等待模型更新':'等待模型数据');
      document.getElementById('fvControl').hidden=true;
      return;
    }
    const e=f.eye_evidence,m=f.mouth_evidence,h=f.head_evidence;
    text('fvMode',`Fusion ${f.mode==='v2'?'V2':'Legacy'}`);
    text('fvFinal',`L${f.final_level} · ${f.valid_sources.length?['正常驾驶','轻度疲劳','中度疲劳','重度疲劳'][f.final_level]:'数据不足 · 待判'}`);
    text('fvCompare',`L${f.legacy_level} / L${f.fusion_v2_level}`);
    text('fvTrend',({up:'证据增强 · 升级观察',down:'证据减弱 · 降级滞回',stable:'稳定'})[f.trend]);
    text('fvReason',f.risk_reasons.join('；'));
    text('fvEyeStatus',e.yolo_stale?'STALE':!e.yolo_valid?'INVALID':label(e));text('fvMouthStatus',m.yolo_stale?'STALE':!m.yolo_valid?'INVALID':label(m));text('fvHeadStatus',label(h));
    text('fvLeft',`${e.yolo_stale?'STALE':e.left_state.toUpperCase()} / ${probability(e.left_open_prob)}`);
    text('fvRight',`${e.yolo_stale?'STALE':e.right_state.toUpperCase()} / ${probability(e.right_open_prob)}`);
    text('fvEar',`${number(e.ear)} / ${probability(e.perclos)}`);text('fvEyeDuration',number(e.closed_duration,' s'));
    text('fvEyeMs',number(e.latency_ms,' ms'));text('fvEyeAgreement',e.conflict?'CONFLICT':e.agreement?'一致':e.yolo_valid?'观察中':'YOLO INVALID');
    text('fvMouthProb',probability(m.yawn_probability));text('fvMar',number(m.mar));text('fvMouthDuration',number(m.duration,' s'));
    text('fvMouthCount',m.event_count);text('fvMouthMs',number(m.latency_ms,' ms'));text('fvMouthConflict',m.conflict?'CONFLICT':'未检测到冲突');
    text('fvAngles',[h.pitch,h.yaw,h.roll].map(x=>number(x,'°')).join(' / '));text('fvHeadDown',`${number(h.head_swing,'°')} / ${number(h.duration,' s')}`);
    text('fvNod',number(h.nod_rate));text('fvNodEvent','未实现 · 保留原 nod 统计');
    const evidence=document.getElementById('fvEvidence');evidence.replaceChildren();
    for(const [name,g] of [['Eye',e],['Mouth',m],['Head',h],['Transformer',f.transformer_evidence],['FaceBranch',f.face_evidence]]) {
      const row=document.createElement('div');row.className='fusion-evidence-row';
      const title=document.createElement('b');title.textContent=name;
      const value=document.createElement('span');value.textContent=`${label(g)} · ${g.valid?'L'+g.level:'不投票'}`;
      row.append(title,value);evidence.append(row);
    }
    text('fvConflicts',f.conflicts.length?`冲突：${f.conflicts.join(' / ')}`:'当前没有记录到模型冲突');
    text('fvDegraded',f.degraded?'已退化为原版融合：YOLO 不可用':'无效支路不参与对应证据组；不累加同一行为');
    const rt=document.getElementById('fvRuntime');rt.replaceChildren();
    const runtimeNames={pose:'Pose',facemesh:'FaceMesh',transformer:'Transformer',yolo_eye:'YOLO Eye',yolo_mouth:'YOLO Mouth',face_branch:'FaceBranch LR'};
    for(const [name,r] of Object.entries(f.runtime||{})) {const row=document.createElement('p');row.textContent=`${runtimeNames[name]||name} · ${r.warmup?'WARMUP':r.stale?'STALE':r.valid?'VALID':'INVALID'} · ${r.backend} · ${number(r.latency_ms,' ms')} · 样本 ${number(r.timestamp,' s')}`;rt.append(row);}
    text('fvUpdated',`最近决策：${new Date(f.last_update_wall*1000).toLocaleTimeString()} · LR 有效样本 ${f.face_evidence.valid_samples}`);
    const events=document.getElementById('fvEvents');events.replaceChildren();
    for(const ev of f.recent_events||[]) {const li=document.createElement('li');li.textContent=`${number(ev.timestamp,' s')} · ${ev.message}`;events.append(li);}
    const select=document.getElementById('fvSelect');document.getElementById('fvControl').hidden=!f.switch_allowed;
    if(requested===f.mode){requested=null;text('fvAck','后端已生效');}
    if(!requested){select.value=f.mode;select.disabled=false;}
  }
  window.addEventListener('xq-state',event=>{latest=event.detail;disconnected=false;paint();});
  window.addEventListener('xq-down',event=>{disconnected=event.detail;paint();});
  window.addEventListener('xq-message',event=>{
    if(event.detail.type!=='fusion_mode')return;
    const d=event.detail.data;
    if(d.ok)text('fvAck','后端已确认，等待下一次决策');
    else{requested=null;text('fvAck',d.error||'切换未成功');const e=document.getElementById('fvSelect');if(e)e.disabled=false;}
  });
  setInterval(paint,500);
})();
