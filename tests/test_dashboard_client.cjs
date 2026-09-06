// Pure dashboard contract checks: no browser, network, or production-data mutation.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('production/static/assets/app.js', 'utf8');
const section = (start, end) => source.slice(source.indexOf(start), source.indexOf(end));
const nodes = new Map();
const node = selector => {
  if (!nodes.has(selector)) nodes.set(selector, {textContent:'', innerHTML:'', hidden:false, classList:{add(){},remove(){}}});
  return nodes.get(selector);
};
const context = vm.createContext({Intl, Date, $:node, document:{querySelectorAll:()=>[]}});
vm.runInContext(`
  const MATCH_TIMEZONE='Europe/Paris';
  const integer=new Intl.NumberFormat('fr-FR');
  const decimal=new Intl.NumberFormat('fr-FR',{maximumFractionDigits:2});
  const decimalOne=new Intl.NumberFormat('fr-FR',{minimumFractionDigits:1,maximumFractionDigits:1});
  ${section('function setText(', 'function publicationIsFresh(')}
  ${section('function futurePublishedPredictions(', 'function validText(')}
  ${section('function formatDate(', 'function formatFullDate(')}
  ${section('function escapeHtml(', 'function predictionMarkup(')}
  ${section('function resultLabel(', 'function usableCurve(')}
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
assert.equal(node('#summary-pending').textContent, '1');
assert.equal(node('#archived-decisions').hidden, false);
assert.equal((node('#archived-list').innerHTML.match(/class="result-row"/g)||[]).length,4);
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
console.log('Dashboard client: 13 assertions passed.');
