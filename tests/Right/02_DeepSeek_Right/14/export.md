# AI 对话记忆导出


<hr style="border: 0; border-top: 5px solid #2563EB; margin: 48px 0 24px 0;">

## 🔵 👤 用户提问

我问你个题：题库一共有 m 道题，考官随机抽取 n 道，我可以选择其中的 q 道作答，如果我至少有 80% 的概率能全部做对我选的q道题，那么我应该背多少道题？（做出假设：我没背的题一定丢分）？（1≤q≤n≤m）


<hr style="border: 0; border-top: 5px solid #9333EA; margin: 48px 0 24px 0;">

## 🟣 🤖 AI 回答

设你背了 $k$ 道题。考官随机抽 $n$ 道，你只要在抽到的 $n$ 道里**至少有 $q$ 道是你背过的**，就可以从中选这 $q$ 道作答，从而全对。

所以成功概率是：抽到的 $n$ 道中，背过的题数 $X\ge q$。  
其中 $X$ 服从超几何分布：



$$
P(X=i)=\frac{\binom{k}{i}\binom{m-k}{n-i}}{\binom{m}{n}}
$$



因此成功概率为



$$
P(k)=\sum_{i=q}^{\min(n,k)}
\frac{\binom{k}{i}\binom{m-k}{n-i}}{\binom{m}{n}}
$$



其中若 $n-i>m-k$，对应组合数记为 $0$。

你要求至少 $80\%$ 概率成功，所以要找最小的整数 $k$，使得



$$
\boxed{
P(k)=\sum_{i=q}^{\min(n,k)}
\frac{\binom{k}{i}\binom{m-k}{n-i}}{\binom{m}{n}}
\ge 0.8
}
$$



这个 $k$ 就是你应该背的最少题数。

等价地，用“没背的题数” $r=m-k$ 表示，失败是你抽到的 $n$ 道里没背的题超过 $n-q$ 道。成功概率为



$$
P=\sum_{j=0}^{n-q}
\frac{\binom{r}{j}\binom{m-r}{n-j}}{\binom{m}{n}}
\ge 0.8
$$



找到最大的 $r$，然后



$$
k=m-r
$$



就是最少背题数。

---

补充结论：

* 如果要求 **100% 保证**无论考官怎么抽都够用，那么需要背

  

$$
\boxed{k=m-n+q}
$$



  道。因为最坏情况下考官抽中的 $n$ 道里有 $m-k$ 道是你没背的，要保证剩下至少 $q$ 道背过，就需要 $m-k\le n-q$。
* 但你的要求是“至少 80% 概率”，所以通常不需要背到 $m-n+q$ 道，按上面的超几何公式求最小 $k$ 即可。

例如 $m=10,n=5,q=3$：



$$
P(k)=\sum_{i=3}^{5}\frac{\binom{k}{i}\binom{10-k}{5-i}}{\binom{10}{5}}
$$



算得：

* 背 $6$ 道：成功概率约 $0.738<0.8$
* 背 $7$ 道：成功概率约 $0.917\ge0.8$

所以最少背 $7$ 道。完全保证则需要 $m-n+q=10-5+3=8$ 道。

因此一般答案就是：



$$
\boxed{
k_{\min}=\min\left\{k:\sum_{i=q}^{\min(n,k)}
\frac{\binom{k}{i}\binom{m-k}{n-i}}{\binom{m}{n}}\ge 0.8\right\}
}
$$



具体数字要代入给定的 $m,n,q$ 计算。


<hr style="border: 0; border-top: 5px solid #2563EB; margin: 48px 0 24px 0;">

## 🔵 👤 用户提问

你可以给我做一个交互演示动画吗


<hr style="border: 0; border-top: 5px solid #9333EA; margin: 48px 0 24px 0;">

## 🟣 🤖 AI 回答

这是可直接运行的交互演示网页，通过拖动滑块设定 m、n、q 后，页面会实时计算并展示最少需要背的题数以及对应的成功概率。

```
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>背多少道题才够？· 交互演示</title>
<style>
*{box-sizing:border-box}
body{
  margin:0;padding:26px 16px 70px;background:#0d1117;color:#e6edf3;
  font-family:ui-sans-serif,-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1040px;margin:0 auto}
h1{font-size:23px;margin:0 0 8px;letter-spacing:.4px}
header p{margin:0 0 22px;color:#8b949e;font-size:13.5px;line-height:1.75}
.controls{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:16px}
@media(max-width:720px){.controls{grid-template-columns:1fr}}
.ctrl{background:#161b22;border:1px solid #21262d;border-radius:12px;padding:11px 14px}
.ctrl-top{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px}
.ctrl-top label{font-size:13px;color:#8b949e}
.ctrl-top output{font-size:17px;font-weight:700;color:#58a6ff;font-variant-numeric:tabular-nums}
input[type=range]{width:100%;-webkit-appearance:none;appearance:none;background:transparent;height:20px;cursor:pointer;display:block}
input[type=range]::-webkit-slider-runnable-track{height:4px;background:#30363d;border-radius:2px}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:16px;height:16px;border-radius:50%;background:#58a6ff;margin-top:-6px;border:none;box-shadow:0 0 0 4px rgba(88,166,255,.15)}
input[type=range]::-moz-range-track{height:4px;background:#30363d;border-radius:2px}
input[type=range]::-moz-range-thumb{width:16px;height:16px;border:none;border-radius:50%;background:#58a6ff}
.panels{display:grid;grid-template-columns:1.65fr 1fr;gap:14px;margin-bottom:14px}
@media(max-width:820px){.panels{grid-template-columns:1fr}}
.card{background:#161b22;border:1px solid #21262d;border-radius:14px;padding:14px}
.chart-card{padding:6px 6px 2px}
#chart{display:block;width:100%;height:300px;border-radius:10px}
.stats{display:flex;flex-direction:column;gap:9px}
.stat{background:#0d1117;border:1px solid #21262d;border-radius:10px;padding:11px 13px}
.stat .k{font-size:12px;color:#8b949e;margin-bottom:5px}
.stat .v{font-size:23px;font-weight:700;color:#3fb950;font-variant-numeric:tabular-nums;line-height:1.1}
.stat .v small{font-size:12px;font-weight:400;color:#8b949e;margin-left:5px}
.stat .v.blue{color:#58a6ff}
.stat .v.amber{color:#d29922}
.pool-head{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:12px}
.pool-head h2{font-size:14px;margin:0;font-weight:600;color:#c9d1d9}
.legend{display:flex;gap:14px;font-size:12px;color:#8b949e;flex-wrap:wrap}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:middle}
.grid{display:flex;flex-wrap:wrap;gap:5px;min-height:30px}
.cell{width:var(--cs,26px);height:var(--cs,26px);border-radius:6px;background:#1c2128;border:1px solid #30363d;transition:all .25s ease}
.cell.known{background:#14341d;border-color:#3fb950}
.cell.picked{animation:pop .35s ease;border-color:#58a6ff;box-shadow:0 0 0 2px rgba(88,166,255,.35)}
.cell.hit{background:#238636;border-color:#3fb950}
.cell.miss{background:#8b2c2c;border-color:#f85149}
.cell.faded{opacity:.2;transform:scale(.86)}
@keyframes pop{0%{transform:scale(1)}50%{transform:scale(1.28)}100%{transform:scale(1)}}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px;align-items:center}
button{background:#238636;color:#fff;border:none;border-radius:9px;padding:10px 18px;font-size:14px;font-weight:600;cursor:pointer;transition:.15s;font-family:inherit}
button:hover{background:#2ea043}
button:disabled{opacity:.45;cursor:not-allowed}
button.ghost{background:#21262d;border:1px solid #30363d;color:#e6edf3}
button.ghost:hover{background:#2a313a}
.status{font-size:14px;font-weight:600;color:#8b949e}
.status.ok{color:#3fb950}
.status.no{color:#f85149}
.note{font-size:12px;color:#6e7681;margin-top:14px;line-height:1.8}
code{background:#0d1117;border:1px solid #21262d;border-radius:4px;padding:1px 5px;font-size:12px;color:#79c0ff}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>背多少道题才够？</h1>
    <p>题库共 <b>m</b> 道，考官随机抽 <b>n</b> 道，你可以从抽中的题里选 <b>q</b> 道作答。假设没背过的题一定丢分——那么想以 <b>≥80%</b> 的概率保证所选 q 道全对，最少要背多少道？</p>
  </header>

  <section class="controls">
    <div class="ctrl">
      <div class="ctrl-top"><label for="mRange">题库总数 m</label><output id="mOut">30</output></div>
      <input type="range" id="mRange" min="4" max="60" value="30">
    </div>
    <div class="ctrl">
      <div class="ctrl-top"><label for="nRange">考官抽取 n</label><output id="nOut">10</output></div>
      <input type="range" id="nRange" min="1" max="30" value="10">
    </div>
    <div class="ctrl">
      <div class="ctrl-top"><label for="qRange">需要作答 q</label><output id="qOut">4</output></div>
      <input type="range" id="qRange" min="1" max="10" value="4">
    </div>
  </section>

  <section class="panels">
    <div class="card chart-card"><canvas id="chart"></canvas></div>
    <div class="stats">
      <div class="stat">
        <div class="k">最少需要背</div>
        <div class="v"><span id="kStar">–</span><small>道题</small></div>
      </div>
      <div class="stat">
        <div class="k">该方案成功率</div>
        <div class="v blue" id="pStar">–</div>
      </div>
      <div class="stat">
        <div class="k">100% 万无一失需要背</div>
        <div class="v amber"><span id="pGuarantee">–</span><small>道</small></div>
      </div>
      <div class="stat">
        <div class="k">背诵量占题库比例</div>
        <div class="v" style="color:#8b949e" id="kRatio">–</div>
      </div>
    </div>
  </section>

  <section class="card">
    <div class="pool-head">
      <h2>题池演示</h2>
      <div class="legend">
        <span><i style="background:#14341d;border:1px solid #3fb950"></i>已背</span>
        <span><i style="background:#1c2128;border:1px solid #30363d"></i>未背</span>
        <span><i style="background:#238636"></i>抽中且背过</span>
        <span><i style="background:#8b2c2c"></i>抽中但没背</span>
      </div>
    </div>
    <div class="grid" id="grid"></div>
    <div class="actions">
      <button id="btnDraw">🎲 模拟一次抽题</button>
      <button class="ghost" id="btnFast">⚡ 快速模拟 3000 次</button>
      <span class="status" id="status"></span>
    </div>
    <div class="note">
      成功条件：抽中的 n 道里，背过的题数 X ≥ q。X 服从超几何分布：
      <code>P(X=i) = C(k,i)·C(m−k,n−i) / C(m,n)</code>，成功概率 = Σ<sub>i≥q</sub> P(X=i)。
      想 100% 保证则需要 <code>k = m − n + q</code> 道。
    </div>
  </section>
</div>

<script>
const $ = s => document.querySelector(s);

/* ---------- 数学：对数阶乘 + 超几何概率 ---------- */
const MAXN = 400;
const LF = new Float64Array(MAXN + 1);
for (let i = 1; i <= MAXN; i++) LF[i] = LF[i - 1] + Math.log(i);
function logC(n, r) {
  if (r < 0 || r > n || n < 0) return -Infinity;
  return LF[n] - LF[r] - LF[n - r];
}
function probAt(m, k, n, q) {
  if (k < q) return 0;
  if (m - k <= n - q) return 1;          // 最坏情况也够
  const den = logC(m, n);
  let s = 0;
  const hi = Math.min(n, k);
  for (let i = q; i <= hi; i++) {
    const v = logC(k, i) + logC(m - k, n - i) - den;
    if (v > -Infinity) s += Math.exp(v);
  }
  return Math.min(1, s);
}
function findK(m, n, q) {
  for (let k = q; k <= m; k++) if (probAt(m, k, n, q) >= 0.8 - 1e-9) return k;
  return m;
}

/* ---------- 状态 ---------- */
const state = { m: 30, n: 10, q: 4, kStar: 0, probs: [], known: new Set() };
let cells = [];
let animating = false;
let hoverK = null;

const mR = $('#mRange'), nR = $('#nRange'), qR = $('#qRange');

/* ---------- 读取输入（自动约束 1≤q≤n≤m） ---------- */
function readInputs() {
  const m = +mR.value;
  nR.max = m;
  let n = Math.min(+nR.value, m);
  if (n < 1) n = 1;
  nR.value = n;
  qR.max = n;
  let q = Math.min(+qR.value, n);
  if (q < 1) q = 1;
  qR.value = q;

  state.m = m; state.n = n; state.q = q;
  $('#mOut').value = m; $('#nOut').value = n; $('#qOut').value = q;
}

/* ---------- 随机选 k 个下标 ---------- */
function randomSet(m, k) {
  const a = [...Array(m).keys()];
  for (let i = m - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return new Set(a.slice(0, k));
}

/* ---------- 更新全部 ---------- */
function updateAll() {
  readInputs();
  const { m, n, q } = state;
  state.kStar = findK(m, n, q);
  state.probs = [];
  for (let k = 0; k <= m; k++) state.probs[k] = probAt(m, k, n, q);
  state.known = randomSet(m, state.kStar);

  $('#kStar').textContent = state.kStar;
  $('#pStar').textContent = (state.probs[state.kStar] * 100).toFixed(1) + '%';
  $('#pGuarantee').textContent = Math.max(0, m - n + q);
  $('#kRatio').textContent = Math.round(state.kStar / m * 100) + '%';

  renderPool();
  drawChart();
  $('#status').textContent = '';
  $('#status').className = 'status';
}

/* ---------- 题池渲染 ---------- */
function renderPool() {
  const g = $('#grid');
  g.innerHTML = '';
  const m = state.m;
  const size = m <= 20 ? 32 : m <= 32 ? 27 : m <= 46 ? 22 : 18;
  g.style.setProperty('--cs', size + 'px');
  cells = [];
  for (let i = 0; i < m; i++) {
    const d = document.createElement('div');
    d.className = 'cell' + (state.known.has(i) ? ' known' : '');
    g.appendChild(d);
    cells.push(d);
  }
}

/* ---------- 画图 ---------- */
function drawChart() {
  const canvas = $('#chart');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const W = Math.max(240, rect.width), H = Math.max(180, rect.height);

  const needW = Math.round(W * dpr), needH = Math.round(H * dpr);
  if (canvas.width !== needW || canvas.height !== needH) {
    canvas.width = needW; canvas.height = needH;
  }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);

  const m = state.m, probs = state.probs;
  const pad = { l: 52, r: 18, t: 22, b: 36 };
  const pw = W - pad.l - pad.r, ph = H - pad.t - pad.b;
  const X = k => pad.l + (k / m) * pw;
  const Y = p => pad.t + (1 - p) * ph;

  const FONT = '11px ui-sans-serif,-apple-system,sans-serif';
  const FONT_B = 'bold 12px ui-sans-serif,-apple-system,sans-serif';

  /* 横向网格 */
  ctx.font = FONT;
  ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
  for (let p = 0; p <= 1.0001; p += 0.25) {
    const y = Y(p);
    ctx.strokeStyle = p === 0 ? '#3d444d' : '#1b2129';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
    ctx.fillStyle = '#7d8590';
    ctx.fillText(Math.round(p * 100) + '%', pad.l - 8, y);
  }

  /* 纵向网格 + x 刻度 */
  const step = Math.max(1, Math.ceil(m / 8));
  ctx.textAlign = 'center'; ctx.textBaseline = 'top';
  for (let k = 0; k <= m; k += step) {
    const x = X(k);
    ctx.strokeStyle = '#1b2129'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x, pad.t); ctx.lineTo(x, H - pad.b); ctx.stroke();
    ctx.fillStyle = '#7d8590';
    ctx.fillText(k, x, H - pad.b + 7);
  }

  /* 面积渐变 */
  const grad = ctx.createLinearGradient(0, pad.t, 0, H - pad.b);
  grad.addColorStop(0, 'rgba(88,166,255,.30)');
  grad.addColorStop(1, 'rgba(88,166,255,.02)');
  ctx.beginPath();
  ctx.moveTo(X(0), Y(0));
  for (let k = 0; k <= m; k++) ctx.lineTo(X(k), Y(probs[k]));
  ctx.lineTo(X(m), Y(0));
  ctx.closePath();
  ctx.fillStyle = grad; ctx.fill();

  /* 曲线 */
  ctx.beginPath();
  for (let k = 0; k <= m; k++) {
    const x = X(k), y = Y(probs[k]);
    k === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }
  ctx.strokeStyle = '#58a6ff'; ctx.lineWidth = 2.5;
  ctx.lineJoin = 'round'; ctx.lineCap = 'round';
  ctx.stroke();

  /* 80% 目标线 */
  const y80 = Y(0.8);
  ctx.save();
  ctx.setLineDash([6, 5]);
  ctx.strokeStyle = 'rgba(210,153,34,.85)'; ctx.lineWidth = 1.4;
  ctx.beginPath(); ctx.moveTo(pad.l, y80); ctx.lineTo(W - pad.r, y80); ctx.stroke();
  ctx.restore();
  ctx.font = FONT;
  ctx.fillStyle = '#d29922';
  ctx.textAlign = 'left'; ctx.textBaseline = 'bottom';
  ctx.fillText('80% 目标线', pad.l + 6, y80 - 4);

  /* k* 标记 */
  const k = state.kStar, pk = probs[k];
  const xk = X(k), yk = Y(pk);
  ctx.save();
  ctx.setLineDash([4, 4]);
  ctx.strokeStyle = 'rgba(63,185,80,.55)'; ctx.lineWidth = 1.2;
  ctx.beginPath(); ctx.moveTo(xk, Y(0)); ctx.lineTo(xk, yk); ctx.stroke();
  ctx.restore();

  ctx.beginPath(); ctx.arc(xk, yk, 5.5, 0, Math.PI * 2);
  ctx.fillStyle = '#3fb950'; ctx.fill();
  ctx.strokeStyle = '#0d1117'; ctx.lineWidth = 2; ctx.stroke();

  ctx.font = FONT_B;
  ctx.fillStyle = '#3fb950';
  ctx.textAlign = 'center';
  ctx.textBaseline = yk - 12 < pad.t ? 'top' : 'bottom';
  ctx.fillText('k=' + k, xk, yk - 12 < pad.t ? yk + 12 : yk - 11);

  /* 悬停提示 */
  if (hoverK !== null && hoverK >= 0 && hoverK <= m) {
    const hk = hoverK, hp = probs[hk];
    const hx = X(hk), hy = Y(hp);

    ctx.save();
    ctx.setLineDash([3, 4]);
    ctx.strokeStyle = 'rgba(230,237,243,.28)'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(hx, pad.t); ctx.lineTo(hx, H - pad.b); ctx.stroke();
    ctx.restore();

    ctx.beginPath(); ctx.arc(hx, hy, 4.5, 0, Math.PI * 2);
    ctx.fillStyle = '#e6edf3'; ctx.fill();
    ctx.strokeStyle = '#0d1117'; ctx.lineWidth = 1.5; ctx.stroke();

    const txt = `k=${hk}   P=${(hp * 100).toFixed(1)}%`;
    ctx.font = FONT;
    const tw = ctx.measureText(txt).width;
    let bx = hx + 12, by = hy - 32;
    if (bx + tw + 18 > W - pad.r) bx = hx - tw - 30;
    if (bx < pad.l) bx = pad.l;
    if (by < pad.t) by = hy + 14;

    const r = 6, bw = tw + 16, bh = 24;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(bx, by, bw, bh, r);
    else {
      ctx.moveTo(bx + r, by);
      ctx.arcTo(bx + bw, by, bx + bw, by + bh, r);
      ctx.arcTo(bx + bw, by + bh, bx, by + bh, r);
      ctx.arcTo(bx, by + bh, bx, by, r);
      ctx.arcTo(bx, by, bx + bw, by, r);
      ctx.closePath();
    }
    ctx.fillStyle = 'rgba(13,17,23,.94)';
    ctx.fill();
    ctx.strokeStyle = '#30363d'; ctx.lineWidth = 1; ctx.stroke();
    ctx.fillStyle = '#e6edf3';
    ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
    ctx.fillText(txt, bx + 8, by + 12);
  }
}

/* ---------- 抽题动画 ---------- */
const sleep = ms => new Promise(r => setTimeout(r, ms));
function shuffle(a) {
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

async function runSim() {
  if (animating) return;
  animating = true;
  $('#btnDraw').disabled = true;
  $('#btnFast').disabled = true;

  const { m, n, q, known } = state;

  cells.forEach((c, i) => {
    c.className = 'cell' + (known.has(i) ? ' known' : '');
  });
  $('#status').textContent = '考官正在抽题…';
  $('#status').className = 'status';
  await sleep(320);

  const order = shuffle([...Array(m).keys()]);
  const drawn = order.slice(0, n);
  const drawnSet = new Set(drawn);
  const delay = Math.max(35, Math.min(110, 900 / n));

  for (const i of drawn) {
    cells[i].classList.add('picked');
    await sleep(delay);
  }
  await sleep(240);

  let hits = 0;
  cells.forEach((c, i) => {
    c.classList.remove('picked');
    if (drawnSet.has(i)) {
      if (known.has(i)) { c.classList.add('hit'); hits++; }
      else c.classList.add('miss');
    } else {
      c.classList.add('faded');
    }
  });

  const ok = hits >= q;
  $('#status').textContent = ok
    ? `✅ 抽中 ${n} 道，其中 ${hits} 道背过（≥${q}）→ 能全对！`
    : `❌ 抽中 ${n} 道，只有 ${hits} 道背过（<${q}）→ 这次翻车`;
  $('#status').className = 'status ' + (ok ? 'ok' : 'no');

  animating = false;
  $('#btnDraw').disabled = false;
  $('#btnFast').disabled = false;
}

/* ---------- 快速模拟 ---------- */
function quickSim(times) {
  const { m, n, q, kStar } = state;
  const arr = new Int8Array(m);
  let ok = 0;
  for (let t = 0; t < times; t++) {
    for (let i = 0; i < m; i++) arr[i] = i < kStar ? 1 : 0;
    for (let i = 0; i < n; i++) {
      const j = i + Math.floor(Math.random() * (m - i));
      const tmp = arr[i]; arr[i] = arr[j]; arr[j] = tmp;
    }
    let c = 0;
    for (let i = 0; i < n; i++) if (arr[i]) c++;
    if (c >= q) ok++;
  }
  return ok / times;
}

/* ---------- 事件绑定 ---------- */
[mR, nR, qR].forEach(r => r.addEventListener('input', updateAll));

$('#btnDraw').addEventListener('click', runSim);

$('#btnFast').addEventListener('click', () => {
  if (animating) return;
  const rate = quickSim(3000);
  const target = state.probs[state.kStar];
  $('#status').textContent =
    `⚡ 背 ${state.kStar} 道，模拟 3000 次成功率 ${(rate * 100).toFixed(1)}%（理论 ${(target * 100).toFixed(1)}%）`;
  $('#status').className = 'status ' + (rate >= 0.8 ? 'ok' : 'no');
});

const canvas = $('#chart');
canvas.addEventListener('mousemove', e => {
  const rect = canvas.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const pad = { l: 52, r: 18 };
  const pw = rect.width - pad.l - pad.r;
  let k = Math.round(((x - pad.l) / pw) * state.m);
  k = Math.max(0, Math.min(state.m, k));
  if (k !== hoverK) { hoverK = k; drawChart(); }
});
canvas.addEventListener('mouseleave', () => {
  if (hoverK !== null) { hoverK = null; drawChart(); }
});

window.addEventListener('resize', () => drawChart());

/* ---------- 启动 ---------- */
updateAll();
</script>
</body>
</html>
```

### 核心机制与操作说明

页面围绕“超几何分布”这个概率模型来运转，您可以一边调参数一边看结果。

**公式逻辑**：成功概率是抽中的 n 道题里背过题数 X ≥ q 的概率，其中 X 服从超几何分布。代码用对数阶乘和组合数累加实现了精确计算，同时给出了 100% 万无一失需要的背诵量 k = m − n + q。

**参数调节**：三个滑块分别控制 m（题库总数）、n（考官抽取数）、q（需要作答数），会自动满足 1 ≤ q ≤ n ≤ m 的约束，数值变化后概率曲线和统计卡片会立即刷新。

**可视化与反馈**：折线图展示 P(X ≥ q) 随 k 的变化，绿色圆点标出满足 80% 目标的最小 k 值，鼠标悬停可查看任意 k 对应的概率。题池用不同颜色区分“已背”“未背”“抽中且背过”“抽中但没背”。

**模拟验证**：点击“模拟一次抽题”会播放抽题动画并统计结果，点击“快速模拟 3000 次”则返回大样本下的实际成功率，可以和理论值对照。

---

**优化建议：** 页面中的 80% 目标阈值、滑块默认值（m=30、n=10、q=4）以及快速模拟的 3000 次都可以在代码开头的状态配置和 updateAll 函数里调整，您可以根据实际场景修改这些数值。

