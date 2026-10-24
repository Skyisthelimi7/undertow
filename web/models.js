/* ---------- Models: machine-learning entry and exit models, walk-forward test and forward paper ledger (undertow/models.py) ---------- */
(function(){
'use strict';
var U=window.Undertow;if(!U)return;
var doc=document,$=function(s,r){return (r||doc).querySelector(s);},$$=function(s,r){return Array.prototype.slice.call((r||doc).querySelectorAll(s));};
var esc=U.esc,usd=U.usd,pc=U.pc,ago=U.ago,int=U.int,MINUS='−',D=null,M=null,CH=null;
var st={set:'*',kind:'all',sort:'pick_net'};
try{var sv=JSON.parse(localStorage.getItem('undertow-models')||'null');if(sv&&sv.sort&&sv.set!=='all')st=sv;}catch(e){}
function save(){try{localStorage.setItem('undertow-models',JSON.stringify(st));}catch(e){}}

/* ---- formatting ---- */
function n1(v){return v==null||isNaN(v)?'–':(v<0?MINUS:'+')+Math.abs(v).toFixed(Math.abs(v)<10?1:0)+'%';}
function n2(v){return v==null||isNaN(v)?'–':(v<0?MINUS:'+')+Math.abs(v).toFixed(2)+'%';}
function f3(v){return v==null||isNaN(v)?'–':v.toFixed(3);}
function f2(v){return v==null||isNaN(v)?'–':(v<0?MINUS:'')+Math.abs(v).toFixed(2);}
function tval(t){return t==null?'':' <span class="nm">t '+(t<0?MINUS:'')+Math.abs(t).toFixed(1)+'</span>';}
function utc(ts){return ts?new Date(ts*1000).toISOString().slice(0,16).replace('T',' ')+' UTC':'–';}
function price(v){if(v==null)return 'n/a';if(v>=1)return '$'+v.toPrecision(4);var s=v.toPrecision(3);return '$'+(s.indexOf('e')>=0?Number(s).toFixed(12).replace(/0+$/,''):s);}
function sec(title,body,id){return '<section class="lab-sec"'+(id?' id="'+id+'"':'')+'><h3>'+title+'</h3>'+body+'</section>';}
function kpi(k,v,s){return '<div class="kpi"><div class="k">'+k+'</div><div class="v">'+v+'</div><div class="s">'+s+'</div></div>';}
function table(head,rows,cls){return '<div class="tscroll"><table class="grid lab mdl'+(cls?' '+cls:'')+'"><thead><tr>'+head.map(function(h,i){return '<th'+(i===0||h.charAt(0)==='<'?' class="l"':'')+'>'+h.replace(/^</,'')+'</th>';}).join('')+'</tr></thead><tbody>'+rows.join('')+'</tbody></table></div>';}
function coin(m,sym){return '<button type="button" class="linkbtn tkbtn" data-tk="'+esc(m)+'">'+esc(sym||m.slice(0,5))+'</button>';}
var STAT={live:['in','Live'],testing:['entering','Testing'],retired:['out','Retired']};
function stChip(s){if(!s)return '<span class="nm">not on the bench</span>';var m=STAT[s]||['out',s];return '<span class="pill '+m[0]+'">'+m[1]+'</span>';}
var VERD={earns:['works','Earns'],loses:['hurts','Loses'],unclear:['none','Unclear'],collecting:['coll','Collecting']};
function vchip(v){var m=VERD[v]||VERD.collecting;return '<span class="vchip '+m[0]+'">'+m[1]+'</span>';}
function setLabel(s){return (((M&&M.sets)||{})[s])||(s==='none'?'no variables':s);}
function varLabel(k){var L=((D.lab||{}).variables||[]).filter(function(v){return v.key===k;})[0]||((D.trade||{}).vars||[]).filter(function(v){return v.key===k;})[0];
  var S={held_h:'Hours held',ret_now:'Return so far',peak_ret:'Peak return so far',dd_peak:'Fall from the peak',liq_ratio:'Liquidity vs entry'};return (L&&L.label)||S[k]||k;}
function lead(l){return (l||[]).slice(0,3).map(function(x){return esc(varLabel(x[0]))+' <span class="ip">'+Math.round(x[1]*100)+'%</span>';}).join('<br>')||'<span class="ip">–</span>';}
function kindName(k){return k==='ret'?'return model':(k==='seq'?'sequence model':(k==='random'?'control':'classifier'));}
function dol(v){return v==null||isNaN(v)?'–':(v>0?'+':'')+usd(v);}
function hasP(m){return m&&m.pnl&&(m.pnl.n||m.pnl.n_open);}
function pnlCell(p){if(!p||!(p.n||p.n_open))return '<span class="nm">no trades yet</span>';
  return '<span class="'+(p.total>0?'tr-up':'tr-dn')+'">'+dol(p.total)+'</span><span class="nm">'+int(p.n)+' closed '+dol(p.real)+(p.n_open?' · '+int(p.n_open)+' open '+dol(p.open):'')+'</span>';}

/* ---- sections ---- */
function head(){
  var E=(M.entry||[]).filter(function(m){return !m.error;}),ctl=E.filter(function(m){return m.id==='random';})[0]||{};
  var real=E.filter(function(m){return m.id!=='random'&&m.pick_net!=null;}).sort(function(a,b){return b.pick_net-a.pick_net;});
  var best=real[0],beat=real.filter(function(m){return m.beats_luck;}).length,profit=real.filter(function(m){return m.pick_net>0;}).length;
  var live=E.filter(function(m){return m.status==='live';}).length,c=M.cfg||{},P=M.pnl_all||{};
  var byP=real.filter(hasP).sort(function(a,b){return b.pnl.total-a.pnl.total;}),bp=byP[0];
  var fN=real.filter(function(m){return (m.fwd||{}).n;}),t2=fN.filter(function(m){return m.fwd.t!=null&&m.fwd.t>=2;}).length;
  return '<div class="trk-head"><div class="kpis">'
    +(M.status==='ok'?kpi('Last trained',esc(ago(M.trained_at,D.generated_at)),esc(utc(M.trained_at))+' · every '+(c.every_h||6)+'h')
      :kpi('Last trained','Not yet',M.trained_at?'checked '+esc(ago(M.trained_at,D.generated_at))+' · again every '+(c.every_h||6)+'h':'the training job runs every '+(c.every_h||6)+' hours'))
    +kpi('Training data',M.samples?int(M.samples)+' samples':'–',M.samples?int(M.coins)+' coins'+(M.period?', '+esc(utc(M.period[0]).slice(0,10))+' to '+esc(utc(M.period[1]).slice(0,10)):(M.status==='ok'?'':' · training starts at '+int(c.min_samples||1200)+' on '+int(c.min_coins||40))):'')
    +kpi('Best out of sample',best?n1(best.pick_net):'–',best?esc(best.algo)+', '+esc(setLabel(best.set))+' · all samples '+n1(best.base_net):'top fifth of each model’s scores, after costs')
    +kpi('Beat the luck line',real.length?int(beat)+' of '+int(real.length):'–',real.length?int(profit)+' made money after costs out of sample':'')
    +kpi('Paper P/L, every model',P.models?dol(P.total):'–',P.models?int(P.n)+' trades at '+usd(M.pnl_usd||100)+' since each started · '+int(P.up)+' of '+int(P.models)+' in profit · '+int(live)+' live':'once the models trade')
    +kpi('Best model’s P/L',bp?dol(bp.pnl.total):'–',bp?esc(bp.algo)+', '+esc(setLabel(bp.set))+(hasP(ctl)?' · random control '+dol(ctl.pnl.total):''):'')
    +kpi('Forward t ≥ 2',fN.length?int(t2)+' of '+int(fN.length):'–',fN.length?'with no edge at all, luck alone gives about '+(fN.length*0.023).toFixed(1):'')
    +kpi('Random control',ctl.pick_net!=null?n1(ctl.pick_net):'–','what a random fifth averaged out of sample')
    +'</div><p class="trk-note">Paper trades, not advice. Every model is tested twice. <b>Walk-forward</b>: trained only on trades that had closed before each test window opened, then scored on the window, so no training trade reaches into a test one; every figure in the table below is out of sample. <b>Forward</b>: from the moment it is trained, each model buys on paper whenever a coin that passes every gate scores in the top '+pc((c.top_share||0.2)*100,0)+' of what its training data scored, and its record is judged like any rule’s: a live buy signal needs '+int((D.trade||{}).cfg&&(D.trade.cfg.min_trades)||30)+' settled trades averaging '+n1(((D.trade||{}).cfg||{}).min_edge||1)+' or better after costs with t ≥ '+(((D.trade||{}).cfg||{}).z||2)+', in two weekly reviews in a row.</p></div>';
}

function entrySec(){
  var E=(M.entry||[]).slice(),c=M.cfg||{};
  if(!E.length){var c2=M.cfg||{},msg=/^collecting/.test(M.status||'')&&M.samples!=null
      ?'Training starts once the Buy &amp; sell path holds '+int(c2.min_samples||1200)+' labelled samples on '+int(c2.min_coins||40)+' coins (one per coin per hour, each a paper trade that has had time to close) and enough history for a walk-forward test. So far: '+int(M.samples)+' samples on '+int(M.coins)+' coins'+(M.trained_at?', checked '+esc(ago(M.trained_at,D.generated_at)):'')+'. Every algorithm’s result in the candle study is below in the meantime.'
      :esc(M.status||'Waiting for the first training run')+'.';
    return sec('Entry models','<p class="empty">'+msg+'</p>','md-entry');}
  var sets=[];E.forEach(function(m){if(m.set&&m.set!=='none'&&sets.indexOf(m.set)<0)sets.push(m.set);});
  E=E.filter(function(m){return (st.set==='*'||m.set===st.set||m.id==='random')&&(st.kind==='all'||m.kind===st.kind||m.id==='random');});
  var sk=function(m){var v=st.sort==='fwd'?((m.fwd||{}).n?(m.fwd||{}).mean:null):(st.sort==='pnl'?(hasP(m)?m.pnl.total:null):m[st.sort]);return v==null?-1e9:v;};
  E.sort(function(a,b){return (b.error?-1:0)-(a.error?-1:0)||sk(b)-sk(a);});
  var rows=E.map(function(m){
    if(m.error)return '<tr><td class="l"><b>'+esc(m.algo)+'</b><br><span class="nm">'+esc(m.family||'')+'</span></td><td class="l">'+esc(setLabel(m.set))+'</td><td class="l" colspan="20"><span class="tr-dn">Failed to train: '+esc(m.error)+'</span></td></tr>';
    var f=m.fwd||{},le=m.last_entry,gapCls=m.gap!=null&&m.gap>0.15?' class="tr-dn"':'';
    var aucCell=m.kind==='ret'?f3(m.auc)+'<span class="nm">rank IC '+f2(m.ic)+'</span>':f3(m.auc)+(m.auc_sd!=null?'<span class="nm">± '+f3(m.auc_sd)+'</span>':'');
    return '<tr'+(m.id==='random'?' class="holdrow"':'')+'><td class="l"><b>'+esc(m.algo)+'</b><br><span class="nm">'+esc(m.family||'')+' · '+esc(kindName(m.kind))+'</span></td>'
      +'<td class="l">'+esc(setLabel(m.set))+'<br><span class="nm">'+int(m.n_vars||0)+' variables</span></td>'
      +'<td class="l">'+stChip(m.status)+(m.status?'<br>'+vchip(m.verdict):'')+'</td>'
      +'<td>'+aucCell+'</td><td>'+f3(m.train_auc)+'</td><td'+gapCls+'>'+(m.gap==null?'–':(m.gap<0?MINUS:'+')+Math.abs(m.gap).toFixed(3))+'</td>'
      +'<td>'+(m.accuracy==null?'–':pc(m.accuracy*100,1))+'</td><td>'+(m.balanced_acc==null?'–':pc(m.balanced_acc*100,1))+'</td>'
      +'<td>'+(m.brier==null?'–':f3(m.brier)+'<span class="nm">log loss '+f3(m.logloss)+'</span>')+'</td>'
      +'<td>'+int(m.picks||0)+'<span class="nm">'+int(m.pick_coins||0)+' coins</span></td><td>'+(m.pick_win==null?'–':pc(m.pick_win*100,0))+'</td>'
      +'<td class="'+(m.pick_net>0?'tr-up':'tr-dn')+'">'+n2(m.pick_net)+tval(m.pick_t)+'</td><td>'+n2(m.base_net)+'</td>'
      +'<td>'+(m.edge==null?'–':(m.edge<0?MINUS:'+')+Math.abs(m.edge).toFixed(2)+' pts')+'</td>'
      +'<td>'+n2(m.luck_best)+'<span class="nm">one draw '+n2(m.luck_one)+'</span></td><td>'+(m.beats_luck?'<span class="vchip works">Yes</span>':'<span class="vchip none">No</span>')+'</td>'
      +'<td class="l lean">'+lead(m.leading)+'</td>'
      +'<td>'+int(m.trades||0)+(m.open?'<span class="nm">'+int(m.open)+' open</span>':'')+'</td>'
      +'<td>'+(f.n?pc(f.win*100,0)+' won':'–')+'</td><td class="'+(f.n?(f.mean>0?'tr-up':'tr-dn'):'')+'">'+(f.n?n1(f.mean)+tval(f.t):'–')+'</td>'
      +'<td>'+pnlCell(m.pnl)+'</td>'
      +'<td class="l lean">'+(le?coin(le.mint,le.sym)+'<br><span class="nm">'+esc(utc(le.ts))+'</span>':'<span class="nm">none yet</span>')+'</td>'
      +'<td>'+int(m.now||0)+'</td></tr>';});
  var seg=function(kind,opts){return '<div class="seg" role="group">'+opts.map(function(o){return '<button type="button" data-m'+kind+'="'+o[0]+'" aria-pressed="'+(st[kind]===o[0])+'">'+esc(o[1])+'</button>';}).join('')+'</div>';};
  var ctl='<div class="md-ctl">'+seg('set',[['*','All variable sets']].concat(sets.map(function(s){return [s,setLabel(s)];})))
    +seg('kind',[['all','All kinds'],['cls','Classifiers'],['ret','Return models'],['seq','LSTM']])
    +seg('sort',[['pick_net','Sort: out-of-sample picks'],['auc','AUC'],['edge','Edge'],['fwd','Forward record'],['pnl','Paper P/L']])+'</div>';
  var body='<p class="trk-note">Trained only on real data: this scanner’s own readings of real coins and what their prices did next; nothing simulated or made up. Label: '+esc(((M.label||{}).text)||'the paper trade made money after costs')+'. One sample per coin per hour (its first reading that hour while passing every gate), '+int(M.samples||0)+' in all, '+int(M.folds||0)+' walk-forward folds. All test samples averaged <b>'+n2(M.base_oos_net)+'</b> after costs; a model is useful only if its picks beat that, beat the luck line, and clear costs.</p>'
    +ctl+table(['Algorithm','<Variables','<Status','AUC (test)','AUC (training)','Overfit gap','Accuracy','Balanced accuracy','Brier','Picks (test)','Picks won','Picks: average after costs','All test samples','Edge','Luck line (best of '+int((M.entry||[]).length)+')','Beats luck','<Leans on','Forward trades','Forward won','Forward average','Paper P/L since it started','<Last entry','Picks now'],rows,'wide cards')
    +'<p class="fine"><b>AUC</b>: how well the scores rank winners above losers on data the model never saw (0.5 is chance). <b>Overfit gap</b>: training AUC minus test AUC; red above 0.15, where a model has learned its training coins rather than the market. <b>Accuracy</b> calls a trade a winner at a probability of 0.5 or more (for return models, a predicted return above zero). <b>Picks</b>: the test samples that scored in the top '+pc((c.top_share||0.2)*100,0)+' of the scores the model gave its own training data, the trades it would have made. <b>Luck line</b>: the 95th percentile of what the luckiest of '+int((M.entry||[]).length)+' random pickers would have averaged with the same number of picks in each fold; beating it means a model did better than luck alone would let the best of this many models look. t: errors clustered by coin. <b>Leans on</b>: the variables with the largest share of the model’s importance (trees) or weight (linear), where the library reports it.</p>';
  return sec('Entry models: when to buy',body,'md-entry');
}

/* every model's realised paper P/L as its trades closed (faint), the median model, the best total and the random control */
function niceStep(span){var r=span/4,m=Math.pow(10,Math.floor(Math.log10(Math.max(r,1e-9))));return [1,2,2.5,5,10].map(function(k){return k*m;}).filter(function(v){return v>=r;})[0]||10*m;}
function pnlChart(S,mods,ctl,W){
  var V=S.v,n=S.n,keys=mods.map(function(m){return m.rule;}).filter(function(k){return V[k];});
  var ck=ctl&&V[ctl.rule]?ctl.rule:null,best=mods.filter(function(m){return V[m.rule];})[0];
  if(!keys.length||n<2)return '';
  var med=[];for(var i=0;i<n;i++){var c=keys.map(function(k){return V[k][i];}).sort(function(a,b){return a-b;}),h=c.length>>1;med.push(c.length%2?c[h]:(c[h-1]+c[h])/2);}
  var vals=[0];keys.concat(ck?[ck]:[]).forEach(function(k){vals=vals.concat(V[k]);});
  var lo=Math.min.apply(null,vals),hi=Math.max.apply(null,vals);if(hi-lo<20){hi+=10;lo-=10;}
  var stp=niceStep(hi-lo);lo=Math.floor(lo/stp)*stp;hi=Math.ceil(hi/stp)*stp;
  var Hh=Math.round(Math.min(300,Math.max(210,W*0.42))),l=58,r=12,t=10,b=24;
  var X=function(i){return l+(W-l-r)*i/(n-1);},Y=function(v){return t+(Hh-t-b)*(hi-v)/(hi-lo);};
  var line=function(a){return a.map(function(v,i){return (i?'L':'M')+X(i).toFixed(1)+' '+Y(v).toFixed(1);}).join('');};
  var g='';for(var v=lo;v<=hi+1e-9;v+=stp)g+='<line class="'+(Math.abs(v)<1e-9?'zero':'gl')+'" x1="'+l+'" x2="'+(W-r)+'" y1="'+Y(v).toFixed(1)+'" y2="'+Y(v).toFixed(1)+'"/><text x="'+(l-6)+'" y="'+(Y(v)+4).toFixed(1)+'" text-anchor="end">'+esc(Math.abs(v)<1e-9?'$0':dol(v))+'</text>';
  var tAt=function(i){return utc(S.t0+(i+1)*S.step).slice(5,16).replace('-','/');},xt='';
  [0,Math.round((n-1)/2),n-1].forEach(function(i,j){xt+='<text x="'+X(i).toFixed(1)+'" y="'+(Hh-6)+'" text-anchor="'+(j===0?'start':(j===2?'end':'middle'))+'">'+esc(tAt(i))+'</text>';});
  var faint=keys.filter(function(k){return !best||k!==best.rule;}).map(function(k){return '<path class="ml" d="'+line(V[k])+'"/>';}).join('');
  CH={S:S,mods:mods,ctl:ctl,W:W};
  var svg='<svg class="pnl-chart" viewBox="0 0 '+W+' '+Hh+'" width="'+W+'" height="'+Hh+'" role="img" aria-label="Realised paper profit and loss of each model since it started, by the time its trades closed: best total '+esc(best?best.algo+' '+dol(best.pnl.total):'')+', median model '+esc(dol(med[n-1]))+(ck?', random control '+esc(dol(V[ck][n-1])):'')+'">'
    +g+xt+faint+'<path class="med" d="'+line(med)+'"/>'+(ck?'<path class="ctl" d="'+line(V[ck])+'"/>':'')+(best?'<path class="best" d="'+line(V[best.rule])+'"/>':'')+'</svg>';
  var key='<div class="pnl-key"><span><i class="k-best"></i>Best total: '+esc(best.algo)+', '+esc(setLabel(best.set))+'</span><span><i class="k-med"></i>Median model</span>'+(ck?'<span><i class="k-ctl"></i>Random control</span>':'')+'<span><i class="k-ml"></i>The other '+int(keys.length-1)+' models</span></div>';
  return {svg:svg,key:key};
}
/* the chart is drawn at the width it gets, so its text stays legible on a phone */
function chartHtml(S,mods,ctl,W){var c=pnlChart(S,mods,ctl,W);return c?'<div class="pnl-wrap">'+c.svg+'</div>'+c.key:'';}
function fitChart(){var pw=$('#modelswrap .pnl-wrap');if(!pw||!CH)return;var cw=Math.max(280,Math.min(980,pw.clientWidth));
  if(Math.abs(cw-CH.W)>2){var c=pnlChart(CH.S,CH.mods,CH.ctl,cw);if(c)pw.innerHTML=c.svg;}}
function pnlSec(){
  var E=(M.entry||[]).filter(function(m){return !m.error&&hasP(m);});
  if(!E.length)return '';
  E.sort(function(a,b){return b.pnl.total-a.pnl.total;});
  var ctl=E.filter(function(m){return m.id==='random';})[0],mods=E.filter(function(m){return m.id!=='random';}),u=M.pnl_usd||100;
  var first=Math.min.apply(null,E.map(function(m){return m.pnl.first||1e12;}));
  var W=Math.max(280,Math.min(980,(($('#modelswrap')||{}).clientWidth||720)-40));
  var top=mods.slice(0,10).concat(ctl?[ctl]:[]);
  var rows=top.map(function(m){var p=m.pnl,k=p.n+p.n_open;
    return '<tr'+(m.id==='random'?' class="holdrow"':'')+'><td class="l"><b>'+esc(m.algo)+'</b><br><span class="nm">'+esc(m.id==='random'?'the control':setLabel(m.set))+'</span></td>'
      +'<td class="'+(p.total>0?'tr-up':'tr-dn')+'"><b>'+dol(p.total)+'</b></td><td>'+dol(p.real)+'<span class="nm">'+int(p.n)+' closed'+(p.n?', '+pc(p.wins/p.n*100,0)+' won':'')+'</span></td>'
      +'<td>'+dol(p.open)+'<span class="nm">'+int(p.n_open)+' open</span></td><td>'+(k?dol(p.total/k):'–')+'<span class="nm">'+(k?n1(p.total/k/u*100)+' of '+usd(u):'')+'</span></td>'
      +'<td>'+int(p.peak)+'<span class="nm">'+usd(p.peak*u)+' at work</span></td><td class="l">'+esc(utc(p.first))+'</td></tr>';});
  var body='<p class="trk-note">Every model’s paper trades from the moment it started ('+esc(utc(first).slice(0,10))+' for the first models), at '+usd(u)+' a trade after fees, price impact and network fees: closed trades at their result, open ones at their last price after the cost of selling there. Every trade counts from the moment it opens, so a total leaves nothing out. Take-profits fill at their target, as an order resting at the target would, even when the price read just after was higher (since 24 Oct, applied to every recorded trade).</p>'
    +(M.pnl_series&&M.pnl_series.n>1?chartHtml(M.pnl_series,mods,ctl,W):'')
    +'<h3 class="sub-h">The ten best totals, and the random control</h3>'
    +table(['Model','Total','Closed','Open','Per trade','Most open at once','<First trade'],rows,'cards')
    +'<p class="fine">The chart counts each trade when it closed (realised); the totals add the open trades at their last price. <b>Most open at once</b>: the money a model had at work at its busiest, at '+usd(u)+' a trade. Sort the table below by <b>Paper P/L</b> for every model.</p>';
  return sec('Paper profit and loss since each model started',body,'md-pnl');
}

function exitSec(){
  var X=(M.exit||[]).slice();
  if(!X.length)return sec('Exit models: when to sell','<p class="empty">'+(M.status==='ok'?'Not enough open-trade history yet to train them.':esc(M.status||'Waiting for the first training run'))+'.</p>','md-exit');
  var thr=(M.cfg||{}).exit_thr||0.5;
  var rows=X.map(function(e){
    if(e.error)return '<tr><td class="l"><b>'+esc(e.algo)+'</b></td><td class="l" colspan="16"><span class="tr-dn">Failed to train: '+esc(e.error)+'</span></td></tr>';
    var f=e.fwd||{};
    return '<tr'+(e.live?' class="holdrow"':'')+'><td class="l"><b>'+esc(e.algo)+'</b>'+(e.live?' <span class="pill in">Live exit</span>':'')+'<br><span class="nm">'+esc(e.family||'')+' · '+int(e.n_vars||0)+' variables</span></td>'
      +'<td>'+int(e.decisions||0)+'</td><td>'+f3(e.auc)+'</td><td>'+f3(e.train_auc)+'</td><td'+(e.gap>0.15?' class="tr-dn"':'')+'>'+(e.gap==null?'–':(e.gap<0?MINUS:'+')+Math.abs(e.gap).toFixed(3))+'</td>'
      +'<td>'+(e.accuracy==null?'–':pc(e.accuracy*100,1))+'</td><td>'+(e.sell_rate==null?'–':pc(e.sell_rate*100,0))+'</td>'
      +'<td>'+int(e.trades||0)+'</td><td>'+n2(e.net)+'</td><td>'+n2(e.base_net)+'</td><td class="'+(e.gain>0?'tr-up':'tr-dn')+'">'+(e.gain==null?'–':(e.gain<0?MINUS:'+')+Math.abs(e.gain).toFixed(2)+' pts')+tval(e.gain_t)+'</td>'
      +'<td>'+(e.early==null?'–':pc(e.early*100,0))+'</td><td class="l lean">'+lead(e.leading)+'</td>'
      +'<td>'+(f.n?int(f.n):'–')+'</td><td>'+(f.n?n2(f.mean):'–')+'</td><td>'+(f.n&&f.gain!=null?(f.gain<0?MINUS:'+')+Math.abs(f.gain).toFixed(2)+' pts'+tval(f.t):'–')+'</td></tr>';});
  var body='<p class="trk-note">At every scan, every open paper trade is asked: would selling now beat holding on to the live exit ('+esc(((M.live_exit||{}).label)||'')+')? An exit model sells when its probability reaches '+thr+'; the live exit’s target and time limit still apply, so it can only sell earlier. Walk-forward figures replay each model’s calls, scan by scan, on test trades it never saw; forward figures compare it with the live exit on the same paper trades since it was trained.</p>'
    +table(['Exit model','Decisions (test)','AUC (test)','AUC (training)','Overfit gap','Accuracy','Says sell','Test trades','Following it','Live exit','Gain','Sold early','<Leans on','Forward trades','Forward average','Forward gain'],rows,'wide cards');
  return sec('Exit models: when to sell',body,'md-exit');
}

function logSec(){
  var L=M.log||[];
  if(!L.length)return sec('Model trades','<p class="empty">No model has made a paper trade yet. Each starts buying on paper on the first scan after it is trained.</p>','md-log');
  var E={};(M.entry||[]).forEach(function(m){E[m.id]=m;});
  var rows=L.slice(0,150).map(function(x){var m=E[x.model]||{},xs=(x.x_sell||[]).map(function(p){return esc(((M.exit||[]).filter(function(e){return e.id===p;})[0]||{}).algo||p);});
    var res=x.ret!=null?'<span class="'+(x.ret>0?'tr-up':'tr-dn')+'">'+n1(x.ret)+'</span><br><span class="nm">'+esc(x.why||'')+', '+(x.h!=null?x.h.toFixed(1)+'h':'')+' · '+esc(utc(x.out_ts))+'</span>'
      :'<span class="nm">open</span> '+n1(x.now_net)+(xs.length?'<br><span class="tr-sell">sell now: '+xs.join(', ')+'</span>':'');
    var xo=x.x_out?Object.keys(x.x_out).map(function(p){var e=(M.exit||[]).filter(function(q){return q.id===p;})[0]||{},v=x.x_out[p];return esc(e.algo||p)+' '+n1(v[0])+'<span class="nm">'+esc(utc(v[1]).slice(11))+'</span>';}).join(''):'<span class="nm">–</span>';
    return '<tr><td class="l">'+esc(utc(x.ts))+'</td><td class="l">'+coin(x.mint,x.sym)+'</td><td class="l">'+esc(m.algo||x.model)+'<br><span class="nm">'+esc(setLabel(m.set))+'</span></td>'
      +'<td>'+(x.sc!=null?f2(x.sc):'–')+'<span class="nm">needs '+(x.thr!=null?f2(x.thr):'a random draw')+'</span></td><td>'+price(x.price)+'</td><td>'+usd(x.mc)+'</td><td>'+usd(x.liq)+'</td>'
      +'<td class="l">'+res+'</td><td class="l">'+xo+'</td></tr>';});
  return sec('Model trades','<p class="trk-note">Every paper entry a model has made in the last '+int(((D.trade||{}).cfg||{}).window_days||28)+' days, newest first: when (UTC), the coin, the model, its score and the threshold it had to reach, and the result under the live exit after costs. The last column is the same trade under each exit model.</p>'
    +table(['<Entered (UTC)','<Coin','<Model','Score','Price','Market cap','Liquidity','<Live exit, after costs','<Under the exit models'],rows,'wide cards'),'md-log');
}

function sellLogSec(){
  var L=M.exit_log||[];if(!(M.exit||[]).length)return '';
  var X={};(M.exit||[]).forEach(function(e){X[e.id]=e;});
  if(!L.length)return sec('Exit model sales','<p class="empty">No exit model has sold a paper trade early yet.</p>','md-sells');
  var rows=L.slice(0,100).map(function(x){var d=x.live_ret!=null?x.ret-x.live_ret:null;
    return '<tr><td class="l">'+esc(utc(x.ts))+'</td><td class="l">'+coin(x.mint,x.sym)+'</td><td class="l">'+esc((X[x.model]||{}).algo||x.model)+'</td><td>'+price(x.price)+'</td><td>'+(x.h!=null?x.h.toFixed(1)+'h':'–')+'</td>'
      +'<td class="'+(x.ret>0?'tr-up':'tr-dn')+'">'+n1(x.ret)+'</td><td>'+(x.live_ret!=null?n1(x.live_ret):'<span class="nm">still open</span>')+'</td><td class="'+(d==null?'':(d>0?'tr-up':'tr-dn'))+'">'+(d==null?'–':(d<0?MINUS:'+')+Math.abs(d).toFixed(1)+' pts')+'</td></tr>';});
  return sec('Exit model sales','<p class="trk-note">Every paper trade an exit model sold before the live exit would have, newest first ('+int(M.exit_sells||0)+' in the last '+int(((D.trade||{}).cfg||{}).window_days||28)+' days): when (UTC), the coin, the model, the price it sold at, and the result against the live exit on the same trade.</p>'
    +table(['<Sold (UTC)','<Coin','<Exit model','Price','Held','After costs','Live exit','Difference'],rows,'cards'),'md-sells');
}
function howSec(){
  var c=M.cfg||{},S=M.study;
  var how='<div class="tr-study"><p><b>Algorithms.</b> Logistic regression; random forest and extra trees (bagged trees); gradient boosting, XGBoost and LightGBM (boosted trees); k nearest neighbours; naive Bayes; a small neural network; an LSTM, a recurrent neural network that reads each coin’s last 8 scans in order; and five models of the trade’s return rather than whether it wins (ridge, random forest, gradient boosting, XGBoost, LightGBM). Each is trained on three variable sets: every variable, every variable except attention, and attention with the price path only, so the gap between the first two shows what attention adds. Four more sets (24 Oct) take the third apart, on six algorithms, one of each family, the LSTM and a return model: the price path alone, attention alone, the two with the pool’s size, and the price path with the minute data. A random-score model is trained and traded the same way as the control.</p>'
    +'<p><b>Overfitting.</b> Every model is small and regularised (shallow trees with large leaves, early stopping, weight decay), because a few days of a few hundred coins cannot support more. Folds split by time, never at random, and train only on trades that had closed before the test window opened; thresholds come from training scores only; the luck line allows for testing many models at once. Retrained every '+(c.every_h||6)+' hours on everything since the ledger started (up to 60 days); a model older than '+(c.max_age_h||30)+' hours stops opening trades.</p>'
    +'<p><b>Limits.</b> A model sees what the scan saw, about every 15 minutes; its buys fill at the moment the scan decides, at the coin’s latest minute price, and its sales on the minute readings (a take-profit at its target). The history is short and one market regime; a model that cleared every test here could still fail when the market turns, which is why only the forward record can make a model live.</p></div>';
  var st2='';
  if(S){
    var er=(S.entry||[]).map(function(m){var g=m.train_auc!=null&&m.auc!=null?m.train_auc-m.auc:null;
      return '<tr><td class="l"><b>'+esc(m.algo)+'</b></td><td>'+(m.auc!=null?f3(m.auc)+'<span class="nm">± '+f3(m.auc_sd)+'</span>':'<span class="nm">rank IC</span>'+f2(m.ic))+'</td><td>'+(m.train_auc!=null?f3(m.train_auc):'<span class="nm">rank IC</span>'+f2(m.train_ic))+'</td>'
        +'<td'+(g>0.15?' class="tr-dn"':'')+'>'+(g==null?'–':(g<0?MINUS:'+')+Math.abs(g).toFixed(3))+'</td><td>'+(m.accuracy==null?'–':pc(m.accuracy*100,1))+'</td><td>'+(m.balanced_acc==null?'–':pc(m.balanced_acc*100,1))+'</td><td>'+(m.brier==null?'–':f3(m.brier))+'</td>'
        +'<td>'+int(m.picks||0)+'</td><td>'+(m.pick_win==null?'–':pc(m.pick_win*100,0))+'</td><td class="'+(m.pick_net>0?'tr-up':'tr-dn')+'">'+n2(m.pick_net)+tval(m.pick_t)+'</td><td>'+n2(m.base_net)+'</td></tr>';});
    var xr=(S.exit||[]).map(function(e){return '<tr><td class="l"><b>'+esc(e.algo)+'</b></td><td>'+f3(e.auc)+'</td><td>'+f3(e.train_auc)+'</td><td>'+pc(e.accuracy*100,1)+'</td><td>'+int(e.trades)+'</td><td>'+n2(e.net)+'</td><td>'+n2(e.base_net)+'</td><td class="'+(e.gain>0?'tr-up':'tr-dn')+'">'+(e.gain<0?MINUS:'+')+Math.abs(e.gain).toFixed(2)+' pts'+tval(e.gain_t)+'</td></tr>';});
    st2='<div class="tr-study"><p><b>'+esc(S.period)+'</b>: '+esc(S.sample)+'.</p>'+(S.findings||[]).map(function(f){return '<p>'+esc(f)+'</p>';}).join('')+'</div>'
      +(er.length?'<h3 class="sub-h">Every algorithm in the study, out of sample</h3>'+table(['Algorithm','AUC (test)','AUC (training)','Overfit gap','Accuracy','Balanced accuracy','Brier','Picks','Picks won','Picks: average after costs','All test trades'],er,'wide cards'):'')
      +(xr.length?'<h3 class="sub-h">Exit models in the study</h3>'+table(['Exit model','AUC (test)','AUC (training)','Accuracy','Trades','Following it','+10% target or 8h','Gain'],xr,'cards'):'')
      +'<p class="fine">Return models are scored by rank IC (the rank correlation of predicted and actual returns) rather than AUC. k nearest neighbours used distance weights in the study, which made it score its own training labels (training AUC 1.000) and pick nothing; the live models use uniform weights.</p>';
  }
  return [sec('How the models are tested',how,'md-how'),st2?sec('What the candle study found before the first training run',st2,'md-study'):''];
}

/* ---- render ---- */
function render(){
  var w=$('#modelswrap');if(!w)return;D=U.data();M=D&&D.models;
  if(!M){w.innerHTML='<p class="empty">The Models tab fills in with the next scan.</p>';return;}
  var y=window.scrollY;
  var note=!M.available?'<p class="trk-note tr-dn">This scan ran without the machine-learning libraries, so no model scored coins.</p>'
    :(M.status==='ok'&&M.fresh===false&&M.trained_at?'<p class="trk-note tr-dn">The latest models were trained '+esc(ago(M.trained_at,D.generated_at))+', longer ago than the '+((M.cfg||{}).max_age_h||30)+' hours a model may trade on; they open no trades until the next training run.</p>':'');
  var hs=howSec(),trained=(M.entry||[]).length>0;
  /* until the first models are trained, the study's table of every algorithm comes straight after the status */
  w.innerHTML=head()+note+(trained?pnlSec():'')+entrySec()+(trained?'':hs[1])+exitSec()+logSec()+sellLogSec()+hs[0]+(trained?hs[1]:'');
  fitChart();
  $$('[data-tk]',w).forEach(function(b){b.onclick=function(){U.open(b.dataset.tk);};});
  ['set','kind','sort'].forEach(function(k){$$('[data-m'+k+']',w).forEach(function(b){b.onclick=function(){st[k]=b.getAttribute('data-m'+k);save();render();};});});
  $$('table.cards',w).forEach(function(t){var hs=$$('thead th',t).map(function(th){return th.textContent;});
    $$('tbody tr',t).forEach(function(tr){$$('td',tr).forEach(function(td,i){td.setAttribute('data-label',hs[i]||'');
      if(i&&td.childNodes.length>1)td.innerHTML='<div class="cv">'+td.innerHTML+'</div>';});});});
  window.scrollTo(window.scrollX,y);
}

var rz=null;window.addEventListener('resize',function(){clearTimeout(rz);rz=setTimeout(function(){if(U.view()==='models')fitChart();},200);});
U.on('data',function(){if(U.view()==='models')render();});
U.on('view',function(v){if(v==='models')render();});
if(U.data()&&U.view()==='models')render();
})();
