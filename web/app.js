(function(){
'use strict';
var doc=document;
var $=function(s,r){return (r||doc).querySelector(s);};
var $$=function(s,r){return Array.prototype.slice.call((r||doc).querySelectorAll(s));};
var RM=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
var wideMQ=window.matchMedia('(min-width:1100px)');
function wide(){return wideMQ.matches;}

/* ---------- formatting ---------- */
var MINUS='−';
function usd(v){if(v==null||isNaN(v))return 'n/a';var a=Math.abs(v),s=v<0?MINUS:'';if(a>=1e9)return s+'$'+(a/1e9).toFixed(2)+'B';if(a>=1e6)return s+'$'+(a/1e6).toFixed(a>=1e7?1:2)+'M';if(a>=1e4)return s+'$'+Math.round(a/1e3)+'k';if(a>=1e3)return s+'$'+(a/1e3).toFixed(1)+'k';if(a>=10)return s+'$'+Math.round(a);return s+'$'+a.toFixed(2);}
function susd(v){if(v==null||isNaN(v))return 'n/a';return (v<0?'':'+')+usd(v);}
function pc(v,d){if(v==null||isNaN(v))return 'n/a';return v.toFixed(d!=null?d:(Math.abs(v)<10?1:0))+'%';}
function spct(v){if(v==null||isNaN(v))return 'n/a';var a=Math.abs(v);return (v<0?MINUS:'+')+a.toFixed(a<10?1:0)+'%';}
function xm(v){if(v==null||isNaN(v))return 'n/a';return (v>=10?v.toFixed(0):v.toFixed(2))+'×';}
function int(v){return v==null?'n/a':Math.round(v).toLocaleString('en-GB');}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
function short(a){return a?a.slice(0,4)+'…'+a.slice(-4):'';}
function ago(ts,now){var s=Math.max(0,(now||Date.now()/1000)-ts);if(s<90)return 'just now';if(s<5400)return Math.round(s/60)+' min ago';if(s<172800)return Math.round(s/3600)+' h ago';return Math.round(s/86400)+' d ago';}
function ageH(h){if(h==null)return 'n/a';if(h<1)return Math.round(h*60)+'m';if(h<48)return Math.round(h)+'h';return Math.round(h/24)+'d';}
function dur(s){if(s==null)return 'n/a';s=Math.abs(s);if(s<5400)return Math.round(s/60)+' min';if(s<172800)return Math.round(s/3600)+' h';return Math.round(s/86400)+' d';}
var WHEN=(function(){try{return new Intl.DateTimeFormat('en-GB',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit',hour12:false,timeZoneName:'short'});}catch(e){return null;}})();
function when(ts){if(!ts)return 'n/a';var d=new Date(ts*1000);return WHEN?WHEN.format(d).replace(',',''):d.toISOString().slice(0,16).replace('T',' ')+' UTC';}
var LP_NAMES={'pump.fun':'pump.fun','pumpfun':'pump.fun','stonkfun':'StonkFun','stonk.fun':'StonkFun','met-dbc':'Meteora DBC','letsbonk.fun':'LetsBonk','bonk.fun':'LetsBonk','bags.fun':'Bags','moonshot':'Moonshot','metadao':'MetaDAO','boop.fun':'Boop','believe':'Believe','raydium-launchlab':'Raydium LaunchLab','launchlab':'Raydium LaunchLab','jup-studio':'Jupiter Studio','heaven':'Heaven','time.fun':'time.fun','ember':'Ember','revshare':'RevShare'};
function lpName(l){return l?(LP_NAMES[l]||LP_NAMES[String(l).toLowerCase()]||String(l)):'Direct DEX launch';}
var DEX_NAMES={pumpswap:'PumpSwap',raydium:'Raydium',meteora:'Meteora',orca:'Orca',meteoradbc:'Meteora DBC',launchlab:'Raydium LaunchLab',pumpfun:'pump.fun curve'};
var BASE_QUOTES=['SOL','WSOL','USDC','USDT'];
function venueName(k){var v=k.venue||{},d=DEX_NAMES[v.dex]||v.dex||k.dex||'DEX';
  return d+(v.labels&&v.labels.length?' '+v.labels.join('/'):'')+(v.quote&&BASE_QUOTES.indexOf(String(v.quote).toUpperCase())<0?', paired with '+v.quote:'');}
function rcDown(){return ((D.meta||{}).source_status||{}).rugcheck==='unreachable';}
function bandName(b){return b==='above'?'Above range':(b==='below'?'Below range':(b?'$'+b.replace('-','–'):''));}
function cfgUsd(v){if(v==null)return 'n/a';if(v>=1e6&&v%1e6===0)return '$'+(v/1e6)+'m';if(v>=1e3&&v%1e3===0)return '$'+(v/1e3)+'k';return usd(v);}
function median(a){if(!a.length)return null;var s=a.slice().sort(function(x,y){return x-y;}),m=s.length>>1;return s.length%2?s[m]:(s[m-1]+s[m])/2;}

/* ---------- data ---------- */
/* Inside claude.ai the page can read only its own files, so it shows the latest scheduled scan and how old it is.
   Anywhere else (GitHub Pages, a downloaded copy) it also asks DEX Screener for live prices every few seconds. */
var IN_CLAUDE=!!(window.claude&&typeof window.claude.use==='function'),SERVED=location.protocol.indexOf('http')===0;
var D,ALL=[],IN=[],WAIT=[],TRK=[],byId={},trkBy={},SLOTI={},CFG={},LABV={};
function prep(){
  ALL=D.tokens||[];CFG=D.config||{};TRK=D.tracker||[];byId={};trkBy={};SLOTI={};var GM=D.gate_meta||{};
  (D.slots||[]).forEach(function(h,i){SLOTI[h]=i;});
  TRK.forEach(function(x){trkBy[x.mint]=x;});
  LABV={};((D.lab||{}).variables||[]).forEach(function(v){LABV[v.key]=v;});
  ALL.forEach(function(k){
    /* gates arrive packed: label, group and the usual rule once in gate_meta, per token only what differs */
    k.gates=(k.gates||[]).map(function(g){if(g.label!=null)return g;var c=GM[g.id]||{};
      return {id:g.id,ok:g.ok,value:g.v,hard:g.k==='h',info:g.k==='i',group:c.group,label:c.label||g.id,rule:g.r||c.rule||''};});
    k.id=k.mint;k.t=String(k.symbol||k.mint.slice(0,5)).toUpperCase();k.n=k.name||k.t;
    k.fails=k.gates.filter(function(g){return !g.ok&&!g.info;});k.hardFails=k.fails.filter(function(g){return g.hard;});
    k.st=k.study||{};k.rk=k.st.risk||null;
    if(!k.band&&(k.state==='IN'||k.state==='WATCH'))k.band=k.cap>(CFG.MAX_MCAP||2e7)?'above':'below';
    k.cap=k.mcap||0;k.fl=k.float_cap!=null?k.float_cap:k.cap;
    k.flow1=k.demand&&k.demand.net_flow?k.demand.net_flow.h1:null;byId[k.id]=k;
    if(trkBy[k.id])k.tracker=trkBy[k.id];});      /* one object, so a live price update reaches both views */
  TRK.forEach(function(x){x.t=String(x.symbol||x.mint.slice(0,5)).toUpperCase();});
  IN=ALL.filter(function(k){return k.state==='IN'||k.state==='WATCH';});
  WAIT=ALL.filter(function(k){return k.state==='OUT'||k.state==='ENTERING';});
}

/* ---------- state ---------- */
var state={view:'map',size:'float',colour:'h1',band:'all',group:'sector',showBand:true,cvd:false,query:'',selected:null,pos:500,
  sort:{key:'mcap',dir:-1},tsort:{key:'in',dir:-1},labPop:'entries',labH:'p24',tview:'table',trange:72};
try{state.cvd=localStorage.getItem('undertow-cvd')==='1';var sp=+localStorage.getItem('undertow-pos');if([100,500,2000,10000].indexOf(sp)>=0)state.pos=sp;}catch(e){}

/* ---------- exit cost at the viewer's position size ---------- */
/* Pool model: selling a position worth a into a constant-product pool with y a side costs a/(y+a) plus the fee.
   When Jupiter's quote for the scanner's standard size showed a thinner route than the pool model, use the
   effective depth implied by that quote instead, so the estimate never looks better than the real route. */
function exitAt(k,a){
  if(!k.liq)return null;var y=k.liq/2,fee=CFG.DEFAULT_FEE_PCT!=null?CFG.DEFAULT_FEE_PCT:0.3;
  var qi=k.exit&&k.exit.quoted_impact_pct,u=(k.exit&&k.exit.usd)||500;
  if(qi!=null&&qi>0){var yq=u*100/qi-u;if(yq>0&&yq<y)y=yq;}
  return a/(y+a)*100+fee;
}
function thin(k){var c=exitAt(k,state.pos);return c!=null&&c>(CFG.MAX_EXIT_COST_PCT||10);}

/* ---------- palette from CSS tokens ---------- */
var P={};
function readPalette(){var cs=getComputedStyle(doc.documentElement);function g(n){return cs.getPropertyValue(n).trim();}
  P={bg:g('--bg'),neu:g('--p-neu'),dn:[g('--p-dn1'),g('--p-dn2'),g('--p-dn3')],up:[g('--p-up1'),g('--p-up2'),g('--p-up3')],cdn:[g('--c-dn1'),g('--c-dn2'),g('--c-dn3')],cup:[g('--c-up1'),g('--c-up2'),g('--c-up3')],
     r:[g('--r1'),g('--r2'),g('--r3'),g('--r4')],inkL:g('--ink-light'),inkD:g('--ink-dark'),band:g('--band'),warn:g('--warn')};}
function hexRgb(h){h=String(h).replace('#','').trim();if(h.length===3)h=h.split('').map(function(c){return c+c;}).join('');var n=parseInt(h,16);if(isNaN(n))return [128,128,128];return [n>>16&255,n>>8&255,n&255];}
function lum(c){function f(v){v/=255;return v<=.03928?v/12.92:Math.pow((v+.055)/1.055,2.4);}return .2126*f(c[0])+.7152*f(c[1])+.0722*f(c[2]);}
function contrast(a,b){var A=lum(a),B=lum(b);return (Math.max(A,B)+.05)/(Math.min(A,B)+.05);}
function parseRgba(s){var m=String(s).match(/rgba?\(([^)]+)\)/);if(!m)return [0,0,0,.4];var p=m[1].split(',').map(parseFloat);return [p[0],p[1],p[2],p[3]==null?1:p[3]];}
function inkFor(fill,overBand){var c=hexRgb(fill);if(overBand){var b=parseRgba(P.band),a=b[3];c=[c[0]*(1-a)+b[0]*a,c[1]*(1-a)+b[1]*a,c[2]*(1-a)+b[2]*a];}
  return contrast(c,hexRgb(P.inkL))>=contrast(c,hexRgb(P.inkD))?P.inkL:P.inkD;}

/* colour bins: price change, net buying and momentum use the validated up/down ramps; top-10 share uses the risk ramp */
var TH={h1:[.5,2,6],h24:[2,10,30],flow:[1,3,8]};
function binOf(v,w){var th=TH[w],a=Math.abs(v),b=a<th[0]?0:(a<th[1]?1:(a<th[2]?2:3));return v<0?-b:b;}
function momBin(s){if(s==null)return 0;return s<15?-3:(s<30?-2:(s<42?-1:(s<60?0:(s<72?1:(s<86?2:3)))));}
function top10Bin(v){return v==null?0:(v<10?0:(v<17?1:(v<25?2:3)));}
function flowPct(k){return k.flow1!=null&&k.liq?k.flow1/k.liq*100:null;}
function arm(b){return b<0?(state.cvd?P.cdn:P.dn):(state.cvd?P.cup:P.up);}
/* rug flags: the study's count, coloured only where its rates apply (under a day old and under $1m FDV) */
function calib(k){return !!(k.rk&&k.rk.calibrated);}
function flagBin(n){return n<=1?0:(n===2?1:(n===3?2:3));}
function flagText(r){return r?r.count+(r.complete?'':'+')+' of 6':'n/a';}
function fillFor(k){
  if(state.colour==='top10')return P.r[top10Bin(k.top10)];
  if(state.colour==='risk')return calib(k)?P.r[flagBin(k.rk.count)]:P.neu;
  var b=state.colour==='mom'?momBin(k.momentum&&k.momentum.score):(state.colour==='flow'?binOf(flowPct(k)||0,'flow'):binOf((k.chg&&k.chg[state.colour])||0,state.colour));
  return b===0?P.neu:arm(b)[Math.abs(b)-1];
}
function chgOf(k){return state.colour==='h24'?(k.chg&&k.chg.h24):(k.chg&&k.chg.h1);}
function dirFill(v){if(v==null)return P.neu;return v>=1?arm(1)[2]:arm(-1)[2];}

/* ---------- squarified treemap (Bruls, Huizing & van Wijk) ---------- */
function squarify(items,x,y,w,h){
  var out=[],total=0,i;for(i=0;i<items.length;i++)total+=items[i].value;
  if(!total||w<=0||h<=0)return out;
  var scale=w*h/total,nodes=items.map(function(it){return {key:it.key,area:it.value*scale};});
  var rect={x:x,y:y,w:w,h:h},row=[],idx=0;
  function worst(r,side){var s=0,mx=0,mn=Infinity;for(var j=0;j<r.length;j++){s+=r[j].area;if(r[j].area>mx)mx=r[j].area;if(r[j].area<mn)mn=r[j].area;}var s2=s*s,q=side*side;return Math.max(q*mx/s2,s2/(q*mn));}
  function lay(r){var s=0,j;for(j=0;j<r.length;j++)s+=r[j].area;
    if(rect.w>=rect.h){var sw=s/rect.h,cy=rect.y;for(j=0;j<r.length;j++){var hh=r[j].area/sw;out.push({key:r[j].key,x:rect.x,y:cy,w:sw,h:hh});cy+=hh;}rect={x:rect.x+sw,y:rect.y,w:rect.w-sw,h:rect.h};}
    else{var sh=s/rect.w,cx=rect.x;for(j=0;j<r.length;j++){var ww=r[j].area/sh;out.push({key:r[j].key,x:cx,y:rect.y,w:ww,h:sh});cx+=ww;}rect={x:rect.x,y:rect.y+sh,w:rect.w,h:rect.h-sh};}}
  while(idx<nodes.length){var n=nodes[idx],side=Math.min(rect.w,rect.h);
    if(!row.length||worst(row.concat([n]),side)<=worst(row,side)){row.push(n);idx++;}else{lay(row);row=[];}}
  if(row.length)lay(row);
  return out;
}

/* ---------- map ---------- */
var mapEl=$('#map'),tiles={},groupEls={},pos={};
function metric(k){return state.size==='mcap'?k.cap:(state.size==='float'?k.fl:(k.vol24||0));}
function visible(k){return state.band==='all'||k.band===state.band;}
function matches(k){var q=state.query;return !q||k.t.indexOf(q.toUpperCase())>=0||String(k.n||'').toUpperCase().indexOf(q.toUpperCase())>=0||(k.id||k.mint).toLowerCase().indexOf(q.toLowerCase())===0;}
function ageGroup(h){return h==null?'Unknown age':(h<24?'Under 1 day':(h<168?'1–7 days':(h<720?'1–4 weeks':'Over 4 weeks')));}
function groupKey(k){
  if(state.band==='all')return k.band;
  if(state.group==='age')return ageGroup(k.age_h);
  if(state.group==='mom')return k.quality&&k.quality.label&&k.quality.label!=='n/a'?k.quality.label:'Unranked';
  if(state.group==='lp')return lpName(k.launchpad);
  return k.sector||'Other';
}
function groupLabel(g,n){return (state.band==='all'?bandName(g):g)+' · '+n;}
function computeLayout(){
  var W=mapEl.clientWidth,H=mapEl.clientHeight,vis=IN.filter(visible),map={},order=[];
  vis.forEach(function(k){var g=groupKey(k);if(!map[g]){map[g]=[];order.push(g);}map[g].push(k);});
  var groups=order.map(function(g){var ks=map[g],sum=ks.reduce(function(a,k){return a+Math.max(metric(k),1);},0),n=ks.length;
    /* across bands the metric spans orders of magnitude, so each band's area follows its token count and the metric only shapes tiles inside it */
    var items=ks.map(function(k){var v=Math.max(metric(k),1);return {key:k.id,value:state.band==='all'?v/sum*n:v};}).sort(function(a,b){return b.value-a.value;});
    return {id:g,n:n,items:items,value:items.reduce(function(a,i){return a+i.value;},0)};}).sort(function(a,b){return b.value-a.value;});
  var sr=squarify(groups.map(function(g){return {key:g.id,value:g.value};}),0,0,W,H),T={},S={};
  sr.forEach(function(r){var g=groups.filter(function(x){return x.id===r.key;})[0],G=2,x=r.x+G/2,y=r.y+G/2,w=Math.max(0,r.w-G),h=Math.max(0,r.h-G),lab=(h>48&&w>56)?17:0;
    S[r.key]={x:x,y:y,w:w,h:h,lab:lab,n:g.n};squarify(g.items,x,y+lab,w,Math.max(0,h-lab)).forEach(function(t){T[t.key]=t;});});
  return {tiles:T,groups:S};
}
function buildDom(){
  mapEl.innerHTML='';tiles={};groupEls={};
  IN.forEach(function(k){var el=doc.createElement('div');el.className='tile';el.tabIndex=0;el.setAttribute('role','button');el.dataset.k=k.id;
    el.innerHTML='<div class="band"><span class="bl"></span></div><div class="lab"><span class="tk"></span><span class="sub"></span><span class="sub2"></span></div><i class="mark" aria-hidden="true"></i>';
    $('.tk',el).textContent=k.t;mapEl.appendChild(el);tiles[k.id]=el;});
}
var meas=doc.createElement('span');meas.className='tk measure';meas.setAttribute('aria-hidden','true');doc.body.appendChild(meas);
var wcache={};
function tkWidth(t,fs){if(!(t in wcache)){meas.style.fontSize='100px';meas.textContent=t;wcache[t]=meas.getBoundingClientRect().width||t.length*60;}return wcache[t]*fs/100;}
function place(animate){
  if(state.view!=='map'||!mapEl.clientWidth)return;
  var L=computeLayout();pos=L.tiles;
  mapEl.classList.toggle('no-anim',!animate);
  Object.keys(L.groups).forEach(function(g){var r=L.groups[g],el=groupEls[g];
    if(!el){el=doc.createElement('div');el.className='sector';mapEl.insertBefore(el,mapEl.firstChild);groupEls[g]=el;}
    el.textContent=groupLabel(g,r.n);el.style.left=r.x+'px';el.style.top=r.y+'px';el.style.width=r.w+'px';el.style.opacity=r.lab?'1':'0';});
  Object.keys(groupEls).forEach(function(g){if(!L.groups[g]){groupEls[g].style.opacity='0';}});
  IN.forEach(function(k){var el=tiles[k.id],r=pos[k.id];
    if(!r){el.classList.add('gone');el.setAttribute('aria-hidden','true');el.tabIndex=-1;return;}
    el.classList.remove('gone');el.removeAttribute('aria-hidden');el.tabIndex=0;
    var w=Math.max(0,r.w-1),h=Math.max(0,r.h-1);
    el.style.left=r.x+'px';el.style.top=r.y+'px';el.style.width=w+'px';el.style.height=h+'px';el.dataset.w=w;el.dataset.h=h;});
  labelAll();applyQuery();
  if(!animate){void mapEl.offsetWidth;requestAnimationFrame(function(){mapEl.classList.remove('no-anim');});}
  var sd=$('#soundings');if(sd)sd.textContent='Soundings in '+(state.size==='mcap'?'market-cap':(state.size==='float'?'float-cap':'24h-volume'))+' USD';
}
function labelAll(){IN.forEach(function(k){if(pos[k.id])labelTile(k);});}
function ctrl(k){return k.top10==null?0:k.top10/100;}
function subLine(k){
  if(state.colour==='risk')return calib(k)?flagText(k.rk)+' flags':'outside study';
  if(state.colour==='mom')return k.momentum&&k.momentum.score!=null?k.momentum.label:'n/a';
  if(state.colour==='top10')return 'top10 '+pc(k.top10,0);
  if(state.colour==='flow')return k.flow1==null?'n/a':susd(k.flow1)+'/h';
  return spct(chgOf(k));
}
function labelTile(k){
  var el=tiles[k.id],w=+el.dataset.w,h=+el.dataset.h;
  var lab=$('.lab',el),tk=$('.tk',el),sub=$('.sub',el),sub2=$('.sub2',el),bl=$('.bl',el);
  var fs=Math.min(30,Math.sqrt(w*h)/5.2),tw=tkWidth(k.t,fs);
  if(tw>w-8)fs=fs*Math.max(0,w-8)/tw;
  var show=fs>=8.5&&h>=fs*1.3+4;lab.hidden=!show;
  if(show){
    tk.style.fontSize=fs.toFixed(1)+'px';
    var sfs=Math.max(9,Math.min(15,fs*.5));sub.style.fontSize=sfs.toFixed(1)+'px';sub2.style.fontSize=Math.max(9,sfs*.86).toFixed(1)+'px';
    var t1=subLine(k);
    var t2=state.size==='float'?('float '+usd(k.fl)):(state.size==='vol'?('vol '+usd(k.vol24)):('mcap '+usd(k.cap)));
    var two=h>=fs*1.15+sfs*1.25+8&&t1.length*sfs*.6<=w-6;
    var three=two&&h>=fs*1.15+sfs*2.6+14&&t2.length*sfs*.55<=w-8;
    sub.hidden=!two;sub2.hidden=!three;sub.textContent=t1;sub2.textContent=t2;
  }
  var showBl=state.showBand&&h>=58&&w>=64&&ctrl(k)>=.08;bl.hidden=!showBl;bl.textContent='top10 '+pc(k.top10,0);
  $('.band',el).style.height=state.showBand?(ctrl(k)*100).toFixed(1)+'%':'0%';
  paintTile(k);
}
function mix(a,b,t){var x=hexRgb(a),y=hexRgb(b);return '#'+[0,1,2].map(function(i){return ('0'+Math.round(x[i]*(1-t)+y[i]*t).toString(16)).slice(-2);}).join('');}
var FADE=.62;
function paintTile(k){
  var el=tiles[k.id],fill=fillFor(k),th=thin(k),seen=th?mix(fill,P.bg,FADE):fill;el.style.backgroundColor=fill;
  el.style.color=inkFor(seen,state.showBand&&ctrl(k)>.42);
  $('.bl',el).style.color=inkFor(seen,true);
  el.classList.toggle('watch',k.state==='WATCH');
  el.classList.toggle('thin',th);
  el.setAttribute('aria-label',k.t+', '+k.n+'. '+(k.state==='WATCH'?'On watch, failing '+k.fails.map(function(g){return g.label;}).join(', ')+'. ':'Passing every gate. ')+(th?'Too thin to exit a '+usd(state.pos)+' position cheaply. ':'')+'Market cap '+usd(k.cap)+', float cap '+usd(k.fl)+', top 10 holders '+pc(k.top10,0)+'. One hour '+spct(k.chg&&k.chg.h1)+', 24 hours '+spct(k.chg&&k.chg.h24)+'.');
}
function applyQuery(){var any=!!state.query;IN.forEach(function(k){var el=tiles[k.id];el.classList.toggle('dim',any&&!matches(k));});}

/* ---------- tooltip + caption ---------- */
var tip=$('#tip'),cap=$('#caption');
function idleCaption(){cap.className='caption idle';cap.innerHTML='Hover a tile for a summary, open one for its X-ray. The dark band is the share held by the top 10 wallets, with pools, lockers, burn and exchanges removed. Faded tiles are too thin to exit your position for under '+(CFG.MAX_EXIT_COST_PCT||10)+'%.';}
function showTip(k,x,y){
  var q=k.quality||{},ec=exitAt(k,state.pos);
  tip.innerHTML='<div class="t1"><b>'+esc(k.t)+'</b><span>'+esc(k.n)+'</span></div><dl><dt>Market cap</dt><dd>'+usd(k.cap)+'</dd><dt>Float cap</dt><dd>'+usd(k.fl)+'</dd><dt>Top 10 holders</dt><dd>'+pc(k.top10)+'</dd><dt>1h / 24h</dt><dd>'+spct(k.chg&&k.chg.h1)+' / '+spct(k.chg&&k.chg.h24)+'</dd><dt>Net buying 1h</dt><dd>'+susd(k.flow1)+'</dd><dt>Traders 1h</dt><dd>'+int(k.demand&&k.demand.traders_1h)+'</dd><dt>Exit '+usd(state.pos)+'</dt><dd>'+pc(ec)+'</dd><dt>Momentum</dt><dd>'+esc(q.label||'n/a')+'</dd><dt>Launchpad</dt><dd>'+esc(lpName(k.launchpad))+'</dd><dt>Rug flags</dt><dd>'+(calib(k)?flagText(k.rk)+(k.rk.rug_rate!=null?' · '+pc(k.rk.rug_rate,0)+' rugged in study':''):'outside study')+'</dd></dl>'+(k.state==='WATCH'?'<div class="hint">Failing: '+esc(k.fails.map(function(g){return g.label;}).join(', '))+'</div>':'<div class="hint">Click for the X-ray</div>');
  tip.hidden=false;var w=tip.offsetWidth,h=tip.offsetHeight,px=Math.min(innerWidth-w-8,x+14),py=y+16+h>innerHeight?y-h-12:y+16;tip.style.left=Math.max(8,px)+'px';tip.style.top=Math.max(8,py)+'px';
  cap.className='caption';cap.innerHTML='<b>'+esc(k.t)+'</b> '+esc(k.n)+' · '+esc(lpName(k.launchpad))+' · '+bandName(k.band)+' · float '+usd(k.fl)+' of '+usd(k.cap);
}
function hideTip(){tip.hidden=true;idleCaption();}

/* ---------- gate maths ---------- */
function fmtGate(g){
  var v=g.value;if(v==null)return /not checked/.test(g.rule)?'not checked':(/warming up/.test(g.rule)?'warming up':'no data');
  switch(g.id){
    case 'mcap':case 'volume':case 'liquidity':case 'activity':return usd(v);
    case 'wash':return v.toFixed(1)+'×';
    case 'crash':return spct(v);
    case 'top10':case 'creator':case 'outflow':case 'exit':return pc(v);
    case 'lp':return pc(v,0);
    case 'linked':case 'devsell':return pc(v*100,0);
    case 'bundle':return int(v)+' alike';
    case 'traders':return int(v)+' wallets';
    case 'twoway':return usd(v)+' sold';
    case 'age':return dur(v*60);
    case 'riskflags':return int(v)+' of 6';
    case 'venue':return v==='curve'?'Bonding curve':(v==='concentrated'?'Concentrated pool':'Constant-product pool');
    case 'telegram':return int(v)+' / 100';
    case 'organic':return String(v);
    case 'flagged':return v?'Flagged':'Clear';
    case 'authority':case 'graduated':return v?'Yes':'No';
    case 'rugged':return v?'Flagged':'Clear';
    case 'extensions':return (v&&v.length)?v.join(', '):'None';
    case 'cluster':return pc(v)+' of supply';
    case 'metadata':return v?'Changeable':'Locked';
  }
  if(String(g.id).indexOf('lab:')===0&&typeof v==='number')return Math.abs(v)>=1000?usd(v):(Math.abs(v)<10?v.toFixed(2):v.toFixed(0));
  return String(v);
}
/* how close each numeric soft gate is to its line, as a fraction of its allowance (0 = on the line) */
function headroom(k){
  var out=[],cap={top10:CFG.MAX_TOP10_PCT,creator:CFG.MAX_CREATOR_PCT,linked:CFG.MAX_LINKED_HOLDER_SHARE,wash:CFG.MAX_VOL_TO_MCAP,bundle:CFG.MAX_SAME_SIZE_HOLDERS,exit:CFG.MAX_EXIT_COST_PCT,riskflags:CFG.MAX_RISK_FLAGS,cluster:CFG.MAX_CLUSTER_PCT},
      floor={volume:CFG.MIN_VOL24,activity:CFG.MIN_VOL1H,traders:CFG.MIN_TRADERS_1H,twoway:CFG.MIN_SOLD_1H};
  k.gates.forEach(function(g){if(g.info||g.value==null||typeof g.value!=='number')return;
    if(cap[g.id])out.push({g:g,room:(cap[g.id]-g.value)/cap[g.id]});
    else if(floor[g.id])out.push({g:g,room:(g.value-floor[g.id])/floor[g.id]});});
  out.sort(function(a,b){return a.room-b.room;});return out;
}
function verdict(k){
  var f=k.fails;
  if(k.state==='IN'){var h=headroom(k)[0];return 'Passing all '+k.gates.filter(function(g){return !g.info;}).length+' gates'+(k.since?' since '+ago(k.since,D.generated_at):'')+'.'+(h?' Closest to the line: '+h.g.label.toLowerCase()+' at '+fmtGate(h.g)+' ('+h.g.rule+').':'');}
  if(k.state==='WATCH')return 'On watch. Failing now: '+f.map(function(g){return g.label+' ('+fmtGate(g)+')';}).join('; ')+'. It drops out if that is still true on the next scan, about '+(CFG.SCAN_MINUTES||20)+' minutes from now.';
  if(k.state==='ENTERING')return 'Entering. It has passed '+(CFG.ENTER_SCANS-1)+' of '+CFG.ENTER_SCANS+' consecutive scans and joins the map if the next one passes too.';
  var hard=k.hardFails.length;
  if(f.length===1&&f[0].id==='age'&&f[0].value!=null){var left=Math.max(1,(CFG.MIN_AGE_MIN||60)-f[0].value);
    return 'Out for now: it reached a DEX '+dur(f[0].value*60)+' ago, and in the rug study 74% of rugs finished within the first hour. It can start entering in about '+dur(left*60)+' if nothing else fails, then needs '+CFG.ENTER_SCANS+' clean scans in a row.';}
  return (hard?'Out for a structural reason. ':'Out for now. ')+'Failing: '+f.map(function(g){return g.label+' ('+fmtGate(g)+')';}).join('; ')+'. '+(hard?'These do not usually change, so it is unlikely to come back.':'It returns on its own after '+CFG.ENTER_SCANS+' clean scans in a row.');
}
function dumpDepth(k){var y0=(k.liq||0)/2;if(!y0)return null;var sold=(k.top10||0)/100*k.cap;return 1-Math.pow(y0/(y0+sold),2);}

/* ---------- since-entry block (shared by the X-ray and the tracker-only panel) ---------- */
/* the rug study's day-one labels: rugged = closed 80% below entry before ever trading 50% above it; doubled = traded at 2x */
function dayCell(x){if(x.rug_24h===true)return 'Rugged'+(x.doubled_24h===true?', then 2×':'');if(x.doubled_24h===true)return 'Doubled';
  if(x.rug_24h===false&&x.doubled_24h===false)return 'Neither';return 'Running';}
/* the token's main numbers at entry, +1h, +6h, +24h and in its latest hourly snapshot */
var TVARS=['mc','liq','v1h','v24h','nf1h','tr1h','brd1h','hold','top10','org','lfdv'];
var TVLAB={hold:'Holders (Jupiter)',top10:'Top-10 holders’ share (Jupiter)'};
var MARKH=[0,1,6,24];
function hrs(h){if(h==null)return 'n/a';h=Math.max(0,h);if(h<72)return Math.round(h)+'h';var d=Math.floor(h/24),r=Math.round(h-d*24);return d+'d'+(r?' '+r+'h':'');}
function varsTable(x){var v=x.vt||{},ks=TVARS.filter(function(k){return v[k];});if(!ks.length)return '';
  var el=(D.generated_at-x.in_ts)/3600;
  return '<div class="tscroll"><table class="since-vars"><thead><tr><th scope="col">How its numbers moved</th><th scope="col">At entry</th><th scope="col">+1h</th><th scope="col">+6h</th><th scope="col">+24h</th><th scope="col">Latest</th></tr></thead><tbody>'
    +ks.map(function(k){return '<tr><td>'+esc(TVLAB[k]||(LABV[k]||{}).label||k)+'</td>'+v[k].map(function(val,i){
      return '<td>'+(val==null&&i<4&&MARKH[i]>el?'<span class="pend">pending</span>':esc(fmtVar(k,val)))+'</td>';}).join('')+'</tr>';}).join('')
    +'</tbody></table></div>'+(x.vt_ts?'<p class="fine">Latest is the hourly snapshot taken '+esc(when(x.vt_ts))+'. “n/a” means no snapshot landed close enough to that hour, or the source had no figure.</p>':'');}
var HORIZONS=[['1','+1h'],['6','+6h'],['24','+24h'],['168','+7d']];
function sinceBlock(x,gen){
  if(!x)return '';
  var o=x.out||{},outs=HORIZONS.map(function(h){var v=o[h[0]];var due=x.in_ts+(+h[0])*3600<=gen;return '<span>'+h[1]+' <b>'+(v!=null?xm(v):(due&&h[0] in o?'missed':'pending'))+'</b></span>';}).join('');
  return '<section class="xr-sec"><h3>Since it first entered</h3>'
    +'<table class="since"><thead><tr><th scope="col"></th><th scope="col">When</th><th scope="col">Market cap</th><th scope="col">vs entry</th></tr></thead><tbody>'
    +'<tr><td>Entered</td><td>'+esc(when(x.in_ts))+'</td><td>'+usd(x.in_mcap)+'</td><td>1.00×</td></tr>'
    +'<tr><td>ATH since entry</td><td>'+esc(when(x.ath_ts))+'</td><td>'+usd(x.ath_mcap)+'</td><td>'+xm(x.ath_x)+'</td></tr>'
    +'<tr><td>Now</td><td data-lv="now_t">'+esc(x.live_ts?ago(x.live_ts):'n/a')+'</td><td data-lv="now_mcap">'+usd(x.now_mcap)+'</td><td data-lv="now_x">'+xm(x.now_x)+'</td></tr>'
    +'</tbody></table>'
    +'<div class="outs" aria-label="Multiple of the entry price at fixed times after entry">'+outs+'<span>Day one <b>'+dayCell(x)+'</b></span></div>'
    +varsTable(x)
    +'<div class="hourly" id="hourly" data-mint="'+esc(x.mint)+'"><p class="sub-h">Hour by hour</p><p class="fine">Loading the hourly snapshots…</p></div>'
    +'<p class="fine">Worst point since entry: '+xm(x.low_x)+' ('+esc(when(x.low_ts))+'). '+(x.entries>1?'Entered '+x.entries+' times; times and multiples are from the first entry. ':'')+'ATH uses the high of each 5-minute candle after the entry, so a single large trade can set it.</p></section>';
}
/* ---------- hourly snapshots: one file per bucket of tokens, loaded when a token is opened ---------- */
var SNAPC={};
function bucketOf(m){var s=0;for(var i=0;i<m.length;i++)s+=m.charCodeAt(i);return s%(CFG.SNAP_BUCKETS||8);}
var HCOLS=[['x','× entry'],['mc','Market cap'],['liq','Liquidity'],['v1h','Volume 1h'],['nf1h','Net buying 1h'],['tr1h','Wallets 1h'],['hold','Holders'],['top10','Top 10']];
function stLabel(c,f){var GM=D.gate_meta||{},why=(f||'').split(',').filter(Boolean).map(function(g){return g==='nodata'?'no market data':(g==='scope'?'out of scope':((GM[g]||{}).label||g));});
  var m={I:'Passing',W:'On watch',E:'Entering',O:'Out',G:'No market data'}[c];if(!m)return '–';
  return esc(m)+(why.length&&c!=='G'?' <span class="nm">'+esc(why.slice(0,2).join(', ')+(why.length>2?' +'+(why.length-2):''))+'</span>':'');}
function miniLine(pts,isX){
  var W=150,Hh=34,p=3;if(pts.length<2)return '<svg class="mini" viewBox="0 0 '+W+' '+Hh+'" aria-hidden="true"></svg>';
  var h0=pts[0][0],h1=pts[pts.length-1][0],vs=pts.map(function(q){return q[1];}),lo=Math.min.apply(null,vs),hi=Math.max.apply(null,vs);
  if(isX){lo=Math.min(lo,1);hi=Math.max(hi,1);}var rg=(hi-lo)||Math.abs(hi)||1;
  var X=function(h){return p+(W-2*p)*(h-h0)/((h1-h0)||1);},Y=function(v){return p+(Hh-2*p)*(1-(v-lo)/rg);};
  var d=pts.map(function(q,i){return (i?'L':'M')+X(q[0]).toFixed(1)+' '+Y(q[1]).toFixed(1);}).join(' '),e=pts[pts.length-1];
  return '<svg class="mini" viewBox="0 0 '+W+' '+Hh+'" aria-hidden="true">'+(isX?'<line class="one" x1="'+p+'" x2="'+(W-p)+'" y1="'+Y(1).toFixed(1)+'" y2="'+Y(1).toFixed(1)+'"/>':'')+'<path d="'+d+'"/><circle cx="'+X(e[0]).toFixed(1)+'" cy="'+Y(e[1]).toFixed(1)+'" r="2.5"/></svg>';}
function hourlyHtml(s){
  var head='<p class="sub-h">Hour by hour</p>';
  if(!s||!s.r||!s.r.length)return head+'<p class="fine">No hourly snapshot yet. The first is taken at the next hourly round after entry; after that one every hour for three days and one every six hours to day '+(CFG.TRACK_DAYS||14)+'.</p>';
  var ci={};s.c.forEach(function(c,i){ci[c]=i;});var rows=s.r,back=rows.some(function(r){return r[ci.st]==null||r[ci.st]==='';});
  var sm=HCOLS.map(function(hc){var k=hc[0],pts=rows.map(function(r){return [r[ci.h],r[ci[k]]];}).filter(function(q){return q[1]!=null;}),last=pts.length?pts[pts.length-1][1]:null;
    return '<div class="sm"><div class="sm-h"><span>'+esc(hc[1])+'</span><b>'+esc(k==='x'?xm(last):fmtVar(k,last))+'</b></div>'+miniLine(pts,k==='x')+'</div>';}).join('');
  var body=rows.slice().reverse().map(function(r){return '<tr><td class="l">'+esc(when(r[ci.ts]))+'</td><td>+'+hrs(r[ci.h])+'</td><td class="l">'+stLabel(r[ci.st],r[ci.fails])+'</td>'
    +HCOLS.map(function(hc){var v=r[ci[hc[0]]];return '<td>'+(v==null?'–':esc(hc[0]==='x'?xm(v):fmtVar(hc[0],v)))+'</td>';}).join('')+'</tr>';}).join('');
  return head+'<div class="smgrid">'+sm+'</div>'
    +'<details class="hourly-all"><summary>Every snapshot ('+rows.length+')</summary><div class="tscroll"><table class="grid hourly-t"><thead><tr><th class="l" scope="col">Time</th><th scope="col">Since entry</th><th class="l" scope="col">Status</th>'
    +HCOLS.map(function(hc){return '<th scope="col">'+esc(hc[1])+'</th>';}).join('')+'</tr></thead><tbody>'+body+'</tbody></table></div></details>'
    +'<p class="fine">Lines run from entry (left) to the latest snapshot (right); the dashed line is the entry price. Holders and top-10 share come from Jupiter in every snapshot, so the series compares like with like.'+(back?' Rows without a status were rebuilt from price candles after the scanner restarted, so they carry the price only.':'')+'</p>';}
function loadHourly(mint){
  var el=$('#hourly');if(!el)return;
  if(!SERVED){el.innerHTML='<p class="sub-h">Hour by hour</p><p class="fine">Hourly snapshots load when the page is opened from its web address; this saved copy carries only the summary above.</p>';return;}
  var b=bucketOf(mint),p=SNAPC[b]||(SNAPC[b]=fetch('snap/'+b+'.json?t='+Math.floor(D.generated_at),{cache:'no-store'}).then(function(r){if(!r.ok)throw 0;return r.json();}));
  p.then(function(all){var e=$('#hourly');if(e&&e.dataset.mint===mint)e.innerHTML=hourlyHtml(all[mint]);})
   .catch(function(){delete SNAPC[b];var e=$('#hourly');if(e&&e.dataset.mint===mint)e.innerHTML='<p class="sub-h">Hour by hour</p><p class="fine">The hourly snapshots could not be loaded just now. Every snapshot is also in snapshots.csv.</p>';});
}

/* ---------- X-ray ---------- */
var xr=$('#xray'),ws=$('#workspace'),scrim=$('#scrim');
function stateChip(st){var m={IN:['in','Passing'],WATCH:['watch','On watch'],ENTERING:['entering','Entering'],OUT:['out','Out']}[st]||['out',st];return '<span class="pill '+m[0]+'">'+m[1]+'</span>';}
function qColour(l){return l==='Healthy'?arm(1)[2]:(l==='Fading'?arm(-1)[2]:(l==='Overextended'?P.warn:P.neu));}
function qChip(q){if(!q||!q.label||q.label==='n/a')return '<span class="qchip"><i style="background:'+P.neu+'"></i>Not enough data</span>';return '<span class="qchip"><i style="background:'+qColour(q.label)+'"></i>'+esc(q.label)+'</span>';}
var GROUPS=[['structure','Structure: one failure removes it at once'],['scope','In range and alive: scope, not safety'],['risk','Rug risk: two failed scans in a row remove it'],['holders','']];
function gateItem(g){
  var cls=g.info?(g.ok?'info':'warnd'):(g.ok?'ok':'bad'),ic=g.info?(g.ok?'·':'!'):(g.ok?'✓':'✕'),
      st=g.info?(g.ok?'shown, not gated':'over the line, shown but not gated'):(g.ok?'passes':'fails');
  return '<li class="gate '+cls+'"><span class="ic" aria-hidden="true">'+ic+'</span><span class="nm2">'+esc(g.label)+'<span class="sr">, '+st+'</span></span><span class="val">'+esc(fmtGate(g))+'</span><span class="rule">'+esc(g.rule)+'</span></li>';}
function gateGroups(k){return GROUPS.map(function(gr){
  var gs=k.gates.filter(function(g){return (g.group||'risk')===gr[0];});if(!gs.length)return '';
  var head=gr[1]||(gs.every(function(g){return g.info;})?'Holder structure: shown, not gated, for a fresh launchpad graduate':'Holder structure: two failed scans in a row remove it');
  return '<p class="sub-h">'+head+'</p><ul class="gates">'+gs.map(gateItem).join('')+'</ul>';}).join('');}

/* ---------- second opinion: GoPlus re-reads the structure ---------- */
function secondSec(k){
  var g=k.goplus;
  if(!g)return '<section class="xr-sec"><h3>Second opinion</h3><p class="fine">GoPlus re-checks tokens inside the screener or close to passing, every '+(CFG.GP_TTL_H||12)+' hours. This one has not been checked yet.</p></section>';
  var yn=function(v,good,bad){return v==null?'n/a':(v?bad:good);},
      au=k.gates.filter(function(x){return x.id==='authority';})[0],
      clash=au&&au.value===true&&(g.mintable||g.freezable),
      clean=!(g.traps&&g.traps.length)&&!g.mintable&&!g.freezable;
  return '<section class="xr-sec"><h3>Second opinion</h3>'
    +'<p class="fine" style="margin-top:0">'+(clean?'GoPlus agrees: no live authority and no trap.':(clash?'GoPlus still sees a live authority that the chain read shows revoked; the gate goes by the chain, which updates first.':'GoPlus flags something, and the structure gate counts it.'))+'</p>'
    +'<dl class="dl split"><dt>Mint authority</dt><dd>'+yn(g.mintable,'Revoked','Live')+'</dd><dt>Freeze authority</dt><dd>'+yn(g.freezable,'Revoked','Live')+'</dd><dt>Traps</dt><dd>'+esc(g.traps&&g.traps.length?g.traps.join(', '):'None')+'</dd><dt>Transfer fee</dt><dd>'+(g.fee_pct?pc(g.fee_pct,2):'None')+'</dd><dt>Name and image</dt><dd>'+yn(g.meta_mutable,'Locked','Changeable')+'</dd></dl>'
    +(g.meta_mutable?'<p class="fine">Changeable metadata lets the team rename the token or swap its image, a trick used to pass as another coin. Plenty of established coins keep it, so it is shown and tested in the Lab, not gated.</p>':'')
    +(g.trusted?'<p class="fine">On GoPlus’s list of trusted tokens.</p>':'')
    +'</section>';
}
/* the free routine shared on X: clusters on InsightX, score and deployer on SolSniffer, authorities on GoPlus */
function checkYourself(k){
  var w=k.deployer&&k.deployer.wallet;
  return '<div class="actions"><div class="links2"><a href="https://inx.gg" target="_blank" rel="noopener noreferrer">InsightX clusters</a><a href="https://solsniffer.com/sniftokens" target="_blank" rel="noopener noreferrer">SolSniffer score</a><a href="https://solsniffer.com/snifwallets" target="_blank" rel="noopener noreferrer">SolSniffer wallets</a><a href="https://gopluslabs.io/token-security" target="_blank" rel="noopener noreferrer">GoPlus</a></div>'
    +(w?'<button class="btn" type="button" id="xr-dev" data-w="'+esc(w)+'">Copy deployer wallet</button>':'')+'</div>'
    +'<p class="fine">To check it yourself, paste the address into these sites, and the deployer wallet into SolSniffer wallets. Never connect a wallet to a scanner.</p>';
}

/* ---------- the rug study's panel ---------- */
function riskTone(n){return n<=1?'ok':(n<=3?'warn':'bad');}
function lfdvZone(v){return v==null?'':(v<(CFG.LFDV_RED||.9)?'red':(v<(CFG.LFDV_GREEN||1)?'amber':'green'));}
function flagVal(f){var v=f.value;if(v==null)return 'no data';
  switch(f.id){case 'lfdv':return v.toFixed(2)+'×';case 'wallets':case 'holders':return int(v);case 'sells':case 'top5':return pc(v*100,0);case 'young':return dur(v*60);}
  return String(v);}
function studySec(k){
  var s=k.st||{},r=s.risk,fl=s.flags||[],sw=s.swarm||{},v=s.lfdv,kind=k.venue&&k.venue.kind,chip,line;
  if(!r&&v==null)return '';
  if(r&&r.calibrated){
    chip='<span class="rchip '+riskTone(r.count)+'"><i></i>'+flagText(r)+' red flags</span>';
    line=r.rug_rate!=null?'In the study’s out-of-sample week, coins with '+r.count+' flag'+(r.count===1?'':'s')+' rugged <b>'+pc(r.rug_rate,1)+'</b> of the time and doubled <b>'+pc(r.doubled_rate,1)+'</b>.'+(k.age_h!=null&&k.age_h>=1?' Its coins were mostly minutes old; past the first hour the age flag cannot fire and the holder flag nearly always does, so read the rate as a guide.':'')
      :r.known+' of the 6 flags could be checked, so no rate is shown yet. The others need the last 10 minutes of trades, which the scanner fetches for the coins closest to passing.';
  }else{
    chip='<span class="rchip na"><i></i>Outside the study</span>';
    line='The study measured coins under a day old and under '+cfgUsd(CFG.CALIBRATED_MAX_FDV||1e6)+' FDV, mostly minutes after graduation. This one is '+((k.age_h!=null&&k.age_h>=(CFG.CALIBRATED_MAX_AGE_H||24))?'older':'larger')+', so no rate applies and its flags are for reference; the wallet and buyer flags are only fetched inside the study’s range.';
  }
  var zone=lfdvZone(v),at=v==null?0:Math.min(v,1.5)/1.5*100;
  var dial=v==null?'<p class="fine">No liquidity or FDV figure for this pool.</p>'
    :'<div class="dial" role="img" aria-label="Liquidity is '+v.toFixed(2)+' times FDV, '+(zone==='red'?'below 0.9':(zone==='amber'?'between 0.9 and 1.0':'1.0 or above'))+'"><span class="z red"></span><span class="z amber"></span><span class="z green"></span><i style="left:'+at.toFixed(1)+'%"></i></div><div class="dial-ax" aria-hidden="true"><span class="a0">0</span><span class="a9">0.9</span><span class="a10">1.0</span><span class="a15">1.5+</span></div>';
  var wc=s.worst_case!=null?'If every holder outside the pool sold, the price would fall about <b>'+pc(s.worst_case*100,s.worst_case>=.995?1:0)+'</b>.'
    :(kind==='concentrated'?'No worst case shown: the formula needs a constant-product pool, and this one is concentrated.':'');
  var thinNote=v!=null&&v<(CFG.LFDV_THIN||.2)&&calib(k)?'<p class="fine">Under 0.2: a thin pool under a big valuation. In the study, coins under 0.2 rugged 54% of the time; most of them were not pump.fun coins.</p>':'';
  var rows=fl.map(function(f){var c=f.fired==null?'unk':(f.fired?'bad':'ok'),ic=f.fired==null?'?':(f.fired?'!':'✓');
    return '<li class="gate '+c+'"><span class="ic" aria-hidden="true">'+ic+'</span><span class="nm2">'+esc(f.label)+'<span class="sr">, '+(f.fired==null?'not known':(f.fired?'fires':'does not fire'))+'</span></span><span class="val">'+esc(flagVal(f))+(f.id==='wallets'&&sw.wallets_est?' (est.)':'')+'</span></li>';}).join('');
  return '<section class="xr-sec"><h3>Rug-risk study</h3>'
    +'<p class="rline">'+chip+'</p><p class="rtext">'+line+'</p>'
    +'<p class="sub-h">Dump headroom: liquidity ÷ FDV'+(v!=null?' <b class="dialv '+zone+'">'+v.toFixed(2)+'×</b>':'')+'</p>'+dial
    +(wc?'<p class="rtext">'+wc+'</p>':'')+thinNote
    +'<p class="sub-h">The six red flags</p><ul class="gates">'+rows+'</ul>'
    +'<p class="fine">A pump.fun coin lands on PumpSwap at about 0.41, and after that the ratio moves with its price, so almost every pump.fun coin in this screener’s range sits below 0.9. Read the dial as how much dumping is still possible, not as a verdict. Sells use the last 15 minutes of trades'+(sw.sell_share_15m==null?'; no trade list was fetched for this coin, so Jupiter’s last hour stands in':'')+'.</p></section>';
}
function sparkSvg(k){
  var a=k.spark||[];if(a.length<3)return '<p class="fine">Not enough history yet. The scanner records one point each run, so this fills in over the first day.</p>';
  var W=320,H=84,pad=4,mn=Math.min.apply(null,a),mx=Math.max.apply(null,a),rg=(mx-mn)||1,n=a.length;
  var pts=a.map(function(v,i){return [pad+(W-2*pad)*i/(n-1),pad+(H-2*pad)*(1-(v-mn)/rg)];});
  var d=pts.map(function(p,i){return (i?'L':'M')+p[0].toFixed(1)+' '+p[1].toFixed(1);}).join(' ');
  var last=pts[n-1];
  return '<svg class="spark2" viewBox="0 0 '+W+' '+(H+14)+'" role="img" aria-label="Market cap over the last 24 hours, from '+usd(a[0])+' to '+usd(a[n-1])+'"><path class="area" d="'+d+' L'+last[0]+' '+H+' L'+pts[0][0]+' '+H+'Z"/><path class="line" d="'+d+'"/><circle class="end" cx="'+last[0].toFixed(1)+'" cy="'+last[1].toFixed(1)+'" r="3.5"/><text class="ax" x="'+pad+'" y="'+(H+11)+'">24h ago '+usd(a[0])+'</text><text class="ax" x="'+(W-pad)+'" y="'+(H+11)+'" text-anchor="end">now '+usd(a[n-1])+'</text></svg>';
}
function demandSec(k){
  var dm=k.demand||{},nf=dm.net_flow||{},hc=dm.holder_change||{},org=k.organic||{};
  if(!k.demand)return '';
  return '<section class="xr-sec"><h3>Demand</h3><dl class="dl split">'
    +'<dt>Net buying, 1h</dt><dd>'+susd(nf.h1)+'</dd><dt>Net buying, 6h</dt><dd>'+susd(nf.h6)+'</dd><dt>Net buying, 24h</dt><dd>'+susd(nf.h24)+'</dd>'
    +'<dt>Wallets trading, 1h</dt><dd>'+int(dm.traders_1h)+'</dd><dt>Of those, net buyers</dt><dd>'+(dm.breadth_1h==null?'n/a':pc(dm.breadth_1h*100,0))+'</dd>'
    +'<dt>Holders, change 1h / 24h</dt><dd>'+spct(hc.h1)+' / '+spct(hc.h24)+'</dd>'
    +'<dt>Organic score (Jupiter)</dt><dd>'+(org.score==null?'n/a':Math.round(org.score)+' · '+esc(org.label))+'</dd>'
    +'<dt>Organic buyers, 24h</dt><dd>'+int(dm.organic_buyers_24h)+'</dd></dl>'
    +'<p class="fine">Net buying is buy volume minus sell volume. Jupiter’s organic score estimates how much trading comes from real users rather than bots; a “low” label fails the organic gate.</p></section>';
}
function renderXray(k){
  var dd=dumpDepth(k),ec=k.exit||{};
  var tgh='';
  if(k.tg){
    if(k.tg.members){var r=k.tg.bot_risk;tgh='<div class="figs"><div class="fig"><div class="k">Members</div><div class="v">'+int(k.tg.members)+'</div><div class="s">'+(k.tg.online!=null?int(k.tg.online)+' online ('+pc(k.tg.online/k.tg.members*100)+')':'online count hidden')+'</div></div><div class="fig"><div class="k">Growth</div><div class="v">'+(k.tg.growth_h!=null?spct(k.tg.growth_h*100)+'/h':'n/a')+'</div><div class="s">'+(k.tg.growth_h!=null?'since the first scan':'needs two scans an hour apart')+'</div></div></div>'
      +'<div class="meter"><span>Bot-risk</span><span class="trk"><i style="width:'+Math.min(100,r||0)+'%"></i></span><span class="num">'+(r==null?'n/a':r)+'</span></div>'
      +(k.tg.why&&k.tg.why.length?'<ul class="reasons">'+k.tg.why.map(function(w){return '<li>'+esc(w)+'</li>';}).join('')+'</ul>':'<p class="fine">No bot signals fired. That is not proof of an organic crowd: the checks use only public counts.</p>');}
    else tgh='<p class="fine">Group @'+esc(k.tg.handle)+' found. It is checked only for tokens that pass the other gates, to stay inside free rate limits.</p>';
  }else tgh='<p class="fine">No Telegram link on DEX Screener or GeckoTerminal.</p>';
  var xh=k.x&&k.x.handle?'<dl class="dl"><dt>Handle</dt><dd><a href="https://x.com/'+encodeURIComponent(k.x.handle)+'" target="_blank" rel="noopener noreferrer">@'+esc(k.x.handle)+'</a></dd><dt>Reused by</dt><dd>'+(k.x.shared_with?k.x.shared_with+' other token'+(k.x.shared_with>1?'s':'')+' in the scan':'no other token in the scan')+'</dd></dl><p class="fine">Follower counts and post activity need the paid X API, so they are left out of the free build.</p>':'<p class="fine">No X account linked.</p>';
  var mom=k.momentum&&k.momentum.parts&&Object.keys(k.momentum.parts).length?Object.keys(k.momentum.parts).map(function(n){var v=k.momentum.parts[n];return '<div class="meter"><span>'+esc(n)+'</span><span class="trk"><i style="width:'+v+'%"></i></span><span class="num">'+v+'</span></div>';}).join(''):'<p class="fine">Not enough tokens clear the hard gates yet to rank momentum.</p>';
  var q=k.quality||{};
  var qline='<p style="margin:0;display:flex;gap:10px;align-items:center;flex-wrap:wrap">'+qChip(q)+(k.momentum&&k.momentum.score!=null?'<span class="xr-meta">score <b>'+k.momentum.score+'</b> · '+esc(k.momentum.label)+'</span>':'')+'</p>'
    +(q.why&&q.why.length?'<ul class="reasons">'+q.why.map(function(w){return '<li>'+esc(w)+'</li>';}).join('')+'</ul>':'')
    +'<dl class="dl split"><dt>Above its 6h average</dt><dd>'+(q.extension==null?'n/a':spct(q.extension*100))+'</dd><dt>Below its 24h high</dt><dd>'+(q.drawdown_24h==null?'n/a':spct(q.drawdown_24h*100))+'</dd><dt>Higher low than the hour before</dt><dd>'+(q.higher_lows==null?'n/a':(q.higher_lows?'Yes':'No'))+'</dd></dl>';
  var dep=k.deployer||{};
  var hold=(k.top10!=null?'<div class="hold" role="img" aria-label="Top 10 holders hold '+pc(k.top10)+' of supply"><span style="width:'+Math.min(100,k.top10)+'%;background:var(--r3)"></span><span style="flex:1;background:var(--p-neu)"></span></div><div class="hold-key"><span><i style="background:var(--r3)"></i>Top 10 holders '+pc(k.top10)+'</span><span><i style="background:var(--p-neu)"></i>Everyone else '+pc(100-k.top10)+'</span></div>':'<p class="fine">Holder data not loaded yet.</p>')
    +'<dl class="dl split"><dt>Deployer holds</dt><dd>'+pc(k.creator_pct)+'</dd><dt>Deployer’s launches</dt><dd>'+(dep.launches==null?'n/a':int(dep.launches)+(dep.graduated!=null?' ('+int(dep.graduated)+' graduated, '+pc(dep.graduated/Math.max(dep.launches,1)*100)+')':''))+'</dd><dt>Deployer sold, 24h</dt><dd>'+(k.dev_drop==null?'warming up':pc(k.dev_drop*100,0))+'</dd><dt>Top holders’ outflow, 6h</dt><dd>'+(k.top_outflow_6h==null?'warming up':pc(k.top_outflow_6h))+'</dd><dt>Transfer-linked wallets</dt><dd>'+(k.linked_share==null?'n/a':pc(k.linked_share*100,0)+' of holders')+'</dd><dt>Largest wallet cluster</dt><dd>'+(k.cluster?pc(k.cluster.pct)+' of supply'+(k.cluster.n?', '+int(k.cluster.n)+' wallets':''):'n/a')+'</dd><dt>Near-identical balances</dt><dd>'+(k.same_size==null?'n/a':k.same_size)+'</dd></dl>'
    +(k.cluster&&k.cluster.n>=500?'<p class="fine">A cluster this large can also be an exchange’s or an airdrop’s wallets, which link thousands of holders without one owner. Open the bubble map before reading it as one team.</p>':'')
    +(dep.launches>20?'<p class="fine">A deployer with many launches is often a launch service or bot rather than one team; it is shown, not gated.</p>':'')
    +(k.launchpad&&calib(k)&&!CFG.HOLDER_GATES_FOR_LAUNCHPADS?'<p class="fine">Shown, not gated, for a launchpad graduate this young and small: in the rug study, top-10, bundler and insider shares did not predict rugs. Bundlers spread supply over many wallets, so the top 10 can look healthy.</p>':'')
    +(rcDown()?'<p class="fine">RugCheck could not be reached this scan, so top-10 and deployer shares come from Jupiter, and wallet links and identical balances were not checked.</p>':'');
  var exitMax=Math.max(1000,Math.min(Math.round((k.liq||2000)/2),50000));
  xr.innerHTML='<div class="xr"><div class="xr-head"><div class="xr-top"><span class="xr-tk">'+esc(k.t)+'</span>'+stateChip(k.state)+(k.band?'<span class="chip sm">'+bandName(k.band)+'</span>':'')+'<span class="chip sm">'+esc(lpName(k.launchpad))+'</span></div>'
    +'<div class="xr-meta">'+esc(k.n)+'</div><div class="xr-ca mono">'+esc(short(k.id))+' · '+esc(venueName(k))+' · on a DEX for '+ageH(k.age_h)+'</div>'
    +'<button class="xr-close" type="button" aria-label="Close X-ray" id="xr-close">✕</button></div>'
    +'<p class="verdict">'+esc(verdict(k))+'</p>'
    +'<div class="figs"><div class="fig"><div class="k">Market cap</div><div class="v" data-lv="cap">'+usd(k.cap)+'</div><div class="s">float '+usd(k.fl)+'</div></div><div class="fig"><div class="k">24h volume</div><div class="v" data-lv="vol24">'+usd(k.vol24)+'</div><div class="s">'+(k.cap?(k.vol24/k.cap).toFixed(1)+'× market cap':'')+'</div></div><div class="fig"><div class="k">Liquidity</div><div class="v" data-lv="liq">'+usd(k.liq)+'</div><div class="s">'+(k.cap?pc(k.liq/k.cap*100)+' of market cap':'')+'</div></div><div class="fig"><div class="k">Holders</div><div class="v">'+int(k.holders)+'</div><div class="s">1h '+spct(k.chg&&k.chg.h1)+' · 24h '+spct(k.chg&&k.chg.h24)+'</div></div></div>'
    +sinceBlock(k.tracker,D.generated_at)
    +studySec(k)
    +'<section class="xr-sec"><h3>Gates</h3>'+gateGroups(k)+'</section>'
    +secondSec(k)
    +'<section class="xr-sec" id="xr-crowd" hidden></section>'
    +demandSec(k)
    +'<section class="xr-sec"><h3>Momentum</h3>'+qline+mom+'<p class="fine">Bars are percentile ranks against the other tokens that clear the hard gates. Healthy means rising on net buying with at least half the traders accumulating; overextended means more than '+pc((CFG.OVEREXTENDED||.5)*100,0)+' above its 6h average, or rising while net selling.</p></section>'
    +'<section class="xr-sec"><h3>Who holds it</h3>'+hold+'</section>'
    +'<section class="xr-sec"><h3>Exit check</h3>'
    +'<p style="margin:0;font-size:13px">Selling a <b>'+usd(ec.usd||500)+'</b> position costs about <b>'+pc(ec.cost_pct)+'</b> '+(ec.from_quote?'(Jupiter quote via '+esc((ec.venues||[]).join(', ')||'its best route')+', plus fees)':'(pool model'+(ec.quoted_impact_pct!=null?'; Jupiter quoted '+pc(ec.quoted_impact_pct,2)+' impact':'')+')')+'.</p>'
    +(dd==null?'':'<p style="margin:0;font-size:13px">If the top 10 holders all sold, the price would fall <b>'+pc(dd*100,0)+'</b>.</p>')
    +(k.liq?'<div class="exit-l"><span>Your position</span><output id="ex-out" class="mono"></output></div><input type="range" id="ex-range" min="100" max="'+exitMax+'" step="100" value="'+Math.min(state.pos,exitMax)+'" aria-label="Position size in US dollars"><div class="exit-res" id="ex-res"></div>':'')
    +'<p class="fine">The estimate takes the worse of a constant-product pool model and Jupiter’s quoted route. Quotes for the same token move by a point or two minute to minute.</p></section>'
    +'<section class="xr-sec"><h3>Telegram</h3>'+tgh+'</section>'
    +'<section class="xr-sec"><h3>X</h3>'+xh+'</section>'
    +'<section class="xr-sec"><h3>Market cap, 24h</h3>'+sparkSvg(k)+'</section>'
    +'<div class="actions"><div class="links2"><a href="https://dexscreener.com/solana/'+k.id+'" target="_blank" rel="noopener noreferrer">DEX Screener</a><a href="https://rugcheck.xyz/tokens/'+k.id+'" target="_blank" rel="noopener noreferrer">RugCheck</a><a href="https://www.geckoterminal.com/solana/tokens/'+k.id+'" target="_blank" rel="noopener noreferrer">GeckoTerminal</a><a href="https://solscan.io/token/'+k.id+'" target="_blank" rel="noopener noreferrer">Solscan</a></div><button class="btn" type="button" id="xr-copy">Copy address</button></div>'
    +checkYourself(k)+'</div>';
  wireXray(k.id);
  emit('xray',k);
  var dw=$('#xr-dev');if(dw)dw.onclick=function(){copyText(dw.getAttribute('data-w'),'Deployer wallet copied');};
  if(k.tracker)loadHourly(k.id);
  var rg=$('#ex-range');if(rg){var upd=function(){var a=+rg.value,s=exitAt(k,a);$('#ex-out').textContent=usd(a);$('#ex-res').innerHTML='<p>Selling <b>'+usd(a)+'</b> now costs about <b>'+pc(s,s<1?2:1)+'</b>'+(s>(CFG.MAX_EXIT_COST_PCT||10)?', more than the '+pc(CFG.MAX_EXIT_COST_PCT||10,0)+' the exit gate allows':'')+'.</p>';};rg.oninput=upd;upd();}
}
/* tracked tokens that have left the scan's ranges have no full record; show what the tracker knows */
function renderTrackerOnly(x){
  xr.innerHTML='<div class="xr"><div class="xr-head"><div class="xr-top"><span class="xr-tk">'+esc(x.t)+'</span>'+stateChip(x.state)+'</div><div class="xr-meta">'+esc(x.name||'')+'</div><div class="xr-ca mono">'+esc(short(x.mint))+'</div><button class="xr-close" type="button" aria-label="Close X-ray" id="xr-close">✕</button></div>'
    +'<p class="verdict">No longer inside the scan’s ranges'+(x.last_exit_ts?'; it left the screener '+esc(ago(x.last_exit_ts,D.generated_at)):'')+'. The tracker keeps following its price for '+(CFG.TRACK_DAYS||14)+' days after first entry.</p>'
    +sinceBlock(x,D.generated_at)
    +'<div class="actions"><div class="links2"><a href="https://dexscreener.com/solana/'+x.mint+'" target="_blank" rel="noopener noreferrer">DEX Screener</a><a href="https://rugcheck.xyz/tokens/'+x.mint+'" target="_blank" rel="noopener noreferrer">RugCheck</a></div><button class="btn" type="button" id="xr-copy">Copy address</button></div></div>';
  wireXray(x.mint);
  loadHourly(x.mint);
}
function wireXray(id){$('#xr-close').onclick=closeX;$('#xr-copy').onclick=function(){copyText(id,'Address copied');};}
function copyText(t,msg){try{navigator.clipboard.writeText(t).then(function(){toast(msg);},function(){toast('Copy failed');});}catch(e){toast('Copy failed');}}
var toastT;function toast(m){var t=$('#toast');t.textContent=m;t.hidden=false;clearTimeout(toastT);toastT=setTimeout(function(){t.hidden=true;},1800);}
function openX(id){
  var k=byId[id],x=null;
  if(!k){x=TRK.filter(function(t){return t.mint===id;})[0];if(!x)return;}
  state.selected=id;if(k)renderXray(k);else renderTrackerOnly(x);
  xr.hidden=false;ws.classList.add('open');if(!wide())scrim.hidden=false;
  IN.forEach(function(j){tiles[j.id].classList.toggle('sel',j.id===id);});$$('#tablewrap tbody tr, #waitwrap tbody tr, #trackwrap tbody tr').forEach(function(r){r.classList.toggle('sel',r.dataset.k===id);});
  if(!wide()){xr.scrollTop=0;var c=$('#xr-close');if(c)c.focus();}else if(state.view==='map')place(false);
}
function closeX(){state.selected=null;xr.hidden=true;ws.classList.remove('open');scrim.hidden=true;IN.forEach(function(j){tiles[j.id].classList.remove('sel');});$$('tr.sel').forEach(function(r){r.classList.remove('sel');});if(state.view==='map')place(false);}

/* ---------- table ---------- */
var COLS=[['t','Ticker',1,function(k){return '<span class="tkr">'+esc(k.t)+'</span> <span class="nm">'+esc(k.n)+'</span>';},function(k){return k.t;}],
 ['band','Band',1,function(k){return bandName(k.band);},function(k){return k.cap;}],
 ['lp','Launchpad',1,function(k){return esc(lpName(k.launchpad));},function(k){return lpName(k.launchpad);}],
 ['mcap','Mkt cap',0,function(k){return usd(k.cap);},function(k){return k.cap;}],
 ['float','Float cap',0,function(k){return usd(k.fl);},function(k){return k.fl;}],
 ['liq','Liquidity',0,function(k){return usd(k.liq);},function(k){return k.liq;}],
 ['h1','1h',0,function(k){return spct(k.chg&&k.chg.h1);},function(k){return k.chg&&k.chg.h1;}],
 ['h24','24h',0,function(k){return spct(k.chg&&k.chg.h24);},function(k){return k.chg&&k.chg.h24;}],
 ['flow','Net buying 1h',0,function(k){return susd(k.flow1);},function(k){return k.flow1;}],
 ['tr','Traders 1h',0,function(k){return int(k.demand&&k.demand.traders_1h);},function(k){return k.demand&&k.demand.traders_1h;}],
 ['top10','Top 10',0,function(k){return pc(k.top10);},function(k){return k.top10;}],
 ['rf','Rug flags',0,function(k){return calib(k)?flagText(k.rk):'–';},function(k){return calib(k)?k.rk.count:null;}],
 ['lf','Liq ÷ FDV',0,function(k){return k.st.lfdv!=null?k.st.lfdv.toFixed(2)+'×':'–';},function(k){return k.st.lfdv;}],
 ['org','Organic',0,function(k){return k.organic&&k.organic.score!=null?Math.round(k.organic.score):'–';},function(k){return k.organic&&k.organic.score;}],
 ['exit','Exit @ your size',0,function(k){return pc(exitAt(k,state.pos));},function(k){return exitAt(k,state.pos);}],
 ['q','Momentum',1,function(k){return qChip(k.quality);},function(k){return k.momentum&&k.momentum.score;}],
 ['tg','TG members',0,function(k){return k.tg&&k.tg.members?int(k.tg.members):'–';},function(k){return k.tg&&k.tg.members;}],
 ['st','Status',1,function(k){return stateChip(k.state);},function(k){return k.state;}]];
function sorter(cols,s){var c=cols.filter(function(x){return x[0]===s.key;})[0]||cols[0],d=s.dir;
  return function(a,b){var x=c[4](a),y=c[4](b);if(x==null&&y==null)return 0;if(x==null)return 1;if(y==null)return -1;return (x<y?-1:(x>y?1:0))*d;};}
function headRow(cols,s){return '<tr>'+cols.map(function(c){var on=s.key===c[0];return '<th class="'+(c[2]?'l':'')+'" aria-sort="'+(on?(s.dir>0?'ascending':'descending'):'none')+'"><button type="button" data-sort="'+c[0]+'">'+c[1]+(on?(s.dir>0?' ▲':' ▼'):'')+'</button></th>';}).join('')+'</tr>';}
function wireRows(sel){$$(sel+' tbody tr').forEach(function(r){r.onclick=function(){openX(r.dataset.k);};r.onkeydown=function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();openX(r.dataset.k);}};});}
function wireSort(sel,s,render,textKeys){$$(sel+' th button').forEach(function(b){b.onclick=function(){var key=b.dataset.sort;if(s.key===key)s.dir*=-1;else{s.key=key;s.dir=textKeys.indexOf(key)>=0?1:-1;}render();};});}
function renderTable(){
  var list=IN.filter(visible).filter(matches).sort(sorter(COLS,state.sort)),w=$('#tablewrap');
  if(!list.length){w.innerHTML='<p class="empty">No tokens in this band pass every gate right now.</p>';return;}
  w.innerHTML='<table class="grid"><caption class="sr">Tokens that pass every gate. Sortable columns.</caption><thead>'+headRow(COLS,state.sort)+'</thead><tbody>'
    +list.map(function(k){return '<tr data-k="'+k.id+'" tabindex="0"'+(state.selected===k.id?' class="sel"':'')+'>'+COLS.map(function(c){return '<td class="'+(c[2]?'l':'')+'">'+c[3](k)+'</td>';}).join('')+'</tr>';}).join('')+'</tbody></table>';
  wireSort('#tablewrap',state.sort,renderTable,['t','band','lp','st']);wireRows('#tablewrap');
}

/* ---------- tracker ---------- */
/* The path glyph is a dumbbell on a log axis (0.1x to 10x): a tick at the entry (1x), a bar from the worst point
   to the ATH since entry, a tick at the ATH and a dot at the current multiple, coloured by direction. */
function pathSvg(x){
  var W=150,Hh=22,lo=Math.log(0.1),hi=Math.log(10);
  function X(v){v=Math.max(0.1,Math.min(10,v||1));return 4+(W-8)*(Math.log(v)-lo)/(hi-lo);}
  var a=X(x.low_x),b=X(x.ath_x),n=x.now_x!=null?X(x.now_x):null,one=X(1);
  return '<svg class="path" viewBox="0 0 '+W+' '+Hh+'" role="img" aria-label="Worst '+xm(x.low_x)+', high '+xm(x.ath_x)+', now '+xm(x.now_x)+' of the entry price"><line class="ax" x1="4" x2="'+(W-4)+'" y1="11" y2="11"/><line class="rng" x1="'+a.toFixed(1)+'" x2="'+Math.max(b,a+0.5).toFixed(1)+'" y1="11" y2="11"/><line class="one" x1="'+one.toFixed(1)+'" x2="'+one.toFixed(1)+'" y1="3" y2="19"/><line class="ath" x1="'+b.toFixed(1)+'" x2="'+b.toFixed(1)+'" y1="5" y2="17"/>'+(n!=null?'<circle class="now" cx="'+n.toFixed(1)+'" cy="11" r="5" fill="'+dirFill(x.now_x)+'"/>':'')+'</svg>';
}
var TCOLS=[['t','Ticker',1,function(x){return '<span class="tkr">'+esc(x.t)+'</span>';},function(x){return x.t;}],
 ['in','Entered',1,function(x){return esc(when(x.in_ts));},function(x){return x.in_ts;}],
 ['inm','At entry',0,function(x){return usd(x.in_mcap);},function(x){return x.in_mcap;}],
 ['nowm','Now',0,function(x){return usd(x.now_mcap);},function(x){return x.now_mcap;}],
 ['nowx','Now vs entry',0,function(x){return xm(x.now_x);},function(x){return x.now_x;}],
 ['athm','ATH since entry',0,function(x){return usd(x.ath_mcap);},function(x){return x.ath_mcap;}],
 ['atht','ATH at',1,function(x){return esc(when(x.ath_ts));},function(x){return x.ath_ts;}],
 ['athx','ATH vs entry',0,function(x){return xm(x.ath_x);},function(x){return x.ath_x;}],
 ['path','Worst · now · ATH',1,function(x){return pathSvg(x);},function(x){return x.now_x;}],
 ['r24','+24h',0,function(x){var v=(x.out||{})['24'];return v!=null?xm(v):'–';},function(x){return (x.out||{})['24'];}],
 ['d1','Day one',1,function(x){return dayCell(x);},function(x){return x.rug_24h===true?2:(x.doubled_24h===true?1:(x.rug_24h===false&&x.doubled_24h===false?0:null));}],
 ['st','Status',1,function(x){return stateChip(x.state);},function(x){return x.state;}]];
function kpi(label,value,sub){return '<div class="kpi"><div class="k">'+label+'</div><div class="v">'+value+'</div><div class="s">'+sub+'</div></div>';}
function renderTracker(){
  var w=$('#trackwrap'),list=TRK.filter(matches);
  if(!TRK.length){w.innerHTML='<p class="empty">Nothing tracked yet. A token joins the tracker the first time it passes every gate.</p>';return;}
  var nx=TRK.map(function(x){return x.now_x;}).filter(function(v){return v!=null;}),n=TRK.length;
  var share=function(f){var c=TRK.filter(f).length;return Math.round(c/n*100)+'%';};
  var d24=TRK.filter(function(x){return (x.out||{})['24']!=null;}).map(function(x){return x.out['24'];});
  var first=Math.min.apply(null,TRK.map(function(x){return x.in_ts;}));
  var full=TRK.filter(function(x){return x.in_ts+86700<=D.generated_at;}),day=function(key){return {n:full.length,c:full.filter(function(x){return x[key]===true;}).length};},rg=day('rug_24h'),db=day('doubled_24h');
  var head='<div class="trk-head"><div class="kpis">'
    +kpi('Tracked',int(n),'tokens that passed every gate')
    +kpi('Median now vs entry',xm(median(nx)),'across all '+n)
    +kpi('Above entry now',share(function(x){return x.now_x>=1;}),'of '+n)
    +kpi('Reached 2× after entry',share(function(x){return x.ath_x>=2;}),'at any point')
    +kpi('Fell 50% or more',share(function(x){return x.low_x!=null&&x.low_x<=.5;}),'at any point')
    +kpi('Rugged on day one',rg.n?Math.round(rg.c/rg.n*100)+'%':'n/a',rg.n?rg.c+' of '+rg.n+' with a full first day, study definition':'first full day ends '+when(first+86400))
    +kpi('Doubled on day one',db.n?Math.round(db.c/db.n*100)+'%':'n/a',db.n?db.c+' of '+db.n+' with a full first day':'first full day ends '+when(first+86400))
    +kpi('Median at +24h',d24.length?xm(median(d24)):'n/a',d24.length?'of '+d24.length+' with 24h of history':'first values from '+when(first+86400))
    +'</div><p class="trk-note">Entry is the first time a token passed every gate; market caps at entry and now come from DEX Screener, and the ATH since entry from GeckoTerminal’s 5-minute candles. Tracking started '+esc(when(first))+'. Every tracked token is also snapshotted once an hour, in or out of the screener; “Hour by hour” compares them. '+(n<30?'With '+n+' tokens these figures are anecdotes, not a hit rate. ':'')+'Read “reached 2×” with care: it counts the best moment, which few people sell into. Day one uses the rug study’s labels: rugged means the price closed 80% below entry before it ever traded 50% above it, within 24 hours; doubled means it traded at 2× entry in that time.'+(SERVED?' '+dlBtn('tracker.csv','Download the full table as CSV')+', with the gate values each token had when it entered.':'')+'</p>'
    +'<div class="lab-ctl"><span class="ctl-pair"><span class="ctl-label">Show</span>'+labSeg('tview',[['table','Entry vs now'],['time','Hour by hour']],state.tview)+'</span>'
    +(state.tview==='time'?'<span class="ctl-pair"><span class="ctl-label">Span</span>'+labSeg('trange',[['24','First day'],['72','First 3 days'],['336','14 days']],String(tspan()))+'</span>':'')+'</div></div>';
  if(state.tview==='time'){
    w.innerHTML=head+overTime(list);
    $$('.ot-chart .tok',w).forEach(function(g){g.onclick=function(){openX(g.dataset.k);};g.onkeydown=function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();openX(g.dataset.k);}};});
    $$('.heat tbody tr',w).forEach(function(r){r.onclick=function(){openX(r.dataset.k);};r.onkeydown=function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();openX(r.dataset.k);}};});
  }else{
    list.sort(sorter(TCOLS,state.tsort));
    w.innerHTML=head+'<div class="tscroll"><table class="grid"><caption class="sr">Every token that has entered the screener, with its market cap at entry, now, and at its high since entry.</caption><thead>'+headRow(TCOLS,state.tsort)+'</thead><tbody>'
      +list.map(function(x){return '<tr data-k="'+x.mint+'" tabindex="0"'+(state.selected===x.mint?' class="sel"':'')+'>'+TCOLS.map(function(c){return '<td class="'+(c[2]?'l':'')+'">'+c[3](x)+'</td>';}).join('')+'</tr>';}).join('')+'</tbody></table></div>';
    wireSort('#trackwrap',state.tsort,renderTracker,['t','st']);wireRows('#trackwrap');
  }
  $$('[data-tview]',w).forEach(function(b){b.onclick=function(){state.tview=b.dataset.tview;renderTracker();};});
  $$('[data-trange]',w).forEach(function(b){b.onclick=function(){state.trange=+b.dataset.trange;state.trangeSet=true;renderTracker();};});
}
/* ---------- tracker over time: each token's multiple of its entry price, hour by hour since entry ---------- */
var TMARKS=[1,3,6,12,24,48,72,168];
/* the chart spans the oldest token's history unless the viewer picked a span */
function tspan(){if(state.trangeSet)return state.trange;var old=Math.max.apply(null,TRK.map(function(x){return (D.generated_at-x.in_ts)/3600;}).concat([0]));return old<=26?24:(old<=74?72:336);}
function hxAt(x,h){var i=SLOTI[h];if(i==null||!x.hx||i>=x.hx.length)return null;return x.hx[i];}
function reached(x,h){return x.in_ts+h*3600<=D.generated_at;}
function quant(s,q){if(!s.length)return null;var p=(s.length-1)*q,i=Math.floor(p),f=p-i;return i+1<s.length?s[i]+(s[i+1]-s[i])*f:s[i];}
function xBin(v){return v<.5?-3:(v<.8?-2:(v<.95?-1:(v<=1.05?0:(v<1.25?1:(v<2?2:3)))));}
function xFill(v){var b=xBin(v);return b===0?P.neu:arm(b)[Math.abs(b)-1];}
function xCell(v){if(v==null)return '<td class="hx na">–</td>';var f=xFill(v);return '<td class="hx" style="background:'+f+';color:'+inkFor(f)+'">'+xm(v)+'</td>';}
function markStats(list){return TMARKS.map(function(h){var vs=list.filter(function(x){return reached(x,h);}).map(function(x){return hxAt(x,h);}).filter(function(v){return v!=null;}).sort(function(a,b){return a-b;});
  return {h:h,n:vs.length,up:vs.length?vs.filter(function(v){return v>=1;}).length/vs.length:null,med:quant(vs,.5),q1:quant(vs,.25),q3:quant(vs,.75)};});}
function overTimeChart(list){
  var cw=($('#trackwrap').clientWidth||788)-28,W=Math.max(320,Math.min(1400,cw)),Hh=W<560?250:(W<900?300:340),l=44,r=14,t=14,b=30,lo=Math.log(0.1),hi=Math.log(10),span=tspan(),narrow=W<560;
  var X=function(h){return l+(W-l-r)*h/span;},Y=function(v){v=Math.max(0.1,Math.min(10,v));return t+(Hh-t-b)*(1-(Math.log(v)-lo)/(hi-lo));};
  var slots=(D.slots||[]).filter(function(h){return h<=span;}),pathOf=function(a){return a.map(function(q,i){return (i?'L':'M')+X(q[0]).toFixed(1)+' '+Y(q[1]).toFixed(1);}).join(' ');};
  var lines=list.map(function(x){var pts=[];slots.forEach(function(h){var v=hxAt(x,h);if(v!=null)pts.push([h,v]);});
    if(pts.length<2)return '';var d=pathOf(pts);
    return '<g class="tok" data-k="'+x.mint+'" tabindex="0" role="button" aria-label="'+esc(x.t)+', now '+xm(x.now_x)+' of entry: open its X-ray"><title>'+esc(x.t)+' · now '+xm(x.now_x)+' of entry</title><path class="hit" d="'+d+'"/><path class="tl" d="'+d+'"/></g>';}).join('');
  var med=[],q1=[],q3=[];slots.forEach(function(h){var vs=list.map(function(x){return hxAt(x,h);}).filter(function(v){return v!=null;}).sort(function(a,b){return a-b;});
    if(vs.length>=5){med.push([h,quant(vs,.5)]);q1.push([h,quant(vs,.25)]);q3.push([h,quant(vs,.75)]);}});
  var band=q1.length>1?'<path class="iqr" d="'+pathOf(q3)+' L'+q1.slice().reverse().map(function(q){return X(q[0]).toFixed(1)+' '+Y(q[1]).toFixed(1);}).join(' L')+' Z"/>':'';
  var ys=[0.1,0.25,0.5,1,2,4,10].map(function(v){return '<line class="gl" x1="'+l+'" x2="'+(W-r)+'" y1="'+Y(v).toFixed(1)+'" y2="'+Y(v).toFixed(1)+'"/><text x="'+(l-6)+'" y="'+(Y(v)+4).toFixed(1)+'" text-anchor="end">'+v+'×</text>';}).join('');
  var xt=(span<=24?(narrow?[0,12,24]:[0,3,6,12,18,24]):(span<=72?(narrow?[0,24,48,72]:[0,6,12,24,48,72]):(narrow?[0,72,168,336]:[0,24,72,168,336]))).map(function(h){return '<text x="'+X(h).toFixed(1)+'" y="'+(Hh-b+18)+'" text-anchor="'+(h===0?'start':(h===span?'end':'middle'))+'">'+(h===0?'entry':'+'+hrs(h))+'</text>';}).join('');
  var me=med.length?med[med.length-1]:null;
  return '<svg class="ot-chart" viewBox="0 0 '+W+' '+Hh+'" role="img" aria-label="Each tracked token’s price as a multiple of its entry price, by hours since entry, with the median">'
    +ys+band+'<g class="toks">'+lines+'</g><line class="one" x1="'+l+'" x2="'+(W-r)+'" y1="'+Y(1).toFixed(1)+'" y2="'+Y(1).toFixed(1)+'"/>'
    +(med.length>1?'<path class="med" d="'+pathOf(med)+'"/>':'')
    +(me?'<text class="medl" x="'+Math.min(W-r,X(me[0])+6).toFixed(1)+'" y="'+(Y(me[1])+(me[1]>=1?-10:18)).toFixed(1)+'" text-anchor="'+(X(me[0])>W-120?'end':'start')+'">median '+xm(me[1])+'</text>':'')
    +xt+'<text class="onel" x="'+(W-r)+'" y="'+(Y(1)-6).toFixed(1)+'" text-anchor="end">entry price</text></svg>';
}
function overTime(list){
  var ms=markStats(list),rows=list.slice().sort(function(a,b){return b.in_ts-a.in_ts;});
  var rose=list.filter(function(x){return x.ath_x>1.05&&x.ath_ts;}),pk=median(rose.map(function(x){return (x.ath_ts-x.in_ts)/3600;}));
  var stats='<div class="tscroll"><table class="grid lab ot-marks"><thead><tr><th class="l" scope="col">Hours since entry</th>'+ms.map(function(m){return '<th scope="col">+'+hrs(m.h)+'</th>';}).join('')+'</tr></thead><tbody>'
    +'<tr><td class="l">Tokens that got this far</td>'+ms.map(function(m){return '<td>'+int(m.n)+'</td>';}).join('')+'</tr>'
    +'<tr><td class="l">Above their entry price</td>'+ms.map(function(m){return '<td>'+(m.up==null?'–':pc(m.up*100,0))+'</td>';}).join('')+'</tr>'
    +'<tr><td class="l">Median multiple</td>'+ms.map(function(m){return '<td>'+(m.med==null?'–':xm(m.med))+'</td>';}).join('')+'</tr>'
    +'<tr><td class="l">Middle half</td>'+ms.map(function(m){return '<td>'+(m.n>=4?xm(m.q1)+'–'+xm(m.q3):'–')+'</td>';}).join('')+'</tr></tbody></table></div>';
  var grid='<div class="tscroll"><table class="grid heat"><caption class="sr">Each tracked token’s price as a multiple of its entry price at fixed hours after entry.</caption><thead><tr><th class="l" scope="col">Ticker</th><th class="l" scope="col">Entered</th>'
    +TMARKS.map(function(h){return '<th scope="col">+'+hrs(h)+'</th>';}).join('')+'<th scope="col">Now</th><th scope="col">Peak</th><th scope="col">Peak came</th></tr></thead><tbody>'
    +rows.map(function(x){return '<tr data-k="'+x.mint+'" tabindex="0"'+(state.selected===x.mint?' class="sel"':'')+'><td class="l"><span class="tkr">'+esc(x.t)+'</span></td><td class="l">'+esc(when(x.in_ts))+'</td>'
      +TMARKS.map(function(h){return reached(x,h)?xCell(hxAt(x,h)):'<td class="hx pend" title="Not reached yet">·</td>';}).join('')
      +xCell(x.now_x)+'<td>'+xm(x.ath_x)+'</td><td>'+(x.ath_ts&&x.ath_x>1.001?((x.ath_ts-x.in_ts)<3600?'within 1h':'+'+hrs((x.ath_ts-x.in_ts)/3600)):'at entry')+'</td></tr>';}).join('')
    +'</tbody></table></div>';
  return '<section class="lab-sec"><h3>Every tracked token, hour by hour since entry</h3>'+overTimeChart(list)
    +'<p class="trk-note">Each grey line is one token’s price as a multiple of its entry price, on a log scale; the blue line is the median and the shaded band the middle half, wherever at least five tokens have a value. Hover a line for its ticker; click it for the X-ray, which has every snapshot of that token. The values are the scanner’s hourly snapshots of every tracked token, in or out of the screener.</p>'
    +stats+'<p class="trk-note">'+(rose.length?'<b>'+rose.length+'</b> of '+list.length+' rose at least 5% above entry at some point, and the median peak came <b>'+hrs(pk)+'</b> after entry. ':'None has risen 5% above its entry yet. ')+'The peak is what an exit rule has to catch; the Lab’s exit rules test take-profit and stop pairs against these paths.</p></section><section class="lab-sec"><h3>Side by side</h3>'+grid
    +'<p class="fine">A dot means the token has not reached that hour yet; a dash means no snapshot landed near it. Colours run from red (well below entry) through grey (within 5% of it) to green (well above). Peak is the ATH since entry, from 5-minute candles, and how long after entry it came. '+(SERVED?dlBtn('snapshots.csv','Download every hourly snapshot as CSV')+'.':'')+'</p></section>';
}

/* ---------- waiting room ---------- */
function renderWait(){
  var list=WAIT.filter(function(k){return k.band&&(state.band==='all'||k.band===state.band);}).filter(matches);
  list.sort(function(a,b){return (a.state==='ENTERING'?0:1)-(b.state==='ENTERING'?0:1)||a.fails.length-b.fails.length||b.cap-a.cap;});
  var near=list.filter(function(k){return k.fails.length===1&&!k.hardFails.length;}).length;
  var w=$('#waitwrap');
  var intro='<p class="wait-intro"><b>'+list.length+' tokens</b> are in range but not on the map. <b>'+near+'</b> fail a single soft gate and can re-enter by themselves; the rest are blocked by several gates or by a structural one. Each needs '+CFG.ENTER_SCANS+' clean scans in a row to come back. Click a row for the full checklist.</p>';
  if(!list.length){w.innerHTML=intro;return;}
  w.innerHTML=intro+'<table class="grid"><caption class="sr">Tokens waiting outside the map, with the gates blocking each.</caption><thead><tr><th class="l" scope="col">Ticker</th><th class="l" scope="col">Band</th><th class="l" scope="col">Status</th><th class="l" scope="col">Blocked by</th><th scope="col">Mkt cap</th><th scope="col">24h vol</th></tr></thead><tbody>'
    +list.slice(0,150).map(function(k){return '<tr data-k="'+k.id+'" tabindex="0"><td class="l"><span class="tkr">'+esc(k.t)+'</span></td><td class="l">'+bandName(k.band)+'</td><td class="l">'+stateChip(k.state)+(k.state==='ENTERING'?' <span class="nm">'+(CFG.ENTER_SCANS-1)+'/'+CFG.ENTER_SCANS+'</span>':'')+'</td><td class="l"><div class="blk">'+(k.fails.length?k.fails.map(function(g){return '<span class="'+(g.hard?'hard':'')+'" title="'+esc(g.rule)+'">'+esc(g.label)+': '+esc(fmtGate(g))+'</span>';}).join(''):'<span>All gates pass; waiting for the next scan</span>')+'</div></td><td>'+usd(k.cap)+'</td><td>'+usd(k.vol24)+'</td></tr>';}).join('')+'</tbody></table>';
  wireRows('#waitwrap');
}

/* ---------- Lab: which variables separate tokens that rose from those that fell ---------- */
var VERD={works:['works','Works'],helps:['works','Helps'],hurts:['hurts','Hurts'],weak:['weak','Weak'],none:['none','No signal'],collecting:['coll','Collecting']};
var VRANK={works:0,helps:0,hurts:1,weak:2,none:3,collecting:4};
var LPOPS=[['entries','Entries','each token’s first entry into the screener'],['passing','Passing every gate','one observation a day per token while it passed every gate'],['all','All candidates','one observation a day per token in your ranges, passing or not']];
var LHOR=[['p6','+6h'],['p24','+24h']];
function vchip(v){var m=VERD[v]||VERD.collecting;return '<span class="vchip '+m[0]+'">'+m[1]+'</span>';}
function fmtVar(key,v){if(v==null)return 'n/a';var u=(LABV[key]||{}).unit;
  if(u==='usd')return usd(v);if(u==='pct')return pc(v);if(u==='chg')return spct(v);if(u==='share')return pc(v*100,0);if(u==='frac')return spct(v*100);
  if(u==='x')return v.toFixed(2)+'×';if(u==='ratio')return Math.abs(v)<100?v.toFixed(2):int(v);if(u==='h')return ageH(v);return int(v);}
function pts(v){return v==null?'n/a':(v>=0?'+':MINUS)+Math.abs(Math.round(v*100))+' pts';}
function fifthsSvg(fs,base){
  if(!fs||!fs.length)return '';var W=70,Hh=22,bw=W/fs.length;
  var bars=fs.map(function(f,i){var h=Math.max(1,(f.up||0)*Hh);return '<rect x="'+(i*bw+1).toFixed(1)+'" y="'+(Hh-h).toFixed(1)+'" width="'+(bw-2).toFixed(1)+'" height="'+h.toFixed(1)+'" rx="1"/>';}).join('');
  var bl=base!=null?'<line class="base" x1="0" x2="'+W+'" y1="'+(Hh-base*Hh).toFixed(1)+'" y2="'+(Hh-base*Hh).toFixed(1)+'"/>':'';
  return '<svg class="fifths" viewBox="0 0 '+W+' '+Hh+'" width="'+W+'" height="'+Hh+'" role="img" aria-label="Share that rose in each fifth, lowest value first: '+fs.map(function(f){return pc((f.up||0)*100,0);}).join(', ')+'">'+bars+bl+'</svg>';}
function labSeg(kind,opts,cur){return '<div class="seg" role="group">'+opts.map(function(o){return '<button type="button" data-'+kind+'="'+o[0]+'" aria-pressed="'+(o[0]===cur)+'">'+o[1]+'</button>';}).join('')+'</div>';}
/* ---------- the weekly gate review ---------- */
var REVW={protects:['works','Protects'],'would protect':['works','Would protect'],costs:['hurts','Costs'],'would cost':['hurts','Would cost'],
  'no effect':['weak','No effect'],unclear:['none','Unclear'],collecting:['coll','Collecting']};
var RSTAT={gate:'Gating',shown:'Dropped',testing:'Testing',promoted:'Promoted to gate',retired:'Retired'};
function rvChip(v){var m=REVW[v]||REVW.collecting;return '<span class="vchip '+m[0]+'">'+m[1]+'</span>';}
function rvSide(s){return !s||!s.n_rug?'–':pc(s.rug*100,0)+' <span class="nm">of '+int(s.n_rug)+'</span>';}
function rvUp(s){return !s||!s.n_rug||s.up50==null?'–':pc(s.up50*100,0);}
function ymd(ts){return ts?new Date(ts*1000).toISOString().slice(0,10):'–';}
function reviewSec(){
  var R=D.review;
  if(!R)return '<section class="lab-sec"><h3>Weekly gate review</h3><p class="trk-note">The first review runs with the next scan.</p></section>';
  var gs=(R.gates||[]).filter(function(g){return g.reviewable||g.status==='shown';}).sort(function(a,b){return (a.status==='shown')-(b.status==='shown')||String(a.label).localeCompare(b.label);});
  var fixed=(R.gates||[]).filter(function(g){return !g.reviewable&&g.status!=='shown';});
  var cs=(R.candidates||[]).filter(function(c){return c.status!=='retired';}).sort(function(a,b){return (a.status!=='promoted')-(b.status!=='promoted')||String(a.label).localeCompare(b.label);});
  var gone=(R.candidates||[]).filter(function(c){return c.status==='retired';});
  var row=function(label,status,l,why){return '<tr><td class="l">'+esc(label)+'</td><td class="l">'+esc(RSTAT[status]||status)+'</td><td>'+rvSide(l&&l.blocked)+'</td><td>'+rvSide(l&&l.passed)+'</td><td>'+rvUp(l&&l.blocked)+' / '+rvUp(l&&l.passed)+'</td><td class="l">'+rvChip(l&&l.verdict)+'</td><td class="l rv-why">'+esc(why||'')+'</td></tr>';};
  return '<section class="lab-sec"><h3>Weekly gate review</h3>'
    +'<p class="trk-note">Every '+((CFG.REVIEW||{}).every_days||7)+' days the scanner checks each gate against what happened next. Last review '+esc(ymd(R.last_review))+', next '+esc(ymd(R.next_review))+'. A gate is judged on the coins it alone blocked: did they rug more often than coins that passed everything? Two reviews in a row of “no effect” or “costs” drop a rug-risk or holder gate (it stays visible and can come back); structure and scope gates never change automatically. Candidate rules are judged on coins that passed every gate: two reviews in a row of “would protect” promote one to a gate, and two of “no effect” or “would cost” retire it and make room for the next variable to test. Rules on the crowd’s calls, votes and tags are tested the same way but never gate.</p>'
    +'<div class="tscroll"><table class="grid lab"><thead><tr><th class="l">Gate</th><th class="l">Status</th><th>Rugged: blocked only by it</th><th>Rugged: passed everything</th><th>+50%: blocked / passed</th><th class="l">Verdict</th><th class="l">Why</th></tr></thead><tbody>'
    +gs.map(function(g){return row(g.label,g.status,g.last,g.status==='shown'?g.reason:(g.last&&g.last.verdict==='collecting'?g.last.why:''));}).join('')
    +'</tbody></table></div>'
    +(fixed.length?'<p class="fine">Not changed automatically: '+esc(fixed.map(function(g){return g.label;}).join(', '))+'.</p>':'')
    +'<h3 class="sub-h">Candidate rules under test</h3><div class="tscroll"><table class="grid lab"><thead><tr><th class="l">Rule</th><th class="l">Status</th><th>Rugged: it would remove</th><th>Rugged: it would keep</th><th>+50%: removed / kept</th><th class="l">Verdict</th><th class="l">Since</th></tr></thead><tbody>'
    +cs.map(function(c){var l=c.last||{};return '<tr><td class="l">'+esc(c.label)+'</td><td class="l">'+esc(RSTAT[c.status]||c.status)+'</td><td>'+rvSide(l.blocked)+'</td><td>'+rvSide(l.passed)+'</td><td>'+rvUp(l.blocked)+' / '+rvUp(l.passed)+'</td><td class="l">'+rvChip(l.verdict)+'</td><td class="l">'+esc(ymd(c.since||c.added))+(c.source&&c.source!=='pool'?' <span class="nm">'+esc(c.source)+'</span>':'')+(c.gateable===false?' <span class="nm">tested only: never gates</span>':'')+'</td></tr>';}).join('')
    +'</tbody></table></div>'
    +((R.log||[]).length?'<h3 class="sub-h">Changes</h3><ul class="rv-log">'+R.log.map(function(e){return '<li><b>'+esc(ymd(e.ts))+'</b> '+esc(e.what)+': '+esc(e.label)+'. '+esc(e.reason)+'</li>';}).join('')+'</ul>':'')
    +(gone.length?'<details class="rv-gone"><summary>Retired rules ('+gone.length+')</summary><ul class="rv-log">'+gone.map(function(c){return '<li><b>'+esc(c.label)+'</b>: '+esc(c.reason||'')+'</li>';}).join('')+'</ul></details>':'')
    +'</section>';
}
function renderLab(){
  var w=$('#labwrap'),L=D.lab;
  if(!L||!L.pops){w.innerHTML='<p class="empty">The Lab starts recording with the next scan.</p>';return;}
  var RL={};(L.rules||[]).forEach(function(r){RL[r.id]=r.label;});
  var cfg=L.cfg||{},stt=L.stats||{},pop=(L.pops[state.labPop]||{})[state.labH]||{},b=pop.base||{},ab=((L.pops.all||{})[state.labH]||{}).base||{};
  var hl=state.labH==='p24'?'+24h':'+6h',popl=LPOPS.filter(function(p){return p[0]===state.labPop;})[0];
  var first=stt.since,due=first?first+(state.labH==='p24'?86400:21600)+(cfg.tol||2400):null;
  var head='<div class="trk-head"><div class="kpis">'
    +kpi('Observations',int(stt.rows),(stt.since?'since '+esc(when(stt.since)):'none yet')+' · '+int(stt.entries)+' entries')
    +kpi('With a '+hl+' result',int(b.n_out),'of '+int(b.n)+' in this view')
    +kpi('Rose by '+hl,b.up==null?'n/a':pc(b.up*100,0),state.labPop==='all'?'all candidates':'all candidates: '+(ab.up==null?'n/a':pc(ab.up*100,0)))
    +kpi('Median multiple',b.med==null?'n/a':xm(b.med),state.labPop==='all'?'middle half '+xm(b.p25)+' to '+xm(b.p75):'all candidates: '+(ab.med==null?'n/a':xm(ab.med)))
    +kpi('Rugged on day one',b.rug==null?'n/a':pc(b.rug*100,0),b.n_rug?b.n_rug+' with a settled first day':'settles within a day')
    +'</div><div class="lab-ctl"><span class="ctl-label">View</span>'+labSeg('labpop',LPOPS,state.labPop)+'<span class="ctl-label">Outcome</span>'+labSeg('labh',LHOR,state.labH)+'</div>'
    +'<p class="trk-note"><b>'+esc(popl[1])+'</b>: '+esc(popl[2])+'. Each observation records about 45 variables and what happened next: the price multiple at +1h, +6h and +24h, and the high and low within a day. '
    +(b.n_out<(cfg.min_n||60)?'<b>Collecting.</b> Verdicts appear once '+(cfg.min_n||60)+' observations in this view have a '+hl+' result'+(b.n_out?' ('+b.n_out+' so far)':(due&&due>D.generated_at?'; the first arrive around '+esc(when(due)):''))+'. Until then the numbers below are early reads, not findings. ':'')
    +(SERVED?dlBtn('observations.csv','Download every observation as CSV')+'.':'')+'</p></div>';
  var rules=(pop.rules||[]).slice().sort(function(x,y){return (VRANK[x.verdict]-VRANK[y.verdict])||((y.lift_out||-9)-(x.lift_out||-9));});
  var rt='<section class="lab-sec"><h3>Shadow rules</h3><p class="trk-note">Candidate gates recorded for every observation but never applied. “Kept” is the share of this view that would pass. A rule helps when the share that rose is clearly higher with it than without (a two-proportion test at '+(cfg.z||2.5)+' standard errors) and by at least '+Math.round((cfg.min_lift||.08)*100)+' points in both the earlier and the later half of the data. At '+(cfg.min_n||60)+' observations only differences of about 25 points can show; a 10-point one needs about 400.</p>'
    +'<div class="tscroll"><table class="grid lab"><thead><tr><th class="l">Rule</th><th>Kept</th><th>Rose: passing</th><th>Rose: failing</th><th>Median: passing</th><th>Rugs: passing</th><th>Lift, earlier / later half</th><th class="l">Verdict</th></tr></thead><tbody>'
    +rules.map(function(r){var p=r.pass||{},f=r.fail||{},kp=r.keep_all!=null?r.keep_all:r.keep;return '<tr><td class="l">'+esc(RL[r.id]||r.label||r.id)+'</td><td>'+(kp==null?'–':pc(kp*100,0))+'</td><td>'+(p.up==null?'–':pc(p.up*100,0)+' <span class="nm">of '+p.n+'</span>')+'</td><td>'+(f.up==null?'–':pc(f.up*100,0)+' <span class="nm">of '+f.n+'</span>')+'</td><td>'+(p.med==null?'–':xm(p.med))+'</td><td>'+(p.rug==null?'–':pc(p.rug*100,0))+'</td><td>'+(r.lift_in==null&&r.lift_out==null?'–':pts(r.lift_in)+' / '+pts(r.lift_out))+'</td><td class="l">'+vchip(r.verdict)+'</td></tr>';}).join('')
    +'</tbody></table></div></section>';
  var noOut=!b.n_out,vars=(pop.vars||[]).filter(function(v){return v.n>0;}).sort(function(x,y){return (VRANK[x.verdict]-VRANK[y.verdict])||(Math.abs((y.auc||.5)-.5)-Math.abs((x.auc||.5)-.5));});
  var vt=noOut?'<section class="lab-sec"><h3>Variables</h3><p class="trk-note">Recorded for every observation, and scored here once outcomes arrive: '+esc((L.variables||[]).map(function(v){return v.label;}).join(', '))+'.</p></section>':'<section class="lab-sec"><h3>Variables</h3><p class="trk-note">AUC is the chance that a token that rose had a higher value than one that fell: 0.5 is a coin flip, above 0.5 higher values did better, below 0.5 lower values did. The bars show the share that rose in each fifth of the variable, lowest values first, against the overall share (line). The suggested line is the single threshold that gave the most risers in the earlier half of the data while keeping at least '+Math.round((cfg.min_keep||.3)*100)+'%; the later half shows whether it held.</p>'
    +'<div class="tscroll"><table class="grid lab"><thead><tr><th class="l">Variable</th><th>n</th><th>AUC</th><th class="l">Rose, by fifth</th><th class="l">Suggested line</th><th>Later half: with line / all</th><th class="l">Verdict</th></tr></thead><tbody>'
    +vars.map(function(v){var c=v.cut,lab=(LABV[v.key]||{}).label||v.key,ci=v.se!=null?1.96*v.se:null;
      return '<tr><td class="l">'+esc(lab)+'</td><td>'+int(v.n)+'</td><td>'+(v.auc==null?'–':v.auc.toFixed(2)+(ci!=null?' <span class="nm">±'+ci.toFixed(2)+'</span>':''))+'</td><td class="l">'+fifthsSvg(v.fifths,b.up)+'</td>'
        +'<td class="l">'+(c?(c.op==='>='?'≥ ':'≤ ')+esc(fmtVar(v.key,c.at))+' <span class="nm">keeps '+pc(c.keep_in*100,0)+'</span>':'–')+'</td>'
        +'<td>'+(c&&c.up_out!=null?pc(c.up_out*100,0)+' / '+pc(c.base_out*100,0):'–')+'</td><td class="l">'+vchip(v.verdict)+'</td></tr>';}).join('')
    +'</tbody></table></div><p class="fine">Verdicts: works means a clear rank signal (AUC at least '+(cfg.min_auc_gap||.08)+' from 0.5 and more than '+(cfg.z||2.5)+' standard errors from it, stricter than the usual 1.96 because dozens of variables are tested at once) and a line that lifted the share that rose by '+Math.round((cfg.min_lift||.08)*100)+' points in both halves; weak means one of the two; collecting means fewer than '+(cfg.min_n||60)+' observations, or under '+(cfg.min_test||30)+' in the later half. A token observed many times counts once a day, so busy tokens do not dominate. None of this is a forecast: it measures what separated risers from fallers in the data so far.</p></section>';
  var ex=(L.pops[state.labPop]||{}).exits,et='';
  if(ex){var hold=ex.hold,top=(ex.rules||[]).slice(0,8),pct=function(v){return v==null?'–':spct(v*100);};
    et='<section class="lab-sec"><h3>Exit rules</h3><p class="trk-note">What a position opened at each '+(state.labPop==='entries'?'entry':'observation')+' would have returned with a take-profit and a stop, against holding for 24 hours. Whether every tracked token ends above its entry depends on the exit as much as the entry: most tokens trade above their entry price at some point before they fall.</p>'
      +(ex.n?'<div class="tscroll"><table class="grid lab"><thead><tr><th class="l">Take profit</th><th class="l">Stop</th><th>Positions</th><th>Ended up</th><th>Average</th><th>Median</th></tr></thead><tbody>'
      +(hold?'<tr class="holdrow"><td class="l">Hold 24h</td><td class="l">none</td><td>'+int(hold.n)+'</td><td>'+pc(hold.win*100,0)+'</td><td>'+pct(hold.mean)+'</td><td>'+pct(hold.med)+'</td></tr>':'')
      +top.map(function(e){return '<tr><td class="l">+'+e.tp+'%</td><td class="l">'+(e.sl?MINUS+e.sl+'%':'none')+'</td><td>'+int(e.n)+'</td><td>'+pc(e.win*100,0)+'</td><td>'+pct(e.mean)+'</td><td>'+pct(e.med)+'</td></tr>';}).join('')
      +'</tbody></table></div><p class="fine">The best eight of '+(ex.rules||[]).length+' pairs by average return. Prices are read once a run, so a spike between runs is missed and a stop fills at the next price, which can be worse; fees and slippage are not deducted. With few positions the ranking will move a lot.</p>'
      :'<p class="empty">No position has a full day behind it yet.</p>')+'</section>';}
  w.innerHTML=head+reviewSec()+rt+et+vt;
  $$('[data-labpop]',w).forEach(function(x){x.onclick=function(){state.labPop=x.dataset.labpop;renderLab();};});
  $$('[data-labh]',w).forEach(function(x){x.onclick=function(){state.labH=x.dataset.labh;renderLab();};});
}

/* ---------- legend ---------- */
function renderLegend(){
  var lg=$('#legend'),neg=function(a){return a.slice().reverse();};
  function ramp(title,labels,fills){return '<div class="lg-group"><div class="lg-title">'+title+'</div><div class="ramp">'+fills.map(function(f,i){return '<span><i style="background:'+f+'"></i>'+labels[i]+'</span>';}).join('')+'</div></div>';}
  var html='',div=neg(arm(-1)).concat([P.neu],arm(1));
  if(state.colour==='top10'){html+=ramp('Top-10 share of supply',['under 10%','10–17%','17–25%','over 25%'],P.r);}
  else if(state.colour==='risk'){html+=ramp('Rug-study red flags, for coins under a day old and under '+cfgUsd(CFG.CALIBRATED_MAX_FDV||1e6)+' FDV',['0–1','2','3','4 or more'],P.r)
    +'<div class="lg-group"><div class="lg-title">Grey</div><div class="lg-keys"><span class="lg-key"><span class="key"></span>Outside what the study measured</span></div></div>';}
  else if(state.colour==='mom'){html+=ramp('Momentum score',['under 15','15–30','30–42','42–60','60–72','72–86','86+'],div);}
  else{var w=state.colour,th=TH[w],lab=['−'+th[2]+'%+','−'+th[1]+'%','−'+th[0]+'%','flat','+'+th[0]+'%','+'+th[1]+'%','+'+th[2]+'%+'];
    html+=ramp(w==='flow'?'Net buying in the last hour, as a share of liquidity':(w==='h1'?'1 hour':'24 hours')+' price change',lab,div);}
  html+='<div class="lg-group"><div class="lg-title">Marks</div><div class="lg-keys"><span class="lg-key"><span class="key band-k"></span>Top-10 share (dark band)</span><span class="lg-key"><span class="key" style="box-shadow:inset 0 0 0 2px var(--warn)"></span>On watch: failing a soft gate</span><span class="lg-key"><span class="key thin-k"></span>Faded: exiting '+usd(state.pos)+' costs over '+pc(CFG.MAX_EXIT_COST_PCT||10,0)+'</span></div></div>';
  html+='<label class="switch lg-cvd"><input type="checkbox" id="opt-cvd"'+(state.cvd?' checked':'')+'><span>Colour-blind safe palette (blue and orange)</span></label>';
  lg.innerHTML=html;
  $('#opt-cvd').onchange=function(e){state.cvd=e.target.checked;try{localStorage.setItem('undertow-cvd',state.cvd?'1':'0');}catch(x){}renderLegend();refresh(false);};
}

/* ---------- summary, moves, notes ---------- */
function renderTape(){
  var m=D.meta||{},nIn=IN.length,en=ALL.filter(function(k){return k.state==='ENTERING';}).length;
  $('#tape').innerHTML='<span><b>'+nIn+'</b> tokens pass every gate</span><span><b>'+en+'</b> entering</span><span><b>'+(ALL.length-nIn-en)+'</b> in range but out</span><span><b>'+TRK.length+'</b> tracked since entry</span><span>Scan covered <b>'+int(m.universe)+'</b> tokens across launchpads and DEXes, <b>'+int(m.priced)+'</b> priced, <b>'+int(m.candidates)+'</b> inside the ranges</span>'
    +(rcDown()?'<span class="warn-t">RugCheck unreachable this scan: holders from Jupiter, wallet-link and bundle checks skipped</span>':'');
  renderStamp();
}
function renderBandSeg(){
  var seg=$('#bandseg'),counts=(D.meta&&D.meta.counts_in_by_band)||{};
  seg.innerHTML='<button type="button" data-band="all" aria-pressed="'+(state.band==='all')+'">All ('+IN.length+')</button>'+(D.bands||[]).map(function(b){return '<button type="button" data-band="'+b+'" aria-pressed="'+(state.band===b)+'">'+bandName(b)+' ('+(counts[b]||0)+')</button>';}).join('');
  $$('button',seg).forEach(function(b){b.onclick=function(){state.band=b.dataset.band;renderBandSeg();refresh(true);};});
}
function renderMoves(){
  var tr=(D.transitions||[]).slice(0,12),l=$('#mv-list');
  $('#mv-note').textContent=tr.length?'Tokens that crossed a gate in the most recent scans. A token must pass '+CFG.ENTER_SCANS+' scans in a row to enter and fail '+CFG.EXIT_SCANS+' to leave, except for structural failures, which remove it at once.':'No moves recorded yet. Moves appear after the second scan.';
  l.innerHTML=tr.map(function(t){var why=(t.reasons||[])[0]||'';return '<li class="mv"><button type="button" data-k="'+t.mint+'"><span class="top"><b>'+esc(t.symbol||short(t.mint))+'</b><span>'+esc(t.from)+' → '+esc(t.to)+'</span><span>'+ago(t.ts,D.generated_at)+'</span></span><span class="why">'+esc(why.length>150?why.slice(0,148)+'…':why)+'</span></button></li>';}).join('');
  $$('button',l).forEach(function(b){b.onclick=function(){openX(b.dataset.k);};});
}
function renderHow(){
  var cl=CFG.CRASH_LIMITS||{},R=CFG.RISK_FLAGS||{},RR=CFG.RUG_RATE_BY_FLAGS||{},DR=CFG.DOUBLED_RATE_BY_FLAGS||{};
  var dv=Object.keys(DR).map(function(n){return DR[n];}),dlo=dv.length?Math.min.apply(null,dv):null,dhi=dv.length?Math.max.apply(null,dv):null;
  $('#how').innerHTML='<div><h3>The gates</h3>'
   +'<p><b>Structure</b> (one failure removes a token at once): trading on a DEX pool rather than a launchpad bonding curve; mint and freeze authority revoked, read from the chain; no permanent delegate, live transfer hook, pause, frozen-by-default or non-transferable setting, no authority that could switch one on later or raise a transfer fee, and no transfer fee above '+CFG.MAX_TRANSFER_FEE_PCT+'%, checked on the chain and again by GoPlus, where either source flagging a trap is enough; liquidity burned or locked (at least '+CFG.MIN_LP_LOCKED_PCT+'%) in the pool it is priced on, where a pump.fun, Raydium LaunchLab or StonkFun graduation pool passes by design and a concentrated pool with no lock evidence fails; not flagged rugged.</p>'
   +'<p><b>In range and alive</b> (scope, not safety): market cap '+cfgUsd(CFG.MIN_MCAP)+' to '+cfgUsd(CFG.MAX_MCAP)+'; 24h volume at least '+cfgUsd(CFG.MIN_VOL24)+'; '+cfgUsd(CFG.MIN_VOL1H)+' and '+CFG.MIN_TRADERS_1H+' wallets in the last hour; at least '+cfgUsd(CFG.MIN_SOLD_1H)+' sold in the last hour, because buy-only flow is a farm pattern.</p>'
   +'<p><b>Rug risk</b> (two failed scans in a row remove a token): out of its first '+CFG.MIN_AGE_MIN+' minutes on a DEX; no more than '+CFG.MAX_RISK_FLAGS+' of the rug study’s six red flags, for coins inside what the study measured; liquidity at least '+cfgUsd(CFG.MIN_LIQ_USD)+' and '+pc(CFG.MIN_LIQ_PCT_MCAP*100,0)+' of market cap; selling '+cfgUsd(CFG.ORDER_USD)+' costs at most '+pc(CFG.MAX_EXIT_COST_PCT,0)+'; 24h volume at most '+CFG.MAX_VOL_TO_MCAP+'× market cap; Jupiter’s organic score not low and no Jupiter suspicious flag; not in free fall ('+spct(cl.h1)+' in 1h, '+spct(cl.h6)+' in 6h, '+spct(cl.h24)+' in 24h); deployer and top holders not selling; Telegram bot-risk at most '+CFG.MAX_TG_BOT_RISK+'.</p>'
   +'<p><b>Holder structure</b>: top 10 at most '+CFG.MAX_TOP10_PCT+'% with pools, lockers, burn and exchanges removed; deployer at most '+CFG.MAX_CREATOR_PCT+'%; linked wallets at most '+pc(CFG.MAX_LINKED_HOLDER_SHARE*100,0)+' of holders; no cluster of identical balances. The largest group of wallets linked by transfers (the bubble-map check) is marked when it holds '+pc(CFG.MAX_CLUSTER_PCT||15,0)+' of supply or more'+(CFG.GATE_ON_CLUSTER?' and gates like the rules above':', and is tested in the Lab before it gates: RugCheck’s groups sometimes span thousands of wallets, which is more likely an exchange or an airdrop than one team')+'. '+(CFG.HOLDER_GATES_FOR_LAUNCHPADS?'These gate every coin.':'These gate every coin except a launchpad graduate under a day old and under '+cfgUsd(CFG.CALIBRATED_MAX_FDV)+' FDV: there the study found they do not predict rugs, so they are shown, not gated. The study says nothing about older or larger coins, so the holder rules still apply to them.')+'</p></div>'
   +'<div><h3>The rug study</h3><p>The rug signals come from a study of 9,467 Solana tokens from 10 to 29 June 2026, mostly pump.fun coins seen minutes after graduation. A rug there means the price closed 80% below entry before it ever traded 50% above it, within a day.</p>'
   +'<p>The main dial is liquidity ÷ FDV. In a constant-product pool it is twice the pool’s share of supply, and if every other holder sold, the price would end at the square of that share: about −96% at 0.41, −80% at 0.9 and −75% at 1.0. Below 0.9 the study saw 41.6% rugs; at or above it, 3.6%. A pump.fun coin starts at about 0.41 and the ratio then moves with its price, so almost every pump.fun coin in this screener’s range is below 0.9. The dial shows how much dumping is still possible; it is not a gate here.</p>'
   +'<p>The six flags: liquidity under '+R.lfdv+'× FDV, over '+R.wallets_10m+' wallets trading in 10 minutes, sells under '+pc(R.sell_share*100,0)+' of recent volume, younger than '+R.age_min+' minutes, over '+R.holders+' holders, and the top 5 buyers under '+pc(R.top5_share*100,0)+' of buying. Out of sample, coins with 0, 2 and 4 flags rugged '+pc(RR[0],0)+', '+pc(RR[2],0)+' and '+pc(RR[4],0)+' of the time'+(dlo!=null?', while '+pc(dlo,0)+' to '+pc(dhi,0)+' doubled at every count':'')+'. Rates are shown, and the count gates, only for coins under '+(CFG.CALIBRATED_MAX_AGE_H||24)+' hours old and under '+cfgUsd(CFG.CALIBRATED_MAX_FDV)+' FDV, which is what the study covered. The study’s thresholds came from three weeks of one market; the tracker records the same day-one outcome for every entry so they can be re-checked here.</p></div>'
   +'<div><h3>Entering, leaving and the tracker</h3><p>A token enters after '+CFG.ENTER_SCANS+' clean scans in a row and leaves after '+CFG.EXIT_SCANS+' failed ones. Tokens already inside get a little slack on each limit so one that hovers on a line does not flicker. Everything outside sits in the waiting room with the gates blocking it, and re-enters by the same rule.</p><p>The first entry starts a tracker: market cap at entry, now, and the ATH since entry with its time, the multiple at +1h, +6h, +24h and +7d, and whether the coin rugged or doubled on day one by the study’s definitions. It keeps following each token for '+(CFG.TRACK_DAYS||14)+' days, including after it drops out, so the scorecard counts the failures too.</p><p>Once an hour it also snapshots every tracked token: market cap, liquidity, volume, net buying, wallets, holders, top-10 share, organic score, liquidity ÷ FDV, the multiple of the entry price and the screener state. Snapshots are hourly for the first '+(CFG.TSNAP_FULL_H||72)+' hours after entry and every six hours after that. The tracker’s Hour by hour view lines every token up at its entry so they can be compared, and each X-ray shows its own snapshots.</p><p>Tile size is float cap: market cap less what the top 10 wallets hold. With All bands selected, each band’s area follows its token count so the largest tokens do not swamp the smallest.</p></div>'
   +'<div><h3>The Lab</h3><p>Every candidate is checked once an hour. The Lab keeps each token’s first observation of the day and its first that passed every gate, and every entry and exit as it happens, with about 45 variables: size, liquidity, volume over 5 minutes to 24 hours and its pace, price changes, buy and sell counts, net buying, traders, holders and their change, organic score, holder concentration, the rug-study signals, momentum and the market backdrop (SOL’s 24h change and the share of candidates rising). Later scans record what happened next: the multiple at +1h, +6h and +24h, the day’s high and low, and when it first reached +10% to +100% or fell 10% to 80%.</p><p>The Lab view scores every variable, '+((D.lab||{}).rules||[]).length+' shadow rules (candidate gates recorded for every observation but never applied) and 25 take-profit and stop pairs. A token counts once a day, verdicts wait for '+(((D.lab||{}).cfg||{}).min_n||60)+' observations in a view, and every suggested line is tested on later data than it was found on.</p></div>'
   +'<div><h3>Where the data comes from, and its limits</h3><p>Free sources only. Jupiter: discovery lists covering every launchpad and DEX, the launchpad and graduation time, holders, audit flags, net buying, traders, organic score, deployer history and sell quotes. GeckoTerminal: hourly pool lists for PumpSwap, Raydium, Meteora and Orca, sectors, liquidity locks, 5-minute candles and a pool’s last 300 trades. DEX Screener: price, volume, liquidity, FDV, pool type and socials. Solana’s public RPC: mint and freeze authority and Token-2022 extensions, straight from the chain. RugCheck: holders with pools and exchanges removed, wallet links and the groups they form, the deployer’s balance and the rugged flag. GoPlus Security: a second reading of authorities and Token-2022 traps, and whether name and image can still change. SolSniffer’s score and InsightX’s cluster maps need paid keys for a screener’s volume of checks, so the X-ray links to both instead. When RugCheck cannot be reached, holder shares come from Jupiter and the wallet-link and bundle checks are skipped and marked as such. Public Telegram pages give member and online counts; X needs a paid key, so only the handle is used.</p>'
   +'<p>Trade lists, which the wallet and buyer flags need, are fetched for up to '+(CFG.TRADES_BUDGET||30)+' coins a run, all inside the study’s range. For a busy coin the last 300 trades can cover less than 10 minutes, so its 10-minute wallet count is scaled up and marked as estimated. The study’s copycat-ticker check is left out: the free search returns at most 20 matches, too few to count reliably. Coins still on a bonding curve are out of scope until they reach a pool, and stablecoins, staked SOL and tokenised stocks are excluded. The free candle feed reaches back 24 hours, so an outage longer than a day loses that day’s highs. Telegram bot-risk and the momentum labels are heuristics that have not been calibrated against outcomes.</p></div>';
}
function sizeNote(){
  $('#size-note').innerHTML='Tiles are sized by <b>'+(state.size==='float'?'float cap':(state.size==='mcap'?'market cap':'24h volume'))+'</b>. Float cap is market cap less what the top 10 wallets hold, so concentrated tokens shrink. <button type="button" id="replay">Replay the float shift</button>';
  $('#replay').onclick=replay;
}

/* ---------- orchestration ---------- */
function show(view){mapEl.hidden=view!=='map';$('#tablewrap').hidden=view!=='table';$('#trackwrap').hidden=view!=='tracker';$('#waitwrap').hidden=view!=='wait';$('#labwrap').hidden=view!=='lab';var cw=$('#callerswrap');if(cw)cw.hidden=view!=='callers';}
function refresh(animate){
  var v=state.view,isMap=v==='map';
  $('#grp-ctl').hidden=state.band==='all'||!isMap;
  ['#ctl-size','#ctl-colour','#ctl-showband','#size-note','#caption','#legend'].forEach(function(s){$(s).hidden=!isMap;});
  $('#ctl-band').hidden=v==='tracker'||v==='lab'||v==='callers';
  $('#ctl-pos').hidden=!(isMap||v==='table');
  var blank=$('#mapblank');if(blank)blank.remove();
  show(state.view);
  if(state.view==='map'){place(animate);
    if(!IN.filter(visible).length){var b=doc.createElement('p');b.id='mapblank';b.className='empty';b.textContent='No tokens in this band pass every gate right now. Check the waiting room to see what is blocking them.';mapEl.appendChild(b);}}
  else if(state.view==='table')renderTable();
  else if(state.view==='tracker')renderTracker();
  else if(state.view==='lab')renderLab();
  else if(state.view==='callers')emit('view','callers');
  else renderWait();
  sizeNote();
}
function replay(){state.size='mcap';syncSeg('size');refresh(false);setTimeout(function(){state.size='float';syncSeg('size');refresh(true);},RM?0:650);}
function syncSeg(kind){$$('[data-'+kind+']').forEach(function(b){b.setAttribute('aria-pressed',String(b.dataset[kind]===String(state[kind])));});}

function wire(){
  $$('[data-view]').forEach(function(b){b.onclick=function(){state.view=b.dataset.view;syncSeg('view');refresh(false);};});
  $$('[data-size]').forEach(function(b){b.onclick=function(){state.size=b.dataset.size;syncSeg('size');refresh(true);};});
  $$('[data-group]').forEach(function(b){b.onclick=function(){state.group=b.dataset.group;syncSeg('group');refresh(true);};});
  $$('[data-colour]').forEach(function(b){b.onclick=function(){state.colour=b.dataset.colour;syncSeg('colour');renderLegend();if(state.view==='map'){labelAll();}};});
  $$('[data-pos]').forEach(function(b){b.onclick=function(){state.pos=+b.dataset.pos;syncSeg('pos');try{localStorage.setItem('undertow-pos',String(state.pos));}catch(x){}renderLegend();idleCaption();refresh(false);if(state.selected&&byId[state.selected])renderXray(byId[state.selected]);};});
  $('#opt-band').onchange=function(e){state.showBand=e.target.checked;if(state.view==='map')labelAll();};
  $('#q').oninput=function(e){state.query=e.target.value.trim();if(state.view==='map')applyQuery();else refresh(false);};
  scrim.onclick=closeX;
  doc.addEventListener('keydown',function(e){if(e.key==='Escape'&&!xr.hidden)closeX();});
  mapEl.addEventListener('mousemove',function(e){var t=e.target.closest&&e.target.closest('.tile');if(t&&!t.classList.contains('gone')){showTip(byId[t.dataset.k],e.clientX,e.clientY);}else hideTip();});
  mapEl.addEventListener('mouseleave',hideTip);
  mapEl.addEventListener('click',function(e){var t=e.target.closest&&e.target.closest('.tile');if(t&&!t.classList.contains('gone')){hideTip();openX(t.dataset.k);}});
  mapEl.addEventListener('keydown',function(e){var t=e.target.closest&&e.target.closest('.tile');if(t&&(e.key==='Enter'||e.key===' ')){e.preventDefault();openX(t.dataset.k);}});
  mapEl.addEventListener('focusin',function(e){var t=e.target.closest&&e.target.closest('.tile');if(t&&byId[t.dataset.k]){var r=t.getBoundingClientRect();showTip(byId[t.dataset.k],r.left+r.width/2,r.top+r.height/2);}});
  mapEl.addEventListener('focusout',hideTip);
  var rt;window.addEventListener('resize',function(){clearTimeout(rt);rt=setTimeout(function(){if(state.view==='map')place(false);},120);});
  try{window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change',function(){readPalette();renderLegend();refresh(false);});}catch(e){}
  new MutationObserver(function(){readPalette();renderLegend();refresh(false);}).observe(doc.documentElement,{attributes:true,attributeFilter:['data-theme']});
}

var wired=false;
function boot(data){
  D=data;SNAPC={};prep();readPalette();
  if(state.selected&&!byId[state.selected]&&!trkBy[state.selected])state.selected=null;
  buildDom();renderTape();renderBandSeg();renderMoves();renderHow();renderLegend();idleCaption();syncSeg('pos');
  if(!wired){wire();wired=true;}
  if(state.selected){openX(state.selected);}
  /* open as market cap, then shrink to float cap, so the effect of supply control is visible on first load */
  if(!RM&&state.size==='float'&&state.view==='map'&&!boot.done){state.size='mcap';syncSeg('size');refresh(false);setTimeout(function(){state.size='float';syncSeg('size');refresh(true);},700);}
  else refresh(false);
  boot.done=true;
  emit('data',D);
}

/* ---------- freshness: when the last scan ran and how often the scheduler runs it ---------- */
var LIVE={on:false,ts:0,fails:0,timer:null,tick:null,busy:false,turn:0,pos:[0,0],paint:0,src:'dexscreener',err:'',jn:0};
function cadenceMin(){return (D&&D.meta&&D.meta.cadence_min)||CFG.SCAN_MINUTES||20;}
function hhmm(ts){return new Date(ts*1000).toISOString().slice(11,16)+' UTC';}
function renderStamp(){
  var st=$('#stamp');if(!st||!D)return;
  var cad=cadenceMin(),age=Date.now()/1000-D.generated_at,every=cad===60?'hourly':(cad>60?'every '+Math.round(cad/60)+' hours':'every '+cad+' min');
  if(LIVE.on){var s=Math.max(0,Math.round(Date.now()/1000-LIVE.ts));
    st.innerHTML='<i class="pulse" aria-hidden="true"></i>Live prices · '+(s<2?'just now':s+' s ago')+' · gates checked '+hhmm(D.generated_at);st.className='stamp live';
    st.title='Prices and market caps come from '+SRC[LIVE.src]+' every few seconds. Gates, holders and the hourly snapshots come from the scan, which reruns every 15 to 20 minutes.';return;}
  if(LIVE.fails>=2&&SERVED&&!IN_CLAUDE){st.textContent='Live prices can’t reach this browser ('+LIVE.err+'); retrying · gates from the '+hhmm(D.generated_at)+' scan';st.className='stamp stale';
    st.title='Neither DEX Screener nor Jupiter answered. A content blocker or network filter can cause this; the page keeps trying.';return;}
  st.title='';
  var ll=$('#livelink'),elsewhere=!!CFG.LIVE_URL&&location.href.indexOf(CFG.LIVE_URL)!==0;
  if(ll){ll.hidden=!elsewhere;if(elsewhere)ll.href=CFG.LIVE_URL;}
  if(elsewhere&&IN_CLAUDE){var rb=$('#refresh');if(rb)rb.hidden=true;st.textContent='Snapshot from the '+hhmm(D.generated_at)+' scan, '+ago(D.generated_at)+' · the live page rescans every 20 min';st.className='stamp';return;}
  if(age>cad*60*2.5+600){st.textContent='Last scan '+hhmm(D.generated_at)+', '+ago(D.generated_at)+' · the '+every+' scan may have stopped';st.className='stamp stale';return;}
  st.textContent='Scanned '+hhmm(D.generated_at)+', '+ago(D.generated_at)+' · refreshes '+every;st.className='stamp ok';
}

/* ---------- live prices from DEX Screener, where the page is allowed to call it ---------- */
/* Tokens on the map (and the open one) refresh every few seconds; every tracked token cycles through after them. */
function chunk(a,n){var o=[];for(var i=0;i<a.length;i+=n)o.push(a.slice(i,i+n));return o;}
function liveQueues(){
  var pri=IN.map(function(k){return k.id;}),seen={};pri.forEach(function(m){seen[m]=1;});
  if(state.selected&&!seen[state.selected]){pri.unshift(state.selected);seen[state.selected]=1;}
  return [chunk(pri,30),chunk(TRK.map(function(x){return x.mint;}).filter(function(m){return !seen[m];}),30)];
}
function mergeLive(arr){
  var best={},now=Date.now()/1000,moved={};
  (arr||[]).forEach(function(p){var m=p&&p.baseToken&&p.baseToken.address;if(!m)return;var k=byId[m],x=trkBy[m],want=(k&&k.pair)||(x&&x.pair),liq=(p.liquidity&&p.liquidity.usd)||0;
    if(want&&p.pairAddress===want){best[m]={p:p,exact:true};return;}
    if(best[m]&&best[m].exact)return;
    if(!best[m]||liq>((best[m].p.liquidity||{}).usd||0))best[m]={p:p};});
  Object.keys(best).forEach(function(m){var p=best[m].p,price=+p.priceUsd,k=byId[m],x=trkBy[m];if(!price)return;
    var mc=p.marketCap||p.fdv||null,v=p.volume||{},c=p.priceChange||{};
    if(k){if(k.price&&price!==k.price)moved[m]=price>k.price?1:-1;
      k.price=price;if(mc)k.cap=k.mcap=mc;if(p.fdv)k.fdv=p.fdv;if(p.liquidity&&p.liquidity.usd!=null)k.liq=p.liquidity.usd;
      if(v.h24!=null)k.vol24=v.h24;if(v.h1!=null)k.vol1h=v.h1;k.chg={m5:c.m5,h1:c.h1,h6:c.h6,h24:c.h24};
      k.fl=k.top10!=null?k.cap*(1-k.top10/100):k.cap;}
    trackLive(x,price,mc,now);});
  return moved;
}
function trackLive(x,price,mc,now){
  if(!x||!x.in_price)return;var r=price/x.in_price;x.now_x=r;x.now_mcap=mc||r*x.in_mcap;x.live_ts=now;
  if(x.ath_x==null||r>x.ath_x){x.ath_x=r;x.ath_mcap=x.now_mcap;x.ath_ts=now;}
  if(x.low_x==null||r<x.low_x){x.low_x=r;x.low_ts=now;}
}
/* Jupiter's price feed, used when DEX Screener cannot be reached: price only, so market cap scales with it and the
   1h change (the tile colour) stays at the scan's value */
function mergeJup(d){
  var moved={},now=Date.now()/1000;
  Object.keys(d||{}).forEach(function(m){var q=d[m]||{},price=+q.usdPrice,k=byId[m];if(!price)return;
    if(k){if(k.price&&price!==k.price)moved[m]=price>k.price?1:-1;
      if(k.price&&k.cap)k.cap=k.mcap=k.cap*price/k.price;k.price=price;
      if(q.priceChange24h!=null){k.chg=k.chg||{};k.chg.h24=q.priceChange24h;}
      k.fl=k.top10!=null?k.cap*(1-k.top10/100):k.cap;}
    trackLive(trkBy[m],price,null,now);});
  return moved;
}
function liveXray(){
  if(xr.hidden||!state.selected)return;var k=byId[state.selected],x=trkBy[state.selected];
  $$('[data-lv]',xr).forEach(function(el){var f=el.dataset.lv;
    if(k&&f==='cap')el.textContent=usd(k.cap);else if(k&&f==='vol24')el.textContent=usd(k.vol24);else if(k&&f==='liq')el.textContent=usd(k.liq);
    else if(x&&f==='now_mcap')el.textContent=usd(x.now_mcap);else if(x&&f==='now_x')el.textContent=xm(x.now_x);else if(x&&f==='now_t')el.textContent=x.live_ts?ago(x.live_ts):'n/a';});
}
/* re-render a pane without losing the reader's place: scroll positions and the focused row survive */
function keepPlace(sel,fn){
  var w=$(sel),y=window.scrollY,t=w.scrollTop,l=w.scrollLeft,inner=$$('.tscroll',w).map(function(e){return e.scrollLeft;});
  var a=doc.activeElement,k=a&&a.closest&&w.contains(a)&&a.closest('tr[data-k]')?a.closest('tr[data-k]').dataset.k:null;
  fn();
  w.scrollTop=t;w.scrollLeft=l;$$('.tscroll',w).forEach(function(e,i){if(inner[i])e.scrollLeft=inner[i];});
  if(k){var r=w.querySelector('tr[data-k="'+k+'"]');if(r)r.focus({preventScroll:true});}
  window.scrollTo(window.scrollX,y);}
function repaintLive(moved){
  liveXray();
  if(state.view==='map'){labelAll();flash(moved);return;}
  var t=Date.now();if(t-LIVE.paint<15000)return;LIVE.paint=t;      /* tables redraw at most every 15 seconds */
  if(state.view==='table')keepPlace('#tablewrap',renderTable);else if(state.view==='tracker'&&state.tview==='table')keepPlace('#trackwrap',renderTracker);
}
/* a tile whose price just moved glows for a moment, brighter for up, darker for down */
function flash(moved){
  if(RM)return;
  Object.keys(moved||{}).forEach(function(m){var el=tiles[m];if(!el||!pos[m])return;var c=moved[m]>0?'flash-up':'flash-dn';
    el.classList.remove('flash-up','flash-dn');void el.offsetWidth;el.classList.add(c);setTimeout(function(){el.classList.remove(c);},1300);});
}
/* A failed call backs off (2 s, then 5 s doubling to a minute) and the page keeps trying while it is open. Each
   failure switches the source between DEX Screener and Jupiter's price feed, so one blocked host costs one try. */
var SRC={dexscreener:'DEX Screener',jupiter:'Jupiter'};
function liveDelay(){return LIVE.fails?Math.min(60000,LIVE.fails===1?2000:5000*Math.pow(2,LIVE.fails-2)):5000;}
function fetchLive(src,mints){
  /* DEX Screener's CDN keeps each answer for 30 seconds, so the same address polled every few seconds kept showing the
     same prices. A 5-second bucket in the query gets a fresh answer without every viewer bypassing the cache. */
  var url=src==='jupiter'?'https://api.jup.ag/price/v3?ids='+mints.join(','):'https://api.dexscreener.com/tokens/v1/solana/'+mints.join(',')+'?b='+Math.floor(Date.now()/5000);
  return fetch(url,{cache:'no-store'}).then(function(r){if(!r.ok)throw new Error(SRC[src]+' answered '+r.status);return r.json();})
    .then(function(d){return src==='jupiter'?mergeJup(d):mergeLive(d);});
}
function pollLive(){
  LIVE.timer=null;
  if(IN_CLAUDE||doc.hidden)return;                /* a hidden tab stops; showing it again starts the loop again */
  if(!D)return schedLive();
  /* three polls in four go to the tokens on the map (and the open one), the fourth to the rest of the tracker */
  var q=liveQueues(),w=(LIVE.turn++%4===3&&q[1].length)?1:0;if(!q[w].length)w=1-w;if(!q[w].length)return schedLive();
  var i=LIVE.pos[w]%q[w].length;LIVE.pos[w]=i+1;LIVE.busy=true;
  fetchLive(LIVE.src,q[w][i])
    .then(function(moved){LIVE.on=true;LIVE.ts=Date.now()/1000;LIVE.fails=0;LIVE.err='';renderStamp();repaintLive(moved);
      if(LIVE.src==='jupiter'&&++LIVE.jn%12===0)LIVE.src='dexscreener';})  /* about once a minute, try DEX Screener again: it has volume and 1h change */
    .catch(function(e){LIVE.fails++;LIVE.err=String((e&&e.message)||'no answer');
      LIVE.src=LIVE.src==='dexscreener'?'jupiter':'dexscreener';
      if(LIVE.fails>=4)LIVE.on=false;renderStamp();})
    .then(function(){LIVE.busy=false;schedLive();});
}
function schedLive(){if(IN_CLAUDE||LIVE.timer||doc.hidden)return;LIVE.timer=setTimeout(pollLive,liveDelay());}
/* the claude.ai viewer blocks calls to other sites, so there the page relies on the scheduled scan alone */
function startLive(){
  if(IN_CLAUDE)return;
  if(!LIVE.timer&&!LIVE.busy)pollLive();
  if(!LIVE.tick)LIVE.tick=setInterval(function(){if(LIVE.on||LIVE.fails)renderStamp();},1000);
}

/* ---------- CSV downloads: claude.ai's save prompt where it exists, a plain download elsewhere ---------- */
var DL=null;
if(IN_CLAUDE){try{window.claude.use('downloads').then(function(d){DL=d;},function(){});}catch(e){}}
function dlBtn(file,label){return '<button type="button" class="linkbtn" data-dl="'+file+'">'+label+'</button>';}
function download(file){
  fetch(file+'?t='+Date.now(),{cache:'no-store'}).then(function(r){if(!r.ok)throw 0;return r.text();}).then(function(txt){
    if(DL){DL.save({filename:file,data:txt}).then(function(){toast('Saved '+file);},function(e){if(!e||e.code!=='declined')toast('Could not save '+file);});return;}
    var a=doc.createElement('a'),u=URL.createObjectURL(new Blob([txt],{type:'text/csv'}));a.href=u;a.download=file;doc.body.appendChild(a);a.click();setTimeout(function(){URL.revokeObjectURL(u);a.remove();},2000);
  }).catch(function(){toast(file+' is not available in this copy of the page');});
}
doc.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('[data-dl]');if(b){e.preventDefault();download(b.dataset.dl);}});

/* ---------- start: an embedded snapshot paints at once; data.json next to the page replaces it and is re-read every 5 minutes ---------- */
function embedded(){var e=$('#data');try{return e?JSON.parse(e.textContent):null;}catch(x){return null;}}
function loadData(){
  return fetch('data.json?t='+Date.now(),{cache:'no-store'}).then(function(r){if(!r.ok)throw 0;return r.json();})
    .then(function(d){if(d&&d.tokens&&(!D||d.generated_at>D.generated_at)){boot(d);return true;}return false;}).catch(function(){return false;});
}
/* a newer scan is spotted from version.json (a few bytes) before the full data is fetched */
function checkForUpdate(manual){
  if(!SERVED)return Promise.resolve();
  return fetch('version.json?t='+Date.now(),{cache:'no-store'}).then(function(r){if(!r.ok)throw 0;return r.json();})
    .then(function(v){if(v&&D&&v.generated_at>D.generated_at+1)return loadData().then(function(ok){if(ok)toast('Updated with the '+hhmm(D.generated_at)+' scan');});
      if(manual)toast('Showing the latest scan, from '+hhmm(D.generated_at));})
    .catch(function(){return loadData().then(function(ok){if(manual)toast(ok?'Updated with the '+hhmm(D.generated_at)+' scan':'Showing the latest scan, from '+hhmm(D.generated_at));});});
}
function start(){
  var emb=embedded();if(emb)boot(emb);
  (SERVED?loadData():Promise.resolve()).then(function(){
    if(!D){$('#stamp').textContent='No data';$('#tape').innerHTML='<span>No scan data was found next to this page.</span>';return;}
    startLive();});
  if(SERVED)setInterval(function(){if(!doc.hidden)checkForUpdate(false);},120000);
  setInterval(renderStamp,30000);
  doc.addEventListener('visibilitychange',function(){if(!doc.hidden){renderStamp();checkForUpdate(false);if(D)startLive();}});
  var rb=$('#refresh');rb.hidden=!SERVED;
  rb.onclick=function(){checkForUpdate(true);if(LIVE.timer)pollLive();};
}
/* ---------- hooks for the community layer (community.js): read-only access plus events ---------- */
var HOOKS={};
function emit(ev,arg){(HOOKS[ev]||[]).forEach(function(fn){try{fn(arg);}catch(e){if(window.console)console.error(e);}});}
window.Undertow={cfg:function(){return CFG;},data:function(){return D;},token:function(id){return byId[id];},
  selected:function(){return xr.hidden?null:state.selected;},view:function(){return state.view;},
  setView:function(v){state.view=v;syncSeg('view');refresh(false);},inClaude:IN_CLAUDE,served:SERVED,
  on:function(ev,fn){(HOOKS[ev]=HOOKS[ev]||[]).push(fn);},toast:toast,esc:esc,usd:usd,pc:pc,ago:ago,when:when,xm:xm,int:int};
window.__undertow=1;
start();
})();
