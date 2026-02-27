"""
Aurora AI Hedge Fund - Production Entry Point

MİMARİ:
- uvicorn ANA THREAD'de çalışır (Railway portu böyle görür)
- Tüm trading ajanları DAEMON THREAD'de asyncio ile çalışır
- PORT: Railway $PORT env var'ından okunur, yoksa 8000
"""
import threading
import asyncio
import signal
import os
import time
import sys

from agents.market_agent import MarketAgent
from agents.strategy_agent import StrategyAgent
from rl_engine.meta_agent import RLMetaAgent
from execution.executor import ExecutionAgent
from utils.state import SharedState
from utils.logger import setup_logger

logger = setup_logger("main")

shared_state = SharedState()
shutdown_event = threading.Event()


# ─────────────────────────────────────────────────────────────────────────────
#  AJAN THREAD'İ
# ─────────────────────────────────────────────────────────────────────────────

def run_agents():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    aio_shutdown = asyncio.Event()

    def monitor():
        while not shutdown_event.is_set():
            time.sleep(0.5)
        loop.call_soon_threadsafe(aio_shutdown.set)

    threading.Thread(target=monitor, daemon=True).start()

    async def agent_main():
        market_agent   = MarketAgent(shared_state)
        strategy_agent = StrategyAgent(shared_state)
        rl_agent       = RLMetaAgent(shared_state)
        exec_agent     = ExecutionAgent(shared_state)

        RESTART_MAP = {
            "MarketAgent":    lambda: market_agent.run(aio_shutdown),
            "StrategyAgent":  lambda: strategy_agent.run(aio_shutdown),
            "RLMetaAgent":    lambda: rl_agent.run(aio_shutdown),
            "ExecutionAgent": lambda: exec_agent.run(aio_shutdown),
        }

        tasks = [asyncio.create_task(fn(), name=n) for n, fn in RESTART_MAP.items()]
        logger.info("✅ Trading ajanları başlatıldı")

        while not aio_shutdown.is_set():
            done, _ = await asyncio.wait(tasks, timeout=30, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task.cancelled(): continue
                exc = task.exception()
                if exc and task.get_name() in RESTART_MAP:
                    logger.error(f"❌ {task.get_name()} çöktü: {exc}")
                    tasks.remove(task)
                    tasks.append(asyncio.create_task(
                        RESTART_MAP[task.get_name()](), name=task.get_name()
                    ))
                    logger.info(f"♻️  {task.get_name()} yeniden başlatıldı")

        for t in tasks: t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    loop.run_until_complete(agent_main())
    loop.close()


# ─────────────────────────────────────────────────────────────────────────────
#  FASTAPI UYGULAMASI
# ─────────────────────────────────────────────────────────────────────────────

def create_app():
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse
    from datetime import datetime

    app = FastAPI(title="Aurora AI Hedge Fund", version="2.0.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.get("/", response_class=HTMLResponse)
    def root():
        return """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Aurora AI — Trading Terminal</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:ital,wght@0,400;0,700;1,400&family=Syne:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
:root {
  --bg:       #050810;
  --surface:  #090d1a;
  --panel:    #0c1220;
  --border:   rgba(0,210,150,0.12);
  --border2:  rgba(0,210,150,0.06);
  --accent:   #00d296;
  --accent2:  #00a3ff;
  --danger:   #ff4d6d;
  --warn:     #f5a623;
  --text:     #c8d6e5;
  --muted:    #4a5568;
  --dim:      #1e2d3d;
  --glow:     0 0 20px rgba(0,210,150,0.15);
  --glow2:    0 0 40px rgba(0,210,150,0.08);
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html { scroll-behavior: smooth; }

body {
  font-family: 'Space Mono', monospace;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  overflow-x: hidden;
}

/* Animated grid background */
body::before {
  content: '';
  position: fixed; inset: 0;
  background-image:
    linear-gradient(rgba(0,210,150,0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,210,150,0.03) 1px, transparent 1px);
  background-size: 40px 40px;
  pointer-events: none;
  z-index: 0;
}

/* Ambient glow blobs */
body::after {
  content: '';
  position: fixed;
  top: -20%; left: -10%;
  width: 60vw; height: 60vw;
  background: radial-gradient(ellipse, rgba(0,210,150,0.04) 0%, transparent 70%);
  pointer-events: none; z-index: 0;
  animation: drift 20s ease-in-out infinite alternate;
}

@keyframes drift {
  from { transform: translate(0,0) scale(1); }
  to   { transform: translate(5vw,3vh) scale(1.05); }
}

/* ── LAYOUT ── */
.shell {
  position: relative; z-index: 1;
  display: grid;
  grid-template-rows: auto 1fr auto;
  min-height: 100vh;
  max-width: 1400px;
  margin: 0 auto;
  padding: 0 1.5rem;
}

/* ── TOPBAR ── */
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.1rem 0;
  border-bottom: 1px solid var(--border2);
  gap: 1rem;
}

.logo {
  font-family: 'Syne', sans-serif;
  font-weight: 800;
  font-size: 1.25rem;
  letter-spacing: -0.02em;
  color: #fff;
  display: flex; align-items: center; gap: .6rem;
}

.logo-mark {
  width: 28px; height: 28px;
  background: conic-gradient(from 180deg, var(--accent), var(--accent2), var(--accent));
  border-radius: 6px;
  display: grid; place-items: center;
  font-size: .75rem;
  animation: spin-slow 8s linear infinite;
}

@keyframes spin-slow {
  to { transform: rotate(360deg); }
}

.pulse-dot {
  width: 7px; height: 7px;
  background: var(--accent);
  border-radius: 50%;
  box-shadow: 0 0 8px var(--accent);
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%,100% { opacity:1; transform:scale(1); }
  50%      { opacity:.5; transform:scale(0.8); }
}

.status-bar {
  display: flex; align-items: center; gap: 1.5rem;
  font-size: .7rem; color: var(--muted);
}

.status-pill {
  display: flex; align-items: center; gap: .4rem;
  background: rgba(0,210,150,0.08);
  border: 1px solid rgba(0,210,150,0.2);
  padding: .25rem .7rem;
  border-radius: 999px;
  color: var(--accent);
  font-size: .65rem; letter-spacing: .08em;
}

#clock { color: var(--text); font-size: .7rem; }

.nav-links {
  display: flex; gap: 1rem;
}
.nav-links a {
  font-size: .65rem; letter-spacing: .08em; color: var(--muted);
  text-decoration: none; text-transform: uppercase;
  transition: color .2s;
}
.nav-links a:hover { color: var(--accent); }

/* ── MAIN GRID ── */
main {
  padding: 1.5rem 0;
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  grid-template-rows: auto auto auto;
  gap: 1rem;
}

/* ── PANELS ── */
.panel {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 1.1rem 1.25rem;
  position: relative;
  overflow: hidden;
  transition: border-color .3s, box-shadow .3s;
}

.panel:hover {
  border-color: rgba(0,210,150,0.25);
  box-shadow: var(--glow);
}

.panel::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  opacity: 0;
  transition: opacity .3s;
}

.panel:hover::before { opacity: 1; }

.panel-label {
  font-size: .6rem;
  letter-spacing: .12em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: .4rem;
}

.panel-value {
  font-family: 'Syne', sans-serif;
  font-size: 2rem;
  font-weight: 700;
  line-height: 1;
  color: #fff;
  transition: color .3s;
}

.panel-sub {
  font-size: .65rem; color: var(--muted);
  margin-top: .3rem;
}

.positive { color: var(--accent) !important; }
.negative { color: var(--danger) !important; }
.neutral  { color: var(--text) !important; }

/* ── UPTIME ── */
.panel-uptime { grid-column: 1; }

/* ── PNL — big card ── */
.panel-pnl {
  grid-column: 2;
  background: linear-gradient(135deg, rgba(0,210,150,0.05), rgba(0,163,255,0.05));
}

/* ── WIN RATE ── */
.panel-winrate { grid-column: 3; }

/* ── MARKET TABLE ── */
.panel-market {
  grid-column: 1 / 3;
  grid-row: 2;
}

/* ── SIGNALS ── */
.panel-signals {
  grid-column: 3;
  grid-row: 2 / 4;
}

/* ── AGENTS ── */
.panel-agents {
  grid-column: 1 / 3;
  grid-row: 3;
}

/* ── TABLE ── */
.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: .72rem;
  margin-top: .6rem;
}

.data-table th {
  font-size: .58rem;
  letter-spacing: .1em;
  text-transform: uppercase;
  color: var(--muted);
  padding: .4rem .6rem;
  border-bottom: 1px solid var(--border2);
  text-align: left;
  font-weight: 400;
}

.data-table td {
  padding: .45rem .6rem;
  border-bottom: 1px solid var(--border2);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.data-table tr:last-child td { border-bottom: none; }

.data-table tr:hover td {
  background: rgba(0,210,150,0.03);
}

/* ── TICKER NAME ── */
.ticker {
  font-family: 'Syne', sans-serif;
  font-weight: 600;
  font-size: .75rem;
  color: #fff;
  letter-spacing: .03em;
}

/* ── SIGNAL BADGE ── */
.sig-badge {
  display: inline-block;
  padding: .15rem .5rem;
  border-radius: 4px;
  font-size: .6rem;
  letter-spacing: .07em;
  text-transform: uppercase;
  font-weight: 700;
}

.sig-buy  { background: rgba(0,210,150,0.12); color: var(--accent); border: 1px solid rgba(0,210,150,0.3); }
.sig-sell { background: rgba(255,77,109,0.12); color: var(--danger); border: 1px solid rgba(255,77,109,0.3); }
.sig-hold { background: rgba(245,166,35,0.1);  color: var(--warn);   border: 1px solid rgba(245,166,35,0.25); }

/* ── AGENT STATUS ── */
.agent-dot {
  display: inline-block;
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 6px var(--accent);
  animation: pulse 2s ease-in-out infinite;
  margin-right: .4rem;
}

/* ── CONFIDENCE BAR ── */
.conf-bar {
  display: flex; align-items: center; gap: .5rem;
}
.conf-track {
  flex: 1; height: 3px;
  background: var(--dim);
  border-radius: 2px;
  overflow: hidden;
}
.conf-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent2), var(--accent));
  border-radius: 2px;
  transition: width .5s ease;
}

/* ── RSI BAR ── */
.rsi-pill {
  display: inline-block;
  padding: .1rem .4rem;
  border-radius: 3px;
  font-size: .65rem;
  font-variant-numeric: tabular-nums;
}
.rsi-low  { background: rgba(0,210,150,0.1);  color: var(--accent); }
.rsi-high { background: rgba(255,77,109,0.1); color: var(--danger); }
.rsi-mid  { background: rgba(100,116,139,0.15); color: var(--muted); }

/* ── SECTION HEADER ── */
.section-title {
  font-family: 'Syne', sans-serif;
  font-size: .65rem;
  letter-spacing: .15em;
  text-transform: uppercase;
  color: var(--muted);
  display: flex; align-items: center; gap: .5rem;
  margin-bottom: .5rem;
}

.section-title::after {
  content: '';
  flex: 1; height: 1px;
  background: var(--border2);
}

/* ── FOOTER ── */
footer {
  border-top: 1px solid var(--border2);
  padding: .8rem 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: .6rem;
  color: var(--muted);
}

/* ── LOADING SHIMMER ── */
@keyframes shimmer {
  from { background-position: -200% 0; }
  to   { background-position:  200% 0; }
}
.shimmer {
  background: linear-gradient(90deg, var(--dim) 25%, rgba(0,210,150,0.06) 50%, var(--dim) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.8s infinite;
  border-radius: 3px;
}

/* ── FLASH ANIMATION ── */
@keyframes flash-green { 0%,100% { background: transparent; } 50% { background: rgba(0,210,150,0.08); } }
@keyframes flash-red   { 0%,100% { background: transparent; } 50% { background: rgba(255,77,109,0.08); } }
.flash-g { animation: flash-green .6s; }
.flash-r { animation: flash-red   .6s; }

/* ── NUMBER CHANGE ── */
@keyframes countup { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
.updated { animation: countup .3s ease; }

/* ── SCROLLBAR ── */
::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: var(--surface); }
::-webkit-scrollbar-thumb { background: var(--dim); border-radius: 2px; }

/* ── RESPONSIVE ── */
@media (max-width: 900px) {
  main { grid-template-columns: 1fr 1fr; }
  .panel-market, .panel-agents { grid-column: 1 / 3; }
  .panel-signals { grid-column: 1 / 3; grid-row: auto; }
}
@media (max-width: 600px) {
  main { grid-template-columns: 1fr; }
  .panel-market, .panel-agents, .panel-signals,
  .panel-pnl, .panel-winrate { grid-column: 1; }
}
</style>
</head>
<body>
<div class="shell">

<!-- HEADER -->
<header>
  <div class="logo">
    <div class="logo-mark">⬡</div>
    AURORA<span style="color:var(--accent)">_</span>AI
  </div>
  <div class="status-bar">
    <div class="status-pill">
      <div class="pulse-dot"></div>
      CANLI
    </div>
    <span id="clock">--:--:-- UTC</span>
  </div>
  <nav class="nav-links">
    <a href="/status">STATUS</a>
    <a href="/market">MARKET</a>
    <a href="/signals">SIGNALS</a>
    <a href="/positions">POSITIONS</a>
    <a href="/docs">API DOCS</a>
  </nav>
</header>

<!-- MAIN -->
<main id="main-grid">

  <!-- UPTIME -->
  <div class="panel panel-uptime">
    <div class="panel-label">Çalışma Süresi</div>
    <div class="panel-value positive" id="uptime">--:--:--</div>
    <div class="panel-sub" id="started-at">başlatılıyor...</div>
  </div>

  <!-- PNL -->
  <div class="panel panel-pnl">
    <div class="panel-label">Toplam PnL</div>
    <div class="panel-value" id="pnl">$+0.0000</div>
    <div class="panel-sub" id="trade-count">0 işlem</div>
  </div>

  <!-- WIN RATE -->
  <div class="panel panel-winrate">
    <div class="panel-label">Kazanma Oranı</div>
    <div class="panel-value" id="winrate">0%</div>
    <div class="panel-sub" id="open-pos">0 açık pozisyon</div>
  </div>

  <!-- MARKET TABLE -->
  <div class="panel panel-market">
    <div class="section-title">Piyasa Verisi</div>
    <table class="data-table">
      <thead>
        <tr>
          <th>Sembol</th>
          <th>Fiyat (USD)</th>
          <th>24s %</th>
          <th>RSI</th>
          <th>MACD</th>
          <th>Momentum</th>
        </tr>
      </thead>
      <tbody id="market-body">
        <tr><td colspan="6" style="color:var(--muted);text-align:center;padding:1.5rem">
          <span class="shimmer" style="display:inline-block;width:80%;height:12px"></span>
        </td></tr>
      </tbody>
    </table>
  </div>

  <!-- SIGNALS -->
  <div class="panel panel-signals">
    <div class="section-title">Son Sinyaller</div>
    <div id="signals-list" style="display:flex;flex-direction:column;gap:.4rem;max-height:420px;overflow-y:auto">
      <div style="color:var(--muted);font-size:.7rem;text-align:center;padding:2rem 0">
        Sinyal bekleniyor...
      </div>
    </div>
  </div>

  <!-- AGENTS -->
  <div class="panel panel-agents">
    <div class="section-title">Ajan Durumları</div>
    <table class="data-table">
      <thead>
        <tr><th>Ajan</th><th>Durum</th><th>Son Aktif</th><th>Rol</th></tr>
      </thead>
      <tbody id="agent-body">
        <tr><td colspan="4" style="color:var(--muted);text-align:center;padding:1rem">Yükleniyor...</td></tr>
      </tbody>
    </table>
  </div>

</main>

<!-- FOOTER -->
<footer>
  <span>Aurora AI Hedge Fund v2.0 · Paper Trading Mode</span>
  <span id="last-update">son güncelleme: --</span>
</footer>

</div>

<script>
// ── STATE ──
let prevPrices = {};
const AGENT_ROLES = {
  MarketAgent:    'Veri Toplayıcı · CoinGecko',
  StrategyAgent:  'Sinyal Üretici · RSI/MACD/BB',
  RLMetaAgent:    'Q-Learning · Ağırlık Güncelleyici',
  ExecutionAgent: 'Emir Uygulayıcı · Paper Mode',
};

// ── CLOCK ──
function updateClock() {
  const now = new Date();
  document.getElementById('clock').textContent =
    now.toUTCString().split(' ')[4] + ' UTC';
}
setInterval(updateClock, 1000);
updateClock();

// ── FORMAT ──
function fmtPrice(n) {
  if (n >= 10000) return '$' + n.toLocaleString('en', {maximumFractionDigits:0});
  if (n >= 100)   return '$' + n.toFixed(2);
  return '$' + n.toFixed(4);
}
function fmtPct(n) {
  const s = (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
  return `<span class="${n>=0?'positive':'negative'}">${s}</span>`;
}
function fmtRsi(r) {
  const cls = r < 35 ? 'rsi-low' : r > 65 ? 'rsi-high' : 'rsi-mid';
  return `<span class="rsi-pill ${cls}">${r.toFixed(1)}</span>`;
}
function timeAgo(isoStr) {
  const d = new Date(isoStr.includes('Z') ? isoStr : isoStr + 'Z');
  const s = Math.floor((Date.now() - d.getTime()) / 1000);
  if (s < 60) return s + 's önce';
  return Math.floor(s/60) + 'm önce';
}
function fmtUptime(secs) {
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = Math.floor(secs % 60);
  return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

// ── FETCH STATUS ──
async function fetchStatus() {
  try {
    const r = await fetch('/status');
    const d = await r.json();

    // PNL
    const pnlEl = document.getElementById('pnl');
    const newPnl = '$' + (d.total_pnl >= 0 ? '+' : '') + d.total_pnl.toFixed(4);
    if (pnlEl.textContent !== newPnl) {
      pnlEl.textContent = newPnl;
      pnlEl.className = 'panel-value updated ' + (d.total_pnl >= 0 ? 'positive' : 'negative');
    }

    document.getElementById('trade-count').textContent = d.trade_count + ' işlem tamamlandı';
    document.getElementById('winrate').textContent = d.win_rate + '%';
    document.getElementById('open-pos').textContent = d.open_positions + ' açık pozisyon · ' + d.market_symbols + ' sembol';
    document.getElementById('uptime').textContent = fmtUptime(d.uptime_seconds);

    // Agents
    const ab = document.getElementById('agent-body');
    const agents = d.agent_heartbeats || {};
    if (Object.keys(agents).length) {
      ab.innerHTML = Object.entries(agents).map(([name, ts]) => `
        <tr>
          <td><span class="ticker">${name}</span></td>
          <td><span class="agent-dot"></span><span class="positive" style="font-size:.65rem">AKTIF</span></td>
          <td style="color:var(--muted)">${timeAgo(ts)}</td>
          <td style="color:var(--muted);font-size:.62rem">${AGENT_ROLES[name] || '—'}</td>
        </tr>`).join('');
    }

    document.getElementById('last-update').textContent =
      'son güncelleme: ' + new Date().toLocaleTimeString('tr-TR');
  } catch(e) { console.warn('status fetch error', e); }
}

// ── FETCH MARKET ──
async function fetchMarket() {
  try {
    const r = await fetch('/market');
    const d = await r.json();
    const symbols = d.symbols || {};
    const mb = document.getElementById('market-body');

    if (!Object.keys(symbols).length) return;

    mb.innerHTML = Object.entries(symbols).map(([sym, data]) => {
      const price = data.price || 0;
      const prev  = prevPrices[sym] || price;
      const flashCls = price > prev ? 'flash-g' : price < prev ? 'flash-r' : '';
      prevPrices[sym] = price;

      const change = data.change_24h || 0;
      const rsi    = data.rsi || 50;
      const macd   = data.macd || 0;
      const mom    = data.momentum_1m || 0;
      const macdClr = macd >= 0 ? 'positive' : 'negative';
      const momClr  = mom >= 0  ? 'positive' : 'negative';

      const symLabel = sym.charAt(0).toUpperCase() + sym.slice(1,3).toUpperCase();

      return `<tr class="${flashCls}">
        <td><span class="ticker">${symLabel}</span> <span style="color:var(--muted);font-size:.6rem">${sym.toUpperCase()}</span></td>
        <td style="color:#fff;font-variant-numeric:tabular-nums">${fmtPrice(price)}</td>
        <td>${fmtPct(change)}</td>
        <td>${fmtRsi(rsi)}</td>
        <td class="${macdClr}" style="font-variant-numeric:tabular-nums">${macd >= 0 ? '+' : ''}${macd.toFixed(5)}</td>
        <td class="${momClr}">${mom >= 0 ? '+' : ''}${mom.toFixed(3)}%</td>
      </tr>`;
    }).join('');
  } catch(e) { console.warn('market fetch error', e); }
}

// ── FETCH SIGNALS ──
async function fetchSignals() {
  try {
    const r = await fetch('/signals');
    const d = await r.json();
    const list = d.signals || [];
    const sl = document.getElementById('signals-list');

    if (!list.length) return;

    sl.innerHTML = list.slice(0, 15).map(sig => {
      const cls = sig.direction === 'buy' ? 'sig-buy' : sig.direction === 'sell' ? 'sig-sell' : 'sig-hold';
      const pct = Math.round(sig.confidence * 100);
      const symShort = sig.symbol.charAt(0).toUpperCase() + sig.symbol.slice(1,3).toUpperCase();
      const t = new Date(sig.timestamp.includes('Z') ? sig.timestamp : sig.timestamp + 'Z');
      const timeStr = t.toLocaleTimeString('tr-TR', {hour:'2-digit',minute:'2-digit',second:'2-digit'});

      return `<div style="background:var(--surface);border:1px solid var(--border2);border-radius:6px;padding:.5rem .7rem">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.3rem">
          <span class="ticker" style="font-size:.72rem">${symShort}</span>
          <span class="sig-badge ${cls}">${sig.direction.toUpperCase()}</span>
        </div>
        <div class="conf-bar">
          <div class="conf-track"><div class="conf-fill" style="width:${pct}%"></div></div>
          <span style="font-size:.6rem;color:var(--muted);white-space:nowrap">${pct}%</span>
        </div>
        <div style="font-size:.58rem;color:var(--muted);margin-top:.25rem">${timeStr}</div>
      </div>`;
    }).join('');
  } catch(e) { console.warn('signals fetch error', e); }
}

// ── INIT & POLL ──
async function refresh() {
  await Promise.all([fetchStatus(), fetchMarket(), fetchSignals()]);
}

refresh();
setInterval(refresh, 5000);  // Her 5 saniyede güncelle
</script>
</body>
</html>"""

    @app.get("/health")
    def health():
        from datetime import datetime
        return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

    @app.get("/status")
    def status():
        return {"status": "running", **shared_state.get_summary(), "rl_metrics": shared_state.rl_metrics}

    @app.get("/market")
    def market():
        return {"symbols": shared_state.market_data}

    @app.get("/signals")
    def signals():
        sigs = shared_state.signals[-20:]
        return {"count": len(sigs), "signals": [
            {"symbol": s.symbol, "direction": s.direction, "confidence": s.confidence,
             "strategy": s.strategy, "timestamp": s.timestamp.isoformat()}
            for s in reversed(sigs)
        ]}

    @app.get("/positions")
    def positions():
        return {"open": [
            {"symbol": p.symbol, "side": p.side, "qty": p.qty,
             "entry_price": p.entry_price, "current_price": p.current_price,
             "pnl": round((p.current_price - p.entry_price) * p.qty, 4),
             "opened_at": p.opened_at.isoformat()}
            for p in shared_state.positions.values()
        ]}

    @app.get("/metrics")
    def metrics():
        return shared_state.rl_metrics

    @app.get("/performance")
    def performance():
        s = shared_state.get_summary()
        return {"total_pnl_usd": s["total_pnl"], "trade_count": s["trade_count"],
                "win_rate_pct": s["win_rate"], "open_positions": s["open_positions"]}

    return app


# ─────────────────────────────────────────────────────────────────────────────
#  GİRİŞ NOKTASI
# ─────────────────────────────────────────────────────────────────────────────

def handle_signal(sig, frame):
    logger.warning(f"Kapatılıyor (signal {sig})...")
    shutdown_event.set()


if __name__ == "__main__":
    import uvicorn

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Railway $PORT inject eder — MUTLAKA kullan
    PORT = int(os.getenv("PORT", "8000"))

    # ÖNEMLİ: Port'u logla — Railway'de doğrulama için
    logger.info(f"🚀 Aurora AI Hedge Fund başlatılıyor...")
    logger.info(f"🌐 PORT={PORT} (env: {os.getenv('PORT', 'YOK — varsayılan 8000')})")

    # Ajanları arka thread'de başlat
    agent_thread = threading.Thread(target=run_agents, name="AgentThread", daemon=True)
    agent_thread.start()
    logger.info("✅ Agent thread başlatıldı")

    app = create_app()

    # uvicorn DOĞRUDAN ana thread'de çalışır
    # Railway bu process'in 0.0.0.0:{PORT} dinlediğini görür
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        log_level="info",       # "info" — Railway'in port detection'ı için
        proxy_headers=True,
        forwarded_allow_ips="*",
        access_log=True,        # HTTP logları aktif — debug için
    )

    shutdown_event.set()
    agent_thread.join(timeout=10)
    logger.info("✅ Kapatma tamamlandı.")
