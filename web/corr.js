/* ---------- Correlations: every variable against the price (undertow/corr.py) ---------- */
(function(){
'use strict';
var U=window.Undertow;if(!U)return;
var doc=document,$=function(s,r){return (r||doc).querySelector(s);},$$=function(s,r){return Array.prototype.slice.call((r||doc).querySelectorAll(s));};
var esc=U.esc,int=U.int,ago=U.ago,MINUS='−',D=null,K=null;
var st={group:'all',sort:'p4'};
try{var sv=JSON.parse(localStorage.getItem('undertow-corr')||'null');if(sv&&sv.sort)st=sv;}catch(e){}
function save(){try{localStorage.setItem('undertow-corr',JSON.stringify(st));}catch(e){}}

function r2(v){return v==null||isNaN(v)?'–':(v<0?MINUS:'')+Math.abs(v).toFixed(2);}
function utc(ts){return ts?new Date(ts*1000).toISOString().slice(0,16).replace('T',' ')+' UTC':'–';}
var VERD={holds:['works','Holds'],weak:['none','Weak'],collecting:['coll','Collecting']};
function vchip(v){var m=VERD[v]||VERD.collecting;return '<span class="vchip '+m[0]+'">'+m[1]+'</span>';}

/* one correlation as a shaded cell: the shade grows with the size of rho (full at 0.3), blue below zero and amber
   above; bold when it is at least 2 standard errors from zero with errors clustered by coin */
function cell(m,label){
  if(!m||m.rho==null)return '<td class="cr-na" data-label="'+esc(label)+'">–</td>';
  var a=Math.min(1,Math.abs(m.rho)/0.3),sig=Math.abs(m.t||0)>=2;
  var tip='rho '+r2(m.rho)+(m.t!=null?', t '+r2(m.t):'')+', '+int(m.n)+' readings on '+int(m.coins)+' coins'+(m.rho1!=null||m.rho2!=null?'; earlier half '+r2(m.rho1)+', later half '+r2(m.rho2):'');
  return '<td class="cr '+(m.rho>=0?'pos':'neg')+(sig?' sig':'')+'" style="--a:'+a.toFixed(2)+'" data-label="'+esc(label)+'" title="'+esc(tip)+'"><span class="cv">'+r2(m.rho)+(m.rho1!=null&&m.rho2!=null?'<span class="nm">'+r2(m.rho1)+' / '+r2(m.rho2)+'</span>':(m.t!=null?'<span class="nm">t '+r2(m.t)+'</span>':''))+'</span></td>';
}
function val(v,col){
  if(col==='size')return v.size;if(col==='together')return v.together;if(col==='leads')return v.leads;
  return (v.predicts||{})[col.slice(1)];
}

function render(){
  var w=$('#corrwrap');if(!w)return;D=U.data();K=D&&D.corr;
  if(!K){w.innerHTML='<p class="empty">Correlations are worked out once an hour from the Buy &amp; sell path; the first set appears with the next scan.</p>';return;}
  var hz=K.horizons||[1,4,12],groups=[];
  (K.vars||[]).forEach(function(v){if(groups.indexOf(v.group)<0)groups.push(v.group);});
  var vs=(K.vars||[]).filter(function(v){return st.group==='all'||v.group===st.group;});
  var key=function(v){var m=val(v,st.sort);return m&&m.rho!=null?Math.abs(m.rho):-1;};
  vs.sort(function(a,b){return key(b)-key(a)||(b.n||0)-(a.n||0);});
  var cols=[['size','With market cap'],['together','Moves with the price'],['leads','Change leads the price']].concat(hz.map(function(h){return ['p'+h,'Predicts: next '+h+'h'];}));
  var head='<tr><th class="l">Variable</th><th>Readings</th>'+cols.map(function(c){return '<th><button type="button" class="linkbtn" data-csort="'+c[0]+'" aria-pressed="'+(st.sort===c[0])+'">'+esc(c[1])+(st.sort===c[0]?' ▾':'')+'</button></th>';}).join('')+'<th class="l">Next '+hz[1]+'h</th></tr>';
  var rows=vs.map(function(v){
    var p=(v.predicts||{})[String(hz[1])]||{};
    return '<tr><td class="l"><b>'+esc(v.label)+'</b><br><span class="nm">'+esc(v.group)+'</span></td><td data-label="Readings">'+int(v.n||0)+'</td>'
      +cell(v.size,'With market cap')+(v.price_derived?'<td class="cr-na" data-label="Moves with the price" title="Worked out from the price, or from liquidity, which moves with the price because half a pool is the coin, so it moves with it by construction">price-derived</td>':cell(v.together,'Moves with the price'))
      +cell(v.leads,'Change leads the price')+hz.map(function(h){return cell((v.predicts||{})[String(h)],'Predicts: next '+h+'h');}).join('')
      +'<td class="l" data-label="Next '+hz[1]+'h">'+vchip(p.verdict||(v.n>=200?'weak':'collecting'))+'</td></tr>';});
  /* the plain-words summary: the strongest relationships that held in both halves */
  var best=[];(K.vars||[]).forEach(function(v){hz.forEach(function(h){var m=(v.predicts||{})[String(h)];if(m&&m.verdict==='holds')best.push({v:v,h:h,m:m});});});
  best.sort(function(a,b){return Math.abs(b.m.rho)-Math.abs(a.m.rho);});
  var seen={},top=best.filter(function(b){if(seen[b.v.key])return false;seen[b.v.key]=1;return true;}).slice(0,6);
  var lead=top.length?'<p class="trk-note"><b>Strongest relationships that held in both halves of the window:</b> '+top.map(function(b){
      return esc(b.v.label)+' ('+(b.m.rho>0?'higher, then the price rose more':'higher, then the price did worse')+' over the next '+b.h+'h; rho '+r2(b.m.rho)+', t '+r2(b.m.t)+')';}).join('; ')+'. A rank correlation of 0.1 is a weak tilt, not a forecast: it ranks coins slightly better than chance and leaves most of the move unexplained.</p>'
    :'<p class="trk-note"><b>No variable has yet shown a relationship with the price that held in both halves of the window</b> with t of 2 or more. That is what most of them will keep showing: in memecoins most of the next move is noise.</p>';
  w.innerHTML='<div class="trk-head"><div class="kpis">'
      +kpi('Readings',int(K.points||0),'one per coin per hour, passing every gate')
      +kpi('Coins',int(K.coins||0),K.since?'since '+esc(utc(K.since)):'')
      +kpi('Updated',esc(ago(K.ts,D.generated_at)),'once an hour'+(K.seconds!=null?', in '+K.seconds+'s':''))
      +kpi('Relationships that hold',int(best.length),'variable and horizon pairs, of '+int((K.vars||[]).length*hz.length))
    +'</div>'+lead
    +'<p class="trk-note">Spearman rank correlations with the price; market cap is price times a fixed supply, so the same figures hold for it. <b>With market cap</b>: does the variable just track size? <b>Moves with the price</b>: its change over an hour against the price change over the same hour. <b>Change leads the price</b>: its change over an hour against the price change over the next hour. <b>Predicts</b>: its level against the price change over the next 1, 4 and 12 hours, with the earlier and later half of the window underneath. Shade grows with the size of the correlation (blue negative, amber positive); bold means at least 2 standard errors from zero, with errors clustered by coin so one coin’s many readings count once. A verdict of “holds” needs |rho| ≥ '+r2(((D.config||{}).CORR||{}).min_rho||0.05)+', t ≥ 2 and the same sign in both halves.</p></div>'
    +'<div class="md-ctl"><div class="seg cr-groups" role="group" aria-label="Group">'+['all'].concat(groups).map(function(g){return '<button type="button" data-cgroup="'+esc(g)+'" aria-pressed="'+(st.group===g)+'">'+esc(g==='all'?'All variables':g)+'</button>';}).join('')+'</div>'
    +'<div class="seg" role="group" aria-label="Sort by">'+cols.map(function(c){return '<button type="button" data-csort="'+c[0]+'" aria-pressed="'+(st.sort===c[0])+'">'+esc(c[1].replace('Predicts: next ','Next '))+'</button>';}).join('')+'</div></div>'
    +'<div class="tscroll"><table class="grid lab corrgrid cards"><thead>'+head+'</thead><tbody>'+rows.join('')+'</tbody></table></div>'
    +'<p class="fine">The sample is every reading the Buy &amp; sell ledger keeps (coins passing every gate, '+int(((D.trade||{}).cfg||{}).path_days||14)+' days), thinned to one reading per coin per hour. A correlation is shown once '+int(200)+' readings have it. Price-derived variables (recent changes, distance from highs and lows, and liquidity and its ratios, since half a pool is the coin itself) move with the price by construction, so “moves with the price” is left blank for them. Correlation is not a trading rule: the Buy &amp; sell and Models tabs test what trading on a variable would have returned after costs.</p>';
  w.insertAdjacentHTML('beforeend',minuteSec(K.minute));
  $$('[data-cgroup]',w).forEach(function(b){b.onclick=function(){st.group=b.dataset.cgroup;save();render();};});
  $$('[data-csort]',w).forEach(function(b){b.onclick=function(){st.sort=b.dataset.csort;save();render();};});
}
function kpi(k,v,s){return '<div class="kpi"><div class="k">'+k+'</div><div class="v">'+v+'</div><div class="s">'+s+'</div></div>';}

/* the minute data against the next 5, 15 and 30 minutes (corr.analyse_fast): what quick rules bet on */
function minuteSec(M){
  if(!M)return '';
  var hz=M.horizons_min||[5,15,30],mid=String(hz[1]);
  var vs=(M.vars||[]).slice().sort(function(a,b){var x=((a.predicts||{})[mid]||{}).rho,y=((b.predicts||{})[mid]||{}).rho;return (y==null?-1:Math.abs(y))-(x==null?-1:Math.abs(x))||(b.n||0)-(a.n||0);});
  var hold=0;vs.forEach(function(v){hz.forEach(function(h){if(((v.predicts||{})[String(h)]||{}).verdict==='holds')hold++;});});
  var rows=vs.map(function(v){var p=(v.predicts||{})[mid]||{};
    return '<tr><td class="l"><b>'+esc(v.label)+'</b></td><td data-label="Readings">'+int(v.n||0)+'</td>'+hz.map(function(h){return cell((v.predicts||{})[String(h)],'Predicts: next '+h+' min');}).join('')
      +'<td class="l" data-label="Verdict, next '+mid+' min">'+vchip(p.verdict||(v.n>=200?'weak':'collecting'))+'</td></tr>';});
  return '<section class="lab-sec" id="cr-minute"><h3>The minute data: the next 5, 15 and 30 minutes</h3>'
    +'<p class="trk-note">The same test on the minute readings taken while each scan runs, for the bets quick rules make: each variable’s level against the price change over the next '+hz.join(', ').replace(/, (\d+)$/,' and $1')+' minutes. '+int(M.points||0)+' readings on '+int(M.coins||0)+' coins'+(M.since?' since '+esc(utc(M.since)):'')+', one per coin every '+int(M.every_min||15)+' minutes, on coins that passed every gate at the scan before (the gates a quick rule could have known); '+int(hold)+' variable and horizon pairs hold so far. Over minutes, price noise and the cost of a round trip both loom larger, so a correlation that holds here still has to pay its fees on the Buy &amp; sell tab.</p>'
    +'<div class="tscroll"><table class="grid lab corrgrid cards"><thead><tr><th class="l">Variable</th><th>Readings</th>'+hz.map(function(h){return '<th>Predicts: next '+h+' min</th>';}).join('')+'<th class="l">Next '+mid+' min</th></tr></thead><tbody>'+rows.join('')+'</tbody></table></div></section>';
}

U.on('data',function(){if(U.view()==='corr')render();});
U.on('view',function(v){if(v==='corr')render();});
if(U.data()&&U.view()==='corr')render();
})();
