// Проверка логики «Свежие» из index.html: node scraper/test_fresh.js
const fs = require('fs'), vm = require('vm'), path = require('path');
const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
const a = html.indexOf('function isoAdd'), bIdx = html.indexOf('function isFresh');
const b = html.indexOf('\n', bIdx);
if (a < 0 || bIdx < 0) { console.error('не нашёл функции свежести в index.html'); process.exit(1); }
const ctx = { MN: {'янв':1,'фев':2,'мар':3,'апр':4,'мая':5,'июн':6,'июл':7,'авг':8,'сен':9,'окт':10,'ноя':11,'дек':12}, D: null, S: { freshDays: 1 } };
vm.createContext(ctx);
vm.runInContext(html.slice(a, b), ctx);
let fails = [];
const eq = (n, got, want) => { if (JSON.stringify(got) !== JSON.stringify(want)) fails.push(n + ': ждали ' + JSON.stringify(want) + ', получили ' + JSON.stringify(got)); };
const run = (code) => vm.runInContext(code, ctx);

ctx.D = { today: '2026-10-20', base: '2026-10-18' };
eq('isoAdd', run("isoAdd('2026-10-01',-1)"), '2026-09-30');
eq('postDate вчера', run("postDate({d:'вчера'})"), '2026-10-19');
eq('postDate 17 окт.', run("postDate({d:'17 окт.'})"), '2026-10-17');
eq('postDate через год', run("(D.today='2026-01-05', postDate({d:'30 дек.'}))"), '2025-12-30');
ctx.D = { today: '2026-10-20', base: '2026-10-18' };
// найдено последним сбором (20.10), 1 день -> свежее; найдено 18.10 после базы -> нет
eq('новое сегодня', run("(S.freshDays=1, isFresh({fs:'2026-10-20'}))"), true);
eq('старое', run("isFresh({fs:'2026-10-19'})"), false);
eq('2 дня', run("(S.freshDays=2, isFresh({fs:'2026-10-19'}))"), true);
// первый снимок: смотрим на дату публикации на крыше
eq('база: опубликовано 19 окт.', run("(S.freshDays=2, isFresh({fs:'2026-10-18', d:'19 окт.'}))"), true);
eq('база: опубликовано 12 окт.', run("isFresh({fs:'2026-10-18', d:'12 окт.'})"), false);
eq('база: без даты -> по fs', run("(S.freshDays=1, isFresh({fs:'2026-10-18'}))"), false);
if (fails.length) { console.log('ПРОВАЛЕНО:\n - ' + fails.join('\n - ')); process.exit(1); }
console.log('OK: логика «Свежие» проверена');
