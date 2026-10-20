/* Undertow community: sign-in, rug calls, votes and crowd tags, kept in Supabase (supabase/schema.sql).
   Built only into the GitHub page; the claude.ai copy has none of it. Nothing here touches a gate: the crowd is
   shown beside the gates, and the Lab tests whether it predicts anything, like any other variable. */
(function(){
'use strict';
var U=window.Undertow;if(!U||U.inClaude||!U.served)return;
var doc=document,esc=U.esc,CFG=null,SB=null;
function $(s,r){return (r||doc).querySelector(s);}
function $$(s,r){return Array.prototype.slice.call((r||doc).querySelectorAll(s));}
var me=null,name=null,crowd={},mine={calls:{},votes:{},tags:{}},myHist=null,board=null,recent=null,busy=false,msg={},
    live=false,listedAt=null;
var TAGS=[['dev_active','Dev active',0],['real_community','Real community',0],['cto','Community takeover',0],
          ['bundled','Bundled',1],['rug_suspected','Rug suspected',1],['fake_volume','Fake volume',1]];
var OPEN=['IN','WATCH','ENTERING'],MIN_RANKED=5,SBJS='https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.112.3/dist/umd/supabase.js';

/* ---------- start once the scan's config (with the Supabase address) has arrived ---------- */
var started=false;
function go(){
  if(started)return;var c=U.cfg()||{};if(!c.SUPABASE_URL||!c.SUPABASE_PUBLISHABLE_KEY)return;
  started=true;CFG=c;
  var bad=/error_description=([^&]+)/.exec(location.hash);          // an expired or reused sign-in link comes back like this
  if(bad){msg.auth=decodeURIComponent(bad[1].replace(/\+/g,' '));try{history.replaceState(null,'',location.pathname+location.search);}catch(e){}}
  var s=doc.createElement('script');s.src=SBJS;s.onload=init;
  s.onerror=function(){if(window.console)console.info('Undertow: supabase-js did not load, so rug calls and votes are off');};
  doc.head.appendChild(s);
}
U.on('data',function(){go();renderXray();if(U.view()==='callers')paintCallers();});
go();

function init(){
  if(!window.supabase||!window.supabase.createClient)return;
  SB=window.supabase.createClient(CFG.SUPABASE_URL,CFG.SUPABASE_PUBLISHABLE_KEY,
    {auth:{persistSession:true,autoRefreshToken:true,detectSessionInUrl:true,flowType:'implicit'}});
  probe();
}
/* Show nothing until the database answers: before supabase/schema.sql has been run, or while Supabase is down,
   the page is the plain screener. Checked again every five minutes. */
function probe(){
  readListed().then(function(ok){if(ok)start();else setTimeout(probe,300000);});
}
function readListed(){
  return SB.from('tokens').select('updated_at').order('updated_at',{ascending:false}).limit(1).then(function(r){
    if(r.error)return false;listedAt=r.data&&r.data[0]?Date.parse(r.data[0].updated_at)/1000:null;return true;
  },function(){return false;});
}
function callsOpen(){return listedAt!=null&&Date.now()/1000-listedAt<7000;}  /* the database refuses calls after 2h */
function start(){
  if(live)return;live=true;addChrome();
  SB.auth.onAuthStateChange(function(ev,session){setTimeout(function(){setUser(session&&session.user);},0);});
  refreshCrowd();
  setInterval(function(){if(doc.hidden)return;readListed();refreshCrowd();if(U.view()==='callers')renderCallers(true);},60000);
  U.on('xray',function(k){renderXray(k);});
  U.on('view',function(v){if(v==='callers')renderCallers(true);});
  if(U.view()==='callers')renderCallers(true);
  renderXray();
  if(msg.auth)openModal();
}
function setUser(u){
  var id=u?u.id:null;if((me?me.id:null)===id&&name!==null)return;
  me=u||null;name=null;mine={calls:{},votes:{},tags:{}};myHist=null;
  if(!me){renderAuth();renderXray();if(U.view()==='callers')paintCallers();return;}
  SB.from('profiles').select('name').eq('id',me.id).maybeSingle().then(function(r){
    if(!me||me.id!==id)return;
    if(r.error){setTimeout(function(){if(me&&me.id===id&&name===null){me=null;setUser(u);}},15000);return;}  /* retry; never ask for a name on a failed read */
    name=r.data?r.data.name:'';renderAuth();refreshMine();
    if(!name)openModal();else if(modal&&!$('#cm-name',modal))closeModal();
  });
}

/* ---------- reads ---------- */
function refreshCrowd(){
  SB.from('token_crowd').select('mint,rug_calls,hold_calls,watch,avoid,tags').then(function(r){
    if(r.error)return;crowd={};(r.data||[]).forEach(function(x){crowd[x.mint]=x;});renderXray();});
}
function refreshMine(){
  if(!me)return;var id=me.id;
  Promise.all([
    SB.from('calls').select('id,mint,side,created_at,price_at_call,priced_at,outcome,points,settled_at,tokens(symbol)')
      .eq('user_id',id).order('created_at',{ascending:false}).limit(100),
    SB.from('votes').select('mint,vote').eq('user_id',id),
    SB.from('tags').select('mint,tag').eq('user_id',id)
  ]).then(function(rs){
    if(!me||me.id!==id)return;
    mine={calls:{},votes:{},tags:{}};myHist=rs[0].data||[];
    myHist.forEach(function(c){if(!c.settled_at)mine.calls[c.mint]=c;});
    (rs[1].data||[]).forEach(function(v){mine.votes[v.mint]=v.vote;});
    (rs[2].data||[]).forEach(function(t){(mine.tags[t.mint]=mine.tags[t.mint]||{})[t.tag]=true;});
    renderXray();if(U.view()==='callers')paintCallers();
  });
}

/* ---------- writes: each goes through a checked function in the database ---------- */
function act(fn,args,ok){
  if(!live)return;
  if(!me||!name){openModal();return;}
  if(busy)return;busy=true;msg.xr='';
  SB.rpc(fn,args).then(function(r){
    busy=false;
    if(r.error){msg.xr=r.error.message||'That did not go through.';renderXray();return;}
    if(ok)U.toast(ok);refreshCrowd();refreshMine();
  },function(){busy=false;msg.xr='Supabase could not be reached. Try again in a minute.';renderXray();});
}
function call(mint,side){act('make_call',{token:mint,call_side:side},side==='rug'?'Called: rugs within 24h':'Called: holds 24h');}
function vote(mint,v){act('set_vote',{token:mint,new_vote:(mine.votes[mint]||0)===v?0:v});}
function tag(mint,t){act('toggle_tag',{token:mint,tag_name:t});}

/* ---------- page furniture: the account button, the Callers view and its pane ---------- */
function addChrome(){
  var car=$('.cartouche');
  if(car&&!$('#cm-me')){var b=doc.createElement('button');b.type='button';b.id='cm-me';b.className='refresh';b.textContent='Sign in';
    b.onclick=openModal;car.appendChild(b);}
  var seg=$('.rail .seg');
  if(seg&&!$('[data-view="callers"]')){var v=doc.createElement('button');v.type='button';v.dataset.view='callers';v.setAttribute('aria-pressed','false');
    v.textContent='Callers';v.onclick=function(){U.setView('callers');};seg.appendChild(v);}
  var lab=$('#labwrap');
  if(lab&&!$('#callerswrap')){var p=doc.createElement('div');p.className='pane callerswrap';p.id='callerswrap';p.hidden=U.view()!=='callers';
    lab.parentNode.insertBefore(p,lab.nextSibling);}
}
function renderAuth(){var b=$('#cm-me');if(!b)return;b.textContent=me?(name?'@'+name:'Pick a name'):'Sign in';
  b.title=me?'Your account':'Sign in to call rugs, vote and tag';}

/* ---------- the sign-in, name and account dialog ---------- */
var modal=null,lastFocus=null;
function openModal(){
  if(!live)return;closeModal();lastFocus=doc.activeElement;
  modal=doc.createElement('div');modal.className='cm-modal';
  modal.innerHTML='<div class="cm-box" role="dialog" aria-modal="true" aria-labelledby="cm-title">'+modalBody()+'<button type="button" class="cm-x" aria-label="Close">✕</button></div>';
  doc.body.appendChild(modal);
  modal.addEventListener('click',function(e){if(e.target===modal)closeModal();});
  modal.addEventListener('keydown',function(e){if(e.key==='Escape'){e.stopPropagation();closeModal();}});
  wireModal();var f=$('input',modal)||$('.btn',modal)||$('.cm-x',modal);if(f)f.focus();
}
function closeModal(){if(!modal)return;modal.remove();modal=null;msg.auth='';if(lastFocus&&lastFocus.focus)try{lastFocus.focus();}catch(e){}}
function err(t){return t?'<p class="cm-err" role="alert">'+esc(t)+'</p>':'';}
function modalBody(){
  if(!me)return '<h2 id="cm-title">Sign in</h2>'+err(msg.auth)
    +'<p>Sign in to call rugs, vote and tag tokens. We email you a link: no password, and never a wallet. Don’t connect a wallet to any screener.</p>'
    +'<form class="cm-form" id="cm-email" novalidate><label for="cm-mail">Email</label><input id="cm-mail" type="email" autocomplete="email" inputmode="email" required placeholder="you@example.com"><button class="btn primary" type="submit">Email me a link</button></form>'
    +(CFG.SUPABASE_X_LOGIN?'<button class="btn" type="button" id="cm-xlogin">Continue with X</button>':'')
    +'<p class="fine">Your email stays private. Other visitors see only the public name you pick next, your settled calls and your points.</p>';
  if(!name)return '<h2 id="cm-title">Pick a public name</h2>'
    +'<p>Your calls and points appear under it. 3 to 20 letters, digits or underscores.</p>'
    +'<form class="cm-form" id="cm-name" novalidate><label for="cm-nm">Name</label><input id="cm-nm" maxlength="20" autocomplete="nickname" required><button class="btn primary" type="submit">Save</button></form>'
    +'<button type="button" class="linkbtn" id="cm-out">Sign out</button>';
  return '<h2 id="cm-title">@'+esc(name)+'</h2><p>Signed in as '+esc(me.email||'you')+'. Only you see this address.</p>'
    +'<form class="cm-form" id="cm-name" novalidate><label for="cm-nm">Public name</label><input id="cm-nm" maxlength="20" autocomplete="nickname" required value="'+esc(name)+'"><button class="btn" type="submit">Rename</button></form>'
    +'<div class="cm-row"><button class="btn primary" type="button" id="cm-board">Your calls and the scoreboard</button><button class="btn" type="button" id="cm-out">Sign out</button></div>';
}
function setErr(t){var box=$('.cm-box',modal),e=$('.cm-err',box);if(e)e.remove();if(t)$('h2',box).insertAdjacentHTML('afterend',err(t));}
function wireModal(){
  $('.cm-x',modal).onclick=closeModal;
  var em=$('#cm-email',modal);
  if(em)em.onsubmit=function(e){e.preventDefault();var a=$('#cm-mail',modal).value.trim(),btn=$('.btn',em);
    if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(a)){setErr('That doesn’t look like an email address.');return;}
    btn.disabled=true;btn.textContent='Sending…';
    SB.auth.signInWithOtp({email:a,options:{emailRedirectTo:location.origin+location.pathname}}).then(function(r){
      btn.disabled=false;btn.textContent='Email me a link';
      if(r.error){setErr(r.error.message);return;}
      $('.cm-box',modal).innerHTML='<h2 id="cm-title">Check your inbox</h2><p>We sent a sign-in link to <b>'+esc(a)+'</b>. Open it in this browser and it brings you back here, signed in. It can take a minute; check spam too.</p><button type="button" class="cm-x" aria-label="Close">✕</button>';
      $('.cm-x',modal).onclick=closeModal;$('.cm-x',modal).focus();
    },function(){btn.disabled=false;btn.textContent='Email me a link';setErr('Supabase could not be reached. Try again in a minute.');});};
  var xb=$('#cm-xlogin',modal);
  if(xb)xb.onclick=function(){SB.auth.signInWithOAuth({provider:'x',options:{redirectTo:location.origin+location.pathname}}).then(function(r){if(r.error)setErr(r.error.message);});};
  var nm=$('#cm-name',modal);
  if(nm)nm.onsubmit=function(e){e.preventDefault();var v=$('#cm-nm',modal).value.trim();
    if(!/^[A-Za-z0-9_]{3,20}$/.test(v)){setErr('Names are 3 to 20 letters, digits or underscores.');return;}
    SB.rpc('set_name',{new_name:v}).then(function(r){if(r.error){setErr(r.error.message);return;}
      name=r.data;renderAuth();closeModal();U.toast('You are @'+name);renderXray();if(U.view()==='callers')renderCallers(true);});};
  var out=$('#cm-out',modal);if(out)out.onclick=function(){SB.auth.signOut().then(function(){closeModal();U.toast('Signed out');});};
  var bd=$('#cm-board',modal);if(bd)bd.onclick=function(){closeModal();U.setView('callers');};
}

/* ---------- the X-ray's crowd section ---------- */
function n(v){return U.int(v||0);}
function since(iso){return iso?U.ago(Date.parse(iso)/1000):'';}
function left(c){
  if(!c.priced_at)return 'priced at the next scan';
  var s=Date.parse(c.priced_at)/1000+86400-Date.now()/1000;
  return s<=0?'settles at the next scan':'settles in '+(s>=3600?Math.round(s/3600)+' h':Math.max(1,Math.round(s/60))+' min');
}
function renderXray(k){
  var sec=$('#xr-crowd');if(!sec)return;
  if(!k){var id=U.selected();k=id&&U.token(id);}
  if(!k||!live){sec.hidden=true;return;}
  var c=crowd[k.id]||{},my=mine.calls[k.id],mv=mine.votes[k.id]||0,mt=mine.tags[k.id]||{},tg=c.tags||{};
  var calls=(c.rug_calls||0)+(c.hold_calls||0),open=OPEN.indexOf(k.state)>=0;
  var callUi=my?'<p class="cr-mine">Your call: <b>'+(my.side==='rug'?'rugs within 24h':'holds 24h')+'</b>, made '+esc(since(my.created_at))+' · '+esc(left(my))+'.</p>'
    :!open?'<p class="fine">Calls open while a token is in the screener or entering it.</p>'
    :!callsOpen()?'<p class="fine">Calls are paused: '+(listedAt?'the scanner last updated the list of callable tokens '+esc(U.ago(listedAt)):'the scanner has not listed any tokens yet')+'. They reopen with its next scan.</p>'
    :'<div class="cr-btns"><button type="button" class="btn" data-cr-call="rug">Call: rugs within 24h</button><button type="button" class="btn" data-cr-call="hold">Call: holds 24h</button></div>';
  sec.hidden=false;
  sec.innerHTML='<h3>Crowd</h3>'
    +'<p class="cr-line"><b>'+(calls?n(c.rug_calls)+' say it rugs, '+n(c.hold_calls)+' say it holds':'No open calls')+'</b><span class="nm">Open 24-hour calls from signed-in visitors, scored on the <button type="button" class="linkbtn" data-cr-board="1">Callers’ scoreboard</button>.</span></p>'
    +callUi
    +(msg.xr?'<p class="cr-msg" role="alert">'+esc(msg.xr)+'</p>':'')
    +'<div class="cr-btns" role="group" aria-label="Your vote"><button type="button" class="chipbtn" data-cr-vote="1" aria-pressed="'+(mv===1)+'">Worth watching · '+n(c.watch)+'</button><button type="button" class="chipbtn bad" data-cr-vote="-1" aria-pressed="'+(mv===-1)+'">Avoid · '+n(c.avoid)+'</button></div>'
    +'<div class="cr-tags" role="group" aria-label="Your tags">'+TAGS.map(function(t){return '<button type="button" class="chipbtn'+(t[2]?' bad':'')+'" data-cr-tag="'+t[0]+'" aria-pressed="'+(!!mt[t[0]])+'">'+esc(t[1])+(tg[t[0]]?' · '+n(tg[t[0]]):'')+'</button>';}).join('')+'</div>'
    +'<p class="fine">Shown beside the gates, never used by them. The Lab tests whether the crowd predicts anything. '+(me?'':'<button type="button" class="linkbtn" data-cr-in="1">Sign in</button> to call, vote or tag.')+'</p>';
  $$('[data-cr-call]',sec).forEach(function(b){b.onclick=function(){call(k.id,b.getAttribute('data-cr-call'));};});
  $$('[data-cr-vote]',sec).forEach(function(b){b.onclick=function(){vote(k.id,+b.getAttribute('data-cr-vote'));};});
  $$('[data-cr-tag]',sec).forEach(function(b){b.onclick=function(){tag(k.id,b.getAttribute('data-cr-tag'));};});
  var bb=$('[data-cr-board]',sec);if(bb)bb.onclick=function(){U.setView('callers');};
  var si=$('[data-cr-in]',sec);if(si)si.onclick=openModal;
}

/* ---------- the Callers view: scoreboard, your calls, recent results ---------- */
function renderCallers(fetchNow){
  if(!live){paintCallers();return;}
  if(fetchNow||!board){
    Promise.all([SB.from('leaderboard').select('*').order('points',{ascending:false}).limit(500),
                 SB.from('recent_calls').select('*').order('settled_at',{ascending:false}).limit(60)])
      .then(function(rs){if(rs[0].error){board=board||[];msg.board='The scoreboard could not load: '+rs[0].error.message;}else{board=rs[0].data||[];msg.board='';}
        recent=rs[1].data||[];paintCallers();},function(){msg.board='Supabase could not be reached.';board=board||[];paintCallers();});
    if(me)refreshMine();
  }
  paintCallers();
}
function pts(v){return v==null?'–':(v>0?'+':v<0?'−':'')+Math.abs(Math.round(v*10)/10);}
function hit(r,a){return a?Math.round(r/a*100)+'% <span class="nm">of '+a+'</span>':'–';}
function row(x,i){return '<tr class="'+(i==null?'unranked':'')+(name&&x.name===name?' me':'')+'"><td>'+(i==null?'–':i+1)+'</td><td class="l">@'+esc(x.name)+'</td><td>'+pts(x.points)+'</td><td>'+x.settled+'</td><td>'+hit(x.rug_right,x.rug_calls)+'</td><td>'+hit(x.hold_right,x.hold_calls)+'</td><td>'+x.open_calls+'</td></tr>';}
function paintCallers(){
  var w=$('#callerswrap');if(!w||U.view()!=='callers')return;
  var D=U.data()||{},M=D.meta||{},r=M.call_base_rate||(CFG&&CFG.CALL_BASE_RATE)||0.1,k=Math.round((1-r)/r*10)/10;
  var rateTxt=M.call_base_rate_measured?'Over the last fortnight '+Math.round(r*100)+'% of coins that passed every gate rugged within a day'
    :'Until a fortnight of passing coins has settled, calls are scored as if '+Math.round(r*100)+'% of them rug within a day';
  var ranked=(board||[]).filter(function(x){return x.settled>=MIN_RANKED;}),rest=(board||[]).filter(function(x){return x.settled<MIN_RANKED;});
  var head='<div class="trk-head"><h2 class="cm-h">Callers</h2>'
    +'<p class="trk-note">Open a token’s X-ray and call it: <b>rugs within 24 hours</b> or <b>holds 24 hours</b>. Each call is priced at the next scan, so nobody calls with hindsight, and settles a day later on the rug study’s definition: rugged means the price fell 80% below the call price before it ever traded 50% above it.</p>'
    +'<p class="trk-note">'+rateTxt+', so a right rug call scores <b>+'+k+'</b> and a wrong one <b>−1</b>; a right hold call scores <b>+1</b> and a wrong one <b>−'+k+'</b>. Guessing at that rate scores nothing on average, so points measure skill, not activity. Ten calls a day, no cancelling, ranked from '+MIN_RANKED+' settled calls. Points only: no money changes hands.'
    +(live&&!me?' <button type="button" class="linkbtn" id="cm-signin2">Sign in to call</button>':'')+'</p></div>';
  var table=!live?'<p class="empty">The scoreboard could not reach its database. It retries every few minutes.</p>'
    :board==null?'<p class="empty">Loading the scoreboard…</p>'
    :!board.length?'<p class="empty">'+(msg.board?esc(msg.board):'No calls yet. The first settle a day after they are made.')+'</p>'
    :'<div class="tscroll"><table class="grid lab cm-t"><thead><tr><th>#</th><th class="l">Caller</th><th>Points</th><th>Settled</th><th>Rug calls right</th><th>Hold calls right</th><th>Open</th></tr></thead><tbody>'
      +ranked.map(function(x,i){return row(x,i);}).join('')+rest.map(function(x){return row(x,null);}).join('')+'</tbody></table></div>';
  var mineT=me&&myHist&&myHist.length?'<section class="lab-sec"><h3>Your calls</h3><div class="tscroll"><table class="grid lab cm-t"><thead><tr><th class="l">Token</th><th class="l">Call</th><th class="l">Made</th><th class="l">Result</th><th>Points</th></tr></thead><tbody>'
    +myHist.map(function(c){var sym=(c.tokens&&c.tokens.symbol)||c.mint.slice(0,6);
      var res=c.settled_at?(c.outcome==='rug'?'Rugged':c.outcome==='held'?'Held':'Void: lost its price'):left(c);
      return '<tr><td class="l">'+esc(sym)+'</td><td class="l">'+(c.side==='rug'?'Rugs':'Holds')+'</td><td class="l">'+esc(since(c.created_at))+'</td><td class="l">'+esc(res)+'</td><td>'+(c.settled_at?pts(c.points):'–')+'</td></tr>';}).join('')
    +'</tbody></table></div></section>':'';
  var rec=recent&&recent.length?'<section class="lab-sec"><h3>Recently settled</h3><div class="tscroll"><table class="grid lab cm-t"><thead><tr><th class="l">Caller</th><th class="l">Token</th><th class="l">Call</th><th class="l">Result</th><th>Day’s high / low</th><th>Points</th></tr></thead><tbody>'
    +recent.map(function(c){return '<tr><td class="l">@'+esc(c.name)+'</td><td class="l">'+esc(c.symbol||c.mint.slice(0,6))+'</td><td class="l">'+(c.side==='rug'?'Rugs':'Holds')+'</td><td class="l">'+(c.outcome==='rug'?'Rugged':'Held')+'</td><td>'+(c.hi!=null?U.xm(c.hi)+' / '+U.xm(c.lo):'–')+'</td><td>'+pts(c.points)+'</td></tr>';}).join('')
    +'</tbody></table></div></section>':'';
  w.innerHTML=head+'<section class="lab-sec"><h3>Scoreboard</h3>'+table+'</section>'+mineT+rec;
  var si=$('#cm-signin2',w);if(si)si.onclick=openModal;
}
})();
