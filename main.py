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
<title>Aurora AI — Pro Trading Terminal</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:ital,wght@0,300;0,400;0,500;0,700;1,400&family=Barlow+Condensed:wght@400;600;700;800&family=Barlow:wght@400;500;600&display=swap" rel="stylesheet">
<style>
/* ═══════════════════════════════════════════════════════
   AURORA AI PRO TERMINAL — Design System
   ═══════════════════════════════════════════════════════ */
:root {
  --c-bg:        #060a10;
  --c-surface:   #0a1018;
  --c-panel:     #0d1520;
  --c-elevated:  #101a28;
  --c-border:    rgba(0,200,140,0.10);
  --c-border-hi: rgba(0,200,140,0.25);
  --c-accent:    #00c88c;
  --c-accent-dim:#00c88c33;
  --c-blue:      #0090ff;
  --c-blue-dim:  #0090ff22;
  --c-yellow:    #f0b429;
  --c-yellow-dim:#f0b42922;
  --c-red:       #ff3b5c;
  --c-red-dim:   #ff3b5c22;
  --c-purple:    #a855f7;
  --c-text:      #b8cce0;
  --c-text-dim:  #506070;
  --c-text-faint:#2a3a4a;
  --glow-g:      0 0 16px rgba(0,200,140,0.18);
  --glow-b:      0 0 16px rgba(0,144,255,0.18);
  --radius:      6px;
  --radius-lg:   10px;
  --font-mono:   'JetBrains Mono', monospace;
  --font-head:   'Barlow Condensed', sans-serif;
  --font-body:   'Barlow', sans-serif;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { font-size: 14px; }

body {
  font-family: var(--font-mono);
  background: var(--c-bg);
  color: var(--c-text);
  min-height: 100vh;
  overflow-x: hidden;
}

/* Subtle scanline overlay */
body::before {
  content: '';
  position: fixed; inset: 0; pointer-events: none; z-index: 9999;
  background: repeating-linear-gradient(
    0deg, transparent, transparent 2px,
    rgba(0,0,0,0.03) 2px, rgba(0,0,0,0.03) 4px
  );
}

/* Grid background */
body::after {
  content: '';
  position: fixed; inset: 0; pointer-events: none; z-index: 0;
  background-image:
    linear-gradient(rgba(0,200,140,0.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,200,140,0.025) 1px, transparent 1px);
  background-size: 50px 50px;
}

a { color: var(--c-accent); text-decoration: none; }
a:hover { color: #fff; }

/* ── SCROLLBAR ── */
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: var(--c-bg); }
::-webkit-scrollbar-thumb { background: var(--c-text-faint); border-radius: 2px; }

/* ════════════════════════════════
   TICKER TAPE
   ════════════════════════════════ */
.ticker-tape {
  position: relative; z-index: 10;
  background: var(--c-surface);
  border-bottom: 1px solid var(--c-border);
  height: 28px;
  overflow: hidden;
  display: flex;
  align-items: center;
}
.ticker-track {
  display: flex;
  gap: 0;
  white-space: nowrap;
  animation: ticker-scroll 60s linear infinite;
}
.ticker-track:hover { animation-play-state: paused; }
@keyframes ticker-scroll {
  from { transform: translateX(0); }
  to   { transform: translateX(-50%); }
}
.ticker-item {
  display: inline-flex; align-items: center; gap: .4rem;
  padding: 0 1.2rem;
  font-size: .68rem; letter-spacing: .03em;
  border-right: 1px solid var(--c-text-faint);
}
.ticker-sym { color: #fff; font-weight: 500; }
.ticker-price { color: var(--c-text); }
.ticker-chg.up   { color: var(--c-accent); }
.ticker-chg.down { color: var(--c-red); }

/* ════════════════════════════════
   TOPBAR
   ════════════════════════════════ */
.topbar {
  position: relative; z-index: 10;
  background: var(--c-surface);
  border-bottom: 1px solid var(--c-border);
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  padding: 0 1.25rem;
  height: 52px;
  gap: 1.5rem;
}

.brand {
  display: flex; align-items: center; gap: .6rem;
  font-family: var(--font-head);
  font-size: 1.35rem; font-weight: 800;
  letter-spacing: .04em; color: #fff;
}
.brand-icon {
  width: 30px; height: 30px;
  background: linear-gradient(135deg, var(--c-accent), var(--c-blue));
  border-radius: var(--radius);
  display: grid; place-items: center;
  font-size: .8rem;
  flex-shrink: 0;
}
.brand-sub {
  font-family: var(--font-body);
  font-size: .65rem; font-weight: 400;
  color: var(--c-text-dim); letter-spacing: .08em;
  margin-top: 1px;
}

/* KPIs in topbar */
.topbar-kpis {
  display: flex; gap: 0;
  align-items: stretch;
  height: 100%;
}
.kpi {
  display: flex; flex-direction: column; justify-content: center;
  padding: 0 1.1rem;
  border-left: 1px solid var(--c-border);
  min-width: 90px;
}
.kpi-label {
  font-size: .55rem; letter-spacing: .12em;
  text-transform: uppercase; color: var(--c-text-dim);
  margin-bottom: 2px;
}
.kpi-val {
  font-family: var(--font-head);
  font-size: 1.1rem; font-weight: 700; line-height: 1;
  color: #fff;
}
.kpi-val.up   { color: var(--c-accent); }
.kpi-val.down { color: var(--c-red); }
.kpi-val.blue { color: var(--c-blue); }
.kpi-val.yellow { color: var(--c-yellow); }

.topbar-right {
  display: flex; align-items: center; gap: .75rem;
}
.status-live {
  display: flex; align-items: center; gap: .4rem;
  background: rgba(0,200,140,0.08);
  border: 1px solid rgba(0,200,140,0.2);
  padding: .25rem .7rem;
  border-radius: 4px;
  font-size: .65rem; letter-spacing: .1em;
  color: var(--c-accent);
}
.dot-live {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--c-accent);
  box-shadow: 0 0 6px var(--c-accent);
  animation: blink 2s ease-in-out infinite;
}
@keyframes blink {
  0%,100% { opacity:1; } 50% { opacity:.3; }
}
#topbar-time {
  font-size: .7rem; color: var(--c-text-dim);
  font-variant-numeric: tabular-nums;
  min-width: 70px; text-align: right;
}

/* ════════════════════════════════
   MAIN LAYOUT
   ════════════════════════════════ */
.workspace {
  position: relative; z-index: 1;
  display: grid;
  grid-template-columns: 1fr 1fr 320px;
  grid-template-rows: 200px 220px 260px auto;
  gap: 1px;
  background: var(--c-text-faint);
  height: calc(100vh - 80px);
  overflow: hidden;
}

/* ════════════════════════════════
   PANEL BASE
   ════════════════════════════════ */
.panel {
  background: var(--c-panel);
  overflow: hidden;
  display: flex; flex-direction: column;
}

.panel-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: .5rem .85rem;
  border-bottom: 1px solid var(--c-border);
  flex-shrink: 0;
}

.panel-title {
  font-family: var(--font-head);
  font-size: .72rem; font-weight: 600;
  letter-spacing: .12em; text-transform: uppercase;
  color: var(--c-text-dim);
  display: flex; align-items: center; gap: .4rem;
}
.panel-title .icon { color: var(--c-accent); font-size: .8rem; }

.panel-badge {
  font-size: .55rem; letter-spacing: .1em;
  padding: .15rem .45rem; border-radius: 3px;
  font-weight: 600; text-transform: uppercase;
}
.badge-green { background: var(--c-accent-dim); color: var(--c-accent); border: 1px solid rgba(0,200,140,0.25); }
.badge-blue  { background: var(--c-blue-dim);   color: var(--c-blue);   border: 1px solid rgba(0,144,255,0.25); }
.badge-red   { background: var(--c-red-dim);    color: var(--c-red);    border: 1px solid rgba(255,59,92,0.25); }
.badge-yellow{ background: var(--c-yellow-dim); color: var(--c-yellow); border: 1px solid rgba(240,180,41,0.25); }

.panel-body { flex: 1; overflow-y: auto; overflow-x: hidden; padding: .6rem .85rem; }
.panel-body.no-pad { padding: 0; }

/* ════════════════════════════════
   LAYOUT — SLOTS
   ════════════════════════════════ */

/* Row 1: PNL Chart (col 1+2), Mini Stats (col 3) */
.slot-chart   { grid-column: 1 / 3; grid-row: 1; }
.slot-stats   { grid-column: 3;     grid-row: 1; }

/* Row 2: Market (col 1+2), Signals (col 3, spans r2+r3) */
.slot-market  { grid-column: 1 / 3; grid-row: 2; }
.slot-signals { grid-column: 3;     grid-row: 2 / 5; }

/* Row 3: Positions (col 1+2) */
.slot-positions { grid-column: 1 / 3; grid-row: 3; }

/* Row 4: Trade History (col 1), Agents+Log (col 2) */
.slot-history { grid-column: 1; grid-row: 4; }
.slot-agents  { grid-column: 2; grid-row: 4; }

/* ════════════════════════════════
   PNL CHART
   ════════════════════════════════ */
.chart-container {
  position: relative;
  flex: 1;
  padding: .4rem .85rem .5rem;
  overflow: hidden;
}
canvas#pnlChart {
  width: 100% !important;
  height: 100% !important;
}

/* ════════════════════════════════
   MINI STATS (right panel)
   ════════════════════════════════ */
.stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1px;
  background: var(--c-text-faint);
  flex: 1;
}
.stat-cell {
  background: var(--c-panel);
  padding: .7rem .85rem;
  display: flex; flex-direction: column; justify-content: center;
}
.stat-label {
  font-size: .55rem; letter-spacing: .1em;
  text-transform: uppercase; color: var(--c-text-dim);
  margin-bottom: .3rem;
}
.stat-val {
  font-family: var(--font-head);
  font-size: 1.3rem; font-weight: 700; line-height: 1;
  color: #fff;
  font-variant-numeric: tabular-nums;
}
.stat-val.green  { color: var(--c-accent); }
.stat-val.red    { color: var(--c-red); }
.stat-val.blue   { color: var(--c-blue); }
.stat-val.yellow { color: var(--c-yellow); }
.stat-sub { font-size: .6rem; color: var(--c-text-dim); margin-top: .25rem; }

/* ════════════════════════════════
   MARKET TABLE
   ════════════════════════════════ */
.data-table {
  width: 100%; border-collapse: collapse;
  font-size: .68rem;
}
.data-table th {
  position: sticky; top: 0;
  background: var(--c-panel);
  font-size: .57rem; letter-spacing: .1em;
  text-transform: uppercase; color: var(--c-text-dim);
  padding: .35rem .7rem;
  border-bottom: 1px solid var(--c-border);
  text-align: right; font-weight: 400;
  cursor: pointer; user-select: none;
}
.data-table th:first-child { text-align: left; }
.data-table th:hover { color: var(--c-accent); }
.data-table th.sort-asc::after  { content: ' ↑'; color: var(--c-accent); }
.data-table th.sort-desc::after { content: ' ↓'; color: var(--c-accent); }

.data-table td {
  padding: .38rem .7rem;
  border-bottom: 1px solid rgba(0,200,140,0.04);
  text-align: right;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.data-table td:first-child { text-align: left; }
.data-table tr:last-child td { border-bottom: none; }
.data-table tr:hover td { background: rgba(0,200,140,0.04); }
.data-table tr.flash-g td { animation: row-flash-g .5s; }
.data-table tr.flash-r td { animation: row-flash-r .5s; }
@keyframes row-flash-g { 50% { background: rgba(0,200,140,0.1); } }
@keyframes row-flash-r { 50% { background: rgba(255,59,92,0.1); } }

.sym-name { color: #e2eef9; font-weight: 500; letter-spacing: .03em; }
.sym-full { color: var(--c-text-dim); font-size: .57rem; display: block; }
.pos { color: var(--c-accent); }
.neg { color: var(--c-red); }
.neu { color: var(--c-text); }

/* RSI pill */
.rsi { display: inline-block; padding: .1rem .4rem; border-radius: 3px; font-size: .63rem; }
.rsi-ob  { background: rgba(255,59,92,0.15);  color: var(--c-red);    border: 1px solid rgba(255,59,92,0.3); }
.rsi-os  { background: rgba(0,200,140,0.12);  color: var(--c-accent); border: 1px solid rgba(0,200,140,0.3); }
.rsi-neu { background: rgba(80,96,112,0.2);   color: var(--c-text-dim); }

/* Mini bar */
.bar-wrap { display: inline-flex; align-items: center; gap: .35rem; width: 80px; }
.bar-track { flex:1; height:3px; background: var(--c-text-faint); border-radius:2px; overflow:hidden; }
.bar-fill  { height:100%; border-radius:2px; transition: width .4s ease; }
.bar-fill.pos-fill { background: linear-gradient(90deg, var(--c-blue), var(--c-accent)); }
.bar-fill.neg-fill { background: linear-gradient(90deg, var(--c-red), #ff8c00); }

/* ════════════════════════════════
   SIGNAL CARDS
   ════════════════════════════════ */
.signal-feed {
  display: flex; flex-direction: column; gap: .4rem;
  padding: .5rem .6rem;
}
.signal-card {
  background: var(--c-elevated);
  border: 1px solid var(--c-border);
  border-radius: var(--radius);
  padding: .55rem .7rem;
  cursor: default;
  transition: border-color .2s;
}
.signal-card:hover { border-color: var(--c-border-hi); }
.signal-card.buy-card  { border-left: 2px solid var(--c-accent); }
.signal-card.sell-card { border-left: 2px solid var(--c-red); }
.signal-card.hold-card { border-left: 2px solid var(--c-yellow); }

.sig-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: .35rem; }
.sig-sym { font-family: var(--font-head); font-size: .85rem; font-weight: 700; color: #fff; }
.sig-dir {
  font-size: .58rem; font-weight: 700; letter-spacing: .1em;
  padding: .15rem .5rem; border-radius: 3px;
}
.dir-buy  { background: var(--c-accent-dim); color: var(--c-accent); }
.dir-sell { background: var(--c-red-dim);    color: var(--c-red); }
.dir-hold { background: var(--c-yellow-dim); color: var(--c-yellow); }
.sig-conf-row { display: flex; align-items: center; gap: .5rem; }
.sig-conf-bar { flex:1; height:2px; background: var(--c-text-faint); border-radius:1px; overflow:hidden; }
.sig-conf-fill { height:100%; border-radius:1px; }
.fill-buy  { background: linear-gradient(90deg, var(--c-blue), var(--c-accent)); }
.fill-sell { background: linear-gradient(90deg, var(--c-red), #ff8800); }
.fill-hold { background: var(--c-yellow); }
.sig-pct { font-size: .6rem; color: var(--c-text-dim); flex-shrink:0; min-width:28px; text-align:right; }
.sig-time { font-size: .57rem; color: var(--c-text-dim); margin-top: .25rem; }

/* ════════════════════════════════
   POSITIONS
   ════════════════════════════════ */
.pos-card {
  display: inline-flex; flex-direction: column;
  background: var(--c-elevated);
  border: 1px solid var(--c-border);
  border-radius: var(--radius);
  padding: .5rem .75rem;
  min-width: 140px;
  margin: .3rem;
  vertical-align: top;
}
.pos-sym { font-family: var(--font-head); font-size: .85rem; font-weight: 700; color: #fff; }
.pos-side {
  font-size: .55rem; font-weight: 700; letter-spacing: .08em;
  display: inline-block; padding: .1rem .35rem; border-radius: 3px;
  margin-left: .3rem;
}
.pos-long  { background: var(--c-accent-dim); color: var(--c-accent); }
.pos-short { background: var(--c-red-dim); color: var(--c-red); }
.pos-entry { font-size: .62rem; color: var(--c-text-dim); margin: .25rem 0 0; }
.pos-pnl   { font-family: var(--font-head); font-size: 1rem; font-weight: 700; margin-top: .15rem; }

/* ════════════════════════════════
   TRADE HISTORY
   ════════════════════════════════ */
.trade-row { display: flex; align-items: center; gap: .5rem; padding: .35rem .7rem;
  border-bottom: 1px solid rgba(0,200,140,0.04); font-size: .66rem; }
.trade-row:last-child { border-bottom: none; }
.trade-side { font-weight: 700; font-size: .58rem; padding: .1rem .35rem; border-radius: 3px; flex-shrink:0; }
.trade-sym { color: #e2eef9; min-width: 55px; font-weight:500; }
.trade-price { color: var(--c-text); flex:1; text-align:right; font-variant-numeric:tabular-nums; }
.trade-pnl { min-width:60px; text-align:right; font-variant-numeric:tabular-nums; font-weight:500; }
.trade-time { color: var(--c-text-dim); font-size: .58rem; flex-shrink:0; min-width:45px; text-align:right; }

/* ════════════════════════════════
   AGENT STATUS
   ════════════════════════════════ */
.agent-row {
  display: flex; align-items: center; gap: .6rem;
  padding: .45rem .75rem;
  border-bottom: 1px solid rgba(0,200,140,0.04);
  font-size: .67rem;
}
.agent-row:last-child { border-bottom: none; }
.agent-indicator {
  width: 6px; height: 6px; border-radius: 50%;
  flex-shrink: 0;
}
.agent-indicator.alive { background: var(--c-accent); box-shadow: 0 0 5px var(--c-accent); animation: blink 2s infinite; }
.agent-indicator.dead  { background: var(--c-red); }
.agent-name { color: #e2eef9; font-weight: 500; min-width: 100px; }
.agent-role { flex:1; color: var(--c-text-dim); font-size:.6rem; }
.agent-time { color: var(--c-text-dim); font-size: .6rem; flex-shrink:0; }

/* ── RL BARS ── */
.rl-item { padding: .45rem .75rem; border-bottom: 1px solid rgba(0,200,140,0.04); }
.rl-item:last-child { border-bottom: none; }
.rl-name { font-size: .65rem; color: #e2eef9; font-weight: 500; display:flex; justify-content:space-between; margin-bottom:.3rem; }
.rl-score { color: var(--c-accent); }
.rl-bar-track { height: 3px; background: var(--c-text-faint); border-radius:2px; overflow:hidden; }
.rl-bar-fill { height:100%; border-radius:2px; transition: width .8s ease; }

/* ════════════════════════════════
   EMPTY / LOADING STATES
   ════════════════════════════════ */
.empty-state {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  height: 100%; gap: .4rem;
  color: var(--c-text-dim); font-size: .68rem;
}
.shimmer-line {
  height: 10px; border-radius: 3px;
  background: linear-gradient(90deg, var(--c-text-faint) 25%, rgba(0,200,140,0.08) 50%, var(--c-text-faint) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
}
@keyframes shimmer { from { background-position:-200% 0; } to { background-position:200% 0; } }

/* ════════════════════════════════
   RESPONSIVE
   ════════════════════════════════ */
@media (max-width: 1100px) {
  .workspace { grid-template-columns: 1fr 280px; grid-template-rows: auto auto auto auto auto; height: auto; overflow:auto; }
  .slot-chart     { grid-column: 1;     grid-row: 1; min-height:180px; }
  .slot-stats     { grid-column: 2;     grid-row: 1; }
  .slot-market    { grid-column: 1 / 3; grid-row: 2; }
  .slot-signals   { grid-column: 1 / 3; grid-row: 3; min-height:250px; }
  .slot-positions { grid-column: 1 / 3; grid-row: 4; }
  .slot-history   { grid-column: 1;     grid-row: 5; }
  .slot-agents    { grid-column: 2;     grid-row: 5; }
}
</style>
</head>
<body>

<!-- ══ TICKER TAPE ══ -->
<div class="ticker-tape">
  <div class="ticker-track" id="ticker-track">
    <!-- JS tarafından doldurulur, başlangıç şablonu: -->
    <span class="ticker-item"><span class="ticker-sym">BTC</span><span class="ticker-price">$--</span><span class="ticker-chg">--</span></span>
    <span class="ticker-item"><span class="ticker-sym">ETH</span><span class="ticker-price">$--</span><span class="ticker-chg">--</span></span>
    <span class="ticker-item"><span class="ticker-sym">SOL</span><span class="ticker-price">$--</span><span class="ticker-chg">--</span></span>
    <span class="ticker-item"><span class="ticker-sym">BNB</span><span class="ticker-price">$--</span><span class="ticker-chg">--</span></span>
    <span class="ticker-item"><span class="ticker-sym">XRP</span><span class="ticker-price">$--</span><span class="ticker-chg">--</span></span>
  </div>
</div>

<!-- ══ TOPBAR ══ -->
<div class="topbar">
  <div class="brand">
    <div class="brand-icon">▲</div>
    <div>
      AURORA AI
      <div class="brand-sub">CRYPTO HEDGE FUND · PAPER TRADING</div>
    </div>
  </div>
  <div class="topbar-kpis">
    <div class="kpi">
      <div class="kpi-label">Toplam PnL</div>
      <div class="kpi-val up" id="kpi-pnl">$+0.00</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Win Rate</div>
      <div class="kpi-val blue" id="kpi-wr">0%</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">İşlemler</div>
      <div class="kpi-val" id="kpi-trades">0</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Açık Pozisyon</div>
      <div class="kpi-val yellow" id="kpi-pos">0</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Çalışma</div>
      <div class="kpi-val" id="kpi-uptime">00:00:00</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Semboller</div>
      <div class="kpi-val" id="kpi-syms">0</div>
    </div>
  </div>
  <div class="topbar-right">
    <div class="status-live">
      <div class="dot-live"></div>CANLI
    </div>
    <div id="topbar-time">--:--:--</div>
  </div>
</div>

<!-- ══ WORKSPACE ══ -->
<div class="workspace">

  <!-- ── PNL CHART ── -->
  <div class="panel slot-chart">
    <div class="panel-header">
      <div class="panel-title"><span class="icon">◆</span> PNL GRAFİĞİ</div>
      <div style="display:flex;gap:.4rem;align-items:center">
        <span class="panel-badge badge-green" id="chart-mode">KÜMÜLATIF</span>
        <button onclick="toggleChartMode()" style="background:var(--c-elevated);border:1px solid var(--c-border);color:var(--c-text-dim);font-size:.58rem;padding:.2rem .5rem;border-radius:3px;cursor:pointer;font-family:var(--font-mono)">DEĞİŞTİR</button>
      </div>
    </div>
    <div class="chart-container">
      <canvas id="pnlChart"></canvas>
    </div>
  </div>

  <!-- ── MINI STATS ── -->
  <div class="panel slot-stats" style="padding:0">
    <div class="panel-header">
      <div class="panel-title"><span class="icon">◈</span> PERFORMANS</div>
    </div>
    <div class="stats-grid">
      <div class="stat-cell">
        <div class="stat-label">Toplam PnL</div>
        <div class="stat-val green" id="stat-pnl">$+0.00</div>
        <div class="stat-sub">başlangıçtan beri</div>
      </div>
      <div class="stat-cell">
        <div class="stat-label">Win Rate</div>
        <div class="stat-val blue" id="stat-wr">0%</div>
        <div class="stat-sub" id="stat-wl">W:0 / L:0</div>
      </div>
      <div class="stat-cell">
        <div class="stat-label">Açık Poz.</div>
        <div class="stat-val yellow" id="stat-pos">0</div>
        <div class="stat-sub">aktif işlem</div>
      </div>
      <div class="stat-cell">
        <div class="stat-label">RL Episode</div>
        <div class="stat-val" id="stat-ep">—</div>
        <div class="stat-sub">ε-greedy</div>
      </div>
      <div class="stat-cell">
        <div class="stat-label">Avg Reward</div>
        <div class="stat-val" id="stat-rew">—</div>
        <div class="stat-sub">son 20 ep.</div>
      </div>
      <div class="stat-cell">
        <div class="stat-label">Epsilon</div>
        <div class="stat-val" id="stat-eps">—</div>
        <div class="stat-sub">keşif oranı</div>
      </div>
    </div>
  </div>

  <!-- ── MARKET TABLE ── -->
  <div class="panel slot-market">
    <div class="panel-header">
      <div class="panel-title"><span class="icon">◉</span> PİYASA VERİSİ</div>
      <span class="panel-badge badge-blue" id="mkt-count">0 Sembol</span>
    </div>
    <div class="panel-body no-pad" style="overflow-y:auto">
      <table class="data-table">
        <thead>
          <tr>
            <th onclick="sortTable('sym')">Sembol</th>
            <th onclick="sortTable('price')">Fiyat</th>
            <th onclick="sortTable('change')">24s Değ.</th>
            <th onclick="sortTable('rsi')">RSI</th>
            <th onclick="sortTable('macd')">MACD</th>
            <th onclick="sortTable('vol')">Hacim 24s</th>
            <th>Momentum</th>
            <th>İşaret</th>
          </tr>
        </thead>
        <tbody id="market-tbody">
          <tr><td colspan="8" style="padding:1.5rem;text-align:center">
            <div class="shimmer-line" style="width:60%;margin:auto"></div>
          </td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- ── SIGNALS FEED ── -->
  <div class="panel slot-signals">
    <div class="panel-header">
      <div class="panel-title"><span class="icon">◎</span> SİNYAL AKIŞI</div>
      <span class="panel-badge badge-green" id="sig-count">0</span>
    </div>
    <div id="signals-feed" class="signal-feed" style="overflow-y:auto;flex:1">
      <div class="empty-state">
        <div>⟳</div>
        <div>Sinyal bekleniyor...</div>
      </div>
    </div>
  </div>

  <!-- ── POSITIONS ── -->
  <div class="panel slot-positions">
    <div class="panel-header">
      <div class="panel-title"><span class="icon">▣</span> AÇIK POZİSYONLAR</div>
      <span class="panel-badge badge-yellow" id="pos-count">0 Aktif</span>
    </div>
    <div class="panel-body" id="positions-body" style="overflow-x:auto;overflow-y:hidden;white-space:nowrap">
      <div class="empty-state" style="height:80px">
        <div style="font-size:.7rem">Açık pozisyon yok · Paper Trading Modu</div>
      </div>
    </div>
  </div>

  <!-- ── TRADE HISTORY ── -->
  <div class="panel slot-history">
    <div class="panel-header">
      <div class="panel-title"><span class="icon">≡</span> İŞLEM GEÇMİŞİ</div>
      <span class="panel-badge badge-blue" id="hist-count">0 Trade</span>
    </div>
    <div class="panel-body no-pad" style="overflow-y:auto" id="trade-history">
      <div class="empty-state" style="height:80px">
        <div>Henüz işlem gerçekleşmedi</div>
      </div>
    </div>
  </div>

  <!-- ── AGENTS + RL ── -->
  <div class="panel slot-agents">
    <div class="panel-header">
      <div class="panel-title"><span class="icon">⬡</span> AJAN DURUMU · RL</div>
      <span class="panel-badge badge-green">AKTİF</span>
    </div>
    <div class="panel-body no-pad" style="overflow-y:auto">
      <div id="agent-list"></div>
      <div style="padding:.4rem .75rem; border-top: 1px solid var(--c-border); margin-top:.2rem">
        <div style="font-size:.58rem;letter-spacing:.1em;text-transform:uppercase;color:var(--c-text-dim);padding:.2rem 0 .4rem">Strateji Ağırlıkları</div>
        <div id="rl-weights"></div>
      </div>
    </div>
  </div>

</div><!-- workspace -->

<!-- ══ CHART.JS CDN ══ -->
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>
'use strict';

// ── STATE ──
const state = {
  pnlHistory: [0],
  prevPrices: {},
  tradeLog: [],
  chartMode: 'cumulative', // 'cumulative' | 'per-trade'
};

// ── CHART SETUP ──
const ctx = document.getElementById('pnlChart').getContext('2d');
const pnlChart = new Chart(ctx, {
  type: 'line',
  data: {
    labels: ['0'],
    datasets: [{
      label: 'PnL',
      data: [0],
      borderColor: '#00c88c',
      borderWidth: 1.5,
      pointRadius: 0,
      pointHoverRadius: 3,
      fill: true,
      backgroundColor: function(ctx) {
        const g = ctx.chart.ctx.createLinearGradient(0, 0, 0, ctx.chart.height);
        g.addColorStop(0, 'rgba(0,200,140,0.18)');
        g.addColorStop(1, 'rgba(0,200,140,0.01)');
        return g;
      },
      tension: 0.4,
    }]
  },
  options: {
    animation: { duration: 400 },
    responsive: true, maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: '#0d1520',
        borderColor: 'rgba(0,200,140,0.3)',
        borderWidth: 1,
        titleColor: '#00c88c',
        bodyColor: '#b8cce0',
        callbacks: {
          label: ctx => ' $' + ctx.parsed.y.toFixed(4)
        }
      }
    },
    scales: {
      x: {
        grid: { color: 'rgba(0,200,140,0.04)', drawBorder: false },
        ticks: { color: '#506070', font: { family: "'JetBrains Mono'", size: 10 }, maxTicksLimit: 8 }
      },
      y: {
        grid: { color: 'rgba(0,200,140,0.06)', drawBorder: false },
        ticks: {
          color: '#506070', font: { family: "'JetBrains Mono'", size: 10 },
          callback: v => '$' + v.toFixed(2)
        }
      }
    }
  }
});

function toggleChartMode() {
  state.chartMode = state.chartMode === 'cumulative' ? 'per-trade' : 'cumulative';
  document.getElementById('chart-mode').textContent = state.chartMode === 'cumulative' ? 'KÜMÜLATİF' : 'İŞLEM BAŞI';
  updateChart();
}

function updateChart() {
  const data = state.pnlHistory;
  if (state.chartMode === 'per-trade') {
    const perTrade = data.map((v, i) => i === 0 ? v : v - data[i-1]);
    pnlChart.data.datasets[0].data = perTrade;
    pnlChart.data.datasets[0].backgroundColor = ctx => {
      const g = ctx.chart.ctx.createLinearGradient(0,0,0,ctx.chart.height);
      g.addColorStop(0, 'rgba(0,144,255,0.18)'); g.addColorStop(1, 'rgba(0,144,255,0.01)');
      return g;
    };
    pnlChart.data.datasets[0].borderColor = '#0090ff';
  } else {
    pnlChart.data.datasets[0].data = data;
    pnlChart.data.datasets[0].backgroundColor = ctx => {
      const g = ctx.chart.ctx.createLinearGradient(0,0,0,ctx.chart.height);
      const lastVal = data[data.length-1];
      const color = lastVal >= 0 ? '0,200,140' : '255,59,92';
      g.addColorStop(0, `rgba(${color},0.18)`); g.addColorStop(1, `rgba(${color},0.01)`);
      return g;
    };
    pnlChart.data.datasets[0].borderColor = data[data.length-1] >= 0 ? '#00c88c' : '#ff3b5c';
  }
  pnlChart.data.labels = data.map((_, i) => i === 0 ? '0' : String(i));
  pnlChart.update('none');
}

// ── CLOCK ──
function tickClock() {
  const now = new Date();
  const s = now.toUTCString().split(' ')[4] + ' UTC';
  document.getElementById('topbar-time').textContent = s;
}
setInterval(tickClock, 1000); tickClock();

// ── FORMAT HELPERS ──
function fmtPrice(n) {
  if (n >= 10000) return '$' + n.toLocaleString('en-US', {maximumFractionDigits:0});
  if (n >= 100)   return '$' + n.toFixed(2);
  if (n >= 1)     return '$' + n.toFixed(3);
  return '$' + n.toFixed(5);
}
function fmtVol(n) {
  if (n >= 1e9) return '$' + (n/1e9).toFixed(2) + 'B';
  if (n >= 1e6) return '$' + (n/1e6).toFixed(1) + 'M';
  if (n >= 1e3) return '$' + (n/1e3).toFixed(0) + 'K';
  return '$' + n.toFixed(0);
}
function fmtUptime(s) {
  const h = Math.floor(s/3600), m = Math.floor((s%3600)/60), sec = Math.floor(s%60);
  return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`;
}
function fmtAgo(iso) {
  const ms = Date.now() - new Date(iso.includes('Z')?iso:iso+'Z').getTime();
  const s = Math.floor(ms/1000);
  if (s < 60) return s + 's';
  if (s < 3600) return Math.floor(s/60) + 'm';
  return Math.floor(s/3600) + 'h';
}
function setEl(id, txt, cls) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = txt;
  if (cls) el.className = el.className.replace(/\b(green|red|blue|yellow|up|down)\b/g,'').trim() + ' ' + cls;
}

const TICKER_NAMES = {
  bitcoin:'BTC', ethereum:'ETH', solana:'SOL',
  binancecoin:'BNB', ripple:'XRP'
};

// ── STATUS ──
async function fetchStatus() {
  try {
    const d = await fetch('/status').then(r=>r.json());

    // KPIs topbar
    const pnl = d.total_pnl || 0;
    const pnlStr = '$' + (pnl>=0?'+':'') + pnl.toFixed(4);
    setEl('kpi-pnl', pnlStr, pnl>=0?'up':'down');
    setEl('kpi-wr', (d.win_rate||0) + '%', 'blue');
    setEl('kpi-trades', d.trade_count||0);
    setEl('kpi-pos', d.open_positions||0, 'yellow');
    setEl('kpi-uptime', fmtUptime(d.uptime_seconds||0));
    setEl('kpi-syms', d.market_symbols||0);

    // Stats panel
    setEl('stat-pnl', pnlStr, pnl>=0?'green':'red');
    setEl('stat-wr', (d.win_rate||0)+'%', 'blue');
    const trades = d.trade_count||0;
    const wins = Math.round((d.win_rate/100)*trades);
    setEl('stat-wl', `W:${wins} / L:${trades-wins}`);
    setEl('stat-pos', d.open_positions||0, 'yellow');

    // PnL history — simulated cumulative
    if (pnl !== state.pnlHistory[state.pnlHistory.length-1]) {
      state.pnlHistory.push(pnl);
      if (state.pnlHistory.length > 120) state.pnlHistory = state.pnlHistory.slice(-120);
      updateChart();
    }

    // RL metrics
    const rl = d.rl_metrics || {};
    setEl('stat-ep', rl.episode !== undefined ? '#' + rl.episode : '—');
    setEl('stat-rew', rl.avg_reward_20ep !== undefined ? rl.avg_reward_20ep.toFixed(3) : '—',
      rl.avg_reward_20ep >= 0 ? 'green' : 'red');
    setEl('stat-eps', rl.epsilon !== undefined ? (rl.epsilon*100).toFixed(1)+'%' : '—');

    // RL weights
    const weights = rl.strategy_weights || {};
    const wEl = document.getElementById('rl-weights');
    if (Object.keys(weights).length) {
      const colors = { rsi:'#00c88c', macd:'#0090ff', bollinger:'#a855f7', composite:'#f0b429' };
      wEl.innerHTML = Object.entries(weights).map(([k,v]) => {
        const pct = Math.round(v * 100);
        const col = colors[k] || '#00c88c';
        return `<div class="rl-item">
          <div class="rl-name">${k} <span class="rl-score">${pct}%</span></div>
          <div class="rl-bar-track"><div class="rl-bar-fill" style="width:${pct}%;background:${col}"></div></div>
        </div>`;
      }).join('');
    }

    // Agent heartbeats
    const agents = d.agent_heartbeats || {};
    const ROLES = {
      MarketAgent:    'Veri Toplayıcı · CoinGecko API',
      StrategyAgent:  'Sinyal Üretici · RSI/MACD/Bollinger',
      RLMetaAgent:    'Q-Learning · Strateji Optimizer',
      ExecutionAgent: 'Emir Uygulayıcı · Paper Mode',
    };
    document.getElementById('agent-list').innerHTML = Object.entries(agents).map(([name, ts]) => `
      <div class="agent-row">
        <div class="agent-indicator alive"></div>
        <div class="agent-name">${name}</div>
        <div class="agent-role">${ROLES[name]||''}</div>
        <div class="agent-time">${fmtAgo(ts)}</div>
      </div>`).join('') || '<div class="empty-state" style="height:60px"><div>Bağlanıyor...</div></div>';

  } catch(e) { console.warn('status err', e); }
}

// ── MARKET ──
let sortCol = 'change', sortDir = -1;

function sortTable(col) {
  if (sortCol === col) sortDir *= -1;
  else { sortCol = col; sortDir = -1; }
  renderMarket();
}

let marketData = {};

async function fetchMarket() {
  try {
    const d = await fetch('/market').then(r=>r.json());
    marketData = d.symbols || {};
    renderMarket();
    updateTicker();
    setEl('mkt-count', Object.keys(marketData).length + ' Sembol');
  } catch(e) { console.warn('market err', e); }
}

function renderMarket() {
  const entries = Object.entries(marketData);
  if (!entries.length) return;

  // Sort
  entries.sort(([,a],[,b]) => {
    const getVal = (x) => ({
      sym: 0, price: x.price||0, change: x.change_24h||0,
      rsi: x.rsi||50, macd: x.macd||0, vol: x.volume_24h||0
    }[sortCol] || 0);
    return (getVal(a) - getVal(b)) * sortDir;
  });

  const tbody = document.getElementById('market-tbody');
  tbody.innerHTML = entries.map(([sym, data]) => {
    const price  = data.price || 0;
    const prev   = state.prevPrices[sym] || price;
    const flash  = price > prev ? 'flash-g' : price < prev ? 'flash-r' : '';
    state.prevPrices[sym] = price;

    const change = data.change_24h || 0;
    const rsi    = data.rsi || 50;
    const macd   = data.macd || 0;
    const vol    = data.volume_24h || 0;
    const mom    = data.momentum_1m || 0;

    const rsiCls = rsi > 70 ? 'rsi-ob' : rsi < 30 ? 'rsi-os' : 'rsi-neu';
    const changeCls = change >= 0 ? 'pos' : 'neg';
    const macdCls   = macd  >= 0 ? 'pos' : 'neg';
    const momCls    = mom   >= 0 ? 'pos' : 'neg';

    // Signal hint
    let sigHint = '–';
    if (rsi < 30 && macd > 0) sigHint = '<span class="pos">▲ BUY</span>';
    else if (rsi > 70 && macd < 0) sigHint = '<span class="neg">▼ SELL</span>';
    else if (rsi < 35) sigHint = '<span class="pos" style="opacity:.7">↑ Zayıf Al</span>';
    else if (rsi > 65) sigHint = '<span class="neg" style="opacity:.7">↓ Zayıf Sat</span>';

    const bbPct = data.bb_upper && data.bb_lower ?
      Math.round(((price - data.bb_lower) / (data.bb_upper - data.bb_lower)) * 100) : 50;
    const barWidth = Math.max(0, Math.min(100, bbPct));
    const barFill = barWidth > 50 ? 'pos-fill' : 'neg-fill';

    const short = TICKER_NAMES[sym] || sym.substring(0,4).toUpperCase();

    return `<tr class="${flash}">
      <td><span class="sym-name">${short}</span><span class="sym-full">${sym.toUpperCase()}</span></td>
      <td style="color:#e2eef9">${fmtPrice(price)}</td>
      <td class="${changeCls}">${change >= 0 ? '+' : ''}${change.toFixed(2)}%</td>
      <td><span class="rsi ${rsiCls}">${rsi.toFixed(1)}</span></td>
      <td class="${macdCls}">${macd >= 0 ? '+' : ''}${macd.toFixed(5)}</td>
      <td style="color:var(--c-text-dim)">${fmtVol(vol)}</td>
      <td><div class="bar-wrap"><div class="bar-track"><div class="bar-fill ${barFill}" style="width:${barWidth}%"></div></div><span class="${momCls}" style="font-size:.6rem;min-width:36px;text-align:right">${mom>=0?'+':''}${mom.toFixed(2)}%</span></div></td>
      <td>${sigHint}</td>
    </tr>`;
  }).join('');
}

function updateTicker() {
  const entries = Object.entries(marketData);
  if (!entries.length) return;
  const items = [...entries, ...entries].map(([sym, d]) => {
    const c = d.change_24h || 0;
    const short = TICKER_NAMES[sym] || sym.substring(0,4).toUpperCase();
    return `<span class="ticker-item">
      <span class="ticker-sym">${short}</span>
      <span class="ticker-price">${fmtPrice(d.price||0)}</span>
      <span class="ticker-chg ${c>=0?'up':'down'}">${c>=0?'+':''}${c.toFixed(2)}%</span>
    </span>`;
  }).join('');
  document.getElementById('ticker-track').innerHTML = items;
}

// ── SIGNALS ──
async function fetchSignals() {
  try {
    const d = await fetch('/signals').then(r=>r.json());
    const sigs = d.signals || [];
    setEl('sig-count', sigs.length);

    const feed = document.getElementById('signals-feed');
    if (!sigs.length) {
      feed.innerHTML = '<div class="empty-state"><div>⟳</div><div>Sinyal bekleniyor...</div></div>';
      return;
    }

    feed.innerHTML = sigs.slice(0,20).map(sig => {
      const pct = Math.round(sig.confidence * 100);
      const short = TICKER_NAMES[sig.symbol] || sig.symbol.substring(0,4).toUpperCase();
      const cardCls = sig.direction + '-card';
      const dirCls  = 'dir-' + sig.direction;
      const fillCls = 'fill-' + sig.direction;
      const t = new Date(sig.timestamp.includes('Z')?sig.timestamp:sig.timestamp+'Z');
      const tStr = t.toLocaleTimeString('tr-TR',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
      const strat = sig.strategy || 'composite';

      return `<div class="signal-card ${cardCls}">
        <div class="sig-top">
          <span class="sig-sym">${short}</span>
          <span class="sig-dir ${dirCls}">${sig.direction.toUpperCase()}</span>
        </div>
        <div class="sig-conf-row">
          <div class="sig-conf-bar"><div class="sig-conf-fill ${fillCls}" style="width:${pct}%"></div></div>
          <span class="sig-pct">${pct}%</span>
        </div>
        <div class="sig-time">${tStr} · ${strat}</div>
      </div>`;
    }).join('');
  } catch(e) { console.warn('signals err', e); }
}

// ── POSITIONS ──
async function fetchPositions() {
  try {
    const d = await fetch('/positions').then(r=>r.json());
    const positions = d.open || [];
    setEl('pos-count', positions.length + ' Aktif');
    setEl('kpi-pos', positions.length, 'yellow');

    const body = document.getElementById('positions-body');
    if (!positions.length) {
      body.innerHTML = '<div class="empty-state" style="height:80px"><div style="font-size:.7rem">Açık pozisyon yok · Paper Trading Modu</div></div>';
      return;
    }

    body.innerHTML = positions.map(p => {
      const short = TICKER_NAMES[p.symbol] || p.symbol.substring(0,4).toUpperCase();
      const pnlCls = p.pnl >= 0 ? 'green' : 'red';
      return `<div class="pos-card">
        <div><span class="pos-sym">${short}</span><span class="pos-side ${p.side==='long'?'pos-long':'pos-short'}">${p.side.toUpperCase()}</span></div>
        <div class="pos-entry">Giriş: ${fmtPrice(p.entry_price)}</div>
        <div class="pos-entry">Anlık: ${fmtPrice(p.current_price||p.entry_price)}</div>
        <div class="pos-pnl ${pnlCls}">${p.pnl>=0?'+':''}$${(p.pnl||0).toFixed(4)}</div>
      </div>`;
    }).join('');
  } catch(e) { console.warn('positions err', e); }
}

// ── REFRESH ──
async function refresh() {
  await Promise.all([fetchStatus(), fetchMarket(), fetchSignals(), fetchPositions()]);
}

refresh();
setInterval(refresh, 5000);
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
