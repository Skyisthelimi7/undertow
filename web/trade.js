/* ---------- Buy & sell: rules tested on paper (undertow/trade.py), live signals, open trades and the record ---------- */
(function(){
'use strict';
var U=window.Undertow;if(!U)return;
var doc=document,$=function(s,r){return (r||doc).querySelector(s);},$$=function(s,r){return Array.prototype.slice.call((r||doc).querySelectorAll(s));};
var esc=U.esc,usd=U.usd,pc=U.pc,ago=U.ago,when=U.when,xm=U.xm,int=U.int,spct=U.spct,ageH=U.ageH;
var MINUS='−',D=null,T=null,EX={},RU={},VL={},PEAK={},painted=0;

/* ---- formatting ---- */
function n1(v){return v==null||isNaN(v)?'n/a':(v<0?MINUS:'+')+Math.abs(v).toFixed(Math.abs(v)<10?1:0)+'%';}
function tval(t){return t==null?'':' <span class="nm">t '+(t<0?MINUS:'')+Math.abs(t).toFixed(1)+'</span>';}
function price(v){if(v==null)return 'n/a';if(v>=1)return '$'+v.toPrecision(4);var s=v.toPrecision(3);return '$'+(s.indexOf('e')>=0?Number(s).toFixed(12).replace(/0+$/,''):s);}
function ymd(ts){return ts?new Date(ts*1000).toISOString().slice(0,10):'–';}
function fmtVar(key,v){
  if(v==null||isNaN(v))return 'n/a';var u=(VL[key]||{}).unit;
  if(u==='usd')return usd(v);if(u==='pct')return pc(v,1);if(u==='chg')return spct(v);if(u==='share')return pc(v*100,0);
  if(u==='frac')return spct(v*100);if(u==='x')return v.toFixed(2)+'×';if(u==='h')return ageH(v);if(u==='ratio')return Math.abs(v)<100?v.toFixed(2):int(v);return Math.abs(v)<10&&v%1?v.toFixed(2):int(v);}
var OPW={'>=':'≥','>':'>','<=':'≤','<':'<'};
function cond(c){var l=(VL[c[0]]||{}).label||c[0];return esc(l)+' '+OPW[c[1]]+' '+esc(fmtVar(c[0],c[2]));}
function conds(r){return (r.all||[]).map(cond).join('; ');}
var STAT={live:['in','Live'],testing:['entering','Testing'],retired:['out','Retired']};
function stChip(s){var m=STAT[s]||['out',s];return '<span class="pill '+m[0]+'">'+m[1]+'</span>';}
var VERD={earns:['works','Earns'],loses:['hurts','Loses'],unclear:['none','Unclear'],collecting:['coll','Collecting'],
  signal:['works','Signal'],'no signal':['none','No signal'],holds:['works','Holds'],'does not hold':['none','Does not hold']};
function vchip(v){var m=VERD[v]||VERD.collecting;return '<span class="vchip '+m[0]+'">'+m[1]+'</span>';}
function cost(liq,size){var c=T.cfg||{};if(!liq||liq<=0)return 100;return Math.min(100,size/(liq/2+size)*100+(c.fee_pct!=null?c.fee_pct:1));}
function netAt(x,liqIn,liqOut){var c=T.cfg||{},s=c.usd||500;return (x*(1-cost(liqIn,s)/100)*(1-cost(liqOut,s)/100)-1)*100;}
function rec(s){return !s||!s.n?'–':int(s.n)+' · '+pc(s.win*100,0)+' won · avg '+n1(s.mean)+tval(s.t);}
function sec(title,body,id){return '<section class="lab-sec"'+(id?' id="'+id+'"':'')+'><h3>'+title+'</h3>'+body+'</section>';}
function table(head,rows,cls){return '<div class="tscroll"><table class="grid lab'+(cls?' '+cls:'')+'"><thead><tr>'+head.map(function(h,i){return '<th'+(i===0||h.charAt(0)==='<'?' class="l"':'')+'>'+h.replace(/^</,'')+'</th>';}).join('')+'</tr></thead><tbody>'+rows.join('')+'</tbody></table></div>';}
function clip(t,n){t=String(t||'');if(t.length<=n)return t;var c=t.slice(0,n),i=c.lastIndexOf(' ');return (i>n*.6?c.slice(0,i):c)+'…';}
function coinCell(m,sym){return '<button type="button" class="linkbtn tkbtn" data-tk="'+esc(m)+'">'+esc(sym||m.slice(0,5))+'</button>';}

/* ---- data ---- */
function load(){
  D=U.data();T=D&&D.trade;EX={};RU={};VL={};if(!T)return;
  (T.exits||[]).forEach(function(e){EX[e.id]=e;});(T.bench||[]).forEach(function(r){RU[r.id]=r;});
  (T.vars||[]).forEach(function(v){VL[v.key]=v;});
  ((D.lab||{}).variables||[]).forEach(function(v){if(!VL[v.key])VL[v.key]=v;});
  (((T.quick||{}).vars)||[]).forEach(function(v){if(!VL[v.key])VL[v.key]=v;});
  U.prioritise((T.open||[]).map(function(x){return x.mint;}).concat((T.signals||[]).map(function(s){return s.mint;})));
}
function liveOf(m){return U.price(m);}

/* ---- the exit policy, judged live between scans ---- */
function sellState(x){
  var e=(EX[x.exit]||{}).params||{},q=liveOf(x.mint),p=q&&q.price?q.price:x.last_price,p0=x.in_price,now=Date.now()/1000;
  if(!p||!p0)return ['hold','No price yet'];
  var pk=Math.max(PEAK[x.id]||0,x.peak||p0,p);PEAK[x.id]=pk;
  var r=p/p0,held=(now-x.in_ts)/3600,maxh=e.max_h||24;
  if(e.sl!=null&&r<=1-e.sl/100)return ['sell','Stop: '+n1(-e.sl)+' from entry'];
  if(e.tp!=null&&r>=1+e.tp/100)return ['sell','Target: '+n1(e.tp)+' reached'];
  if(e.trail!=null&&pk/p0>=1+(e.arm||0)/100&&p<=pk*(1-e.trail/100))return ['sell','Trailing stop: '+e.trail+'% below the peak'];
  if(e.cool!=null&&pk/p0>=1+e.cool/100&&x.last_price&&p/x.last_price-1<=-(e.cool_drop||5)/100)return ['sell','Cooling off after a +'+e.cool+'% push'];
  if(e.fade!=null&&held>=1&&q&&q.c1h!=null&&q.c1h<=-e.fade)return ['sell','Fading: '+n1(q.c1h)+' in an hour'];
  if(held>=maxh)return ['sell','Time limit: '+heldTxt(maxh)];
  var next=[];if(e.sl!=null)next.push('stop '+price(p0*(1-e.sl/100)));if(e.tp!=null)next.push('target '+price(p0*(1+e.tp/100)));
  if(e.trail!=null)next.push(pk/p0>=1+(e.arm||0)/100?'trailing stop '+price(pk*(1-e.trail/100)):'trailing stop arms at '+price(p0*(1+(e.arm||0)/100)));
  next.push('sell by '+when(x.in_ts+maxh*3600));
  return ['hold','Hold: '+next.join(', ')];
}

/* ---- sections ---- */
function head(){
  var live=(T.bench||[]).filter(function(r){return r.status==='live';}),testing=(T.bench||[]).filter(function(r){return r.status==='testing';});
  var sigLive=(T.signals||[]).filter(function(s){return s.live;}).length,sigTest=(T.signals||[]).length-sigLive,R=T.record||{},c=T.cfg||{};
  var pnl=R.n?R.mean*R.n*(c.usd||500)/100:null;
  return '<div class="trk-head"><div class="kpis">'
    +kpi('Live buy rules',live.length?int(live.length):'None yet',live.length?esc(clip(live[0].label,70))+(live.length>1?' and '+(live.length-1)+' more':''):int(testing.length)+' rules under test')
    +kpi('Buy signals now',int(sigLive),sigTest?int(sigTest)+' coins match a rule under test':'nothing matches a rule under test')
    +kpi('Open paper trades',int((T.open||[]).length),'live rules only')
    +kpi('Record',R.n?pc(R.win*100,0)+' won':'No trades yet',R.n?int(R.n)+' trades, average '+n1(R.mean)+(pnl!=null?'; '+(pnl<0?MINUS:'+')+usd(Math.abs(pnl))+' in all at '+usd(c.usd||500)+' a trade':''):'closed live trades appear here')
    +kpi('Exit',esc(T.exit&&T.exit.id||'n/a'),esc((T.exit&&T.exit.label)||''))
    +kpi('Next review',esc(ymd(T.next_review)),'last '+esc(ymd(T.last_review)))
    +'</div><p class="trk-note">Paper trades, not advice. Every rule on the bench records what following it would have returned on a <b>'+usd(c.usd||500)+'</b> position after a '+pc(c.fee_pct,1)+' fee allowance a side plus price impact, priced at every scan and once a minute while a scan runs. A rule earns a live buy signal only on trades it made after joining the bench: at least '+int(c.min_trades)+' that have had time to close, averaging '+n1(c.min_edge)+' or better after costs with t ≥ '+c.z+', in '+c.promote_after+' weekly reviews in a row. Until then its matches show as “under test”.</p></div>';
}
function kpi(k,v,s){return '<div class="kpi"><div class="k">'+k+'</div><div class="v">'+v+'</div><div class="s">'+s+'</div></div>';}

/* the testing rules with the best record so far: the forward record once it has 10 matured trades, else the backtest */
function leaders(n){
  var score=function(r){var f=r.fwd_now||{},b=(r.last||{}).bt||{};return f.n>=10?f.mean:(b.n?b.mean:null);};
  return (T.bench||[]).filter(function(r){return r.status==='testing'&&!r.model&&!r.fast&&score(r)!=null;}).sort(function(a,b){return score(b)-score(a);}).slice(0,n);
}
function buySec(){
  var c=T.cfg||{},size=U.posSize()||500,e=(T.exit||{}).params||{};
  var sigs=T.signals||[],live=sigs.filter(function(s){return s.live;});
  /* the exit plan from the price you would pay now: the live policy's target, stop and time limit */
  var plan=function(p){var o=[];if(e.tp!=null)o.push('target '+price(p*(1+e.tp/100))+' (+'+e.tp+'%)');if(e.sl!=null)o.push('stop '+price(p*(1-e.sl/100)));o.push('sell within '+(e.max_h||24)+'h');return o.join(', ');};
  var row=function(s,extra){var rt=2*cost(s.liq,size),q=liveOf(s.mint),p=q&&q.price||s.price;
    return '<tr><td class="l">'+coinCell(s.mint,s.sym)+'</td><td data-tl="px:'+esc(s.mint)+'">'+price(p)+'</td><td>'+usd(s.mc)+'</td><td>'+spct((s.f||{}).c1h)+'</td><td>'+spct((s.f||{}).ru6)+'</td><td>'+pc(rt,1)+'</td>'+(extra?extra(s,p):'')+'</tr>';};
  var body='';
  if(live.length)body+=table(['Coin','Price','Market cap','1h','Off 6h low','Round trip at '+usd(size),'<Rule','<Exit plan'],live.map(function(s){
    return row(s,function(s,p){return '<td class="l">'+s.rules.filter(function(id){return (RU[id]||{}).status==='live';}).map(function(id){return '<span class="rl">'+esc((RU[id]||{}).label||id)+'</span>';}).join('<br>')+'</td><td class="l">'+esc(plan(p))+'</td>';});}),'cards');
  else body+='<p class="empty">'+((T.live_rules||[]).length?'No coin meets a live buy rule right now.':'No rule has earned a live buy signal yet. In the candle study before the ledger started, none of the rules tried cleared costs; every rule’s forward record is below.')+'</p>';
  var L=leaders(3);
  if(L.length){body+='<h3 class="sub-h">Under test: what the leading rules match now</h3><p class="trk-note">The three testing rules with the best record so far. Their matches are paper trades, not signals: none of these rules has cleared the bar yet.</p>';
    L.forEach(function(r){var f=r.fwd_now||{},b=(r.last||{}).bt||{},m=sigs.filter(function(s){return s.rules.indexOf(r.id)>=0;});
      body+='<div class="lead"><p><b>'+esc(r.label)+'</b><br><span class="nm">'+(f.n?'forward '+rec(f):'no matured forward trades yet')+(b.n?' · backtest '+int(b.n)+' trades, avg '+n1(b.mean):'')+'</span></p>'
        +(m.length?table(['Coin','Price','Market cap','1h','Off 6h low','Round trip at '+usd(size)],m.slice(0,8).map(function(s){return row(s);}),'cards')+(m.length>8?'<p class="fine">and '+(m.length-8)+' more.</p>':''):'<p class="fine">Matches no coin right now.</p>')+'</div>';});}
  var near=(T.near||[]).slice(0,12);
  if(near.length)body+='<details class="rv-gone"><summary>One condition short of '+((T.live_rules||[]).length?'a live rule':'a leading rule')+' ('+(T.near||[]).length+')</summary><ul class="rv-log">'+near.map(function(n){var r=RU[n.rule]||{},m=n.miss[0];
    return '<li><b>'+coinCell(n.mint,(((D.tokens||[]).filter(function(k){return k.mint===n.mint;})[0])||{}).symbol)+'</b> for “'+esc(r.label||n.rule)+'”: needs '+cond(m)+', has '+esc(m[3]==null?'no value':fmtVar(m[0],m[3]))+'</li>';}).join('')+'</ul></details>';
  body+='<p class="fine">Round trip: the fees and the price impact of buying and later selling your '+usd(size)+' at today’s liquidity (change the size in the bar above). The record itself is kept at '+usd(c.usd||500)+'.</p>';
  return sec('Buy signals now',body,'tr-buy');
}

function openSec(){
  var op=T.open||[],body='';
  if(!op.length)body='<p class="empty">No open paper trades from a live rule.</p>';
  else body=table(['Coin','<Sell signal','Since entry, after costs','Now','Entry','Bought','Peak'],op.map(function(x){
    return '<tr><td class="l">'+coinCell(x.mint,x.sym)+'<br><span class="nm">'+esc(clip((RU[x.rule]||{}).label||x.rule,60))+'</span></td><td class="l sellcell" data-tl="st:'+x.id+'"></td><td data-tl="pl:'+x.id+'">'+n1(x.now_net)+'</td>'
      +'<td data-tl="px:'+esc(x.mint)+'">'+price(x.last_price)+'</td><td>'+price(x.in_price)+'<br><span class="nm">'+usd(x.in_mc)+'</span></td><td>'+esc(ago(x.in_ts))+'</td><td>'+xm((x.peak||x.in_price)/x.in_price)+'</td></tr>';}),'cards');
  body+='<p class="fine">Prices refresh every few seconds from the live feed; the sell signal applies the live exit policy to them. The ledger itself records the sale at the first price it reads at or past the level, a minute later at most while a scan runs and at the next scan otherwise (about two minutes between scans), so a stop can fill worse than its level.</p>';
  return sec('Open paper trades and sell signals',body,'tr-open');
}

function warnSec(){
  var W=T.warnings||[],R=T.warning_rules||[],byId={};R.forEach(function(w){byId[w.id]=w;});
  var rrows=R.map(function(w){var l=w.last||{},a=l['in']||{},b=l.out||{};
    return '<tr><td class="l">'+esc(w.label)+'</td><td>'+(a.n?int(a.n)+' <span class="nm">on '+int(a.coins)+' coins</span>':'–')+'</td><td>'+(a.n?n1(a.mean):'–')+'</td><td>'+(b.n?n1(b.mean):'–')+'</td><td>'+(l.share_lower!=null?pc(l.share_lower*100,0):'–')+'</td><td class="l">'+vchip(l.verdict)+tval(l.t)+'</td></tr>';});
  var body='<p class="trk-note">States that were followed by falls among coins that pass every gate. Each review measures the price change over the next '+(((R[0]||{}).last||{}).hours||4)+' hours for coins in the state against every other reading, before costs. A warning holds when coins in the state did at least '+((T.cfg||{}).warn_gap||2)+' points worse, with t ≤ −'+((T.cfg||{}).z||2)+'.</p>'
    +table(['Warning','Readings','Next 4h: in this state','Next 4h: the rest','No higher 4h later','<Verdict'],rrows);
  if(W.length)body+='<h3 class="sub-h">Coins in a warning state now</h3>'+table(['Coin','<Warnings','Off 6h low','From 6h high','Since last scan','1h'],W.map(function(w){var f=w.f||{};
    return '<tr><td class="l">'+coinCell(w.mint,w.sym)+'</td><td class="l">'+w.ids.map(function(i){var r=byId[i]||{};return esc(r.label||i)+' '+vchip(((r.last||{}).verdict));}).join('<br>')+'</td><td>'+spct(f.ru6)+'</td><td>'+spct(f.dd6)+'</td><td>'+spct(f.r15)+'</td><td>'+spct(f.c1h)+'</td></tr>';}),'cards');
  else body+='<p class="empty">No coin that passes every gate is in a warning state right now.</p>';
  return sec('Sell-side warnings: a push that tends to cool off',body,'tr-warn');
}

function heldTxt(h){return h==null?'–':(h<1?Math.round(h*60)+' min':h.toFixed(1)+'h');}
function recordSec(){
  var cl=T.closed||[],R=T.record||{},body='';
  if(!cl.length)body='<p class="empty">No live paper trade has closed yet.</p>';
  else body='<p class="trk-note">'+rec(R)+'. Median '+n1(R.med)+', best '+n1(R.best)+', worst '+n1(R.worst)+', average hold '+(R.hold_h!=null?R.hold_h.toFixed(1)+'h':'n/a')+'.</p>'
    +table(['Coin','<Rule','Bought','Sold','Held','After costs','<Why'],cl.slice(0,40).map(function(x){
      return '<tr><td class="l">'+coinCell(x.mint,x.sym)+'</td><td class="l">'+esc((RU[x.rule]||{}).label||x.rule)+'</td><td>'+price(x.in_price)+'<br><span class="nm">'+esc(when(x.in_ts))+'</span></td><td>'+price(x.out_price)+'<br><span class="nm">'+esc(when(x.out_ts))+'</span></td><td>'+heldTxt(x.h)+'</td><td class="'+(x.ret>0?'tr-up':'tr-dn')+'">'+n1(x.ret)+'</td><td class="l">'+esc(x.why)+'</td></tr>';}),'cards');
  return sec('Record of the live rules',body,'tr-rec');
}

function benchSec(){
  var nm=(T.bench||[]).filter(function(r){return r.model&&r.status!=='retired';}).length;
  var b=(T.bench||[]).filter(function(r){return r.status!=='retired'&&((!r.model&&!r.fast)||r.status==='live');}).sort(function(x,y){return (y.status==='live')-(x.status==='live')||(((y.fwd_now||{}).mean||((y.last||{}).bt||{}).mean||-99)-((x.fwd_now||{}).mean||((x.last||{}).bt||{}).mean||-99));});
  var gone=(T.bench||[]).filter(function(r){return r.status==='retired'&&!r.model&&!r.fast;}),c=T.cfg||{};
  var rows=b.map(function(r){var l=r.last||{},f=r.fwd_now||{},bt=l.bt||{},hv=l.bt_halves||[];
    return '<tr><td class="l"><span title="'+esc(conds(r))+'">'+esc(r.label)+'</span><br><span class="nm">'+conds(r)+'</span></td><td class="l">'+stChip(r.status)+'</td>'
      +'<td>'+int(f.n||0)+(r.open?' <span class="nm">+'+r.open+' open</span>':'')+'</td><td>'+(f.n?pc(f.win*100,0):'–')+'</td><td>'+(f.n?n1(f.mean)+tval(f.t):'–')+'</td>'
      +'<td>'+(bt.n?int(bt.n)+' · '+n1(bt.mean):'–')+(hv[0]&&hv[1]&&hv[0].n&&hv[1].n?'<br><span class="nm">halves '+n1(hv[0].mean)+' / '+n1(hv[1].mean)+'</span>':'')+'</td>'
      +'<td class="l">'+vchip(l.verdict)+'</td><td class="l">'+esc(ymd(r.status==='live'?r.since:r.added))+(r.source&&r.source!=='pool'?' <span class="nm">'+esc(r.source)+'</span>':'')+'</td></tr>';});
  var body='<p class="trk-note">Forward: trades opened since the rule joined the bench (or went live), under the live exit, after costs. Backtest: the same rule on the last '+(c.path_days||14)+' days of the path the scanner keeps; it ranks rules, but only the forward record can promote one. A rule is retired after '+c.retire_after+' reviews in a row of losing, or when it fires too rarely to judge, and the next one from the pool, or one built from a variable that shows a signal, takes its place.</p>'
    +table(['Rule','<Status','Forward trades','Made money','Average after costs','Backtest: trades · average','<Verdict','<Since'],rows)
    +(nm?'<p class="fine">'+nm+' machine-learning models are on the same bench, judged on the same bar; their records are on the <button type="button" class="linkbtn" id="tr-models-go">Models tab</button>. A model that earns a live signal shows above with the rules.</p>':'');
  if(gone.length)body+='<details class="rv-gone"><summary>Retired rules ('+gone.length+')</summary><ul class="rv-log">'+gone.map(function(r){return '<li><b>'+esc(r.label)+'</b>: '+esc(r.reason||'')+'</li>';}).join('')+'</ul></details>';
  return sec('Rules under test',body,'tr-bench');
}

/* quick rules on the minute data (undertow/fast.py): their own bench, their trades, and the exits on quick entries */
function quickSec(){
  var Q=T.quick;if(!Q)return '';
  var M=Q.minute||{},K=Q.ticks||{},F=Q.cfg||{},c=T.cfg||{},body='';
  body+='<p class="trk-note">While each scan works out its gates (10 to 15 minutes), the scanner reads DEX Screener once a minute for every coin inside the screener, close to passing, recently passing or held in a paper trade: price, liquidity, 5-minute volume, 5-minute buys and sells, boosts, plus GeckoTerminal’s 5-minute trending list and DEX Screener’s new boosts and ads every 2 minutes. Every open paper trade, from every rule, is stepped on those minutes, so a stop or a target fills within a minute of being reached instead of at the next scan. The quick rules below look at every minute and may buy a coin that passed every gate at the previous scan; each is judged on its own exit (15 minutes to 2 hours), on the same bar as every rule: at least '+int(c.min_trades)+' trades that have had time to close, averaging '+n1(c.min_edge)+' or better after costs with t ≥ '+c.z+', in '+c.promote_after+' weekly reviews in a row. The random control buys a random 0.5% of minutes on the same coins: what a quick rule has to beat.</p>';
  body+='<p class="fine">'+(K.rows?int(K.rows)+' minute readings of '+int(K.coins)+' coins kept (the last '+(F.keep_h||36)+' hours), the latest '+esc(ago(K.last)):'No minute readings yet')+'. '
    +(M.rounds?'This scan: '+int(M.rounds)+' rounds between '+esc(when(M.from))+' and '+esc(when(M.to))+' on '+int(M.coins)+' coins'+(M.errors?' ('+int(M.errors)+' failed)':'')+'; GeckoTerminal’s 5-minute trending list read '+int(M.gt_ok)+' of '+int(M.gt_tries)+' times; '+int(M.closed)+' paper trades closed on the minute data and '+int(M.opened)+' quick trades opened. Quick rules could buy '+int(M.eligible)+' coins.':'')+'</p>';
  var R=(Q.rules||[]).filter(function(r){return r.status!=='retired';}).sort(function(a,b){return (b.status==='live')-(a.status==='live')||(((b.fwd_now||{}).mean||-99)-((a.fwd_now||{}).mean||-99));});
  body+=R.length?table(['Quick rule','<Exit','<Status','Forward trades','Made money','Average after costs','<Verdict','<Since'],R.map(function(r){var f=r.fwd_now||{},l=r.last||{};
    return '<tr><td class="l qrule">'+esc(r.label)+(r.all&&r.all.length?'<br><span class="nm">'+conds(r)+'</span>':'')+'</td><td class="l"><span class="nm">'+esc((EX[r.exit]||{}).label||r.exit)+'</span></td><td class="l">'+stChip(r.status)+'</td>'
      +'<td>'+int(f.n||0)+(r.open?' <span class="nm">+'+r.open+' open</span>':'')+'</td><td>'+(f.n?pc(f.win*100,0):'–')+'</td><td>'+(f.n?n1(f.mean)+tval(f.t):'–')+'</td><td class="l">'+vchip(l.verdict)+'</td><td class="l">'+esc(ymd(r.status==='live'?r.since:r.added))+'</td></tr>';}),'cards')
    :'<p class="empty">The quick rules join the bench at the next scan.</p>';
  var tr=(Q.trades||[]).slice(0,40);
  if(tr.length)body+='<h3 class="sub-h">Quick trades: the latest '+tr.length+' of '+int(Q.n_trades)+'</h3>'+table(['Coin','<Rule','Bought','After costs','Held','<Why'],tr.map(function(x){var r=RU[x.rule]||{},done=x.ret!=null;
    return '<tr><td class="l">'+coinCell(x.mint,x.sym)+(x.live?' <span class="pill in">Live</span>':'')+'</td><td class="l">'+esc(clip(r.label||x.rule,70))+'</td><td>'+price(x.in_price)+'<br><span class="nm">'+esc(when(x.in_ts))+'</span></td>'
      +'<td class="'+((done?x.ret:x.now_net)>0?'tr-up':'tr-dn')+'">'+n1(done?x.ret:x.now_net)+(done?'':' <span class="nm">open</span>')+'</td><td>'+(done?heldTxt(x.h):esc(ago(x.in_ts).replace(' ago','')))+'</td><td class="l">'+esc(done?x.why:'–')+'</td></tr>';}),'cards');
  else body+='<p class="empty">No quick trade yet.</p>';
  var ex=(Q.exits||[]).filter(function(e){return (e.now||{}).n||e.quick;}).sort(function(a,b){return (b.base-a.base)||((((b.now||{}).mean)||-99)-(((a.now||{}).mean)||-99));});
  body+='<h3 class="sub-h">Exit policies on the quick entries</h3><p class="trk-note">Every quick trade is priced under every quick exit and under the live exit too, so they can be compared on the same entries: here against “'+esc(((Q.exits||[]).filter(function(e){return e.base;})[0]||{}).label||Q.base)+'”. A trade counts once every trade opened at that time could have closed under both policies.</p>'
    +table(['Exit policy','Trades','Made money','Average after costs','Against the baseline'],ex.map(function(e){var n=e.now||{};
      return '<tr'+(e.base?' class="holdrow"':'')+'><td class="l">'+esc(e.label)+(e.base?' <span class="nm">baseline</span>':'')+'</td><td>'+(n.n?int(n.n):'–')+'</td><td>'+(n.n?pc(n.win*100,0):'–')+'</td><td>'+(n.n?n1(n.mean):'–')+'</td><td>'+(e.base||!n.n||n.gain==null?'–':n1(n.gain).replace('%',' pts')+tval(n.t))+'</td></tr>';}),'cards');
  return sec('Quick trades on the minute data',body,'tr-quick');
}

function exitSec(){
  var ex=(T.exits||[]).slice().sort(function(a,b){return (b.live-a.live)||((((b.now||{}).mean)||-99)-(((a.now||{}).mean)||-99));}),c=T.cfg||{};
  var rows=ex.map(function(e){var n=e.now||{},l=e.last||{};
    return '<tr'+(e.live?' class="holdrow"':'')+'><td class="l">'+esc(e.label)+(e.live?' <span class="pill in">Live</span>':'')+(e.model?' <span class="nm">exit model</span>':'')+'</td><td>'+(n.n?int(n.n):'–')+'</td><td>'+(n.n?pc(n.win*100,0):'–')+'</td><td>'+(n.n?n1(n.mean):'–')+'</td><td>'+(e.live||!n.n||n.gain==null?'–':n1(n.gain).replace('%',' pts')+tval(n.t))+'</td><td>'+(l.n>=10?int(l.n)+' '+esc(l.basis||'')+': '+n1(l.mean):'–')+'</td></tr>';});
  var none=!ex.some(function(e){return (e.now||{}).n;});
  return sec('Exit policies compared',(ex.some(function(e){return e.reason;})?'<p class="trk-note">'+esc(ex.filter(function(e){return e.reason;}).map(function(e){return e.reason;}).join(' '))+'</p>':'')
    +(none?'<p class="trk-note"><b>Collecting.</b> A policy is compared once trades have had time to close under it and under the live one, up to 25 hours for the slowest.</p>':'')
    +'<p class="trk-note">Every paper trade is priced under every exit policy, so they are compared on the same entries. The live exit switches when another beat it by at least '+(c.switch_min_gain||1)+' point with t ≥ '+(c.z||2)+' in '+(c.switch_after||2)+' reviews in a row.</p>'
    +table(['Exit policy','Trades','Made money','Average after costs','Against the live exit','At the last review'],rows),'tr-exits');
}

function barsSvg(fs){
  if(!fs||!fs.length)return '';var W=80,H=24,bw=W/fs.length,vals=fs.map(function(f){return f.mean||0;}),mx=Math.max.apply(null,vals.map(Math.abs).concat([1]));
  return '<svg class="fifths" viewBox="0 0 '+W+' '+H+'" width="'+W+'" height="'+H+'" role="img" aria-label="Average return after costs in each fifth, lowest values first: '+vals.map(function(v){return n1(v);}).join(', ')+'"><line class="base" x1="0" x2="'+W+'" y1="'+H/2+'" y2="'+H/2+'"/>'
    +vals.map(function(v,i){var h=Math.max(1,Math.abs(v)/mx*(H/2-1));return '<rect class="'+(v<0?'neg':'pos')+'" x="'+(i*bw+1).toFixed(1)+'" y="'+(v<0?H/2:H/2-h).toFixed(1)+'" width="'+(bw-2).toFixed(1)+'" height="'+h.toFixed(1)+'" rx="1"/>';}).join('')+'</svg>';
}
function varSec(){
  var RK={signal:0,'no signal':1,collecting:2};
  var vs=(T.vars||[]).filter(function(v){return v.last;}).sort(function(a,b){return (RK[a.last.verdict]-RK[b.last.verdict])||(Math.abs(b.last.rho2||0)-Math.abs(a.last.rho2||0));});
  if(!vs.length)return sec('Variables','<p class="empty">Scored at the first review.</p>','tr-vars');
  var rows=vs.map(function(v){var l=v.last;return '<tr><td class="l">'+esc(v.label)+(v.status==='retired'?' <span class="nm">set aside</span>':'')+'</td><td>'+int(l.n)+'</td><td>'+(l.rho1==null?'–':l.rho1.toFixed(2)+' / '+l.rho2.toFixed(2))+'</td><td class="l">'+barsSvg(l.fifths)+'</td><td class="l">'+(l.better?(l.better==='high'?'higher is better':'lower is better'):'–')+'</td><td class="l">'+vchip(l.verdict)+'</td></tr>';});
  return sec('Variables','<p class="trk-note">For every reading of a coin that passed every gate: the return over the next 4 hours after costs, against each variable. Rank correlation in the earlier and the later half of the window; bars are the average in each fifth, lowest values first. A signal needs the same sign in both halves and at least '+((T.cfg||{}).var_min_rho||0.05)+' in each. Variables with a signal seed new rules; ones with none in three reviews in a row stop seeding them until a later check.</p>'
    +table(['Variable','Readings','Rank correlation, halves','<Average by fifth','<Direction','<Verdict'],rows),'tr-vars');
}

function studySec(){
  var S=T.study;if(!S)return '';
  return sec('What the history said before the first trade','<div class="tr-study"><p><b>'+esc(S.period)+'</b>: '+esc(S.sample)+'.</p>'
    +(S.findings||[]).map(function(f){return '<p>'+esc(f)+'</p>';}).join('')
    +'<p class="fine">Replayed on GeckoTerminal’s 5-minute candles for every coin the scanner had seen in range, each from the moment the scanner first saw it, priced once every 15 minutes as a scan would, with the costs above. It chose which rules and exits went on the bench first; only the forward record decides what goes live.</p></div>','tr-study');
}
function logSec(){
  var L=T.log||[];if(!L.length)return '';
  return sec('Changes','<ul class="rv-log">'+L.map(function(e){return '<li><b>'+esc(ymd(e.ts))+'</b> '+esc(e.what)+': '+esc(e.label)+'. '+esc(e.reason)+'</li>';}).join('')+'</ul>');
}

/* ---- render ---- */
function render(){
  var w=$('#tradewrap');if(!w)return;load();
  if(!T){w.innerHTML='<p class="empty">The buy and sell ledger starts with the next scan.</p>';return;}
  var y=window.scrollY;
  w.innerHTML=head()+buySec()+openSec()+warnSec()+recordSec()+benchSec()+quickSec()+exitSec()+varSec()+studySec()+logSec();
  $$('[data-tk]',w).forEach(function(b){b.onclick=function(){U.open(b.dataset.tk);};});
  var mg=$('#tr-models-go',w);if(mg)mg.onclick=function(){U.setView('models');};
  /* card tables stack into labelled rows on a phone: each cell carries its column's name */
  $$('table.cards',w).forEach(function(t){var hs=$$('thead th',t).map(function(th){return th.textContent;});
    $$('tbody tr',t).forEach(function(tr){$$('td',tr).forEach(function(td,i){td.setAttribute('data-label',hs[i]||'');
      if(i&&td.childNodes.length>1)td.innerHTML='<div class="cv">'+td.innerHTML+'</div>';});});});
  paintLive();window.scrollTo(window.scrollX,y);painted=Date.now();
}
function paintLive(){
  var w=$('#tradewrap');if(!w||!T)return;
  $$('[data-tl]',w).forEach(function(el){var p=el.dataset.tl.split(':'),k=p[0],id=p.slice(1).join(':');
    if(k==='px'){var q=liveOf(id);if(q&&q.price)el.textContent=price(q.price);}
    else{var x=(T.open||[]).filter(function(o){return String(o.id)===id;})[0];if(!x)return;var q2=liveOf(x.mint);
      if(k==='pl'&&q2&&q2.price){var v=netAt(q2.price/x.in_price,x.in_liq,q2.liq||x.in_liq);el.textContent=n1(v);el.className=v>0?'tr-up':'tr-dn';}
      if(k==='st'){var s=sellState(x);el.innerHTML='<span class="'+(s[0]==='sell'?'tr-sell':'tr-hold')+'">'+(s[0]==='sell'?'<b>Sell</b> · ':'')+esc(s[1])+'</span>';}}});
}

/* ---- the X-ray's line: is this coin a buy signal, an open trade, or in a warning state? ---- */
function xray(k){
  var s=$('#xr-trade');if(!s)return;load();if(!T||!k){s.hidden=true;return;}
  var sig=(T.signals||[]).filter(function(x){return x.mint===k.id;})[0],op=(T.open||[]).filter(function(x){return x.mint===k.id;})[0],
      wn=(T.warnings||[]).filter(function(x){return x.mint===k.id;})[0],out=[];
  if(op){var st=sellState(op);out.push('<p class="'+(st[0]==='sell'?'tr-sell':'tr-hold')+'"><b>'+(st[0]==='sell'?'Sell signal':'Open paper trade')+'</b>: bought '+esc(ago(op.in_ts))+' at '+price(op.in_price)+' by “'+esc((RU[op.rule]||{}).label||op.rule)+'”. '+esc(st[1])+'.</p>');}
  if(sig){var ids=sig.rules.filter(function(id){return !sig.live||(RU[id]||{}).status==='live';}),nm=ids.slice(0,3).map(function(id){return '“'+esc((RU[id]||{}).label||id)+'”';}).join(', ')+(ids.length>3?' and '+(ids.length-3)+' more':'');
    out.push('<p class="'+(sig.live?'tr-buy':'tr-hold')+'"><b>'+(sig.live?'Buy signal':'Under test')+'</b>: matches '+nm+(sig.live?'.':(ids.length>1?', rules that have':', a rule that has')+' not earned a live signal.')+'</p>');}
  if(wn){var R={};(T.warning_rules||[]).forEach(function(w){R[w.id]=w;});
    out.push('<p class="tr-warn"><b>Warning</b>: '+wn.ids.map(function(i){var r=R[i]||{},l=r.last||{},a=l['in']||{};return esc(r.label||i)+(a.n?' (coins in this state moved '+n1(a.mean)+' on average over the next 4h; '+pc((l.share_lower||0)*100,0)+' were lower)':'');}).join('; ')+'.</p>');}
  if(!out.length){s.hidden=true;return;}
  s.innerHTML='<h3>Buy &amp; sell</h3>'+out.join('')+'<p class="fine"><button type="button" class="linkbtn" id="xr-trade-go">Open the Buy &amp; sell tab</button></p>';s.hidden=false;
  var g=$('#xr-trade-go');if(g)g.onclick=function(){U.setView('trade');};
}

U.on('data',function(){load();if(U.view()==='trade')render();});
U.on('view',function(v){if(v==='trade')render();});
U.on('live',function(){if(U.view()!=='trade')return;if(Date.now()-painted>30000)render();else paintLive();});
U.on('xray',xray);
if(U.data()){load();if(U.view()==='trade')render();}
})();
