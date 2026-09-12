// Pure dashboard contract checks: no browser, network, or production-data mutation.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('production/static/assets/app.js', 'utf8');
const section = (start, end) => source.slice(source.indexOf(start), source.indexOf(end));
const nodes = new Map();
const node = selector => {
  if (!nodes.has(selector)) nodes.set(selector, {textContent:'', innerHTML:'', hidden:false, addEventListener(){}, setAttribute(){}, classList:{add(){},remove(){}}});
  return nodes.get(selector);
};
const context = vm.createContext({Intl, Date, $:node, document:{querySelectorAll:()=>[]}});
vm.runInContext(`
  const MATCH_TIMEZONE='Europe/Paris';
  const integer=new Intl.NumberFormat('fr-FR');
  const decimal=new Intl.NumberFormat('fr-FR',{maximumFractionDigits:2});
  const decimalOne=new Intl.NumberFormat('fr-FR',{minimumFractionDigits:1,maximumFractionDigits:1});
  const percent=new Intl.NumberFormat('fr-FR',{style:'percent',maximumFractionDigits:0});
  ${section('function setText(', 'function publicationIsFresh(')}
  ${section('function futurePublishedPredictions(', 'function validText(')}
  ${section('function formatDate(', 'function formatFullDate(')}
  ${section('function escapeHtml(', 'function predictionMarkup(')}
  ${section('function predictionMarkup(', 'function resetNoPickCopy(')}
  ${section('function resultLabel(', 'function usableCurve(')}
  ${section('function currentSeasonData(', 'function renderPerformance(')}
`, context);
const evaluate = code => vm.runInContext(code, context);
assert.equal(evaluate(`inPublicWindow('2026-10-27T22:59:00Z', Date.parse('2026-10-24T22:30:00Z'))`), true);
assert.equal(evaluate(`inPublicWindow('2026-10-27T23:00:00Z', Date.parse('2026-10-24T22:30:00Z'))`), false);
assert.equal(evaluate(`inPublicWindow('invalid')`), false);
evaluate(`
  const base=Date.now();
  const activity=[0,5,6,6,6].map((days,i)=>({id:String(i),date:new Date(base+days*86400000).toISOString(),recommended:true,status:'pending',homeTeam:'Home',awayTeam:'Away',outcomeLabel:'Match nul'}));
  const fixture={activity,summary:{},tracking:{pending:5,verified:0},performance:{live:{}}};
  renderTracking(fixture);
`);
assert.equal(node('#tracking-pending').textContent, '1');
assert.equal(node('#tracking-verified').textContent, '0');
assert.equal(nodes.has('#archived-decisions'), false);
assert.equal(nodes.has('#archived-list'), false);
assert.equal((node('#result-list').innerHTML.match(/class="result-row"/g)||[]).length,1);
evaluate(`
  fixture.activity[0].status='won'; fixture.activity[0].actualScore='2 - 2';
  fixture.tracking={verified:1,won:1,lost:0}; fixture.performance.live={roi:3.3,profitUnits:3.3};
  renderTracking(fixture);
`);
assert.equal(node('#tracking-pending').textContent,'0');
assert.equal(node('#live-return').textContent,'+330,0 %');
assert.match(node('#result-list').innerHTML, /final-score">2 - 2/);
evaluate(`historyFilter='pending'; renderHistory();`);
assert.match(node('#result-list').innerHTML, /Aucune décision/);
evaluate(`historyFilter='settled'; renderHistory();`);
assert.match(node('#result-list').innerHTML, /Gagné/);
evaluate(`
  fixture.activity.push({id:'past',date:new Date(base-7*86400000).toISOString(),recommended:true,status:'pending',homeTeam:'Past',awayTeam:'Match'});
  fixture.activity.push({id:'tomorrow',date:new Date(base+86400000).toISOString(),recommended:true,status:'pending',homeTeam:'Tomorrow',awayTeam:'Match'});
  historyFilter='all'; renderTracking(fixture);
`);
assert.match(node('#result-list').innerHTML, /Past/);
assert.match(node('#result-list').innerHTML, /Tomorrow/);
assert.equal((node('#result-list').innerHTML.match(/class="result-row"/g)||[]).length,3);
evaluate(`
  const clock=Date.parse('2026-09-07T15:00:00Z');
  const choice={id:'choice',league:'Bundesliga',homeTeam:'Home',awayTeam:'Away',recommended:true,date:'2026-09-07T15:00:00Z',outcomeLabel:'Match nul'};
  const lifecycle={predictions:[choice],activity:[]};
`);
assert.equal(evaluate('matchCards(lifecycle,clock-1).length'),1);
assert.equal(evaluate('matchCards(lifecycle,clock)[0].started'),true);
evaluate(`lifecycle.predictions=[]; lifecycle.activity=[{...choice,id:'ledger',status:'pending'}];`);
assert.equal(evaluate('matchCards(lifecycle,clock+3600000).length'),1);
evaluate(`lifecycle.activity[0].status='lost'; lifecycle.activity[0].actualScore='1 - 4';`);
assert.equal(evaluate('matchCards(lifecycle,clock+3*3600000)[0].actualScore'),'1 - 4');
assert.equal(evaluate('matchCards(lifecycle,clock+86400000).length'),0);
evaluate(`lifecycle.predictions=[choice];`);
assert.equal(evaluate('matchCards(lifecycle,clock+86400000).length'),0);
evaluate(`lifecycle.predictions=[{...choice,date:'2026-09-12T15:00:00Z'}]; lifecycle.activity=[];`);
assert.equal(evaluate('matchCards(lifecycle,clock).length'),0);
evaluate(`
  const historyFixture=Array.from({length:18},(_,i)=>({...choice,id:String(i),date:new Date(clock-i*86400000).toISOString(),status:'lost',profitUnits:-1}));
  historyRows=historyFixture; historyFilter='all'; historyLimit=8; renderHistory();
`);
assert.equal((node('#result-list').innerHTML.match(/class="result-row"/g)||[]).length,8);
assert.equal(node('#history-more').hidden,false);
evaluate('historyLimit=24; renderHistory();');
assert.equal((node('#result-list').innerHTML.match(/class="result-row"/g)||[]).length,18);
assert.equal(node('#history-more').hidden,true);
assert.match(node('#result-list').innerHTML,/août 2026/);
assert.equal(evaluate('liveRoiPoints(historyFixture,18,-1).length'),18);
assert.equal(evaluate('liveRoiPoints(historyFixture.slice(0,1),1,-1).length'),0);
assert.equal(evaluate('liveRoiPoints(historyFixture.slice(0,8),18,-1).length'),0);
assert.equal(evaluate('liveRoiPoints(historyFixture,18,.2).length'),0);
const upcomingCard = evaluate('predictionMarkup({...choice, odds:3.7, stakeEur:2.5, modelProbability:.31})');
assert.doesNotMatch(upcomingCard, /Choix publié|estimate-explanation|Comprendre cette estimation/);
assert.match(upcomingCard, /Match nul/);
assert.match(upcomingCard, /Indice du modèle/);
assert.doesNotMatch(evaluate('followedMatchMarkup({...choice,status:"pending"})'), /Choix publié/);
console.log('Dashboard client: 36 assertions passed.');
evaluate(`
  const seasonFixture={meta:{currentSeason:2025},summary:{liveReturn:100},performance:{metrics:{betCount:530,roi:.9}},predictions:[],activity:[
    {...choice,id:'old',date:'2026-05-12T13:00:00Z',status:'won',profitUnits:90},
    {...choice,id:'one',date:'2026-09-01T13:00:00Z',status:'lost',profitUnits:-1},
    {...choice,id:'two',date:'2026-09-02T13:00:00Z',status:'won',profitUnits:3},
    {...choice,id:'two',date:'2026-09-02T13:00:00Z',status:'won',profitUnits:3},
    {...choice,id:'void',date:'2026-09-03T13:00:00Z',status:'void',profitUnits:0},
    {...choice,id:'future',date:'2026-09-13T13:00:00Z',status:'pending',profitUnits:0}]};
  const seasonResult=currentSeasonData(seasonFixture,Date.parse('2026-09-12T12:00:00Z'));
`);
assert.equal(evaluate('seasonResult.meta.currentSeason'),2026);
assert.equal(evaluate('seasonResult.performance.metrics.betCount'),2);
assert.equal(evaluate('seasonResult.performance.metrics.roi'),1);
assert.equal(evaluate('seasonResult.performance.metrics.maxDrawdown'),-1);
assert.equal(evaluate('seasonResult.performance.monthly.length'),1);
assert.equal(evaluate('seasonResult.activity.length'),4);
assert.equal(evaluate('currentSeasonData({...seasonFixture,activity:[]}).performance.metrics.roi'),null);
assert.equal(evaluate('currentSeasonData({...seasonFixture,activity:[{...seasonFixture.activity[1],profitUnits:null}]}).performance.metrics.roi'),null);
console.log('Current season: 8 assertions passed.');
