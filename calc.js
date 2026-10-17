/* krysha-kz: расчёт маржи флиппинга и подсказка цены продажи.
   Все деньги здесь в МИЛЛИОНАХ тенге (в data.json цены в тенге).
   Работает и в браузере (window.KZ), и в node (module.exports) — для проверки тестом. */
(function (root) {
  'use strict';

  var DEFAULTS = {
    costs: {
      reno: { 1: 5, 2: 7.5, 3: 10, 4: 12 }, // ремонт, млн: 2к = 7,5 (твоё значение), остальные — ориентир, поправь
      realtor: 0.5,   // риелтор, млн
      tax: 0.10,      // налог 10% с (ДКП продажи − ДКП покупки)
      dkpLow: 5,      // «заниженный» ДКП покупки, млн
      target: 3,      // нижняя граница хорошей маржи, млн
      good: 5         // «отлично», млн
    },
    // твои эталоны цены продажи 2к (можно менять в приложении)
    refs: [
      { id: 'r1', name: '18 мкр · Самал 18-28 / 18-30, от 75 м²', mkr: '18', rooms: 2, amin: 75, amax: 999, price: 35 },
      { id: 'r2', name: '18 мкр · Самал, 60–75 м² (около 68 м²)', mkr: '18', rooms: 2, amin: 60, amax: 74.99, price: 32 }
    ]
  };

  function mln(p) { return p / 1e6; }

  function norm(s) { return (s || '').toString().toLowerCase().replace(/[«»"']/g, '').trim(); }

  function isComp(l) {
    // сравнимая «готовая» квартира: с ремонтом, не новостройка от застройщика, актуальная
    return l.cl === 'renovated' && !l.dev && !l.ms;
  }

  function buildCompIndex(listings) {
    var idx = { zk: {}, house: {}, mkr: {} };
    function put(map, key, l) { if (key) (map[key] = map[key] || []).push(l); }
    listings.forEach(function (l) {
      if (!isComp(l)) return;
      put(idx.zk, l.zk ? norm(l.zk) + '|' + l.r : null, l);
      put(idx.house, (l.m && l.h) ? l.m + '|' + l.h + '|' + l.r : null, l);
      put(idx.mkr, l.m ? l.m + '|' + l.r : null, l);
    });
    return idx;
  }

  function median(arr) {
    var s = arr.slice().sort(function (a, b) { return a - b; });
    var n = s.length;
    return n ? (n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2) : null;
  }

  function pickComps(list, l) {
    var out = (list || []).filter(function (c) {
      return c.id !== l.id && Math.abs(c.a - l.a) <= l.a * 0.10;
    });
    if (out.length >= 4) { // выбрасываем явные «дешёвки»: цена за м² < 70% медианы
      var med = median(out.map(function (c) { return c.p / c.a; }));
      out = out.filter(function (c) { return c.p / c.a >= med * 0.7; });
    }
    return out;
  }

  // Подсказка: самая низкая цена похожей готовой квартиры (±10% площади) — в том же ЖК, иначе в том же доме, иначе в мкр
  function suggestSale(l, idx) {
    var levels = [
      ['zk', l.zk ? norm(l.zk) + '|' + l.r : null, 'в том же ЖК'],
      ['house', (l.m && l.h) ? l.m + '|' + l.h + '|' + l.r : null, 'в том же доме'],
      ['mkr', l.m ? l.m + '|' + l.r : null, 'в мкр']
    ];
    for (var i = 0; i < levels.length; i++) {
      var key = levels[i][1];
      if (!key) continue;
      var comps = pickComps(idx[levels[i][0]][key], l);
      if (comps.length) {
        var prices = comps.map(function (c) { return mln(c.p); });
        return {
          price: Math.min.apply(null, prices), n: comps.length, where: levels[i][2],
          min: Math.min.apply(null, prices), max: Math.max.apply(null, prices), med: median(prices),
          ids: comps.slice().sort(function (a, b) { return a.p - b.p; }).slice(0, 3).map(function (c) { return c.id; })
        };
      }
    }
    return null;
  }

  function refSale(l, refs) {
    for (var i = 0; i < (refs || []).length; i++) {
      var r = refs[i];
      if (r.mkr && r.mkr !== l.m) continue;
      if (r.rooms && r.rooms !== l.r) continue;
      if (l.a < (r.amin || 0) || l.a > (r.amax || 9999)) continue;
      return { price: +r.price, name: r.name };
    }
    return null;
  }

  // Три сценария ДКП при покупке. P — реальная цена покупки, S — цена продажи (ДКП продажи = S).
  function scenarios(P, S, reno, costs) {
    var base = P + reno + costs.realtor;
    function one(dkp) {
      var tax = Math.max(0, S - dkp) * costs.tax;
      return { dkp: dkp, tax: tax, margin: S - base - tax };
    }
    return { cost: base, fact: one(P), high: one(S), low: one(costs.dkpLow) };
  }

  /* l — объявление; ov — ручные правки {sale, buy, scen, dkp}; ctx — {costs, refs, idx} */
  function evaluate(l, ov, ctx) {
    ov = ov || {};
    var costs = ctx.costs;
    var P = ov.buy != null && ov.buy !== '' ? +ov.buy : mln(l.p);
    var reno = costs.reno[l.r] != null ? costs.reno[l.r] : costs.reno[2];
    var S = null, src = null, info = null;
    if (ov.sale != null && ov.sale !== '' && !isNaN(+ov.sale)) { S = +ov.sale; src = 'ручная'; }
    else {
      var rf = refSale(l, ctx.refs);
      if (rf) { S = rf.price; src = 'эталон'; info = rf; }
      else {
        var sg = suggestSale(l, ctx.idx);
        if (sg) { S = sg.price; src = 'авто'; info = sg; }
      }
    }
    var cashHint = (l.fl || []).indexOf('cash') >= 0;
    var scen = ov.scen || (cashHint ? 'low' : 'fact');
    var c = costs;
    if (ov.dkp != null && ov.dkp !== '' && !isNaN(+ov.dkp)) c = Object.assign({}, costs, { dkpLow: +ov.dkp });
    var all = null, cur = null;
    if (S != null) {
      all = scenarios(P, S, reno, c);
      cur = all[scen];
    }
    return { P: P, reno: reno, S: S, src: src, info: info, scen: scen, all: all, cur: cur,
             margin: cur ? cur.margin : null };
  }

  var api = { DEFAULTS: DEFAULTS, mln: mln, buildCompIndex: buildCompIndex, suggestSale: suggestSale,
              refSale: refSale, scenarios: scenarios, evaluate: evaluate, isComp: isComp, median: median };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.KZ = api;
})(typeof window !== 'undefined' ? window : this);
