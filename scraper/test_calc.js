// Проверка расчёта маржи на примерах пользователя.  Запуск:  node scraper/test_calc.js
const KZ = require('../calc.js');
let fails = 0;
function eq(name, got, want, eps) {
  const ok = eps != null ? Math.abs(got - want) < eps : got === want;
  if (!ok) { fails++; console.log('FAIL', name, 'ожидали', want, 'получили', got); }
}
const costs = KZ.DEFAULTS.costs;

// Пример 1: покупаю за 22, в ДКП продавец пишет 35, продаю за 35 → затраты 30, налога нет, маржа 5
let s = KZ.scenarios(22, 35, 7.5, costs);
eq('ex1.cost', s.cost, 30, 1e-9);
eq('ex1.high.tax', s.high.tax, 0, 1e-9);
eq('ex1.high.margin', s.high.margin, 5, 1e-9);
// тот же объект, но ДКП по факту: налог 10% × (35−22) = 1,3 → маржа 3,7
eq('ex1.fact.tax', s.fact.tax, 1.3, 1e-9);
eq('ex1.fact.margin', s.fact.margin, 3.7, 1e-9);

// Пример 2: покупаю за 20, в ДКП 5, продаю за 35 → затраты 28, налог 3, маржа 4
s = KZ.scenarios(20, 35, 7.5, costs);
eq('ex2.cost', s.cost, 28, 1e-9);
eq('ex2.low.tax', s.low.tax, 3, 1e-9);
eq('ex2.low.margin', s.low.margin, 4, 1e-9);

// Эталон цены: 18 мкр, 2к, от 75 м² → 35; 68 м² → 32; другой мкр → нет эталона
const L = (o) => Object.assign({ id: 1, r: 2, a: 80, p: 22e6, m: '18', cl: 'draft', fl: [] }, o);
eq('ref75', KZ.refSale(L({ a: 80 }), KZ.DEFAULTS.refs).price, 35);
eq('ref68', KZ.refSale(L({ a: 68 }), KZ.DEFAULTS.refs).price, 32);
eq('ref_other_mkr', KZ.refSale(L({ m: '17' }), KZ.DEFAULTS.refs), null);

// Подсказка: самая низкая цена похожей готовой квартиры в том же ЖК (±10% площади), сам объект и черновые не в счёт
const comps = [
  L({ id: 10, cl: 'renovated', zk: 'Самал', a: 78, p: 36e6, m: '17' }),
  L({ id: 11, cl: 'renovated', zk: 'Самал', a: 82, p: 34e6, m: '17' }),
  L({ id: 12, cl: 'renovated', zk: 'Самал', a: 120, p: 20e6, m: '17' }),   // площадь не подходит
  L({ id: 13, cl: 'draft', zk: 'Самал', a: 80, p: 15e6, m: '17' }),       // черновая — не сравнение
  L({ id: 14, cl: 'renovated', zk: 'Самал', a: 80, p: 30e6, m: '17', dev: true }) // застройщик — не сравнение
];
const idx = KZ.buildCompIndex(comps);
const target = L({ id: 99, zk: 'Самал', a: 80, m: '17' });
const sg = KZ.suggestSale(target, idx);
eq('suggest.price', sg.price, 34, 1e-9);
eq('suggest.n', sg.n, 2);
eq('suggest.where', sg.where, 'в том же ЖК');

// evaluate: приоритет ручная > эталон > авто; «наличка» → сценарий «занижен»
const ctx = { costs, refs: KZ.DEFAULTS.refs, idx };
let ev = KZ.evaluate(L({ id: 98, a: 80, fl: ['cash'] }), {}, ctx);
eq('eval.src', ev.src, 'эталон'); eq('eval.scen', ev.scen, 'low');
eq('eval.margin', ev.margin, 35 - (22 + 7.5 + 0.5) - 3, 1e-9);
ev = KZ.evaluate(L({ id: 98, a: 80 }), { sale: 33, scen: 'high' }, ctx);
eq('eval.manual', ev.src, 'ручная'); eq('eval.manual.margin', ev.margin, 33 - 30, 1e-9);
ev = KZ.evaluate(L({ id: 97, m: '17', a: 200, zk: null }), {}, ctx);
eq('eval.nosale', ev.margin, null);

if (fails) { console.log('ПРОВАЛЕНО:', fails); process.exit(1); }
console.log('OK: расчёт маржи совпал с примерами');
