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
#  FASTAPI + DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Aurora AI — Trading Terminal</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&family=Barlow+Condensed:wght@400;600;700;800&family=Barlow:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<style>
:root{
  --bg:#05080f;--s0:#070b14;--s1:#0b1018;--s2:#0f1620;--s3:#141e2a;
  --b0:rgba(0,195,130,0.07);--b1:rgba(0,195,130,0.15);
  --g:#00c382;--r:#ff3b5c;--b:#0096ff;--y:#f5a623;--p:#a855f7;--cy:#00d4ff;
  --t0:#cde0f0;--t1:#6a8fa8;--t2:#2e4055;--t3:#162030;
  --mono:'JetBrains Mono',monospace;--head:'Barlow Condensed',sans-serif;
  --rad:5px;--sh:0 2px 12px rgba(0,0,0,.5);
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden}
body{font-family:var(--mono);background:var(--bg);color:var(--t0);font-size:12px;
  display:flex;flex-direction:column}
body::after{content:'';position:fixed;inset:0;pointer-events:none;z-index:0;
  background:repeating-linear-gradient(0deg,transparent,transparent 43px,rgba(0,195,130,0.015) 44px),
             repeating-linear-gradient(90deg,transparent,transparent 43px,rgba(0,195,130,0.015) 44px)}
::-webkit-scrollbar{width:3px;height:3px}
::-webkit-scrollbar-thumb{background:var(--t2);border-radius:2px}

/* ── TICKER ── */
.tape{height:24px;background:var(--s0);border-bottom:1px solid var(--b0);
  overflow:hidden;display:flex;align-items:center;flex-shrink:0;position:relative;z-index:100}
.tape-inner{display:flex;white-space:nowrap;animation:tape 900s linear infinite}
.tape-inner:hover{animation-play-state:paused}
@keyframes tape{from{transform:translateX(0)}to{transform:translateX(-50%)}}
.ti{display:inline-flex;align-items:center;gap:.3rem;padding:0 .9rem;font-size:.6rem;border-right:1px solid var(--t2)}
.ti-s{color:#fff;font-weight:600}.ti-p{color:var(--t1)}.up{color:var(--g)}.dn{color:var(--r)}

/* ── TOPBAR ── */
.topbar{height:46px;background:var(--s0);border-bottom:1px solid var(--b0);
  display:flex;align-items:stretch;flex-shrink:0;position:relative;z-index:99}
.brand{display:flex;align-items:center;gap:.5rem;padding:0 1rem;border-right:1px solid var(--b0);flex-shrink:0}
.brand-icon{width:24px;height:24px;background:linear-gradient(135deg,var(--g),var(--b));
  border-radius:4px;display:grid;place-items:center;font-size:.65rem;color:#000;font-weight:800;font-family:var(--head)}
.brand-name{font-family:var(--head);font-size:1.1rem;font-weight:800;letter-spacing:.05em;color:#fff}
.brand-sub{font-size:.48rem;color:var(--t2);letter-spacing:.12em;text-transform:uppercase}
.top-kpis{display:flex;align-items:stretch;flex:1;overflow:hidden}
.tkpi{display:flex;flex-direction:column;justify-content:center;padding:0 .8rem;
  border-right:1px solid var(--b0);min-width:72px;cursor:default}
.tkpi:hover{background:rgba(0,195,130,0.03)}
.tkpi-l{font-size:.45rem;letter-spacing:.1em;text-transform:uppercase;color:var(--t2);margin-bottom:1px}
.tkpi-v{font-family:var(--head);font-size:.95rem;font-weight:700;color:#fff;font-variant-numeric:tabular-nums}
.tkpi-v.g{color:var(--g)}.tkpi-v.r{color:var(--r)}.tkpi-v.b{color:var(--b)}.tkpi-v.y{color:var(--y)}
.bot-ctrl{display:flex;align-items:center;gap:.35rem;padding:0 .7rem;border-left:1px solid var(--b0);flex-shrink:0}
.btn{display:inline-flex;align-items:center;gap:.25rem;padding:.25rem .55rem;border-radius:4px;
  border:1px solid;cursor:pointer;font-size:.58rem;font-family:var(--mono);letter-spacing:.05em;
  font-weight:600;transition:all .12s;user-select:none}
.btn-start{background:rgba(0,195,130,0.08);border-color:rgba(0,195,130,0.28);color:var(--g)}
.btn-start:hover{background:rgba(0,195,130,0.18);border-color:var(--g)}
.btn-pause{background:rgba(245,166,35,0.08);border-color:rgba(245,166,35,0.28);color:var(--y)}
.btn-pause:hover{background:rgba(245,166,35,0.18)}
.btn-stop{background:rgba(255,59,92,0.08);border-color:rgba(255,59,92,0.28);color:var(--r)}
.btn-stop:hover{background:rgba(255,59,92,0.18)}
.btn-settings{background:rgba(0,150,255,0.08);border-color:rgba(0,150,255,0.28);color:var(--b)}
.btn-settings:hover{background:rgba(0,150,255,0.18)}
#bot-status-badge{font-size:.52rem;padding:.18rem .45rem;border-radius:3px;letter-spacing:.08em;flex-shrink:0}
.top-right{display:flex;align-items:center;gap:.6rem;padding:0 .7rem;border-left:1px solid var(--b0);flex-shrink:0}
#clock{font-size:.6rem;color:var(--t1);min-width:65px;text-align:right}

/* ── MOVERS BAR ── */
.movers-bar{height:22px;background:var(--s0);border-bottom:1px solid var(--b0);
  display:flex;align-items:center;overflow:hidden;flex-shrink:0;position:relative;z-index:98}
.movers-label{padding:0 .7rem;font-size:.5rem;letter-spacing:.1em;text-transform:uppercase;
  color:var(--t2);border-right:1px solid var(--b0);flex-shrink:0;white-space:nowrap}
.movers-inner{display:flex;flex:1;overflow:hidden}
.mover-item{display:inline-flex;align-items:center;gap:.28rem;padding:0 .65rem;
  border-right:1px solid var(--t2);height:22px;cursor:pointer;font-size:.58rem;
  transition:background .1s;flex-shrink:0}
.mover-item:hover{background:rgba(255,255,255,0.04)}
.nxt-update{padding:0 .7rem;border-left:1px solid var(--b0);font-size:.55rem;
  color:var(--t2);flex-shrink:0;display:flex;align-items:center;gap:.3rem}

/* ── MAIN WORKSPACE ── */
/* 3 kolon, tam yükseklik, HİÇ çakışma yok */
.workspace{
  flex:1;display:grid;min-height:0;overflow:hidden;
  grid-template-columns:1fr 260px 290px;
  grid-template-rows:100%;
  gap:1px;background:var(--t2)
}

/* Her kolon kendi içinde flex column */
.col{display:flex;flex-direction:column;overflow:hidden;min-height:0;background:var(--bg)}

/* ── TAB SYSTEM ── */
.tab-bar{display:flex;flex-shrink:0;background:var(--s0);border-bottom:1px solid var(--b0)}
.tab-btn{padding:.3rem .75rem;font-size:.58rem;font-family:var(--mono);letter-spacing:.07em;
  text-transform:uppercase;color:var(--t1);cursor:pointer;border-bottom:2px solid transparent;
  border-right:1px solid var(--b0);transition:all .12s;white-space:nowrap}
.tab-btn:hover{color:var(--t0);background:rgba(255,255,255,0.02)}
.tab-btn.active{color:var(--g);border-bottom-color:var(--g);background:rgba(0,195,130,0.04)}
.tab-pane{display:none;flex:1;flex-direction:column;overflow:hidden;min-height:0}
.tab-pane.active{display:flex}

/* ── PANEL BASE ── */
.panel{background:var(--s1);display:flex;flex-direction:column;overflow:hidden;min-height:0;flex:1}
.ph{display:flex;align-items:center;justify-content:space-between;
  padding:.35rem .75rem;border-bottom:1px solid var(--b0);flex-shrink:0;min-height:28px}
.ph-title{font-family:var(--head);font-size:.62rem;letter-spacing:.1em;text-transform:uppercase;
  color:var(--t1);display:flex;align-items:center;gap:.3rem}
.ph-icon{color:var(--g);font-size:.7rem}
.scroll{flex:1;overflow-y:auto;overflow-x:hidden;min-height:0}
.badge{font-size:.5rem;letter-spacing:.07em;padding:.1rem .35rem;border-radius:3px;font-weight:700}
.bg{background:rgba(0,195,130,0.1);color:var(--g);border:1px solid rgba(0,195,130,0.22)}
.bb{background:rgba(0,150,255,0.1);color:var(--b);border:1px solid rgba(0,150,255,0.22)}
.br{background:rgba(255,59,92,0.1);color:var(--r);border:1px solid rgba(255,59,92,0.22)}
.by{background:rgba(245,166,35,0.1);color:var(--y);border:1px solid rgba(245,166,35,0.22)}

/* ── MARKET TABLE ── */
.mkt-wrap{flex:1;overflow:auto;min-height:0}
table{width:100%;border-collapse:collapse;font-size:.6rem}
thead{position:sticky;top:0;z-index:10;background:var(--s0)}
th{padding:.3rem .5rem;text-align:right;color:var(--t2);letter-spacing:.07em;
  text-transform:uppercase;border-bottom:1px solid var(--b0);cursor:pointer;white-space:nowrap;font-size:.52rem}
th:first-child,th:nth-child(2){text-align:left}
th:hover{color:var(--t1)}
th.sorted{color:var(--g)}
td{padding:.28rem .5rem;border-bottom:1px solid rgba(0,195,130,0.03);text-align:right;
  white-space:nowrap;vertical-align:middle}
td:first-child{text-align:left}
tr:hover td{background:rgba(0,195,130,0.03)}
.sym-cell{display:flex;flex-direction:column}
.sym-name{color:#fff;font-weight:600;font-size:.62rem}
.sym-sub{font-size:.48rem;color:var(--t2)}
.rsi-ob{background:rgba(255,59,92,0.15);color:var(--r);padding:.1rem .3rem;border-radius:3px}
.rsi-os{background:rgba(0,195,130,0.15);color:var(--g);padding:.1rem .3rem;border-radius:3px}
.rsi-n{color:var(--t1);padding:.1rem .3rem}
.sig-cell{display:flex;align-items:center;gap:.25rem}
.sig-dir{font-size:.5rem;font-weight:700;padding:.08rem .25rem;border-radius:2px}
.sd-buy{background:rgba(0,195,130,0.12);color:var(--g)}
.sd-sell{background:rgba(255,59,92,0.12);color:var(--r)}
.trade-btns{display:flex;gap:.2rem}
.tb{font-size:.5rem;padding:.08rem .28rem;border-radius:3px;cursor:pointer;font-family:var(--mono);
  font-weight:700;border:1px solid;background:transparent;transition:all .1s}
.tb-l{color:var(--g);border-color:rgba(0,195,130,0.25)}
.tb-l:hover{background:rgba(0,195,130,0.15)}
.tb-s{color:var(--r);border-color:rgba(255,59,92,0.25)}
.tb-s:hover{background:rgba(255,59,92,0.15)}

/* ── POSITION CARDS ── */
.pos-card{padding:.5rem .75rem;border-bottom:1px solid rgba(0,195,130,0.05);
  display:flex;flex-direction:column;gap:.22rem;flex-shrink:0}
.pos-card:last-child{border-bottom:none}
.pc-row1{display:flex;align-items:center;justify-content:space-between;gap:.3rem;flex-wrap:nowrap}
.pc-sym{font-family:var(--head);font-size:.9rem;font-weight:700;color:#fff}
.pc-side{font-size:.48rem;font-weight:800;padding:.08rem .28rem;border-radius:3px}
.ps-l{background:rgba(0,195,130,0.12);color:var(--g);border:1px solid rgba(0,195,130,0.25)}
.ps-s{background:rgba(255,59,92,0.12);color:var(--r);border:1px solid rgba(255,59,92,0.25)}
.pc-lev{font-size:.48rem;padding:.08rem .28rem;border-radius:3px;
  background:rgba(0,150,255,0.1);color:var(--b);border:1px solid rgba(0,150,255,0.22)}
.pc-dur{font-size:.48rem;color:var(--t2)}
.pc-pnl{font-family:var(--head);font-size:.85rem;font-weight:700;font-variant-numeric:tabular-nums;
  padding:.1rem .4rem;border-radius:4px}
.pc-close{font-size:.52rem;padding:.12rem .35rem;background:rgba(255,59,92,0.08);
  border:1px solid rgba(255,59,92,0.22);color:var(--r);border-radius:3px;cursor:pointer;
  font-family:var(--mono);flex-shrink:0}
.pc-close:hover{background:rgba(255,59,92,0.2)}
.pc-row2{display:flex;gap:.5rem;font-size:.57rem;color:var(--t1);flex-wrap:wrap}
.pc-lbl{color:var(--t2);font-size:.5rem}
.pc-bar-wrap{display:flex;align-items:center;gap:.3rem;font-size:.55rem}
.pc-bar-track{flex:1;height:4px;background:var(--t2);border-radius:2px;overflow:hidden;min-width:60px}
.pc-bar-fill{height:100%;border-radius:2px;background:linear-gradient(90deg,var(--b),var(--g));transition:width .4s}
.pc-tp-list{display:flex;gap:.18rem;flex-wrap:wrap}
.pc-tp{font-size:.5rem;padding:.08rem .28rem;border-radius:3px;border:1px solid}
.pc-ai{font-size:.54rem;color:var(--t1);background:rgba(0,150,255,0.04);
  border-left:2px solid rgba(0,150,255,0.18);padding:.18rem .4rem;
  border-radius:0 3px 3px 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* ── SENTIMENT BAR ── */
.sent-wrap{padding:.35rem .75rem;border-bottom:1px solid var(--b0);flex-shrink:0}
.sent-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:.22rem}
.sent-title{font-size:.5rem;letter-spacing:.08em;text-transform:uppercase;color:var(--t2)}
.sent-score{font-size:.58rem;font-weight:700}
.sent-bar{display:flex;height:5px;border-radius:3px;overflow:hidden;background:var(--t2)}
.sent-labels{display:flex;justify-content:space-between;margin-top:.18rem;font-size:.48rem;color:var(--t2)}

/* ── POS SUMMARY ── */
.pos-summary{display:flex;gap:.35rem;padding:.3rem .75rem;border-bottom:1px solid var(--b0);
  flex-shrink:0;flex-wrap:wrap;background:var(--s0)}
.psb{display:flex;flex-direction:column;padding:.15rem .4rem;background:var(--s1);
  border-radius:3px;border:1px solid var(--b0);min-width:52px}
.psb-l{font-size:.45rem;color:var(--t2);text-transform:uppercase;letter-spacing:.07em;margin-bottom:.08rem}
.psb-v{font-family:var(--head);font-size:.75rem;font-weight:700}

/* ── SIGNAL CARDS ── */
.sig-card{padding:.4rem .65rem;border-bottom:1px solid rgba(0,195,130,0.04)}
.sig-card:last-child{border-bottom:none}
.sc-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:.2rem}
.sc-sym{font-family:var(--head);font-size:.82rem;font-weight:700;color:#fff}
.sc-dir{font-size:.5rem;font-weight:800;padding:.08rem .28rem;border-radius:3px}
.sd-buy{background:rgba(0,195,130,0.12);color:var(--g)}
.sd-sell{background:rgba(255,59,92,0.12);color:var(--r)}
.sc-conf-bar{height:3px;border-radius:2px;transition:width .3s}
.sc-meta{display:flex;justify-content:space-between;align-items:center;margin-top:.2rem}
.sc-reason{font-size:.52rem;color:var(--t1);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sc-trade-btn{font-size:.48rem;padding:.07rem .28rem;background:rgba(0,150,255,0.08);
  border:1px solid rgba(0,150,255,0.22);color:var(--b);border-radius:3px;cursor:pointer;
  font-family:var(--mono);flex-shrink:0;margin-left:.4rem}
.sc-time{font-size:.48rem;color:var(--t2);margin-top:.12rem}
.buy-c{border-left:2px solid rgba(0,195,130,0.3)}
.sell-c{border-left:2px solid rgba(255,59,92,0.3)}

/* ── RIGHT PANEL: STATS GRID ── */
.stats-grid{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--t2);flex-shrink:0}
.stat-cell{background:var(--s1);padding:.55rem .7rem;display:flex;flex-direction:column;justify-content:center}
.stat-l{font-size:.46rem;letter-spacing:.1em;text-transform:uppercase;color:var(--t2);margin-bottom:.18rem}
.stat-v{font-family:var(--head);font-size:1.15rem;font-weight:700;color:#fff;font-variant-numeric:tabular-nums;line-height:1}
.stat-v.g{color:var(--g)}.stat-v.r{color:var(--r)}.stat-v.b{color:var(--b)}.stat-v.y{color:var(--y)}
.stat-s{font-size:.45rem;color:var(--t2);margin-top:.15rem}

/* ── ANALYTICS ── */
.an-grid{display:grid;grid-template-columns:1fr 1fr;gap:.5rem;padding:.6rem;flex-shrink:0}
.an-card{background:var(--s2);border-radius:var(--rad);padding:.5rem .65rem;border:1px solid var(--b0)}
.an-l{font-size:.48rem;letter-spacing:.09em;text-transform:uppercase;color:var(--t2);margin-bottom:.2rem}
.an-v{font-family:var(--head);font-size:1.1rem;font-weight:700;font-variant-numeric:tabular-nums}
.an-s{font-size:.46rem;color:var(--t2);margin-top:.12rem}
.an-chart-wrap{flex:1;padding:.5rem .6rem;min-height:0;display:flex;flex-direction:column;gap:.5rem}
.an-section-title{font-size:.52rem;letter-spacing:.1em;text-transform:uppercase;color:var(--t1);
  padding:.3rem .6rem;border-bottom:1px solid var(--b0);flex-shrink:0}
.reason-list{padding:.3rem .6rem;display:flex;flex-direction:column;gap:.3rem}
.reason-row{display:flex;align-items:center;gap:.5rem;font-size:.58rem}
.reason-bar-bg{flex:1;height:4px;background:var(--t2);border-radius:2px;overflow:hidden}
.reason-bar{height:100%;border-radius:2px;transition:width .5s}

/* ── CONTROL PANEL ── */
.ctrl-panel{flex-shrink:0;background:var(--s0);border-top:1px solid var(--b0)}
.ctrl-header{display:flex;align-items:center;justify-content:space-between;
  padding:.3rem .75rem;border-bottom:1px solid var(--b0)}
.ctrl-title{font-family:var(--head);font-size:.62rem;letter-spacing:.1em;text-transform:uppercase;
  color:var(--g);display:flex;align-items:center;gap:.35rem}
.ctrl-live-badge{font-size:.48rem;padding:.08rem .3rem;background:rgba(0,195,130,0.12);
  color:var(--g);border:1px solid rgba(0,195,130,0.25);border-radius:3px;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
.ctrl-save-btn{font-size:.55rem;padding:.25rem .65rem;background:rgba(0,195,130,0.12);
  border:1px solid rgba(0,195,130,0.35);color:var(--g);border-radius:4px;cursor:pointer;
  font-family:var(--mono);font-weight:600;transition:all .12s}
.ctrl-save-btn:hover{background:rgba(0,195,130,0.25);border-color:var(--g)}
.ctrl-body{padding:.45rem .75rem;display:grid;grid-template-columns:repeat(4,1fr);gap:.6rem}
.ctrl-item{display:flex;flex-direction:column;gap:.22rem}
.ctrl-lbl{font-size:.5rem;letter-spacing:.09em;text-transform:uppercase;color:var(--t2)}
.ctrl-val{font-family:var(--head);font-size:.88rem;font-weight:700;color:var(--cy);
  font-variant-numeric:tabular-nums;text-align:center}
.ctrl-slider{width:100%;-webkit-appearance:none;height:3px;border-radius:2px;
  background:var(--t2);outline:none;cursor:pointer}
.ctrl-slider::-webkit-slider-thumb{-webkit-appearance:none;width:12px;height:12px;
  border-radius:50%;background:var(--cy);cursor:pointer;border:2px solid var(--bg)}
.ctrl-slider:hover::-webkit-slider-thumb{background:var(--g)}
.ctrl-hint{font-size:.44rem;color:var(--t2);line-height:1.35}
.ctrl-lev-btns{display:flex;gap:.2rem;flex-wrap:wrap}
.clev-btn{font-size:.5rem;padding:.1rem .3rem;border-radius:3px;border:1px solid var(--t2);
  background:transparent;color:var(--t1);cursor:pointer;font-family:var(--mono);transition:all .1s}
.clev-btn.active{background:rgba(0,212,255,0.12);border-color:var(--cy);color:var(--cy)}

/* ── TRADE MODAL ── */
.modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:1000;
  display:none;align-items:center;justify-content:center;backdrop-filter:blur(4px)}
.modal-bg.open{display:flex}
.modal-box{background:var(--s1);border:1px solid rgba(0,150,255,0.25);border-radius:var(--rad);
  width:360px;max-width:95vw;display:flex;flex-direction:column;box-shadow:var(--sh)}
.modal-head{display:flex;align-items:center;justify-content:space-between;
  padding:.55rem .8rem;border-bottom:1px solid var(--b0)}
.modal-head h2{font-family:var(--head);font-size:.9rem;font-weight:700;letter-spacing:.08em;color:var(--b)}
.modal-close{background:none;border:none;color:var(--t1);font-size:.9rem;cursor:pointer;padding:.1rem .3rem}
.modal-close:hover{color:var(--t0)}
.modal-body{padding:.6rem .8rem;display:flex;flex-direction:column;gap:.4rem}
.modal-foot{display:flex;gap:.5rem;padding:.5rem .8rem;border-top:1px solid var(--b0)}
.side-btns{display:flex;gap:.4rem}
.side-btn{flex:1;padding:.45rem;border-radius:4px;border:1px solid;cursor:pointer;
  font-family:var(--head);font-size:.82rem;font-weight:700;text-align:center;transition:all .12s}
.sb-long{background:rgba(0,195,130,0.08);border-color:rgba(0,195,130,0.3);color:var(--g)}
.sb-long:hover,.sb-long.active{background:rgba(0,195,130,0.2);border-color:var(--g)}
.sb-short{background:rgba(255,59,92,0.08);border-color:rgba(255,59,92,0.3);color:var(--r)}
.sb-short:hover,.sb-short.active{background:rgba(255,59,92,0.2);border-color:var(--r)}
.lev-btns{display:flex;gap:.25rem;flex-wrap:wrap}
.lev-btn{font-size:.52rem;padding:.12rem .38rem;border-radius:3px;border:1px solid var(--t2);
  background:transparent;color:var(--t1);cursor:pointer;font-family:var(--mono);transition:all .1s}
.lev-btn.active{background:rgba(0,150,255,0.12);border-color:var(--b);color:var(--b)}
.trade-preview{background:var(--s0);border-radius:4px;padding:.4rem .55rem;
  border:1px solid var(--b0);font-size:.58rem;color:var(--t1)}
.tp-row{display:flex;justify-content:space-between;margin:.1rem 0}
.tp-row .lbl{color:var(--t2)}
.modal-exec{flex:1;padding:.38rem;border-radius:4px;cursor:pointer;font-family:var(--mono);
  font-size:.65rem;font-weight:700;border:1px solid;transition:all .12s}
.me-long{background:rgba(0,195,130,0.1);border-color:rgba(0,195,130,0.35);color:var(--g)}
.me-long:hover{background:rgba(0,195,130,0.22)}
.me-short{background:rgba(255,59,92,0.1);border-color:rgba(255,59,92,0.35);color:var(--r)}
.me-short:hover{background:rgba(255,59,92,0.22)}
.modal-cancel{padding:.38rem .7rem;border-radius:4px;border:1px solid var(--b0);
  color:var(--t1);background:transparent;cursor:pointer;font-family:var(--mono);font-size:.6rem}

/* ── HISTORY ROWS ── */
.hist-row{display:flex;align-items:center;gap:.35rem;padding:.3rem .65rem;
  border-bottom:1px solid rgba(0,195,130,0.03);font-size:.58rem;border-left:2px solid transparent}
.hist-row:last-child{border-bottom:none}
.hist-row.win{border-left-color:rgba(0,195,130,0.3)}
.hist-row.loss{border-left-color:rgba(255,59,92,0.3)}
.hist-side{font-size:.48rem;font-weight:700;padding:.08rem .25rem;border-radius:3px;flex-shrink:0}
.hist-sym{color:#fff;font-weight:600;min-width:42px;flex-shrink:0}
.hist-reason{font-size:.5rem;padding:.06rem .25rem;border-radius:3px;flex-shrink:0}
.hist-pnl{font-weight:700;font-variant-numeric:tabular-nums;min-width:60px;text-align:right;flex-shrink:0}
.hist-pct{font-size:.52rem;min-width:42px;text-align:right;flex-shrink:0}
.hist-dur{font-size:.5rem;color:var(--t2);min-width:30px;text-align:right;flex-shrink:0}
.hist-time{font-size:.5rem;color:var(--t2);margin-left:auto;flex-shrink:0}
.hist-stats{display:flex;gap:.5rem;padding:.28rem .65rem;border-bottom:1px solid var(--b0);
  font-size:.55rem;flex-shrink:0;background:var(--s0)}

/* ── AGENT LOG ── */
.agent-cards{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--t2);flex-shrink:0}
.agent-card{background:var(--s2);padding:.35rem .55rem;display:flex;align-items:center;gap:.4rem}
.agent-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0}
.agent-name{font-size:.58rem;font-weight:600;color:#fff}
.agent-desc{font-size:.5rem;color:var(--t2)}
.agent-hb{font-size:.48rem;color:var(--t2);margin-left:auto;flex-shrink:0}
.log-entry{display:flex;gap:.4rem;padding:.22rem .65rem;border-bottom:1px solid rgba(0,195,130,0.02);
  font-size:.55rem;align-items:baseline}
.log-ts{color:var(--t2);flex-shrink:0;min-width:45px}
.log-lv-TRADE{color:var(--g);font-weight:700;flex-shrink:0}
.log-lv-INFO{color:var(--b);flex-shrink:0}
.log-lv-WARN{color:var(--y);flex-shrink:0}
.log-lv-ERROR{color:var(--r);flex-shrink:0}
.log-msg{color:var(--t1);flex:1;word-break:break-all}

/* ── EMPTY STATES ── */
.empty{display:flex;flex-direction:column;align-items:center;justify-content:center;
  flex:1;gap:.4rem;color:var(--t2);font-size:.62rem;padding:1rem}
.empty-icon{font-size:1.5rem;opacity:.4}

/* ── CHART ── */
.chart-wrap{flex:1;padding:.4rem .6rem .5rem;overflow:hidden;display:flex;flex-direction:column;gap:.3rem}
canvas{width:100%!important;height:100%!important}

/* ── SCROLLBAR COLORS ── */
.scroll::-webkit-scrollbar{width:3px}.scroll::-webkit-scrollbar-thumb{background:var(--t2)}

/* ── MISC ── */
.g{color:var(--g)}.r{color:var(--r)}.b{color:var(--b)}.y{color:var(--y)}
input[type=text]{background:var(--s2);border:1px solid var(--b0);color:var(--t0);
  padding:.3rem .5rem;border-radius:4px;font-family:var(--mono);font-size:.65rem;width:100%}
input[type=text]:focus{outline:none;border-color:var(--b)}
.field-group{display:flex;flex-direction:column;gap:.25rem}
.field-group label{font-size:.5rem;letter-spacing:.09em;text-transform:uppercase;color:var(--t2)}
</style>
</head>
<body>

<!-- ═══════════════ TAPE ═══════════════ -->
<div class="tape"><div class="tape-inner" id="tape">
  <span class="ti"><span class="ti-s">BTC</span><span class="ti-p">$—</span><span>—</span></span>
  <span class="ti"><span class="ti-s">ETH</span><span class="ti-p">$—</span><span>—</span></span>
</div></div>

<!-- ═══════════════ TOPBAR ═══════════════ -->
<div class="topbar">
  <div class="brand">
    <div class="brand-icon">A</div>
    <div><div class="brand-name">AURORA AI</div><div style="font-size:.44rem;color:var(--t2);letter-spacing:.12em">CRYPTO HEDGE FUND · v4.0</div></div>
  </div>
  <div class="top-kpis">
    <div class="tkpi"><div class="tkpi-l">Sermaye</div><div class="tkpi-v" id="k-cap">$1,000</div></div>
    <div class="tkpi"><div class="tkpi-l">Equity</div><div class="tkpi-v" id="k-eq">$1,000</div></div>
    <div class="tkpi"><div class="tkpi-l">Realized PnL</div><div class="tkpi-v" id="k-pnl">$0.00</div></div>
    <div class="tkpi"><div class="tkpi-l">Getiri</div><div class="tkpi-v" id="k-ret">0.00%</div></div>
    <div class="tkpi"><div class="tkpi-l">Win Rate</div><div class="tkpi-v b" id="k-wr">0%</div></div>
    <div class="tkpi"><div class="tkpi-l">W / L</div><div class="tkpi-v" id="k-wl">0/0</div></div>
    <div class="tkpi"><div class="tkpi-l">İşlemler</div><div class="tkpi-v" id="k-tr">0</div></div>
    <div class="tkpi"><div class="tkpi-l">Açık Poz.</div><div class="tkpi-v y" id="k-op">0</div></div>
    <div class="tkpi"><div class="tkpi-l">Çalışma</div><div class="tkpi-v" id="k-up">00:00</div></div>
  </div>
  <div class="bot-ctrl">
    <span id="bot-status-badge" class="badge br">DURDURULDU</span>
    <button class="btn btn-start" onclick="botCtrl('start')">▶ BAŞLAT</button>
    <button class="btn btn-pause" onclick="botCtrl('pause')">⏸ DURAKLAT</button>
    <button class="btn btn-stop" onclick="botCtrl('stop')">⏹ DURDUR</button>
  </div>
  <div class="top-right">
    <div id="clock" style="font-size:.6rem;color:var(--t1)">—</div>
  </div>
</div>

<!-- ═══════════════ MOVERS BAR ═══════════════ -->
<div class="movers-bar">
  <div class="movers-label">🔥 ÖNCÜLER</div>
  <div class="movers-inner" id="movers-inner">
    <span class="mover-item"><span style="color:var(--t2)">Yükleniyor...</span></span>
  </div>
  <div class="nxt-update">Güncelleme: <span id="countdown" style="color:var(--b);font-variant-numeric:tabular-nums;min-width:22px">30s</span></div>
</div>

<!-- ═══════════════ WORKSPACE ═══════════════ -->
<div class="workspace">

  <!-- ═══ COL 1: PIYASA / POZİSYON / ANALİTİK ═══ -->
  <div class="col">
    <div class="tab-bar">
      <div class="tab-btn active" onclick="switchTab('mkt')">📊 PİYASA</div>
      <div class="tab-btn" onclick="switchTab('pos')">▣ POZİSYONLAR <span class="badge by" id="pos-cnt" style="margin-left:.3rem">0</span></div>
      <div class="tab-btn" onclick="switchTab('ana')">📈 ANALİTİK</div>
      <div class="tab-btn" onclick="switchTab('hist')">≡ GEÇMİŞ</div>
    </div>

    <!-- PİYASA TAB -->
    <div class="tab-pane active" id="tab-mkt" style="overflow:hidden;min-height:0">
      <div style="display:flex;align-items:center;gap:.5rem;padding:.3rem .6rem;border-bottom:1px solid var(--b0);flex-shrink:0;background:var(--s0)">
        <input type="text" id="mkt-search" placeholder="BTC, ETH, SOL..." style="max-width:140px" oninput="renderMkt()">
        <span style="font-size:.55rem;color:var(--t2)" id="mkt-cnt">0 sembol</span>
        <span style="margin-left:auto;font-size:.52rem;color:var(--t2)">Sırala:</span>
        <select id="mkt-sort" onchange="renderMkt()" style="background:var(--s2);border:1px solid var(--b0);color:var(--t1);font-family:var(--mono);font-size:.55rem;padding:.15rem .3rem;border-radius:3px">
          <option value="vol">Hacim</option>
          <option value="chg">24s %</option>
          <option value="rsi">RSI</option>
          <option value="sym">Sembol</option>
        </select>
      </div>
      <div class="mkt-wrap">
        <table>
          <thead><tr>
            <th style="text-align:left">Sembol</th>
            <th>Fiyat</th>
            <th>24s %</th>
            <th>RSI</th>
            <th>MACD</th>
            <th>Hacim</th>
            <th>Trend</th>
            <th>Sinyal</th>
            <th>İşlem</th>
          </tr></thead>
          <tbody id="mkt-body"><tr><td colspan="9" class="empty" style="height:60px">Veriler yükleniyor...</td></tr></tbody>
        </table>
      </div>
    </div>

    <!-- POZİSYON TAB -->
    <div class="tab-pane" id="tab-pos" style="overflow:hidden;min-height:0">
      <!-- Özet bar -->
      <div id="pos-summary" style="display:none" class="pos-summary"></div>
      <!-- Sentiment -->
      <div class="sent-wrap">
        <div class="sent-header">
          <span class="sent-title">◈ Piyasa Duygusu (RSI Dağılımı)</span>
          <span class="sent-score" id="sent-score">—</span>
        </div>
        <div class="sent-bar">
          <div id="sent-os" style="background:var(--g);width:0%;transition:width .5s"></div>
          <div id="sent-n"  style="background:var(--t2);width:100%;transition:width .5s"></div>
          <div id="sent-ob" style="background:var(--r);width:0%;transition:width .5s"></div>
        </div>
        <div class="sent-labels">
          <span id="sent-os-lbl">Aşırı Satım 0</span>
          <span id="sent-n-lbl">Nötr</span>
          <span id="sent-ob-lbl">Aşırı Alım 0</span>
        </div>
      </div>
      <!-- Pozisyon kartları -->
      <div class="scroll" id="pos-body">
        <div class="empty"><div class="empty-icon">📭</div><div>Açık pozisyon yok</div><div style="font-size:.5rem">Bot sinyal bekliyor...</div></div>
      </div>
    </div>

    <!-- ANALİTİK TAB -->
    <div class="tab-pane" id="tab-ana" style="overflow:hidden;min-height:0;overflow-y:auto">
      <div class="an-grid" id="an-grid">
        <div class="an-card"><div class="an-l">Toplam Kazanç</div><div class="an-v g" id="an-win-pnl">$0</div></div>
        <div class="an-card"><div class="an-l">Toplam Kayıp</div><div class="an-v r" id="an-loss-pnl">$0</div></div>
        <div class="an-card"><div class="an-l">Ort. Kazanç</div><div class="an-v g" id="an-avg-win">$0</div><div class="an-s" id="an-win-cnt">0 işlem</div></div>
        <div class="an-card"><div class="an-l">Ort. Kayıp</div><div class="an-v r" id="an-avg-loss">$0</div><div class="an-s" id="an-loss-cnt">0 işlem</div></div>
        <div class="an-card"><div class="an-l">Risk / Ödül</div><div class="an-v b" id="an-rr">0.00</div><div class="an-s">Kazanç / Kayıp oranı</div></div>
        <div class="an-card"><div class="an-l">Max Drawdown</div><div class="an-v r" id="an-dd">0.00%</div></div>
        <div class="an-card"><div class="an-l">Kazanç Serisi</div><div class="an-v g" id="an-wstr">0</div><div class="an-s" id="an-curr-str">—</div></div>
        <div class="an-card"><div class="an-l">Kayıp Serisi</div><div class="an-v r" id="an-lstr">0</div></div>
      </div>
      <div class="an-section-title">PnL Dağılımı (Kapanış Nedeni)</div>
      <div class="reason-list" id="reason-list"></div>
      <div class="an-section-title">Günlük PnL</div>
      <div style="padding:.5rem .6rem;flex-shrink:0;height:120px"><canvas id="daily-chart"></canvas></div>
    </div>

    <!-- GEÇMİŞ TAB -->
    <div class="tab-pane" id="tab-hist" style="overflow:hidden;min-height:0">
      <div class="hist-stats">
        <span>Kazanç: <span id="h-win-pnl" class="g">$0</span></span>
        <span>Kayıp: <span id="h-loss-pnl" class="r">$0</span></span>
        <span>Ort. Süre: <span id="h-avg-dur" style="color:var(--b)">—</span></span>
        <span style="margin-left:auto">Toplam: <span id="h-total" style="color:var(--y)">0</span></span>
      </div>
      <div class="scroll" id="hist-body">
        <div class="empty"><div class="empty-icon">📋</div><div>Henüz işlem yok</div></div>
      </div>
    </div>
  </div>

  <!-- ═══ COL 2: SİNYALLER + LOG ═══ -->
  <div class="col">
    <div class="tab-bar">
      <div class="tab-btn active" onclick="switchTab2('sigs')">⚡ SİNYALLER</div>
      <div class="tab-btn" onclick="switchTab2('log')">▸ SİSTEM LOGU</div>
    </div>

    <div class="tab-pane active" id="tab2-sigs" style="overflow:hidden;min-height:0">
      <div class="ph" style="flex-shrink:0">
        <div class="ph-title"><span class="ph-icon">⚡</span>Sinyal Akışı</div>
        <span class="badge bb" id="sig-cnt">0</span>
      </div>
      <div class="scroll" id="sigs-body">
        <div class="empty"><div class="empty-icon">🔍</div><div>Sinyal bekleniyor...</div></div>
      </div>
    </div>

    <div class="tab-pane" id="tab2-log" style="overflow:hidden;min-height:0">
      <div class="ph" style="flex-shrink:0">
        <div class="ph-title"><span class="ph-icon">▸</span>Sistem Logu</div>
        <button onclick="fetchLog()" style="background:var(--s2);border:1px solid var(--b0);color:var(--t1);font-size:.5rem;padding:.1rem .3rem;border-radius:3px;cursor:pointer;font-family:var(--mono)">↻</button>
      </div>
      <div class="scroll" id="log-body">
        <div class="empty"><div>Log bekleniyor...</div></div>
      </div>
    </div>
  </div>

  <!-- ═══ COL 3: STATS + AJANLAR + KONTROL PANELİ ═══ -->
  <div class="col">
    <!-- Stats -->
    <div class="ph" style="flex-shrink:0;background:var(--s0)">
      <div class="ph-title"><span class="ph-icon">◉</span>PERFORMANS</div>
    </div>
    <div class="stats-grid" style="flex-shrink:0">
      <div class="stat-cell"><div class="stat-l">Başlangıç</div><div class="stat-v" id="s-init">$1,000</div><div class="stat-s">Paper Trading</div></div>
      <div class="stat-cell"><div class="stat-l">Equity</div><div class="stat-v" id="s-eq">$1,000</div><div class="stat-s" id="s-ret">+0.00%</div></div>
      <div class="stat-cell"><div class="stat-l">PnL</div><div class="stat-v" id="s-pnl">$+0.0000</div><div class="stat-s" id="s-wl">W:0 / L:0</div></div>
      <div class="stat-cell"><div class="stat-l">Win Rate</div><div class="stat-v b" id="s-wr">0%</div><div class="stat-s" id="s-trades">0 işlem</div></div>
      <div class="stat-cell"><div class="stat-l">RL Episode</div><div class="stat-v" id="s-ep">#—</div><div class="stat-s">Q-Learning</div></div>
      <div class="stat-cell"><div class="stat-l">Epsilon</div><div class="stat-v" id="s-eps">—</div><div class="stat-s">keşif oranı</div></div>
      <div class="stat-cell"><div class="stat-l">Max Drawdown</div><div class="stat-v r" id="s-dd">0.00%</div><div class="stat-s">peak'ten</div></div>
      <div class="stat-cell"><div class="stat-l">Açık PnL</div><div class="stat-v" id="s-opnl">$0</div><div class="stat-s">unrealized</div></div>
      <div class="stat-cell"><div class="stat-l">Semboller</div><div class="stat-v b" id="s-syms">0</div><div class="stat-s">izleniyor</div></div>
      <div class="stat-cell"><div class="stat-l">Risk/Ödül</div><div class="stat-v y" id="s-rr">—</div><div class="stat-s">avg win/loss</div></div>
    </div>

    <!-- PnL Chart -->
    <div class="ph" style="flex-shrink:0;background:var(--s0);border-top:1px solid var(--b0)">
      <div class="ph-title"><span class="ph-icon">◉</span>PNL GRAFİĞİ</div>
      <div style="display:flex;gap:.3rem">
        <button onclick="setPnlMode('cumulative')" id="pm-cum" class="btn btn-settings" style="font-size:.48rem;padding:.1rem .35rem">KÜMÜLATİF</button>
        <button onclick="setPnlMode('change')" id="pm-chg" class="btn" style="font-size:.48rem;padding:.1rem .35rem;background:transparent;border-color:var(--b0);color:var(--t2)">DEĞİŞİM</button>
      </div>
    </div>
    <div class="chart-wrap" style="flex:1;min-height:0">
      <canvas id="pnl-chart"></canvas>
    </div>

    <!-- Ajanlar -->
    <div class="ph" style="flex-shrink:0;background:var(--s0);border-top:1px solid var(--b0)">
      <div class="ph-title"><span class="ph-icon">◈</span>AJANLAR</div>
      <span class="badge bg" id="agents-status">AKTİF</span>
    </div>
    <div class="agent-cards" id="agent-cards">
      <div class="agent-card"><div class="agent-dot" style="background:var(--t2)"></div><div><div class="agent-name">StrategyAgent</div><div class="agent-desc">RSI/MACD/BB</div></div></div>
      <div class="agent-card"><div class="agent-dot" style="background:var(--t2)"></div><div><div class="agent-name">RLMetaAgent</div><div class="agent-desc">Q-Learning</div></div></div>
      <div class="agent-card"><div class="agent-dot" style="background:var(--t2)"></div><div><div class="agent-name">ExecutionAgent</div><div class="agent-desc">Paper Trade</div></div></div>
      <div class="agent-card"><div class="agent-dot" style="background:var(--t2)"></div><div><div class="agent-name">MarketAgent</div><div class="agent-desc">Binance Futures</div></div></div>
    </div>

    <!-- ═══ CANLI KONTROL PANELİ ═══ -->
    <div class="ctrl-panel">
      <div class="ctrl-header">
        <div class="ctrl-title">⚙ RİSK & BOT AYARLARI <span class="ctrl-live-badge">CANLI DEĞİŞTİR</span></div>
        <button class="ctrl-save-btn" onclick="saveCtrl()">💾 KAYDET</button>
      </div>
      <div class="ctrl-body">
        <div class="ctrl-item">
          <div class="ctrl-lbl">Max Pozisyon</div>
          <div class="ctrl-val" id="cv-maxpos">5</div>
          <input type="range" class="ctrl-slider" id="cs-maxpos" min="1" max="20" value="5" oninput="updateCtrl('maxpos',this.value)">
          <div class="ctrl-hint">Aynı anda açılabilecek max pozisyon</div>
        </div>
        <div class="ctrl-item">
          <div class="ctrl-lbl">Risk % (sermaye başına)</div>
          <div class="ctrl-val" id="cv-risk">2%</div>
          <input type="range" class="ctrl-slider" id="cs-risk" min="1" max="20" value="2" step="1" oninput="updateCtrl('risk',this.value)">
          <div class="ctrl-hint">Her trade için bakiyenin yüzdesi</div>
        </div>
        <div class="ctrl-item">
          <div class="ctrl-lbl">Take Profit %</div>
          <div class="ctrl-val" id="cv-tp">5%</div>
          <input type="range" class="ctrl-slider" id="cs-tp" min="1" max="20" value="5" step="1" oninput="updateCtrl('tp',this.value)">
          <div class="ctrl-hint">Kâr hedefi</div>
        </div>
        <div class="ctrl-item">
          <div class="ctrl-lbl">Stop Loss %</div>
          <div class="ctrl-val" id="cv-sl">3%</div>
          <input type="range" class="ctrl-slider" id="cs-sl" min="1" max="15" value="3" step="1" oninput="updateCtrl('sl',this.value)">
          <div class="ctrl-hint">Zarar kes</div>
        </div>
        <div class="ctrl-item">
          <div class="ctrl-lbl">Min Güven %</div>
          <div class="ctrl-val" id="cv-conf">60%</div>
          <input type="range" class="ctrl-slider" id="cs-conf" min="30" max="95" value="60" step="5" oninput="updateCtrl('conf',this.value)">
          <div class="ctrl-hint">AI güven eşiği — yüksek = az trade</div>
        </div>
        <div class="ctrl-item">
          <div class="ctrl-lbl">Tarama Büyüklüğü</div>
          <div class="ctrl-val" id="cv-batch">50</div>
          <input type="range" class="ctrl-slider" id="cs-batch" min="10" max="200" value="50" step="10" oninput="updateCtrl('batch',this.value)">
          <div class="ctrl-hint">Her turda kaç coin taransın</div>
        </div>
        <div class="ctrl-item" style="grid-column:1/3">
          <div class="ctrl-lbl">Kaldıraç</div>
          <div class="ctrl-lev-btns" id="ctrl-lev-btns">
            <button class="clev-btn active" onclick="selectLevCtrl(1)">RAST.</button>
            <button class="clev-btn" onclick="selectLevCtrl(2)">2x</button>
            <button class="clev-btn" onclick="selectLevCtrl(3)">3x</button>
            <button class="clev-btn" onclick="selectLevCtrl(5)">5x</button>
            <button class="clev-btn" onclick="selectLevCtrl(10)">10x</button>
            <button class="clev-btn" onclick="selectLevCtrl(20)">20x</button>
          </div>
          <div class="ctrl-hint">0 = rastgele (1x/2x/3x/5x/10x)</div>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- TRADE MODAL -->
<div class="modal-bg" id="trade-modal">
  <div class="modal-box">
    <div class="modal-head">
      <h2>⚡ MANUEL İŞLEM — <span id="tm-sym">—</span></h2>
      <button class="modal-close" onclick="closeTM()">✕</button>
    </div>
    <div class="modal-body">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div><div style="font-size:.5rem;color:var(--t2)">Anlık Fiyat</div><div style="font-family:var(--head);font-size:1.3rem;font-weight:800" id="tm-price">$—</div></div>
        <div style="text-align:right"><div style="font-size:.5rem;color:var(--t2)">24s</div><div style="font-family:var(--head);font-size:1rem;font-weight:700" id="tm-chg">—</div></div>
      </div>
      <div style="display:flex;gap:.8rem;font-size:.58rem">
        <span>RSI: <span id="tm-rsi" style="color:var(--y)">—</span></span>
        <span>Vol: <span id="tm-vol" style="color:var(--b)">—</span></span>
      </div>
      <div class="side-btns">
        <div class="side-btn sb-long active" id="sb-long" onclick="tmSide('long')">▲ LONG</div>
        <div class="side-btn sb-short" id="sb-short" onclick="tmSide('short')">▼ SHORT</div>
      </div>
      <div class="field-group"><label>Kaldıraç</label>
        <div class="lev-btns">
          <button class="lev-btn active" onclick="tmLev(1)">1x</button>
          <button class="lev-btn" onclick="tmLev(2)">2x</button>
          <button class="lev-btn" onclick="tmLev(3)">3x</button>
          <button class="lev-btn" onclick="tmLev(5)">5x</button>
          <button class="lev-btn" onclick="tmLev(10)">10x</button>
          <button class="lev-btn" onclick="tmLev(20)">20x</button>
        </div>
      </div>
      <div class="trade-preview" id="tm-preview">
        <div class="tp-row"><span class="lbl">Pozisyon</span><span id="tp-size">—</span></div>
        <div class="tp-row"><span class="lbl">Stop Loss</span><span id="tp-sl" class="r">—</span></div>
        <div class="tp-row"><span class="lbl">TP 1</span><span id="tp-tp1" class="g">—</span></div>
        <div class="tp-row"><span class="lbl">TP 2</span><span id="tp-tp2" class="g">—</span></div>
        <div class="tp-row"><span class="lbl">TP 3</span><span id="tp-tp3" class="g">—</span></div>
      </div>
    </div>
    <div class="modal-foot">
      <button class="modal-cancel" onclick="closeTM()">İptal</button>
      <button id="tm-exec" class="modal-exec me-long" onclick="execTrade()">⚡ LONG AÇ</button>
    </div>
  </div>
</div>

<script>
// ═══════════════════════════════════════════════════════════════
//  STATE
// ═══════════════════════════════════════════════════════════════
let mktData={}, sparkData={}, pnlMode='cumulative';
let tmState={sym:'',side:'long',lev:1};
let ctrlLev=1;
let pnlChart=null, dailyChart=null;

// ── Utils ──────────────────────────────────────────────────────
const fP = v => {
  if(!v) return '$0';
  const a=Math.abs(v);
  if(a>=1000)  return '$'+v.toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2});
  if(a>=1)     return '$'+v.toFixed(4);
  if(a>=0.001) return '$'+v.toFixed(6);
  return '$'+v.toFixed(8);
};
const fV = v => {
  if(!v) return '$0';
  if(v>=1e9) return '$'+(v/1e9).toFixed(2)+'B';
  if(v>=1e6) return '$'+(v/1e6).toFixed(1)+'M';
  if(v>=1e3) return '$'+(v/1e3).toFixed(0)+'K';
  return '$'+v.toFixed(0);
};
const fT = s => {
  if(!s) return '—';
  const d=new Date(s.endsWith('Z')?s:s+'Z');
  return d.toLocaleTimeString('tr',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
};
const fDur = sec => {
  if(!sec) return '0s';
  if(sec<60) return Math.floor(sec)+'s';
  if(sec<3600) return Math.floor(sec/60)+'d';
  return Math.floor(sec/3600)+'s '+Math.floor((sec%3600)/60)+'d';
};
const shortSym = s => s.replace(/USDT$|BUSD$|PERP$/,'');
const set = (id,val,cls) => {
  const el=document.getElementById(id);
  if(!el) return;
  el.textContent=val;
  if(cls) el.className=el.className.replace(/\b(g|r|b|y)\b/g,'')+' '+cls;
};
const col = v => v>0?'var(--g)':v<0?'var(--r)':'var(--t1)';

// ── Clock & Countdown ─────────────────────────────────────────
let _cnt=30;
setInterval(()=>{
  document.getElementById('clock').textContent=new Date().toLocaleTimeString('tr');
  _cnt--;if(_cnt<=0)_cnt=30;
  const el=document.getElementById('countdown');
  if(el){el.textContent=_cnt+'s';el.style.color=_cnt<=5?'var(--r)':_cnt<=10?'var(--y)':'var(--b)';}
},1000);

// ═══════════════════════════════════════════════════════════════
//  TAB SYSTEM
// ═══════════════════════════════════════════════════════════════
function switchTab(t){
  document.querySelectorAll('#tab-mkt,#tab-pos,#tab-ana,#tab-hist').forEach(el=>el.classList.remove('active'));
  document.getElementById('tab-'+t).classList.add('active');
  const labels=['mkt','pos','ana','hist'];
  document.querySelectorAll('.col:first-child .tab-btn').forEach((btn,i)=>{
    btn.classList.toggle('active',labels[i]===t);
  });
  if(t==='ana') fetchAnalytics();
  if(t==='hist') fetchHistory();
}
function switchTab2(t){
  document.querySelectorAll('#tab2-sigs,#tab2-log').forEach(el=>el.classList.remove('active'));
  document.getElementById('tab2-'+t).classList.add('active');
  document.querySelectorAll('.col:nth-child(2) .tab-btn').forEach((btn,i)=>{
    btn.classList.toggle('active',i===(t==='sigs'?0:1));
  });
}

// ═══════════════════════════════════════════════════════════════
//  FETCH FUNCTIONS
// ═══════════════════════════════════════════════════════════════

// ── STATUS ────────────────────────────────────────────────────
async function fetchStatus(){
  try{
    const d=await fetch('/status').then(r=>r.json());
    const eq=d.equity||1000, pnl=d.total_pnl||0, ret=d.return_pct||0;
    set('k-cap','$'+(d.initial_capital||1000).toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2}));
    set('k-eq','$'+eq.toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2}),eq>=1000?'g':'r');
    set('k-pnl',(pnl>=0?'+':'')+'$'+pnl.toFixed(4),pnl>=0?'g':'r');
    set('k-ret',(ret>=0?'+':'')+ret.toFixed(2)+'%',ret>=0?'g':'r');
    set('k-wr',(d.win_rate||0)+'%','b');
    set('k-wl',(d.win_count||0)+'/'+(d.loss_count||0));
    set('k-tr',d.trade_count||0);
    set('k-op',d.open_positions||0,'y');
    const up=d.uptime_seconds||0;
    const h=Math.floor(up/3600),m=Math.floor((up%3600)/60),s=Math.floor(up%60);
    set('k-up',`${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`);

    set('s-init','$'+(d.initial_capital||1000).toLocaleString('en',{minimumFractionDigits:2}));
    set('s-eq','$'+eq.toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2}),eq>=1000?'g':'r');
    set('s-ret',(ret>=0?'+':'')+ret.toFixed(2)+'%');
    document.getElementById('s-ret').style.color=ret>=0?'var(--g)':'var(--r)';
    set('s-pnl',(pnl>=0?'+$':'$')+pnl.toFixed(4),pnl>=0?'g':'r');
    set('s-wl','W:'+(d.win_count||0)+' / L:'+(d.loss_count||0));
    set('s-wr',(d.win_rate||0)+'%','b');
    set('s-trades',(d.trade_count||0)+' işlem');
    set('s-syms',d.market_symbols||0,'b');

    const rl=d.rl_metrics||{};
    set('s-ep','#'+(rl.episode||'—'));
    set('s-eps',rl.epsilon?rl.epsilon.toFixed(3):'—');
    set('s-dd',(d.max_drawdown_pct||0).toFixed(2)+'%','r');
    set('s-rr',(d.risk_reward||0).toFixed(2),'y');

    const openPnl=d.open_pnl||0;
    set('s-opnl',(openPnl>=0?'+':'')+'$'+openPnl.toFixed(4),openPnl>=0?'g':'r');

    // Status badge
    const badge=document.getElementById('bot-status-badge');
    if(d.bot_paused){badge.textContent='DURAKLADI';badge.className='badge by';}
    else if(d.bot_running){badge.textContent='ÇALIŞIYOR';badge.className='badge bg';}
    else{badge.textContent='DURDURULDU';badge.className='badge br';}

    // Agent heartbeats
    const hbs=d.agent_heartbeats||{};
    const cards=document.getElementById('agent-cards').querySelectorAll('.agent-card');
    const agentOrder=['StrategyAgent','RLMetaAgent','ExecutionAgent','MarketAgent'];
    cards.forEach((card,i)=>{
      const name=agentOrder[i];
      const dot=card.querySelector('.agent-dot');
      const hb=hbs[name];
      if(hb){
        const age=(Date.now()-new Date(hb+'Z').getTime())/1000;
        dot.style.background=age<60?'var(--g)':age<180?'var(--y)':'var(--r)';
        const hbEl=card.querySelector('.agent-hb');
        if(hbEl) hbEl.textContent=age<60?Math.round(age)+'s':'!';
      }
    });

    // PnL chart
    if(d.pnl_history&&d.pnl_history.length>1) updatePnlChart(d.pnl_history);

    // Sync control sliders with settings
    const st=d.settings||{};
    syncSlider('maxpos',st.max_positions||5,1,20);
    syncSlider('risk',Math.round((st.risk_pct||0.02)*100),1,20);
    syncSlider('tp',Math.round((st.take_profit_pct||0.05)*100),1,20);
    syncSlider('sl',Math.round((st.stop_loss_pct||0.03)*100),1,15);
    syncSlider('conf',Math.round((st.min_confidence||0.60)*100),30,95);
    syncSlider('batch',st.scan_batch||50,10,200);

  }catch(e){console.warn('status',e)}
}

function syncSlider(key,val){
  const s=document.getElementById('cs-'+key);
  const v=document.getElementById('cv-'+key);
  if(s&&s.value!=val) s.value=val;
  if(v) updateCtrlDisplay(key,val);
}

// ── MARKET ────────────────────────────────────────────────────
let sparkBuf={};
async function fetchMarket(){
  try{
    const d=await fetch('/market').then(r=>r.json());
    mktData=d.symbols||{};
    Object.entries(mktData).forEach(([sym,dd])=>{
      if(!sparkBuf[sym]) sparkBuf[sym]=[];
      sparkBuf[sym].push(dd.price||0);
      if(sparkBuf[sym].length>20) sparkBuf[sym].shift();
    });
    renderMkt();
    updateTape();
    updateMovers();
    updateSentiment();
  }catch(e){console.warn('market',e)}
}

function sparkSVG(sym){
  const h=sparkBuf[sym]||[];
  if(h.length<2) return '<span style="color:var(--t2)">—</span>';
  const W=56,H=16;
  const mn=Math.min(...h),mx=Math.max(...h),rng=mx-mn||1;
  const pts=h.map((v,i)=>{
    const x=Math.round(i/(h.length-1)*(W-2))+1;
    const y=Math.round((1-(v-mn)/rng)*(H-2))+1;
    return x+','+y;
  }).join(' ');
  const up=h[h.length-1]>=h[0];
  return`<svg width="${W}" height="${H}" style="vertical-align:middle"><polyline points="${pts}" fill="none" stroke="${up?'#00c382':'#ff3b5c'}" stroke-width="1.2" stroke-linejoin="round"/></svg>`;
}

function renderMkt(){
  const q=(document.getElementById('mkt-search')||{}).value||'';
  const sort=(document.getElementById('mkt-sort')||{}).value||'vol';
  let entries=Object.entries(mktData);
  if(q) entries=entries.filter(([s])=>s.toLowerCase().includes(q.toLowerCase()));
  entries.sort((a,b)=>{
    if(sort==='vol') return (b[1].volume_24h||0)-(a[1].volume_24h||0);
    if(sort==='chg') return Math.abs(b[1].change_24h||0)-Math.abs(a[1].change_24h||0);
    if(sort==='rsi') return (b[1].rsi||50)-(a[1].rsi||50);
    return a[0].localeCompare(b[0]);
  });
  document.getElementById('mkt-cnt').textContent=entries.length+' sembol';
  updateMovers(entries);

  const rows=entries.slice(0,100).map(([sym,d])=>{
    const chg=d.change_24h||0,rsi=d.rsi||50,price=d.price||0;
    const rsiCls=rsi>70?'rsi-ob':rsi<30?'rsi-os':'rsi-n';
    const chgCol=chg>=0?'var(--g)':'var(--r)';
    const sig=d.signal||'';
    const sigDir=sig.toLowerCase().includes('al')||sig.toLowerCase().includes('buy')?'buy':sig.toLowerCase().includes('sat')||sig.toLowerCase().includes('sell')?'sell':'';
    return`<tr>
      <td><div class="sym-cell"><div class="sym-name">${shortSym(sym)}</div><div class="sym-sub">${sym}</div></div></td>
      <td>${fP(price)}</td>
      <td style="color:${chgCol}">${chg>=0?'+':''}${chg.toFixed(2)}%</td>
      <td><span class="${rsiCls}">${rsi.toFixed(1)}</span></td>
      <td style="color:${(d.macd||0)>=(d.macd_signal||0)?'var(--g)':'var(--r)'}">${(d.macd||0).toFixed(5)}</td>
      <td>${fV(d.volume_24h||0)}</td>
      <td>${sparkSVG(sym)}</td>
      <td>${sig?`<div class="sig-cell">${sigDir?`<span class="sig-dir ${sigDir==='buy'?'sd-buy':'sd-sell'}">${sigDir==='buy'?'AL':'SAT'}</span>`:''}${sig.replace(/↑\s*(Al|Buy)|↓\s*(Sat|Sell)/i,'').trim().substring(0,12)}</div>`:'<span style="color:var(--t2)">—</span>'}</td>
      <td class="trade-btns"><button class="tb tb-l" onclick="openTM('${sym}','long')">▲L</button><button class="tb tb-s" onclick="openTM('${sym}','short')">▼S</button></td>
    </tr>`;
  }).join('');
  document.getElementById('mkt-body').innerHTML=rows||'<tr><td colspan="9" class="empty" style="height:60px">Sonuç yok</td></tr>';
}

function updateTape(){
  const items=Object.entries(mktData).slice(0,80);
  if(!items.length) return;
  const html=items.map(([s,d])=>{
    const chg=d.change_24h||0;
    return`<span class="ti"><span class="ti-s">${shortSym(s)}</span><span class="ti-p">${fP(d.price||0)}</span><span class="${chg>=0?'up':'dn'}">${chg>=0?'+':''}${chg.toFixed(2)}%</span></span>`;
  }).join('');
  const t=document.getElementById('tape');
  if(t) t.innerHTML=html+html; // duplicate for seamless loop
}

function updateMovers(entries){
  if(!entries) entries=Object.entries(mktData);
  if(!entries.length) return;
  const sorted=[...entries].sort((a,b)=>(b[1].change_24h||0)-(a[1].change_24h||0));
  const top5=sorted.slice(0,5), bot5=sorted.slice(-5).reverse();
  const all=[...top5,...bot5];
  document.getElementById('movers-inner').innerHTML=all.map(([s,d])=>{
    const chg=d.change_24h||0;
    const col=chg>=0?'var(--g)':'var(--r)';
    const bg=chg>=0?'rgba(0,195,130,0.06)':'rgba(255,59,92,0.06)';
    return`<div class="mover-item" style="background:${bg}" onclick="openTM('${s}','long')">
      <span style="color:#fff;font-weight:600">${shortSym(s)}</span>
      <span style="color:${col}">${chg>=0?'+':''}${chg.toFixed(2)}%</span>
    </div>`;
  }).join('');
}

function updateSentiment(){
  const vals=Object.values(mktData);
  if(!vals.length) return;
  let os=0,ob=0,n=0;
  vals.forEach(d=>{const r=d.rsi||50;if(r<30)os++;else if(r>70)ob++;else n++;});
  const tot=vals.length;
  document.getElementById('sent-os').style.width=(os/tot*100)+'%';
  document.getElementById('sent-n').style.width=(n/tot*100)+'%';
  document.getElementById('sent-ob').style.width=(ob/tot*100)+'%';
  document.getElementById('sent-os-lbl').textContent='🟢 '+os;
  document.getElementById('sent-n-lbl').textContent='Nötr '+n;
  document.getElementById('sent-ob-lbl').textContent=ob+' 🔴';
  const score=Math.round((os-ob)/tot*100);
  const scoreEl=document.getElementById('sent-score');
  if(score>15){scoreEl.textContent='BULLISH +'+score;scoreEl.style.color='var(--g)';}
  else if(score<-15){scoreEl.textContent='BEARISH '+score;scoreEl.style.color='var(--r)';}
  else{scoreEl.textContent='NÖTR '+score;scoreEl.style.color='var(--t1)';}
}

// ── SIGNALS ───────────────────────────────────────────────────
async function fetchSignals(){
  try{
    const d=await fetch('/signals').then(r=>r.json());
    const sigs=d.signals||[];
    set('sig-cnt',sigs.length);
    const body=document.getElementById('sigs-body');
    if(!sigs.length){body.innerHTML='<div class="empty"><div class="empty-icon">🔍</div><div>Sinyal yok</div></div>';return;}
    body.innerHTML=sigs.slice(0,30).map(s=>{
      const pct=Math.round(s.confidence*100);
      const isBuy=s.direction==='buy';
      const ind=s.indicators||{};
      const rsi=ind.rsi||50;
      const rsiCol=rsi<35?'var(--g)':rsi>65?'var(--r)':'var(--y)';
      const chg=ind.change_24h||0;
      const barCol=isBuy?'#00c382':'#ff3b5c';
      return`<div class="sig-card ${isBuy?'buy-c':'sell-c'}">
        <div class="sc-top">
          <span class="sc-sym">${shortSym(s.symbol)}</span>
          <div style="display:flex;align-items:center;gap:.3rem">
            <span style="font-size:.5rem;color:${rsiCol}">RSI ${rsi.toFixed(0)}</span>
            <span style="font-size:.5rem;color:${chg>=0?'var(--g)':'var(--r)'}">${chg>=0?'+':''}${chg.toFixed(1)}%</span>
            <span class="sc-dir ${isBuy?'sd-buy':'sd-sell'}">${isBuy?'AL':'SAT'}</span>
          </div>
        </div>
        <div style="height:3px;border-radius:2px;background:var(--t2);margin:.1rem 0">
          <div style="height:100%;width:${pct}%;background:${barCol};border-radius:2px;transition:width .3s"></div>
        </div>
        <div class="sc-meta">
          <span class="sc-reason">${s.reason||'—'}</span>
          <button class="sc-trade-btn" onclick="openTM('${s.symbol}','${isBuy?'long':'short'}')">⚡ İşlem</button>
        </div>
        <div class="sc-time">${fT(s.timestamp)} · ${pct}% güven</div>
      </div>`;
    }).join('');
  }catch(e){console.warn('signals',e)}
}

// ── POSITIONS ─────────────────────────────────────────────────
async function fetchPositions(){
  try{
    const d=await fetch('/positions').then(r=>r.json());
    const open=d.open||[];
    const cnt=open.length;
    set('pos-cnt',cnt);
    set('k-op',cnt,'y');

    // Pos summary
    const sumEl=document.getElementById('pos-summary');
    if(cnt>0){
      const totPnl=open.reduce((s,p)=>s+(p.pnl||0),0);
      const longs=open.filter(p=>p.side==='long').length;
      const shorts=open.filter(p=>p.side==='short').length;
      const best=open.reduce((a,b)=>(a.pnl||0)>(b.pnl||0)?a:b);
      const worst=open.reduce((a,b)=>(a.pnl||0)<(b.pnl||0)?a:b);
      sumEl.style.display='flex';
      sumEl.innerHTML=`
        <div class="psb"><div class="psb-l">Toplam PnL</div><div class="psb-v" style="color:${totPnl>=0?'var(--g)':'var(--r)'}">${totPnl>=0?'+':''}$${totPnl.toFixed(3)}</div></div>
        <div class="psb"><div class="psb-l">L/S</div><div class="psb-v" style="color:var(--b)">L${longs}/S${shorts}</div></div>
        <div class="psb"><div class="psb-l">En İyi</div><div class="psb-v g">${shortSym(best.symbol)} $${(best.pnl||0).toFixed(3)}</div></div>
        <div class="psb"><div class="psb-l">En Kötü</div><div class="psb-v r">${shortSym(worst.symbol)} $${(worst.pnl||0).toFixed(3)}</div></div>`;
      const openPnl=totPnl;
      set('s-opnl',(openPnl>=0?'+':'')+'$'+openPnl.toFixed(4),openPnl>=0?'g':'r');
    } else { sumEl.style.display='none'; }

    const body=document.getElementById('pos-body');
    if(!cnt){body.innerHTML='<div class="empty"><div class="empty-icon">📭</div><div>Açık pozisyon yok</div><div style="font-size:.5rem">Bot sinyal bekliyor...</div></div>';return;}
    body.innerHTML=open.map(p=>{
      const isL=p.side==='long';
      const pnl=p.pnl||0,pnlPct=p.pnl_pct||0;
      const pnlCol=pnl>=0?'var(--g)':'var(--r)';
      const pnlBg=pnl>=0?'rgba(0,195,130,0.1)':'rgba(255,59,92,0.1)';
      const lev=p.leverage||1;
      const prog=Math.min(100,p.progress_pct||0);
      const dur=fDur(p.duration_sec||0);
      const tps=p.take_profit_levels||[p.take_profit];
      const idx=p.tp_hit_count||0;
      const sym=shortSym(p.symbol);
      const curVsEntry=(p.current_price||0)>=(p.entry_price||0);
      return`<div class="pos-card" style="border-left:3px solid ${pnl>=0?'rgba(0,195,130,0.4)':'rgba(255,59,92,0.4)'}">
        <div class="pc-row1">
          <div style="display:flex;align-items:center;gap:.25rem;flex-shrink:0">
            <span class="pc-sym">${sym}</span>
            <span class="pc-side ${isL?'ps-l':'ps-s'}">${isL?'LONG':'SHORT'}</span>
            ${lev>1?`<span class="pc-lev">${lev}x</span>`:''}
            <span class="pc-dur">⏱ ${dur}</span>
          </div>
          <div style="display:flex;align-items:center;gap:.3rem;flex-shrink:0">
            <span class="pc-pnl" style="color:${pnlCol};background:${pnlBg}">${pnl>=0?'+':''}$${pnl.toFixed(4)} <span style="font-size:.65rem;opacity:.8">${pnlPct>=0?'+':''}${pnlPct.toFixed(2)}%</span></span>
            <button class="pc-close" onclick="closePos('${p.symbol}')">✕</button>
          </div>
        </div>
        <div class="pc-row2">
          <span><span class="pc-lbl">Giriş</span> ${fP(p.entry_price)}</span>
          <span><span class="pc-lbl">Anlık</span> <span style="color:${curVsEntry?'var(--g)':'var(--r)'}">${fP(p.current_price)}</span></span>
          <span><span class="pc-lbl">Değer</span> $${(p.value_usd||0).toFixed(2)}</span>
        </div>
        <div class="pc-bar-wrap">
          <span style="color:var(--r);flex-shrink:0;font-size:.52rem">🛑 ${fP(p.stop_loss)}</span>
          <div class="pc-bar-track"><div class="pc-bar-fill" style="width:${prog}%"></div></div>
          <span style="color:var(--t2);font-size:.5rem;flex-shrink:0">${prog.toFixed(0)}%</span>
          <span style="color:var(--g);flex-shrink:0;font-size:.52rem">🎯 ${fP(p.take_profit)}${tps.length>1?' '+(idx+1)+'/'+tps.length:''}</span>
        </div>
        ${tps.length>1?`<div class="pc-tp-list">${tps.map((t,i)=>`<span class="pc-tp" style="color:${i<idx?'var(--g)':i===idx?'#fff':'var(--t2)'};border-color:${i<idx?'rgba(0,195,130,0.35)':i===idx?'rgba(255,255,255,0.3)':'var(--t2)'};background:${i<idx?'rgba(0,195,130,0.08)':i===idx?'rgba(255,255,255,0.04)':'transparent'}">${i<idx?'✓':i===idx?'▶':'○'} TP${i+1} ${fP(t)}</span>`).join('')}</div>`:''}
        ${p.ai_summary?`<div class="pc-ai" title="${p.ai_summary}">⬡ ${p.ai_summary}</div>`:''}
      </div>`;
    }).join('');
  }catch(e){console.warn('positions',e)}
}

// ── HISTORY ───────────────────────────────────────────────────
async function fetchHistory(){
  try{
    const d=await fetch('/positions/closed').then(r=>r.json());
    const closed=d.closed||[];
    const wins=closed.filter(x=>x.pnl>0);
    const losses=closed.filter(x=>x.pnl<=0);
    const winPnl=wins.reduce((s,x)=>s+x.pnl,0);
    const lossPnl=losses.reduce((s,x)=>s+x.pnl,0);
    const avgDur=closed.length?closed.reduce((s,x)=>s+(x.duration_sec||0),0)/closed.length:0;
    set('h-win-pnl','+$'+winPnl.toFixed(3));
    set('h-loss-pnl','$'+lossPnl.toFixed(3));
    set('h-avg-dur',fDur(avgDur));
    set('h-total',closed.length);
    const body=document.getElementById('hist-body');
    if(!closed.length){body.innerHTML='<div class="empty"><div class="empty-icon">📋</div><div>Henüz işlem yok</div></div>';return;}
    body.innerHTML=closed.slice(0,60).map(c=>{
      const win=c.pnl>0;
      const sideCls=c.side==='long'?'ps-l':'ps-s';
      const rCls=c.close_reason&&c.close_reason.startsWith('TP')?'bg':c.close_reason==='SL'?'br':c.close_reason==='MANUAL'?'bb':'by';
      return`<div class="hist-row ${win?'win':'loss'}">
        <span class="hist-side ${sideCls}">${c.side==='long'?'L':'S'}</span>
        <span class="hist-sym">${shortSym(c.symbol)}</span>
        <span class="hist-reason badge ${rCls}">${c.close_reason||'?'}</span>
        <span class="hist-pnl" style="color:${win?'var(--g)':'var(--r)'}">${c.pnl>=0?'+':''}$${c.pnl.toFixed(4)}</span>
        <span class="hist-pct" style="color:${win?'var(--g)':'var(--r)'}">${c.pnl_pct>=0?'+':''}${c.pnl_pct.toFixed(1)}%</span>
        <span class="hist-dur">${fDur(c.duration_sec||0)}</span>
        <span class="hist-time">${fT(c.closed_at)}</span>
      </div>`;
    }).join('');
  }catch(e){console.warn('history',e)}
}

// ── ANALYTICS ─────────────────────────────────────────────────
async function fetchAnalytics(){
  try{
    const d=await fetch('/analytics').then(r=>r.json());
    set('an-win-pnl','+$'+(d.total_win_pnl||0).toFixed(4),'g');
    set('an-loss-pnl','$'+(d.total_loss_pnl||0).toFixed(4),'r');
    set('an-avg-win','$'+(d.avg_win||0).toFixed(4),'g');
    set('an-avg-loss','$'+(d.avg_loss||0).toFixed(4),'r');
    set('an-win-cnt',(d.win_count||0)+' kazanç');
    set('an-loss-cnt',(d.loss_count||0)+' kayıp');
    set('an-rr',(d.risk_reward||0).toFixed(2),'b');
    set('an-dd',(d.max_drawdown_pct||0).toFixed(2)+'%','r');
    set('an-wstr',d.win_streak||0,'g');
    set('an-lstr',d.loss_streak||0,'r');
    const cs=d.current_streak||0;
    document.getElementById('an-curr-str').textContent=cs>0?`+${cs} kazanç serisi`:cs<0?`${cs} kayıp serisi`:'Seri yok';
    document.getElementById('an-curr-str').style.color=cs>0?'var(--g)':cs<0?'var(--r)':'var(--t2)';

    // Reason breakdown
    const br=d.by_reason||{};
    const total=Object.values(br).reduce((s,x)=>s+x.count,0)||1;
    const reasonEl=document.getElementById('reason-list');
    const sorted=Object.entries(br).sort((a,b)=>b[1].count-a[1].count);
    reasonEl.innerHTML=sorted.map(([r,v])=>{
      const pct=Math.round(v.count/total*100);
      const col=r.startsWith('TP')?'var(--g)':r==='SL'?'var(--r)':'var(--b)';
      return`<div class="reason-row">
        <span style="min-width:42px;color:${col};font-weight:600">${r}</span>
        <div class="reason-bar-bg"><div class="reason-bar" style="width:${pct}%;background:${col}"></div></div>
        <span style="min-width:32px;text-align:right;color:${col}">${pct}%</span>
        <span style="color:var(--t2);min-width:40px;text-align:right">${v.count} işlem</span>
        <span style="color:${v.pnl>=0?'var(--g)':'var(--r)'};min-width:60px;text-align:right">${v.pnl>=0?'+':''}$${v.pnl.toFixed(3)}</span>
      </div>`;
    }).join('');

    // Daily PnL chart
    const daily=d.daily_pnl||{};
    const days=Object.keys(daily).sort().slice(-14);
    const vals=days.map(k=>daily[k]);
    if(days.length>0) updateDailyChart(days.map(d=>d.slice(5)),vals);

  }catch(e){console.warn('analytics',e)}
}

// ── LOG ───────────────────────────────────────────────────────
async function fetchLog(){
  try{
    const d=await fetch('/log').then(r=>r.json());
    const logs=d.log||[];
    const body=document.getElementById('log-body');
    if(!logs.length){body.innerHTML='<div class="empty"><div>Log boş</div></div>';return;}
    body.innerHTML=logs.slice(0,80).map(l=>{
      const ts=fT(l.ts);
      return`<div class="log-entry">
        <span class="log-ts">${ts}</span>
        <span class="log-lv-${l.level}">${l.level}</span>
        <span class="log-msg">${l.msg}</span>
      </div>`;
    }).join('');
  }catch(e){console.warn('log',e)}
}

// ═══════════════════════════════════════════════════════════════
//  CHARTS
// ═══════════════════════════════════════════════════════════════
function chartDefaults(){
  return{
    responsive:true,maintainAspectRatio:false,
    plugins:{legend:{display:false},tooltip:{backgroundColor:'#0b1018',borderColor:'rgba(0,195,130,0.3)',borderWidth:1,titleColor:'#cde0f0',bodyColor:'#6a8fa8',padding:8}},
    scales:{x:{grid:{color:'rgba(0,195,130,0.05)'},ticks:{color:'#2e4055',font:{size:9}}},y:{grid:{color:'rgba(0,195,130,0.05)'},ticks:{color:'#2e4055',font:{size:9}}}}
  };
}

function updatePnlChart(history){
  const canvas=document.getElementById('pnl-chart');
  if(!canvas) return;
  const data=pnlMode==='cumulative'?history:history.map((v,i)=>i===0?0:v-history[i-1]);
  const labels=history.map((_,i)=>i);
  const maxV=Math.max(...data.map(Math.abs))||1;
  const col=data[data.length-1]>=0?'rgba(0,195,130,0.8)':'rgba(255,59,92,0.8)';
  const fillCol=data[data.length-1]>=0?'rgba(0,195,130,0.08)':'rgba(255,59,92,0.08)';
  if(pnlChart){
    pnlChart.data.labels=labels;
    pnlChart.data.datasets[0].data=data;
    pnlChart.data.datasets[0].borderColor=col;
    pnlChart.data.datasets[0].backgroundColor=fillCol;
    pnlChart.update('none');
  } else {
    pnlChart=new Chart(canvas,{type:'line',data:{labels,datasets:[{data,borderColor:col,backgroundColor:fillCol,borderWidth:1.5,fill:true,tension:0.3,pointRadius:0,pointHoverRadius:3}]},options:{...chartDefaults(),animation:{duration:0}}});
  }
}

function setPnlMode(m){
  pnlMode=m;
  document.getElementById('pm-cum').style.opacity=m==='cumulative'?'1':'0.4';
  document.getElementById('pm-chg').style.opacity=m==='change'?'1':'0.4';
  fetchStatus();
}

function updateDailyChart(labels,vals){
  const canvas=document.getElementById('daily-chart');
  if(!canvas) return;
  const cols=vals.map(v=>v>=0?'rgba(0,195,130,0.7)':'rgba(255,59,92,0.7)');
  if(dailyChart){
    dailyChart.data.labels=labels;dailyChart.data.datasets[0].data=vals;dailyChart.data.datasets[0].backgroundColor=cols;dailyChart.update('none');
  } else {
    dailyChart=new Chart(canvas,{type:'bar',data:{labels,datasets:[{data:vals,backgroundColor:cols,borderRadius:2}]},options:{...chartDefaults(),animation:{duration:300}}});
  }
}

// ═══════════════════════════════════════════════════════════════
//  BOT CONTROLS
// ═══════════════════════════════════════════════════════════════
async function botCtrl(action){
  await fetch('/bot/'+action,{method:'POST'});
  await fetchStatus();
}

async function closePos(sym){
  const r=await fetch('/positions/close/'+sym,{method:'POST'}).then(r=>r.json());
  if(r.error) alert('Hata: '+r.error);
  else await Promise.all([fetchPositions(),fetchHistory(),fetchStatus()]);
}

// ═══════════════════════════════════════════════════════════════
//  CONTROL PANEL
// ═══════════════════════════════════════════════════════════════
function updateCtrl(key,val){
  document.getElementById('cs-'+key).value=val;
  updateCtrlDisplay(key,val);
}

function updateCtrlDisplay(key,val){
  const displays={'maxpos':v=>v,'risk':v=>v+'%','tp':v=>v+'%','sl':v=>v+'%','conf':v=>v+'%','batch':v=>v};
  const el=document.getElementById('cv-'+key);
  if(el) el.textContent=(displays[key]||String)(val);
}

function selectLevCtrl(l){
  ctrlLev=l;
  document.querySelectorAll('.clev-btn').forEach((b,i)=>{
    const levs=[0,2,3,5,10,20];
    b.classList.toggle('active',l===levs[i]||(l===1&&i===0));
  });
}

async function saveCtrl(){
  const payload={
    max_positions:parseInt(document.getElementById('cs-maxpos').value),
    risk_pct:parseFloat(document.getElementById('cs-risk').value)/100,
    take_profit_pct:parseFloat(document.getElementById('cs-tp').value)/100,
    stop_loss_pct:parseFloat(document.getElementById('cs-sl').value)/100,
    min_confidence:parseFloat(document.getElementById('cs-conf').value)/100,
    scan_batch:parseInt(document.getElementById('cs-batch').value),
    leverage:ctrlLev,
  };
  const r=await fetch('/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}).then(r=>r.json());
  if(r.ok){
    const btn=document.querySelector('.ctrl-save-btn');
    const orig=btn.textContent;
    btn.textContent='✓ KAYDEDİLDİ';btn.style.color='var(--g)';
    setTimeout(()=>{btn.textContent=orig;btn.style.color='';},2000);
  }
}

// ═══════════════════════════════════════════════════════════════
//  TRADE MODAL
// ═══════════════════════════════════════════════════════════════
function openTM(sym,side){
  const fullSym=sym.endsWith('USDT')||sym.endsWith('BUSD')?sym:sym+'USDT';
  tmState={sym:fullSym,side,lev:1};
  const d=mktData[fullSym]||{};
  document.getElementById('tm-sym').textContent=shortSym(fullSym);
  document.getElementById('tm-price').textContent=fP(d.price||0);
  const chg=d.change_24h||0;
  const chgEl=document.getElementById('tm-chg');
  chgEl.textContent=(chg>=0?'+':'')+chg.toFixed(2)+'%';
  chgEl.style.color=chg>=0?'var(--g)':'var(--r)';
  const rsi=d.rsi||50;
  document.getElementById('tm-rsi').textContent=rsi.toFixed(1);
  document.getElementById('tm-rsi').style.color=rsi<35?'var(--g)':rsi>65?'var(--r)':'var(--y)';
  document.getElementById('tm-vol').textContent=fV(d.volume_24h||0);
  tmSide(side);
  document.querySelectorAll('.lev-btn').forEach(b=>b.classList.toggle('active',parseInt(b.textContent)===1));
  document.getElementById('trade-modal').classList.add('open');
  updateTMPreview();
}

function closeTM(){ document.getElementById('trade-modal').classList.remove('open'); }

function tmSide(side){
  tmState.side=side;
  document.getElementById('sb-long').classList.toggle('active',side==='long');
  document.getElementById('sb-short').classList.toggle('active',side==='short');
  const btn=document.getElementById('tm-exec');
  if(side==='long'){btn.textContent='⚡ LONG AÇ';btn.className='modal-exec me-long';}
  else{btn.textContent='⚡ SHORT AÇ';btn.className='modal-exec me-short';}
  updateTMPreview();
}

function tmLev(l){
  tmState.lev=l;
  document.querySelectorAll('.lev-btn').forEach(b=>b.classList.toggle('active',parseInt(b.textContent)===l));
  updateTMPreview();
}

function updateTMPreview(){
  const d=mktData[tmState.sym]||{};
  const price=d.price||0;
  if(!price) return;
  const slPct=0.03,tpPct=0.05;
  const posSize=(1000*0.02)*tmState.lev;
  let sl,tp1,tp2,tp3;
  if(tmState.side==='long'){sl=price*(1-slPct);tp1=price*(1+tpPct);tp2=price*(1+tpPct*2);tp3=price*(1+tpPct*3);}
  else{sl=price*(1+slPct);tp1=price*(1-tpPct);tp2=price*(1-tpPct*2);tp3=price*(1-tpPct*3);}
  document.getElementById('tp-size').textContent='$'+posSize.toFixed(2);
  document.getElementById('tp-sl').textContent=fP(sl)+' (-'+( slPct*100).toFixed(0)+'%)';
  document.getElementById('tp-tp1').textContent=fP(tp1)+' (+'+( tpPct*100).toFixed(0)+'%)';
  document.getElementById('tp-tp2').textContent=fP(tp2)+' (+'+(tpPct*200).toFixed(0)+'%)';
  document.getElementById('tp-tp3').textContent=fP(tp3)+' (+'+(tpPct*300).toFixed(0)+'%)';
}

async function execTrade(){
  const btn=document.getElementById('tm-exec');
  btn.disabled=true;btn.textContent='⏳ Gönderiliyor...';
  try{
    const r=await fetch('/trade/manual',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({symbol:tmState.sym,side:tmState.side,leverage:tmState.lev})}).then(r=>r.json());
    if(r.error) alert('Hata: '+r.error);
    else if(r.action==='opened'){closeTM();await Promise.all([fetchPositions(),fetchStatus(),fetchLog()]);}
    else if(r.action==='closed'){alert('Kapatıldı. PnL: $'+(r.pnl>=0?'+':'')+r.pnl.toFixed(4));closeTM();await Promise.all([fetchPositions(),fetchHistory(),fetchStatus()]);}
  }catch(e){alert('Bağlantı hatası: '+e);}
  finally{btn.disabled=false;tmSide(tmState.side);}
}

document.getElementById('trade-modal').addEventListener('click',e=>{if(e.target===e.currentTarget)closeTM();});

// ═══════════════════════════════════════════════════════════════
//  MAIN REFRESH LOOP
// ═══════════════════════════════════════════════════════════════
async function refresh(){
  await Promise.all([fetchStatus(),fetchMarket(),fetchSignals(),fetchPositions()]);
  // Analytics ve history sadece o tab açıksa güncelle
  if(document.getElementById('tab-hist').classList.contains('active')) fetchHistory();
  if(document.getElementById('tab-ana').classList.contains('active')) fetchAnalytics();
  fetchLog();
}

refresh();
setInterval(refresh,5000);
</script>
</body>
</html>"""


def create_app():
    from fastapi import FastAPI, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse
    from datetime import datetime

    app = FastAPI(title="Aurora AI Pro Terminal", version="4.0.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.get("/", response_class=HTMLResponse)
    def root(): return DASHBOARD_HTML

    @app.get("/health")
    def health(): return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

    @app.get("/status")
    def status():
        s = shared_state.get_summary()
        return {"status": "running", **s}

    @app.get("/market")
    def market(): return {"symbols": shared_state.market_data}

    @app.get("/signals")
    def signals():
        sigs = shared_state.signals[-50:]
        return {"count": len(sigs), "signals": [
            {"symbol": s.symbol, "direction": s.direction,
             "confidence": s.confidence, "strategy": s.strategy,
             "reason": s.reason, "timestamp": s.timestamp.isoformat(),
             "indicators": s.indicators}
            for s in reversed(sigs)
        ]}

    @app.get("/positions")
    def positions(): return {"open": shared_state.get_positions_detail()}

    @app.get("/positions/closed")
    def closed_positions(): return {"closed": shared_state.get_closed_positions()}

    @app.get("/analytics")
    def analytics():
        s = shared_state.get_summary()
        closed = shared_state.get_closed_positions()
        by_reason = {}
        for cp in closed:
            r = cp["close_reason"]
            by_reason.setdefault(r, {"count": 0, "pnl": 0.0})
            by_reason[r]["count"] += 1
            by_reason[r]["pnl"] = round(by_reason[r]["pnl"] + cp["pnl"], 4)
        return {**{k: s[k] for k in ["total_pnl","open_pnl","win_count","loss_count","win_rate",
            "avg_win","avg_loss","risk_reward","max_drawdown_pct","win_streak","loss_streak",
            "current_streak","total_win_pnl","total_loss_pnl","pnl_history","daily_pnl"]},
            "by_reason": by_reason}

    @app.get("/log")
    def syslog():
        with shared_state._lock:
            return {"log": list(reversed(shared_state.system_log[-100:]))}

    @app.get("/settings")
    def get_settings(): return shared_state.settings.to_dict()

    @app.post("/settings")
    async def update_settings(req: Request):
        data = await req.json()
        shared_state.settings.update(data)
        shared_state._add_log("INFO", f"⚙ Ayarlar güncellendi: {list(data.keys())}")
        return {"ok": True, "settings": shared_state.settings.to_dict()}

    @app.post("/bot/start")
    def bot_start(): shared_state.start_bot(); return {"status": "started"}

    @app.post("/bot/stop")
    def bot_stop(): shared_state.stop_bot(); return {"status": "stopped"}

    @app.post("/bot/pause")
    def bot_pause(): shared_state.pause_bot(); return {"status": "paused" if shared_state.bot_paused else "resumed"}

    @app.post("/positions/close/{symbol}")
    async def close_pos(symbol: str):
        market = shared_state.market_data.get(symbol, {})
        price = market.get("price", 0)
        if price <= 0: return {"error": "Fiyat verisi yok"}
        pnl = await shared_state.close_position(symbol, price, "MANUAL")
        return {"ok": True, "pnl": pnl}

    @app.post("/trade/manual")
    async def manual_trade(req: Request):
        from utils.state import Position
        data = await req.json()
        symbol = data.get("symbol", "").upper()
        side   = data.get("side", "long")
        leverage = int(data.get("leverage", 1))
        if not symbol: return {"error": "Sembol gerekli"}
        market = shared_state.market_data.get(symbol, {})
        price  = market.get("price", 0)
        if price <= 0: return {"error": f"{symbol} için fiyat yok"}
        if symbol in shared_state.positions:
            pnl = await shared_state.close_position(symbol, price, "MANUAL")
            return {"ok": True, "action": "closed", "pnl": pnl}
        if len(shared_state.positions) >= shared_state.settings.max_positions:
            return {"error": "Max pozisyon sayısına ulaşıldı"}
        sl_pct = shared_state.settings.stop_loss_pct
        tp_pct = shared_state.settings.take_profit_pct
        pos_val = shared_state.capital * shared_state.settings.risk_pct
        qty = round(pos_val / price, 8)
        if side == "long":
            sl = round(price * (1 - sl_pct), 8)
            tps = [round(price*(1+tp_pct*i),8) for i in range(1,4)]
        else:
            sl = round(price * (1 + sl_pct), 8)
            tps = [round(price*(1-tp_pct*i),8) for i in range(1,4)]
        pos = Position(
            symbol=symbol, side=side, qty=qty,
            entry_price=price, current_price=price,
            stop_loss=sl, take_profit=tps[0], take_profit_levels=tps,
            tp_hit_count=0, value_usd=round(pos_val, 4),
            reason=f"Manuel {side.upper()} {leverage}x",
            ai_summary=f"Manuel işlem @ ${price:.6f} | {leverage}x",
            indicators_at_open={**market, "leverage": leverage},
        )
        await shared_state.open_position(pos)
        shared_state._add_log("TRADE", f"🖐 Manuel {side.upper()} {symbol} @ ${price:.6f} | {leverage}x")
        return {"ok": True, "action": "opened", "symbol": symbol, "side": side, "price": price}

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
    PORT = int(os.getenv("PORT", "8000"))
    logger.info(f"🚀 Aurora AI v4.0 başlatılıyor | PORT={PORT}")
    agent_thread = threading.Thread(target=run_agents, name="AgentThread", daemon=True)
    agent_thread.start()
    logger.info("✅ Agent thread başlatıldı")
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info",
                proxy_headers=True, forwarded_allow_ips="*", access_log=True)
    shutdown_event.set()
    agent_thread.join(timeout=10)
    logger.info("✅ Kapatma tamamlandı.")
