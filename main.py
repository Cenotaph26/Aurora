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

# ─────────────────────────────────────────────────────────────────────────────
#  DASHBOARD HTML (Pro Trading Terminal)
# ─────────────────────────────────────────────────────────────────────────────

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Aurora AI — Pro Terminal</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&family=Barlow+Condensed:wght@400;600;700;800&family=Barlow:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#05080f;--s0:#080d17;--s1:#0c1220;--s2:#101828;--s3:#162030;
  --b0:rgba(0,195,130,0.08);--b1:rgba(0,195,130,0.18);--b2:rgba(0,195,130,0.30);
  --g:#00c382;--g2:#00ff9f;--r:#ff3b5c;--b:#0096ff;--y:#f5a623;--p:#a855f7;
  --t0:#d4e5f5;--t1:#7a96b0;--t2:#3a5060;--t3:#1a2535;
  --mono:'JetBrains Mono',monospace;--head:'Barlow Condensed',sans-serif;--body:'Barlow',sans-serif;
  --rad:6px;--rad2:10px;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{font-size:13px}
body{font-family:var(--mono);background:var(--bg);color:var(--t0);min-height:100vh;overflow-x:hidden}
body::after{content:'';position:fixed;inset:0;pointer-events:none;z-index:0;
  background-image:linear-gradient(rgba(0,195,130,0.02) 1px,transparent 1px),linear-gradient(90deg,rgba(0,195,130,0.02) 1px,transparent 1px);
  background-size:44px 44px}
::-webkit-scrollbar{width:4px;height:4px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--t3);border-radius:2px}
a{color:var(--g);text-decoration:none}

/* ── TICKER TAPE ── */
.tape{position:relative;z-index:100;background:var(--s0);border-bottom:1px solid var(--b0);height:26px;overflow:hidden;display:flex;align-items:center}
.tape-inner{display:flex;white-space:nowrap;animation:tape 900s linear infinite}
.tape-inner:hover{animation-play-state:paused}
@keyframes tape{from{transform:translateX(0)}to{transform:translateX(-50%)}}
.ti{display:inline-flex;align-items:center;gap:.35rem;padding:0 1rem;font-size:.65rem;border-right:1px solid var(--t3)}
.ti-s{color:#fff;font-weight:500}.ti-p{color:var(--t1)}.ti-c.up{color:var(--g)}.ti-c.dn{color:var(--r)}

/* ── TOPBAR ── */
.topbar{position:relative;z-index:99;background:var(--s0);border-bottom:1px solid var(--b0);
  display:flex;align-items:stretch;height:50px;gap:0}
.brand{display:flex;align-items:center;gap:.6rem;padding:0 1.2rem;border-right:1px solid var(--b0);flex-shrink:0}
.brand-icon{width:26px;height:26px;background:linear-gradient(135deg,var(--g),var(--b));border-radius:5px;
  display:grid;place-items:center;font-size:.7rem;color:#000;font-weight:700;font-family:var(--head)}
.brand-name{font-family:var(--head);font-weight:800;font-size:1.15rem;letter-spacing:.05em;color:#fff}
.brand-sub{font-size:.55rem;color:var(--t2);letter-spacing:.1em}

/* Topbar KPIs */
.top-kpis{display:flex;align-items:stretch;flex:1;overflow-x:auto}
.tkpi{display:flex;flex-direction:column;justify-content:center;padding:0 1rem;border-right:1px solid var(--b0);min-width:80px;cursor:default}
.tkpi:hover{background:rgba(0,195,130,0.04)}
.tkpi-l{font-size:.5rem;letter-spacing:.1em;text-transform:uppercase;color:var(--t2);margin-bottom:2px}
.tkpi-v{font-family:var(--head);font-size:1rem;font-weight:700;line-height:1;color:#fff;font-variant-numeric:tabular-nums}
.tkpi-v.g{color:var(--g)}.tkpi-v.r{color:var(--r)}.tkpi-v.b{color:var(--b)}.tkpi-v.y{color:var(--y)}

/* Bot controls */
.bot-ctrl{display:flex;align-items:center;gap:.4rem;padding:0 .8rem;border-left:1px solid var(--b0);flex-shrink:0}
.btn{display:inline-flex;align-items:center;gap:.3rem;padding:.3rem .65rem;border-radius:4px;
  border:1px solid;cursor:pointer;font-size:.6rem;font-family:var(--mono);letter-spacing:.05em;font-weight:500;
  transition:all .15s}
.btn-start{background:rgba(0,195,130,0.1);border-color:rgba(0,195,130,0.3);color:var(--g)}
.btn-start:hover{background:rgba(0,195,130,0.2);border-color:var(--g)}
.btn-pause{background:rgba(245,166,35,0.1);border-color:rgba(245,166,35,0.3);color:var(--y)}
.btn-pause:hover{background:rgba(245,166,35,0.2)}
.btn-stop{background:rgba(255,59,92,0.1);border-color:rgba(255,59,92,0.3);color:var(--r)}
.btn-stop:hover{background:rgba(255,59,92,0.2)}
.btn-settings{background:rgba(0,150,255,0.1);border-color:rgba(0,150,255,0.3);color:var(--b)}
.btn-settings:hover{background:rgba(0,150,255,0.2)}
#bot-status-badge{font-size:.55rem;padding:.2rem .5rem;border-radius:3px;letter-spacing:.08em}

/* Clock */
.top-right{display:flex;align-items:center;gap:.7rem;padding:0 .8rem;border-left:1px solid var(--b0);flex-shrink:0}
#clock{font-size:.65rem;color:var(--t1);min-width:70px;text-align:right}

/* ── MAIN LAYOUT ── */
.workspace{position:relative;z-index:1;display:grid;
  grid-template-columns:1fr 1fr 1fr 300px;
  grid-template-rows:180px 200px 280px 200px;
  gap:1px;background:var(--t3);
  height:calc(100vh - 100px);overflow:hidden}

/* ── PANELS ── */
.panel{background:var(--s1);display:flex;flex-direction:column;overflow:hidden}
.ph{display:flex;align-items:center;justify-content:space-between;
  padding:.4rem .8rem;border-bottom:1px solid var(--b0);flex-shrink:0;min-height:30px}
.ph-title{font-family:var(--head);font-size:.65rem;letter-spacing:.12em;text-transform:uppercase;
  color:var(--t2);display:flex;align-items:center;gap:.35rem}
.ph-icon{color:var(--g);font-size:.75rem}
.pb{flex:1;overflow:auto;padding:.5rem .8rem}
.pb-np{flex:1;overflow:auto;padding:0}
.badge{font-size:.52rem;letter-spacing:.08em;padding:.12rem .4rem;border-radius:3px;font-weight:600}
.bg{background:rgba(0,195,130,0.1);color:var(--g);border:1px solid rgba(0,195,130,0.25)}
.bb{background:rgba(0,150,255,0.1);color:var(--b);border:1px solid rgba(0,150,255,0.25)}
.br{background:rgba(255,59,92,0.1);color:var(--r);border:1px solid rgba(255,59,92,0.25)}
.by{background:rgba(245,166,35,0.1);color:var(--y);border:1px solid rgba(245,166,35,0.25)}
.bp{background:rgba(168,85,247,0.1);color:var(--p);border:1px solid rgba(168,85,247,0.25)}

/* Grid positions */
.s-chart{grid-column:1/4;grid-row:1}
.s-stats{grid-column:4;grid-row:1/3}
.s-market{grid-column:1/3;grid-row:2}
.s-signals{grid-column:3;grid-row:2/5}
.s-positions{grid-column:1/3;grid-row:3/5}
.s-history{grid-column:1;grid-row:4}
.s-agents{grid-column:2;grid-row:4}

/* ── PNL CHART ── */
.chart-wrap{flex:1;padding:.3rem .8rem .5rem;overflow:hidden}
canvas#pc{width:100%!important;height:100%!important}

/* ── STATS PANEL ── */
.stats-grid{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--t3);flex:1}
.sc{background:var(--s1);padding:.65rem .8rem;display:flex;flex-direction:column;justify-content:center}
.sc-l{font-size:.52rem;letter-spacing:.1em;text-transform:uppercase;color:var(--t2);margin-bottom:.2rem}
.sc-v{font-family:var(--head);font-size:1.25rem;font-weight:700;line-height:1;color:#fff;font-variant-numeric:tabular-nums}
.sc-v.g{color:var(--g)}.sc-v.r{color:var(--r)}.sc-v.b{color:var(--b)}.sc-v.y{color:var(--y)}
.sc-s{font-size:.58rem;color:var(--t2);margin-top:.2rem}

/* ── TABLE ── */
.dt{width:100%;border-collapse:collapse;font-size:.66rem}
.dt th{position:sticky;top:0;background:var(--s1);font-size:.55rem;letter-spacing:.1em;
  text-transform:uppercase;color:var(--t2);padding:.3rem .65rem;border-bottom:1px solid var(--b0);
  text-align:right;font-weight:400;cursor:pointer;white-space:nowrap}
.dt th:first-child{text-align:left}
.dt th:hover{color:var(--g)}
.dt td{padding:.35rem .65rem;border-bottom:1px solid rgba(0,195,130,0.03);text-align:right;
  font-variant-numeric:tabular-nums;white-space:nowrap}
.dt td:first-child{text-align:left}
.dt tr:hover td{background:rgba(0,195,130,0.03)}
.dt tr.fl-g td{animation:fg .5s}.dt tr.fl-r td{animation:fr .5s}
@keyframes fg{50%{background:rgba(0,195,130,0.08)}}
@keyframes fr{50%{background:rgba(255,59,92,0.08)}}
.sym{color:#e0eef8;font-weight:500;letter-spacing:.02em}
.sym-s{color:var(--t2);font-size:.58rem;display:block}
.pos-g{color:var(--g)}.pos-r{color:var(--r)}.neu{color:var(--t1)}
.rsi{display:inline-block;padding:.08rem .35rem;border-radius:3px;font-size:.6rem}
.rsi-ob{background:rgba(255,59,92,0.12);color:var(--r);border:1px solid rgba(255,59,92,0.25)}
.rsi-os{background:rgba(0,195,130,0.1);color:var(--g);border:1px solid rgba(0,195,130,0.25)}
.rsi-n{background:rgba(58,80,96,0.3);color:var(--t2)}
.bar{display:inline-flex;align-items:center;gap:.3rem;width:70px}
.bt{flex:1;height:3px;background:var(--t3);border-radius:2px;overflow:hidden}
.bf{height:100%;border-radius:2px;transition:width .4s}
.bf-g{background:linear-gradient(90deg,var(--b),var(--g))}
.bf-r{background:linear-gradient(90deg,var(--r),#ff8800)}

/* ── SIGNAL CARDS ── */
.sfc{display:flex;flex-direction:column;gap:.35rem;padding:.45rem .6rem;overflow-y:auto;flex:1}
.sc2{background:var(--s2);border:1px solid var(--b0);border-radius:var(--rad);padding:.5rem .65rem;cursor:default;transition:border-color .2s}
.sc2:hover{border-color:var(--b1)}
.sc2.buy-c{border-left:2px solid var(--g)}.sc2.sell-c{border-left:2px solid var(--r)}.sc2.hold-c{border-left:2px solid var(--y)}
.si-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:.3rem}
.si-sym{font-family:var(--head);font-size:.82rem;font-weight:700;color:#fff}
.si-dir{font-size:.55rem;font-weight:700;letter-spacing:.1em;padding:.12rem .45rem;border-radius:3px}
.db{background:rgba(0,195,130,0.1);color:var(--g)}.ds{background:rgba(255,59,92,0.1);color:var(--r)}.dh{background:rgba(245,166,35,0.1);color:var(--y)}
.si-conf{display:flex;align-items:center;gap:.4rem;margin-bottom:.2rem}
.si-bar{flex:1;height:2px;background:var(--t3);border-radius:1px;overflow:hidden}
.si-fill{height:100%;border-radius:1px}
.fb{background:linear-gradient(90deg,var(--b),var(--g))}.fs{background:linear-gradient(90deg,var(--r),#f60)}.fh{background:var(--y)}
.si-pct{font-size:.58rem;color:var(--t2);min-width:26px;text-align:right}
.si-reason{font-size:.57rem;color:var(--t2);line-height:1.35;margin-top:.15rem}
.si-time{font-size:.55rem;color:var(--t3);margin-top:.2rem}

/* ── POSITION CARDS ── */
.pos-row{padding:.4rem .8rem;border-bottom:1px solid rgba(0,195,130,0.04);display:flex;flex-direction:column;gap:.3rem}
.pos-row:last-child{border-bottom:none}
.pos-header{display:flex;align-items:center;justify-content:space-between}
.pos-sym{font-family:var(--head);font-size:.85rem;font-weight:700;color:#fff}
.pos-side{font-size:.52rem;font-weight:700;padding:.1rem .35rem;border-radius:3px}
.ps-l{background:rgba(0,195,130,0.1);color:var(--g)}.ps-s{background:rgba(255,59,92,0.1);color:var(--r)}
.pos-pnl{font-family:var(--head);font-size:.9rem;font-weight:700;font-variant-numeric:tabular-nums}
.pos-meta{display:flex;gap:1rem;font-size:.6rem;color:var(--t2)}
.pos-meta span{display:flex;gap:.25rem;align-items:center}
.pos-meta .lbl{color:var(--t3)}
.sltp-bar{display:flex;align-items:center;gap:.5rem;font-size:.6rem}
.sltp-sl{color:var(--r);min-width:55px}.sltp-tp{color:var(--g);text-align:right;min-width:55px}
.sltp-track{flex:1;height:6px;background:var(--t3);border-radius:3px;position:relative;overflow:visible}
.sltp-fill{height:100%;border-radius:3px;transition:width .5s ease;background:linear-gradient(90deg,var(--b),var(--g))}
.sltp-pct{font-size:.55rem;color:var(--t2);min-width:30px;text-align:right}
.pos-ai{font-size:.58rem;color:var(--t2);line-height:1.45;padding:.3rem .5rem;
  background:rgba(0,150,255,0.05);border-left:2px solid rgba(0,150,255,0.25);border-radius:0 3px 3px 0;margin-top:.15rem}
.pos-ai-label{font-size:.52rem;color:var(--b);text-transform:uppercase;letter-spacing:.08em;margin-bottom:.15rem}
.pos-close-btn{font-size:.55rem;padding:.15rem .4rem;background:rgba(255,59,92,0.1);border:1px solid rgba(255,59,92,0.25);
  color:var(--r);border-radius:3px;cursor:pointer;font-family:var(--mono)}
.pos-close-btn:hover{background:rgba(255,59,92,0.2)}

/* ── TRADE HISTORY ── */
.tr-row{display:flex;align-items:center;gap:.4rem;padding:.3rem .8rem;border-bottom:1px solid rgba(0,195,130,0.03);font-size:.63rem}
.tr-row:last-child{border-bottom:none}
.tr-side{font-size:.55rem;font-weight:700;padding:.1rem .3rem;border-radius:3px;flex-shrink:0}
.tr-sym{color:#e0eef8;font-weight:500;min-width:42px}
.tr-reason{color:var(--t2);font-size:.57rem;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tr-pnl{min-width:55px;text-align:right;font-weight:600;font-variant-numeric:tabular-nums}
.tr-time{color:var(--t2);font-size:.57rem;flex-shrink:0;min-width:40px;text-align:right}

/* ── AGENT ROWS ── */
.ag-row{display:flex;align-items:center;gap:.5rem;padding:.38rem .8rem;border-bottom:1px solid rgba(0,195,130,0.03);font-size:.64rem}
.ag-row:last-child{border-bottom:none}
.ag-dot{width:5px;height:5px;border-radius:50%;flex-shrink:0}
.ag-dot.on{background:var(--g);box-shadow:0 0 5px var(--g);animation:bl 2s infinite}
.ag-dot.off{background:var(--r)}
@keyframes bl{0%,100%{opacity:1}50%{opacity:.3}}
.ag-name{color:#e0eef8;font-weight:500;min-width:105px}
.ag-role{flex:1;color:var(--t2);font-size:.58rem}
.ag-t{color:var(--t2);font-size:.58rem;flex-shrink:0}
/* RL weights */
.rl-item{padding:.35rem .8rem;border-bottom:1px solid rgba(0,195,130,0.03)}
.rl-item:last-child{border-bottom:none}
.rl-nm{display:flex;justify-content:space-between;font-size:.62rem;margin-bottom:.2rem}
.rl-sc{color:var(--g)}
.rl-tr{height:3px;background:var(--t3);border-radius:2px;overflow:hidden}
.rl-fi{height:100%;border-radius:2px;transition:width .8s ease}

/* ── SYSTEM LOG ── */
.log-row{display:flex;gap:.5rem;padding:.28rem .8rem;border-bottom:1px solid rgba(0,195,130,0.02);font-size:.6rem;line-height:1.4}
.log-row:last-child{border-bottom:none}
.log-ts{color:var(--t2);flex-shrink:0;min-width:55px}
.log-lv{flex-shrink:0;min-width:40px;font-size:.55rem;font-weight:700}
.log-lv.INFO{color:var(--b)}.log-lv.WARN{color:var(--y)}.log-lv.TRADE{color:var(--g)}.log-lv.ERROR{color:var(--r)}
.log-msg{color:var(--t1);flex:1}

/* ── SETTINGS MODAL ── */
.modal-bg{position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:1000;display:none;place-items:center}
.modal-bg.open{display:grid}
.modal{background:var(--s1);border:1px solid var(--b1);border-radius:var(--rad2);width:480px;max-width:95vw;max-height:85vh;overflow:auto}
.modal-head{display:flex;justify-content:space-between;align-items:center;padding:.8rem 1rem;border-bottom:1px solid var(--b0)}
.modal-head h2{font-family:var(--head);font-size:1rem;font-weight:700;letter-spacing:.08em;color:#fff}
.modal-close{background:none;border:none;color:var(--t2);cursor:pointer;font-size:1rem;padding:.2rem .4rem}
.modal-close:hover{color:#fff}
.modal-body{padding:1rem}
.field-group{margin-bottom:.8rem}
.field-group label{display:block;font-size:.6rem;letter-spacing:.1em;text-transform:uppercase;color:var(--t2);margin-bottom:.3rem}
.field-group input{width:100%;background:var(--s2);border:1px solid var(--b0);border-radius:var(--rad);
  padding:.4rem .6rem;color:var(--t0);font-family:var(--mono);font-size:.75rem;outline:none;transition:border-color .15s}
.field-group input:focus{border-color:var(--b1)}
.field-grid{display:grid;grid-template-columns:1fr 1fr;gap:.6rem}
.modal-foot{padding:.7rem 1rem;border-top:1px solid var(--b0);display:flex;justify-content:flex-end;gap:.5rem}
.btn-save{background:rgba(0,195,130,0.15);border:1px solid rgba(0,195,130,0.35);color:var(--g);
  padding:.4rem .9rem;border-radius:4px;cursor:pointer;font-family:var(--mono);font-size:.7rem;font-weight:500}
.btn-save:hover{background:rgba(0,195,130,0.25)}
.btn-cancel{background:var(--s2);border:1px solid var(--b0);color:var(--t2);
  padding:.4rem .9rem;border-radius:4px;cursor:pointer;font-family:var(--mono);font-size:.7rem}

/* ── MANUAL TRADE MODAL ── */
.modal-trade{background:var(--s1);border:1px solid rgba(0,150,255,0.3);border-radius:var(--rad2);width:380px;max-width:95vw}
.lev-btns{display:flex;gap:.3rem;flex-wrap:wrap;margin-top:.3rem}
.lev-btn{padding:.25rem .6rem;border-radius:3px;border:1px solid var(--b0);background:var(--s2);color:var(--t2);cursor:pointer;font-family:var(--mono);font-size:.65rem;transition:all .15s}
.lev-btn.active{background:rgba(0,150,255,0.2);border-color:var(--b);color:var(--b)}
.trade-side-btns{display:flex;gap:.4rem;margin:.5rem 0}
.ts-btn{flex:1;padding:.5rem;border-radius:5px;border:1px solid;cursor:pointer;font-family:var(--head);font-size:.85rem;font-weight:700;letter-spacing:.05em;transition:all .15s;text-align:center}
.ts-long{background:rgba(0,195,130,0.1);border-color:rgba(0,195,130,0.35);color:var(--g)}
.ts-long:hover,.ts-long.active{background:rgba(0,195,130,0.25);border-color:var(--g)}
.ts-short{background:rgba(255,59,92,0.1);border-color:rgba(255,59,92,0.35);color:var(--r)}
.ts-short:hover,.ts-short.active{background:rgba(255,59,92,0.25);border-color:var(--r)}
.trade-preview{background:var(--s2);border-radius:5px;padding:.5rem .7rem;font-size:.62rem;color:var(--t1);margin:.4rem 0;border:1px solid var(--b0)}
.tp{display:flex;justify-content:space-between;margin:.15rem 0}
.tp .lbl{color:var(--t2)}
/* ── SENTIMENT BAR ── */
.sent-bar{display:flex;align-items:center;gap:.5rem;padding:.35rem .8rem;border-bottom:1px solid var(--b0);flex-shrink:0;font-size:.6rem}
.sent-seg{height:6px;border-radius:2px;transition:width .6s ease;min-width:2px}
.sent-labels{display:flex;justify-content:space-between;font-size:.52rem;color:var(--t2);margin-top:.15rem}
.sent-info{display:flex;gap:.7rem;font-size:.6rem;flex-shrink:0}
.sent-dot{width:7px;height:7px;border-radius:50%;display:inline-block;margin-right:.25rem}
/* ── POS SUMMARY ── */
.pos-summary-bar{display:flex;gap:.5rem;padding:.3rem .8rem;border-bottom:1px solid var(--b0);flex-shrink:0;font-size:.6rem;flex-wrap:wrap;align-items:center}
.psb-item{display:flex;flex-direction:column;padding:.2rem .5rem;background:var(--s2);border-radius:4px;border:1px solid var(--b0);min-width:60px}
.psb-lbl{font-size:.5rem;color:var(--t2);text-transform:uppercase;letter-spacing:.08em;margin-bottom:.1rem}
.psb-val{font-family:var(--head);font-size:.85rem;font-weight:700}
/* ── SHIMMER ── */
.shim{background:linear-gradient(90deg,var(--t3) 25%,rgba(0,195,130,0.05) 50%,var(--t3) 75%);background-size:200% 100%;animation:shim 1.5s infinite;border-radius:3px}
@keyframes shim{from{background-position:-200% 0}to{background-position:200% 0}}
.empty{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:.4rem;color:var(--t2);font-size:.65rem}
</style>
</head>
<body>

<!-- TAPE -->
<div class="tape"><div class="tape-inner" id="tape">
  <span class="ti"><span class="ti-s">BTC</span><span class="ti-p">$--</span><span class="ti-c">--</span></span>
  <span class="ti"><span class="ti-s">ETH</span><span class="ti-p">$--</span><span class="ti-c">--</span></span>
  <span class="ti"><span class="ti-s">SOL</span><span class="ti-p">$--</span><span class="ti-c">--</span></span>
</div></div>

<!-- TOPBAR -->
<div class="topbar">
  <div class="brand">
    <div class="brand-icon">A</div>
    <div><div class="brand-name">AURORA AI</div><div class="brand-sub">CRYPTO HEDGE FUND · v3.0</div></div>
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
    <div class="tkpi"><div class="tkpi-l">Sinyaller</div><div class="tkpi-v" id="k-sigs">0</div></div>
    <div class="tkpi"><div class="tkpi-l">Çalışma</div><div class="tkpi-v" id="k-up">00:00:00</div></div>
  </div>
  </div>
  <div class="bot-ctrl">
    <span class="badge" id="bot-status-badge" style="margin-right:.3rem">⬤ LOADING</span>
    <button class="btn btn-start" onclick="botAction('start')">▶ BAŞLAT</button>
    <button class="btn btn-pause" onclick="botAction('pause')">⏸ DURAKLAT</button>
    <button class="btn btn-stop" onclick="botAction('stop')">⏹ DURDUR</button>
    <button class="btn btn-settings" onclick="openSettings()">⚙ AYARLAR</button>
  </div>
  <div class="top-right">
    <div id="clock">--:--:--</div>
  </div>
</div>

<!-- TOP MOVERS STRIP -->
<div style="position:relative;z-index:98;background:var(--s0);border-bottom:1px solid var(--b0);height:24px;display:flex;align-items:center;overflow:hidden;flex-shrink:0">
  <div style="display:flex;align-items:center;padding:0 .8rem;border-right:1px solid var(--b0);flex-shrink:0;gap:.3rem">
    <span style="font-size:.52rem;letter-spacing:.1em;text-transform:uppercase;color:var(--t2)">🔥 ÖNCÜLER</span>
  </div>
  <div id="movers-strip" style="display:flex;gap:0;overflow:hidden;flex:1">
    <span style="font-size:.6rem;color:var(--t2);padding:0 .8rem">Veriler yükleniyor...</span>
  </div>
  <div style="display:flex;align-items:center;padding:0 .7rem;border-left:1px solid var(--b0);flex-shrink:0;gap:.5rem">
    <span style="font-size:.52rem;color:var(--t2)">Sonraki güncelleme:</span>
    <span id="update-countdown" style="font-size:.6rem;color:var(--b);font-variant-numeric:tabular-nums;min-width:25px">30s</span>
  </div>
</div>

<!-- WORKSPACE -->
<div class="workspace">

  <!-- PNL CHART -->
  <div class="panel s-chart">
    <div class="ph">
      <div class="ph-title"><span class="ph-icon">◆</span>PNL GRAFİĞİ</div>
      <div style="display:flex;gap:.4rem;align-items:center">
        <span class="badge bb" id="chart-lbl">KÜMÜLATİF</span>
        <button onclick="toggleChart()" style="background:var(--s2);border:1px solid var(--b0);color:var(--t2);font-size:.55rem;padding:.18rem .45rem;border-radius:3px;cursor:pointer;font-family:var(--mono)">DEĞİŞTİR</button>
      </div>
    </div>
    <div class="chart-wrap"><canvas id="pc"></canvas></div>
  </div>

  <!-- STATS -->
  <div class="panel s-stats" style="padding:0">
    <div class="ph"><div class="ph-title"><span class="ph-icon">◈</span>PERFORMANS</div></div>
    <div class="stats-grid">
      <div class="sc"><div class="sc-l">Başlangıç</div><div class="sc-v b">$1,000</div><div class="sc-s">Paper Trading</div></div>
      <div class="sc"><div class="sc-l">Equity</div><div class="sc-v" id="s-eq">$1,000</div><div class="sc-s" id="s-ret">+0.00%</div></div>
      <div class="sc"><div class="sc-l">PnL</div><div class="sc-v g" id="s-pnl">$+0.0000</div><div class="sc-s" id="s-wl">W:0 / L:0</div></div>
      <div class="sc"><div class="sc-l">Win Rate</div><div class="sc-v b" id="s-wr">0%</div><div class="sc-s" id="s-trades">0 işlem</div></div>
      <div class="sc"><div class="sc-l">RL Episode</div><div class="sc-v" id="s-ep">—</div><div class="sc-s">Q-Learning</div></div>
      <div class="sc"><div class="sc-l">Epsilon</div><div class="sc-v" id="s-eps">—</div><div class="sc-s">keşif oranı</div></div>
      <div class="sc"><div class="sc-l">Avg Reward</div><div class="sc-v" id="s-rew">—</div><div class="sc-s">son 20 ep.</div></div>
      <div class="sc"><div class="sc-l">Semboller</div><div class="sc-v" id="s-syms">0</div><div class="sc-s">izleniyor</div></div>
      <div class="sc"><div class="sc-l">Max Drawdown</div><div class="sc-v r" id="s-dd">0.00%</div><div class="sc-s">peak'ten düşüş</div></div>
      <div class="sc"><div class="sc-l">Açık PnL</div><div class="sc-v" id="s-opnl">$0</div><div class="sc-s">unrealized</div></div>
      <div class="sc"><div class="sc-l">Sinyaller</div><div class="sc-v b" id="s-totsig">0</div><div class="sc-s">üretilen</div></div>
      <div class="sc"><div class="sc-l">Sonraki Güncelleme</div><div class="sc-v" id="s-nxt" style="font-size:.9rem">—</div><div class="sc-s">market verisi</div></div>
    </div>
    <!-- RL Weights -->
    <div style="border-top:1px solid var(--b0);padding:.4rem 0">
      <div style="font-size:.52rem;letter-spacing:.1em;text-transform:uppercase;color:var(--t2);padding:.1rem .8rem .3rem">Strateji Ağırlıkları</div>
      <div id="rl-w"></div>
    </div>
  </div>

  <!-- MARKET TABLE -->
  <div class="panel s-market">
    <div class="ph">
      <div class="ph-title"><span class="ph-icon">◉</span>PİYASA VERİSİ</div>
      <div style="display:flex;align-items:center;gap:.4rem">
        <input id="mkt-search" placeholder="BTC, ETH, SOL..." oninput="renderMkt()" onkeydown="if(event.key==='Escape')this.value='',renderMkt()" oninput="renderMkt()" style="background:var(--s2);border:1px solid var(--b0);color:var(--t0);font-family:var(--mono);font-size:.62rem;padding:.2rem .5rem;border-radius:4px;outline:none;width:110px">
        <span class="badge bg" id="mkt-cnt">0 Sembol</span>
      </div>
    </div>
    <div class="pb-np">
      <table class="dt">
        <thead><tr>
          <th onclick="sortMkt('sym')">Sembol</th>
          <th onclick="sortMkt('price')">Fiyat</th>
          <th onclick="sortMkt('change')">24s %</th>
          <th onclick="sortMkt('rsi')">RSI</th>
          <th onclick="sortMkt('macd')">MACD</th>
          <th onclick="sortMkt('vol')">Hacim</th>
          <th>BB %</th>
          <th>Sinyal</th>
          <th>Fiyat Trendi</th>
          <th>İşlem</th>
        </tr></thead>
        <tbody id="mkt-body"><tr><td colspan="10" style="padding:1.5rem;text-align:center">
          <div class="shim" style="width:70%;margin:auto;height:12px"></div>
        </td></tr></tbody>
      </table>
    </div>
  </div>

  <!-- SIGNALS -->
  <div class="panel s-signals">
    <div class="ph">
      <div class="ph-title"><span class="ph-icon">◎</span>SİNYAL AKIŞI</div>
      <span class="badge bg" id="sig-cnt">0</span>
    </div>
    <div id="sig-feed" class="sfc"><div class="empty"><div>⟳</div><div>Sinyal bekleniyor...</div></div></div>
  </div>

  <!-- OPEN POSITIONS -->
  <div class="panel s-positions">
    <div class="ph">
      <div class="ph-title"><span class="ph-icon">▣</span>AÇIK POZİSYONLAR</div>
      <div style="display:flex;gap:.4rem;align-items:center">
        <span class="badge by" id="pos-cnt">0 Aktif</span>
        <button onclick="fetchPositions()" style="background:var(--s2);border:1px solid var(--b0);color:var(--t2);font-size:.55rem;padding:.15rem .4rem;border-radius:3px;cursor:pointer;font-family:var(--mono)">↻</button>
      </div>
    </div>
    <!-- Pozisyon özet barı -->
    <div class="pos-summary-bar" id="pos-summary" style="display:none">
      <div class="psb-item"><div class="psb-lbl">Toplam PnL</div><div class="psb-val" id="psb-pnl">$0</div></div>
      <div class="psb-item"><div class="psb-lbl">Toplam Büyüklük</div><div class="psb-val" id="psb-size" style="color:var(--y)">$0</div></div>
      <div class="psb-item"><div class="psb-lbl">En İyi</div><div class="psb-val pos-g" id="psb-best">—</div></div>
      <div class="psb-item"><div class="psb-lbl">En Kötü</div><div class="psb-val pos-r" id="psb-worst">—</div></div>
      <div class="psb-item"><div class="psb-lbl">L/S Oran</div><div class="psb-val" id="psb-ratio" style="color:var(--b)">0/0</div></div>
    </div>
    <!-- RSI Sentiment bar -->
    <div class="sent-bar" id="sent-wrap" style="flex-direction:column;align-items:stretch;padding:.4rem .8rem">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.25rem">
        <span style="font-size:.55rem;letter-spacing:.08em;text-transform:uppercase;color:var(--t2)">◈ PİYASA DUYGUSU (RSI Dağılımı)</span>
        <span style="font-size:.58rem;color:var(--t1)" id="sent-score">—</span>
      </div>
      <div style="display:flex;height:6px;border-radius:3px;overflow:hidden;background:var(--t3)">
        <div id="sent-os" class="sent-seg" style="background:#00c382;width:0%"></div>
        <div id="sent-n"  class="sent-seg" style="background:#3a5060;width:100%"></div>
        <div id="sent-ob" class="sent-seg" style="background:#ff3b5c;width:0%"></div>
      </div>
      <div style="display:flex;justify-content:space-between;margin-top:.2rem;font-size:.52rem;color:var(--t2)">
        <span id="sent-os-lbl">Aşırı Satım 0</span>
        <span id="sent-n-lbl">Nötr</span>
        <span id="sent-ob-lbl">Aşırı Alım 0</span>
      </div>
    </div>
    <div class="pb-np" id="pos-body">
      <div class="empty" style="height:80px"><div>Açık pozisyon yok</div></div>
    </div>
  </div>

  <!-- TRADE HISTORY -->
  <div class="panel s-history">
    <div class="ph">
      <div class="ph-title"><span class="ph-icon">≡</span>İŞLEM GEÇMİŞİ</div>
      <span class="badge bb" id="hist-cnt">0</span>
    </div>
    <div style="display:flex;gap:.4rem;padding:.3rem .8rem;border-bottom:1px solid var(--b0);font-size:.58rem;flex-shrink:0">
      <span style="color:var(--t2)">Kazanç: <span id="h-wins-pnl" style="color:var(--g)">$0</span></span>
      <span style="color:var(--t2)">Kayıp: <span id="h-loss-pnl" style="color:var(--r)">$0</span></span>
      <span style="color:var(--t2)">Ort Süre: <span id="h-avg-dur" style="color:var(--b)">—</span></span>
    </div>
    <div class="pb-np" id="hist-body">
      <div class="empty" style="height:80px"><div>Henüz işlem yok</div></div>
    </div>
  </div>

  <!-- AGENTS + LOG -->
  <div class="panel s-agents">
    <div class="ph">
      <div class="ph-title"><span class="ph-icon">⬡</span>AJANLAR · LOG</div>
      <span class="badge bg">AKTİF</span>
    </div>
    <div class="pb-np" style="overflow-y:auto;flex:1">
      <div id="ag-list"></div>
      <div style="border-top:1px solid var(--b0);padding:.3rem 0">
        <div style="font-size:.52rem;letter-spacing:.1em;text-transform:uppercase;color:var(--t2);padding:.1rem .8rem .3rem">Sistem Logu</div>
        <div id="sys-log"></div>
      </div>
    </div>
  </div>

</div><!-- workspace -->

<!-- MANUAL TRADE MODAL -->
<div class="modal-bg" id="trade-modal">
  <div class="modal modal-trade">
    <div class="modal-head" style="border-color:rgba(0,150,255,0.25)">
      <h2 style="color:var(--b)">⚡ MANUEL İŞLEM — <span id="tm-sym-title">—</span></h2>
      <button class="modal-close" onclick="closeTradeModal()">✕</button>
    </div>
    <div class="modal-body">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.6rem">
        <div>
          <div style="font-size:.55rem;color:var(--t2);text-transform:uppercase;letter-spacing:.1em">Anlık Fiyat</div>
          <div style="font-family:var(--head);font-size:1.4rem;font-weight:800;color:#fff" id="tm-price">$—</div>
        </div>
        <div style="text-align:right">
          <div style="font-size:.55rem;color:var(--t2);text-transform:uppercase;letter-spacing:.1em">24s Değişim</div>
          <div style="font-family:var(--head);font-size:1rem;font-weight:700" id="tm-change">—</div>
        </div>
      </div>
      <div style="display:flex;gap:.8rem;margin-bottom:.5rem;font-size:.62rem">
        <span style="color:var(--t2)">RSI: <span id="tm-rsi" style="color:var(--y)">—</span></span>
        <span style="color:var(--t2)">MACD: <span id="tm-macd" style="color:var(--t1)">—</span></span>
        <span style="color:var(--t2)">Vol: <span id="tm-vol" style="color:var(--b)">—</span></span>
      </div>
      <div class="trade-side-btns">
        <div class="ts-btn ts-long active" id="ts-long" onclick="selectSide('long')">▲ LONG</div>
        <div class="ts-btn ts-short" id="ts-short" onclick="selectSide('short')">▼ SHORT</div>
      </div>
      <div class="field-group">
        <label>Kaldıraç</label>
        <div class="lev-btns" id="lev-btns">
          <button class="lev-btn active" onclick="selectLev(1)">1x</button>
          <button class="lev-btn" onclick="selectLev(2)">2x</button>
          <button class="lev-btn" onclick="selectLev(3)">3x</button>
          <button class="lev-btn" onclick="selectLev(5)">5x</button>
          <button class="lev-btn" onclick="selectLev(10)">10x</button>
          <button class="lev-btn" onclick="selectLev(20)">20x</button>
        </div>
      </div>
      <div class="trade-preview" id="trade-preview">
        <div class="tp"><span class="lbl">Pozisyon Büyüklüğü</span><span id="tp-size">—</span></div>
        <div class="tp"><span class="lbl">Stop Loss</span><span id="tp-sl" style="color:var(--r)">—</span></div>
        <div class="tp"><span class="lbl">TP 1</span><span id="tp-tp1" style="color:var(--g)">—</span></div>
        <div class="tp"><span class="lbl">TP 2</span><span id="tp-tp2" style="color:var(--g)">—</span></div>
        <div class="tp"><span class="lbl">TP 3</span><span id="tp-tp3" style="color:var(--g)">—</span></div>
        <div class="tp" style="margin-top:.3rem;border-top:1px solid var(--b0);padding-top:.3rem"><span class="lbl">Risk</span><span id="tp-risk" style="color:var(--y)">—</span></div>
      </div>
    </div>
    <div class="modal-foot" style="border-color:rgba(0,150,255,0.15)">
      <button class="btn-cancel" onclick="closeTradeModal()">İptal</button>
      <button id="tm-exec-btn" onclick="executeTrade()" style="background:rgba(0,195,130,0.15);border:1px solid rgba(0,195,130,0.4);color:var(--g);padding:.4rem 1.2rem;border-radius:4px;cursor:pointer;font-family:var(--mono);font-size:.7rem;font-weight:600">⚡ LONG AÇ</button>
    </div>
  </div>
</div>

<!-- SETTINGS MODAL -->
<div class="modal-bg" id="settings-modal">
  <div class="modal">
    <div class="modal-head">
      <h2>⚙ BOT AYARLARI</h2>
      <button class="modal-close" onclick="closeSettings()">✕</button>
    </div>
    <div class="modal-body">
      <div class="field-grid">
        <div class="field-group">
          <label>Min Güven Eşiği</label>
          <input type="number" id="cfg-conf" step="0.01" min="0.1" max="0.99" placeholder="0.55">
        </div>
        <div class="field-group">
          <label>Risk % (her işlem)</label>
          <input type="number" id="cfg-risk" step="0.01" min="0.01" max="0.5" placeholder="0.02">
        </div>
        <div class="field-group">
          <label>Stop Loss %</label>
          <input type="number" id="cfg-sl" step="0.01" min="0.01" max="0.5" placeholder="0.03">
        </div>
        <div class="field-group">
          <label>Take Profit %</label>
          <input type="number" id="cfg-tp" step="0.01" min="0.01" max="1.0" placeholder="0.06">
        </div>
        <div class="field-group">
          <label>Max Pozisyon</label>
          <input type="number" id="cfg-maxpos" step="1" min="1" max="20" placeholder="5">
        </div>
        <div class="field-group">
          <label>Market Aralık (s)</label>
          <input type="number" id="cfg-mktint" step="1" min="5" max="300" placeholder="15">
        </div>
      </div>
    </div>
    <div class="modal-foot">
      <button class="btn-cancel" onclick="closeSettings()">İptal</button>
      <button class="btn-save" onclick="saveSettings()">💾 Kaydet</button>
    </div>
  </div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>
'use strict';
const ST={pnlHist:[0],prevP:{},chartMode:'cumulative',peakEquity:1000};
const SYM={'bitcoin':'BTC','ethereum':'ETH','solana':'SOL','binancecoin':'BNB','ripple':'XRP'};
const ROLES={MarketAgent:'Binance Futures · Veri Toplayıcı',StrategyAgent:'RSI/MACD/BB · Sinyal Üretici',
  RLMetaAgent:'Q-Learning · Ağırlık Güncelleyici',ExecutionAgent:'Paper Trade · Emir Uygulayıcı'};

// ── CHART ──
const pctx=document.getElementById('pc').getContext('2d');
const chart=new Chart(pctx,{type:'line',data:{labels:['0'],datasets:[{
  label:'PnL',data:[0],borderColor:'#00c382',borderWidth:1.5,
  pointRadius:0,pointHoverRadius:3,fill:true,tension:0.4,
  backgroundColor:c=>{const g=c.chart.ctx.createLinearGradient(0,0,0,c.chart.height);
    g.addColorStop(0,'rgba(0,195,130,0.18)');g.addColorStop(1,'rgba(0,195,130,0.01)');return g}
}]},options:{animation:{duration:300},responsive:true,maintainAspectRatio:false,
  plugins:{legend:{display:false},tooltip:{backgroundColor:'#0c1220',borderColor:'rgba(0,195,130,0.3)',
    borderWidth:1,titleColor:'#00c382',bodyColor:'#b8cce0',
    callbacks:{label:c=>' $'+c.parsed.y.toFixed(4)}}},
  scales:{x:{grid:{color:'rgba(0,195,130,0.03)'},ticks:{color:'#3a5060',font:{family:"'JetBrains Mono'",size:10},maxTicksLimit:8}},
    y:{grid:{color:'rgba(0,195,130,0.05)'},ticks:{color:'#3a5060',font:{family:"'JetBrains Mono'",size:10},callback:v=>'$'+v.toFixed(2)}}}}
});

function toggleChart(){
  ST.chartMode=ST.chartMode==='cumulative'?'per-trade':'cumulative';
  document.getElementById('chart-lbl').textContent=ST.chartMode==='cumulative'?'KÜMÜLATİF':'İŞLEM BAŞI';
  redrawChart();
}
function redrawChart(){
  const d=ST.pnlHist;
  const vals=ST.chartMode==='per-trade'?d.map((v,i)=>i===0?v:v-d[i-1]):d;
  const last=d[d.length-1];
  const col=last>=0?'#00c382':'#ff3b5c';
  chart.data.datasets[0].data=vals;
  chart.data.datasets[0].borderColor=col;
  chart.data.datasets[0].backgroundColor=c=>{
    const g=c.chart.ctx.createLinearGradient(0,0,0,c.chart.height);
    g.addColorStop(0,last>=0?'rgba(0,195,130,0.18)':'rgba(255,59,92,0.18)');
    g.addColorStop(1,'rgba(0,0,0,0)');return g;
  };
  chart.data.labels=d.map((_,i)=>String(i));
  chart.update('none');
}

// ── CLOCK ──
setInterval(()=>{document.getElementById('clock').textContent=new Date().toUTCString().split(' ')[4]+' UTC';},1000);

// ── HELPERS ──
function fP(n){if(n>=10000)return'$'+n.toLocaleString('en-US',{maximumFractionDigits:0});
  if(n>=100)return'$'+n.toFixed(2);if(n>=1)return'$'+n.toFixed(3);return'$'+n.toFixed(5)}
function fV(n){if(n>=1e9)return'$'+(n/1e9).toFixed(2)+'B';if(n>=1e6)return'$'+(n/1e6).toFixed(1)+'M';
  if(n>=1e3)return'$'+(n/1e3).toFixed(0)+'K';return'$'+n.toFixed(0)}
function fU(s){const h=Math.floor(s/3600),m=Math.floor((s%3600)/60),sec=Math.floor(s%60);
  return`${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`}
function fAgo(iso){const ms=Date.now()-new Date(iso.includes('Z')?iso:iso+'Z').getTime();
  const s=Math.floor(ms/1000);if(s<60)return s+'s';if(s<3600)return Math.floor(s/60)+'m';return Math.floor(s/3600)+'h'}
function fT(iso){const d=new Date(iso.includes('Z')?iso:iso+'Z');
  return d.toLocaleTimeString('tr-TR',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}
function set(id,v,cls){const e=document.getElementById(id);if(!e)return;
  e.textContent=v;if(cls)e.className=e.className.replace(/\b(g|r|b|y)\b/g,'')+' '+cls}
function shortSym(s){
  // Binance format: BTCUSDT → BTC, ETHUSDT → ETH
  if(s.endsWith('USDT')) return s.slice(0,-4);
  if(s.endsWith('BUSD')) return s.slice(0,-4);
  return SYM[s]||(s.substring(0,6).toUpperCase());
}

// ── STATUS ──
async function fetchStatus(){
  try{
    const d=await fetch('/status').then(r=>r.json());
    const pnl=d.total_pnl||0;
    const ret=d.return_pct||0;
    const eq=d.equity||1000;
    set('k-cap','$'+(d.initial_capital||1000).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}));
    set('k-eq','$'+eq.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}),eq>=1000?'g':'r');
    set('k-pnl','$'+(pnl>=0?'+':'')+pnl.toFixed(4),pnl>=0?'g':'r');
    set('k-ret',(ret>=0?'+':'')+ret.toFixed(2)+'%',ret>=0?'g':'r');
    set('k-wr',(d.win_rate||0)+'%','b');
    set('k-wl',(d.win_count||0)+'/'+(d.loss_count||0));
    set('k-tr',d.trade_count||0);
    set('k-op',d.open_positions||0,'y');
    const totalSigs=d.rl_metrics&&d.rl_metrics.total_signals_processed||0;
    set('k-sigs',totalSigs);
    set('k-up',fU(d.uptime_seconds||0));

    // Stats panel
    set('s-eq','$'+eq.toFixed(2),eq>=1000?'g':'r');
    set('s-ret',(ret>=0?'+':'')+ret.toFixed(2)+'%');
    document.getElementById('s-ret').style.color=ret>=0?'var(--g)':'var(--r)';
    set('s-pnl','$'+(pnl>=0?'+':'')+pnl.toFixed(4),pnl>=0?'g':'r');
    set('s-wl','W:'+(d.win_count||0)+' / L:'+(d.loss_count||0));
    set('s-wr',(d.win_rate||0)+'%','b');
    set('s-trades',(d.trade_count||0)+' işlem');
    set('s-syms',d.market_symbols||0);
    // Drawdown
    if(eq>ST.peakEquity)ST.peakEquity=eq;
    const dd=ST.peakEquity>0?((ST.peakEquity-eq)/ST.peakEquity*100):0;
    const ddEl=document.getElementById('s-dd');
    ddEl.textContent=(dd>0?'-':'')+dd.toFixed(2)+'%';
    ddEl.className='sc-v '+(dd>5?'r':dd>2?'y':'g');
    // Open position PnL (from positions data fetched separately)

    // Bot status
    const bBadge=document.getElementById('bot-status-badge');
    if(!d.bot_running){bBadge.textContent='⏹ DURDURULDU';bBadge.className='badge br'}
    else if(d.bot_paused){bBadge.textContent='⏸ DURAKLATILDI';bBadge.className='badge by'}
    else{bBadge.textContent='▶ ÇALIŞIYOR';bBadge.className='badge bg'}

    // PnL history
    if(pnl!==ST.pnlHist[ST.pnlHist.length-1]){
      ST.pnlHist.push(pnl);
      if(ST.pnlHist.length>150)ST.pnlHist=ST.pnlHist.slice(-150);
      redrawChart();
    }

    // RL
    const rl=d.rl_metrics||{};
    set('s-ep',rl.episode!==undefined?'#'+rl.episode:'—');
    const rew=rl.avg_reward_20ep;
    set('s-rew',rew!==undefined?rew.toFixed(3):'—',rew>=0?'g':'r');
    set('s-eps',rl.epsilon!==undefined?((rl.epsilon||0)*100).toFixed(1)+'%':'—');

    // RL Weights
    const w=rl.strategy_weights||{};
    const COLS={rsi:'#00c382',macd:'#0096ff',bollinger:'#a855f7',composite:'#f5a623'};
    document.getElementById('rl-w').innerHTML=Object.entries(w).map(([k,v])=>{
      const pct=Math.round((v||0)*100);
      return`<div class="rl-item"><div class="rl-nm">${k}<span class="rl-sc">${pct}%</span></div>
        <div class="rl-tr"><div class="rl-fi" style="width:${pct}%;background:${COLS[k]||'#00c382'}"></div></div></div>`;
    }).join('')||'<div style="padding:.4rem .8rem;font-size:.62rem;color:var(--t2)">Bekleniyor...</div>';

    // Agents
    const agents=d.agent_heartbeats||{};
    document.getElementById('ag-list').innerHTML=Object.entries(agents).map(([n,ts])=>`
      <div class="ag-row">
        <div class="ag-dot on"></div>
        <div class="ag-name">${n}</div>
        <div class="ag-role">${ROLES[n]||''}</div>
        <div class="ag-t">${fAgo(ts)}</div>
      </div>`).join('')||'<div class="empty" style="height:50px"><div>Bağlanıyor...</div></div>';

    // Load settings into modal if not open
    if(d.settings){const s=d.settings;
      ['conf','risk','sl','tp','maxpos'].forEach(k=>{});
      document.getElementById('cfg-conf').placeholder=s.min_confidence;
      document.getElementById('cfg-risk').placeholder=s.risk_pct;
      document.getElementById('cfg-sl').placeholder=s.stop_loss_pct;
      document.getElementById('cfg-tp').placeholder=s.take_profit_pct;
      document.getElementById('cfg-maxpos').placeholder=s.max_positions;
      document.getElementById('cfg-mktint').placeholder=s.market_interval;
    }
  }catch(e){console.warn('status',e)}
}

// ── MARKET ──
let mktData={},mktSort='vol',mktDir=-1,sparkData={};
function sortMkt(c){mktSort===c?mktDir*=-1:(mktSort=c,mktDir=-1);renderMkt()}
async function fetchMarket(){
  try{
    const d=await fetch('/market').then(r=>r.json());
    const prev=mktData;
    mktData=d.symbols||{};
    // Update sparkline history (last 20 prices per symbol)
    Object.entries(mktData).forEach(([sym,d2])=>{
      if(!sparkData[sym])sparkData[sym]=[];
      sparkData[sym].push(d2.price||0);
      if(sparkData[sym].length>20)sparkData[sym].shift();
    });
    renderMkt();updateTape();
    set('mkt-cnt',Object.keys(mktData).length+' Sembol');
    updateSentiment();
  }catch(e){console.warn('market',e)}
}
function renderMkt(){
  const q=(document.getElementById('mkt-search')||{}).value||'';
  let entries=Object.entries(mktData);
  if(q.trim()) entries=entries.filter(([sym])=>sym.toLowerCase().includes(q.toLowerCase()));
  if(!entries.length)return;
  entries.sort(([,a],[,b])=>{
    const gv=x=>({'sym':0,price:x.price||0,change:x.change_24h||0,rsi:x.rsi||50,macd:x.macd||0,vol:x.volume_24h||0}[mktSort]||0);
    return(gv(a)-gv(b))*mktDir;
  });
  updateMoversStrip(entries);
  document.getElementById('mkt-body').innerHTML=entries.map(([sym,d])=>{
    const price=d.price||0;const prev=ST.prevP[sym]||price;
    const fl=price>prev?'fl-g':price<prev?'fl-r':'';ST.prevP[sym]=price;
    const chg=d.change_24h||0;const rsi=d.rsi||50;const macd=d.macd||0;
    const vol=d.volume_24h||0;const mom=d.momentum_1m||0;
    const rsiCls=rsi>70?'rsi-ob':rsi<30?'rsi-os':'rsi-n';
    const rowBg=chg>3?'rgba(0,195,130,0.03)':chg<-3?'rgba(255,59,92,0.03)':'';
    let sig='<span style="color:var(--t2)">–</span>';
    if(rsi<30&&macd>0)sig='<span class="pos-g">▲ BUY</span>';
    else if(rsi>70&&macd<0)sig='<span class="pos-r">▼ SELL</span>';
    else if(rsi<35)sig='<span class="pos-g" style="opacity:.7">↑ Zayıf Al</span>';
    else if(rsi>65)sig='<span class="pos-r" style="opacity:.7">↓ Zayıf Sat</span>';
    const bbPct=d.bb_upper&&d.bb_lower?Math.round(((price-d.bb_lower)/(d.bb_upper-d.bb_lower))*100):50;
    const bw=Math.max(0,Math.min(100,bbPct));
    return`<tr class="${fl}" style="background:${rowBg}">
      <td><span class="sym">${shortSym(sym)}</span><span class="sym-s">${sym.toUpperCase()}</span></td>
      <td style="color:#e0eef8">${fP(price)}</td>
      <td class="${chg>=0?'pos-g':'pos-r'}">${chg>=0?'+':''}${chg.toFixed(2)}%</td>
      <td><span class="rsi ${rsiCls}">${rsi.toFixed(1)}</span></td>
      <td class="${macd>=0?'pos-g':'pos-r'}">${macd>=0?'+':''}${macd.toFixed(5)}</td>
      <td class="neu">${fV(vol)}</td>
      <td><div class="bar"><div class="bt"><div class="bf ${bw>50?'bf-g':'bf-r'}" style="width:${bw}%"></div></div><span style="font-size:.58rem;min-width:28px;text-align:right;color:${mom>=0?'var(--g)':'var(--r)'}">${mom>=0?'+':''}${mom.toFixed(2)}%</span></div></td>
      <td>${sig}</td>
      <td>${renderSparkline(sym)}</td>
      <td style="white-space:nowrap">
        <button onclick="openTradeModalDirect('${sym}')" style="font-size:.52rem;padding:.1rem .35rem;background:rgba(0,195,130,0.1);border:1px solid rgba(0,195,130,0.25);color:var(--g);border-radius:3px;cursor:pointer;font-family:var(--mono)" title="Long Aç">▲L</button>
        <button onclick="openTradeModalDirectShort('${sym}')" style="font-size:.52rem;padding:.1rem .35rem;background:rgba(255,59,92,0.1);border:1px solid rgba(255,59,92,0.25);color:var(--r);border-radius:3px;cursor:pointer;font-family:var(--mono);margin-left:.2rem" title="Short Aç">▼S</button>
      </td>
    </tr>`;
  }).join('');
}
function updateTape(){
  const items=[...Object.entries(mktData),...Object.entries(mktData)].map(([sym,d])=>{
    const c=d.change_24h||0;
    return`<span class="ti"><span class="ti-s">${shortSym(sym)}</span><span class="ti-p">${fP(d.price||0)}</span><span class="ti-c ${c>=0?'up':'dn'}">${c>=0?'+':''}${c.toFixed(2)}%</span></span>`;
  }).join('');
  document.getElementById('tape').innerHTML=items;
}

// ── SIGNALS ──
async function fetchSignals(){
  try{
    const d=await fetch('/signals').then(r=>r.json());
    const sigs=d.signals||[];set('sig-cnt',sigs.length);
    const feed=document.getElementById('sig-feed');
    if(!sigs.length){feed.innerHTML='<div class="empty"><div>⟳</div><div>Sinyal bekleniyor...</div></div>';return}
    feed.innerHTML=sigs.slice(0,20).map(s=>{
      const pct=Math.round(s.confidence*100);const sym=shortSym(s.symbol);
      const cc=s.direction+'-c',dc='d'+s.direction.charAt(0),fc='f'+s.direction.charAt(0);
      const ind=s.indicators||{};
      const rsiV=ind.rsi||50;
      const rsiCol=rsiV<35?'var(--g)':rsiV>65?'var(--r)':'var(--y)';
      const chgV=ind.change_24h||0;
      return`<div class="sc2 ${cc}">
        <div class="si-top">
          <span class="si-sym">${sym}</span>
          <div style="display:flex;align-items:center;gap:.3rem">
            <span style="font-size:.52rem;color:${rsiCol}">RSI ${rsiV.toFixed(0)}</span>
            <span style="font-size:.52rem;color:${chgV>=0?'var(--g)':'var(--r)'}">${chgV>=0?'+':''}${chgV.toFixed(1)}%</span>
            <span class="si-dir ${dc}">${s.direction.toUpperCase()}</span>
          </div>
        </div>
        <div class="si-conf"><div class="si-bar"><div class="si-fill ${fc}" style="width:${pct}%"></div></div><span class="si-pct">${pct}%</span></div>
        ${s.reason?`<div class="si-reason">${s.reason}</div>`:''}
        <div style="display:flex;justify-content:space-between;margin-top:.2rem">
          <span class="si-time">${fT(s.timestamp)}</span>
          <button onclick="openTradeModalDirect('${s.symbol}','${s.direction==='buy'?'long':'short'}')" style="font-size:.5rem;padding:.08rem .3rem;background:rgba(0,150,255,0.1);border:1px solid rgba(0,150,255,0.25);color:var(--b);border-radius:3px;cursor:pointer;font-family:var(--mono)">⚡ İşlem</button>
        </div>
      </div>`;
    }).join('');
  }catch(e){console.warn('signals',e)}
}

// ── POSITIONS ──
async function fetchPositions(){
  try{
    const d=await fetch('/positions').then(r=>r.json());
    const open=d.open||[];set('pos-cnt',open.length+' Aktif');set('k-op',open.length,'y');
    const body=document.getElementById('pos-body');
    updatePosSummary(open);
    // Update open PnL in stats panel
    const openPnl=open.reduce((s,p)=>s+(p.pnl||0),0);
    const opEl=document.getElementById('s-opnl');
    if(opEl){opEl.textContent=(openPnl>=0?'+':'')+'$'+openPnl.toFixed(4);opEl.className='sc-v '+(openPnl>=0?'g':'r');}
    if(!open.length){body.innerHTML='<div class="empty" style="height:100px"><div style="font-size:1.2rem">📭</div><div>Bot işlem arıyor...</div><div style="font-size:.55rem;color:var(--t3)">Strateji sinyalleri bekleniyor</div></div>';return}
    body.innerHTML=open.map(p=>{
      const sym=shortSym(p.symbol);const pnlCls=p.pnl>=0?'pos-g':'pos-r';
      const sideCls=p.side==='long'?'ps-l':'ps-s';
      const prog=p.progress_pct||0;
      const lev=p.leverage||1;
      const posSize=(p.value_usd||0)*lev;
      const pnlBg=p.pnl>=0?'rgba(0,195,130,0.08)':'rgba(255,59,92,0.08)';
      const borderCol=p.pnl>=0?'var(--g)':'var(--r)';
      return`<div class="pos-row" style="border-left:2px solid ${borderCol};padding-left:.7rem">
        <div class="pos-header">
          <div style="display:flex;align-items:center;gap:.4rem">
            <span class="pos-sym">${sym}</span>
            <span class="pos-side ${sideCls}">${p.side.toUpperCase()}</span>
            <span style="font-size:.52rem;padding:.1rem .32rem;border-radius:3px;background:rgba(0,150,255,0.12);color:var(--b);border:1px solid rgba(0,150,255,0.3)">${lev}x</span>
          </div>
          <div style="display:flex;align-items:center;gap:.4rem">
            <span class="pos-pnl ${pnlCls}" style="background:${pnlBg};padding:.15rem .5rem;border-radius:4px;font-size:.8rem">${p.pnl>=0?'+':''}$${(p.pnl||0).toFixed(4)} <span style="font-size:.65rem">(${p.pnl_pct>=0?'+':''}${(p.pnl_pct||0).toFixed(2)}%)</span></span>
            <button class="pos-close-btn" onclick="closePos('${p.symbol}')">✕ KAPAT</button>
          </div>
        </div>
        <div class="pos-meta" style="flex-wrap:wrap;margin:.2rem 0">
          <span><span class="lbl">Giriş</span>${fP(p.entry_price)}</span>
          <span><span class="lbl">Anlık</span><span style="color:${(p.current_price||0)>=(p.entry_price||0)?'var(--g)':'var(--r)'}">${fP(p.current_price)}</span></span>
          <span title="Pozisyon Büyüklüğü = Teminat × Kaldıraç"><span class="lbl">Pos. Büyüklük</span><span style="color:var(--y)">$${posSize.toFixed(2)}</span></span>
          <span><span class="lbl">Teminat</span>$${(p.value_usd||0).toFixed(2)}</span>
          <span><span class="lbl">Miktar</span>${(p.qty||0).toFixed(6)}</span>
          <span><span class="lbl">Açıldı</span>${fT(p.opened_at)}</span>
        </div>
        <div class="sltp-bar">
          <span class="sltp-sl">🛑 ${fP(p.stop_loss)}</span>
          <div class="sltp-track"><div class="sltp-fill" style="width:${prog}%"></div></div>
          <span class="sltp-pct">${prog.toFixed(0)}%</span>
          <span class="sltp-tp">🎯 ${fP(p.take_profit)}${p.take_profit_levels&&p.take_profit_levels.length>1?' ('+(p.tp_hit_count+1)+'/'+p.take_profit_levels.length+')':''}</span>
        </div>
        ${p.take_profit_levels&&p.take_profit_levels.length>1?`<div style="display:flex;gap:.28rem;padding:.2rem 0;flex-wrap:wrap">${p.take_profit_levels.map((t,i)=>`<span style="font-size:.54rem;padding:.12rem .38rem;border-radius:3px;background:${i<p.tp_hit_count?'rgba(0,195,130,0.2)':'rgba(0,195,130,0.05)'};color:${i<p.tp_hit_count?'var(--g)':'var(--t1)'};border:1px solid rgba(0,195,130,${i<p.tp_hit_count?'0.4':'0.12'})">${i<p.tp_hit_count?'✓ ':''}TP${i+1} ${fP(t)}</span>`).join('')}</div>`:''}
        ${p.ai_summary?`<div class="pos-ai"><div class="pos-ai-label">⬡ AI Özeti</div>${p.ai_summary}</div>`:''}
        ${p.reason?`<div style="font-size:.57rem;color:var(--t2);padding-top:.12rem">📍 ${p.reason}</div>`:''}
      </div>`;
    }).join('');
  }catch(e){console.warn('positions',e)}
}

// ── POSITION SUMMARY + SENTIMENT ──
// ── MOVERS STRIP + COUNTDOWN ──
let countdownVal=30;
setInterval(()=>{
  countdownVal--;
  if(countdownVal<=0)countdownVal=30;
  const el=document.getElementById('update-countdown');
  if(el){el.textContent=countdownVal+'s';el.style.color=countdownVal<=5?'var(--r)':countdownVal<=10?'var(--y)':'var(--b)';}
},1000);

function renderSparkline(sym){
  const hist=sparkData[sym]||[];
  if(hist.length<2)return'<span style="color:var(--t3)">—</span>';
  const w=60,h=18;
  const mn=Math.min(...hist),mx=Math.max(...hist);
  const rng=mx-mn||1;
  const pts=hist.map((v,i)=>{
    const x=Math.round(i/(hist.length-1)*(w-2))+1;
    const y=Math.round((1-(v-mn)/rng)*(h-2))+1;
    return x+','+y;
  }).join(' ');
  const last=hist[hist.length-1],first=hist[0];
  const col=last>=first?'#00c382':'#ff3b5c';
  return`<svg width="${w}" height="${h}" style="vertical-align:middle"><polyline points="${pts}" fill="none" stroke="${col}" stroke-width="1.2" stroke-linejoin="round"/></svg>`;
}

function updateMoversStrip(entries){
  if(!entries.length)return;
  const sorted=[...entries].sort((a,b)=>(b[1].change_24h||0)-(a[1].change_24h||0));
  const top5=sorted.slice(0,5);
  const bot5=sorted.slice(-5).reverse();
  const movers=[...top5,...bot5];
  const html=movers.map(([sym,d])=>{
    const chg=d.change_24h||0;
    const col=chg>=0?'var(--g)':'var(--r)';
    const bg=chg>=0?'rgba(0,195,130,0.06)':'rgba(255,59,92,0.06)';
    return`<span style="display:inline-flex;align-items:center;gap:.3rem;padding:0 .7rem;border-right:1px solid var(--b0);height:24px;background:${bg};font-size:.6rem;cursor:pointer" onclick="openTradeModal('${shortSym(sym)}')">
      <span style="color:#e0eef8;font-weight:500">${shortSym(sym)}</span>
      <span style="color:${col}">${chg>=0?'+':''}${chg.toFixed(2)}%</span>
    </span>`;
  }).join('');
  const el=document.getElementById('movers-strip');
  if(el)el.innerHTML=html;
}

function updateSentiment(){
  const entries=Object.values(mktData);
  if(!entries.length)return;
  let os=0,ob=0,neutral=0;
  entries.forEach(d=>{
    const r=d.rsi||50;
    if(r<30)os++;
    else if(r>70)ob++;
    else neutral++;
  });
  const total=entries.length;
  const osPct=Math.round(os/total*100);
  const obPct=Math.round(ob/total*100);
  const nPct=100-osPct-obPct;
  document.getElementById('sent-os').style.width=osPct+'%';
  document.getElementById('sent-n').style.width=nPct+'%';
  document.getElementById('sent-ob').style.width=obPct+'%';
  document.getElementById('sent-os-lbl').textContent='🟢 Aşırı Satım '+os;
  document.getElementById('sent-n-lbl').textContent='Nötr '+neutral;
  document.getElementById('sent-ob-lbl').textContent='Aşırı Alım '+ob+' 🔴';
  // Piyasa skoru: -100 (tam bearish) → +100 (tam bullish)
  const score=Math.round((os-ob)/total*100);
  const scoreEl=document.getElementById('sent-score');
  if(score>20){scoreEl.textContent='BULLISH +'+score;scoreEl.style.color='var(--g)';}
  else if(score<-20){scoreEl.textContent='BEARISH '+score;scoreEl.style.color='var(--r)';}
  else{scoreEl.textContent='NÖTR '+score;scoreEl.style.color='var(--t1)';}
}

function updatePosSummary(open){
  const summaryEl=document.getElementById('pos-summary');
  if(!open.length){summaryEl.style.display='none';return;}
  summaryEl.style.display='flex';
  const totalPnl=open.reduce((s,p)=>s+(p.pnl||0),0);
  const totalSize=open.reduce((s,p)=>s+(p.value_usd||0)*(p.leverage||1),0);
  const longs=open.filter(p=>p.side==='long').length;
  const shorts=open.filter(p=>p.side==='short').length;
  const sorted=[...open].sort((a,b)=>(b.pnl||0)-(a.pnl||0));
  const best=sorted[0],worst=sorted[sorted.length-1];
  const pnlEl=document.getElementById('psb-pnl');
  pnlEl.textContent=(totalPnl>=0?'+':'')+'$'+totalPnl.toFixed(4);
  pnlEl.style.color=totalPnl>=0?'var(--g)':'var(--r)';
  document.getElementById('psb-size').textContent='$'+totalSize.toFixed(2);
  document.getElementById('psb-best').textContent=best?shortSym(best.symbol)+' +'+(best.pnl||0).toFixed(3):'—';
  document.getElementById('psb-worst').textContent=worst?shortSym(worst.symbol)+' '+(worst.pnl||0).toFixed(3):'—';
  document.getElementById('psb-ratio').textContent='L'+longs+'/S'+shorts;
}

// ── CLOSED POSITIONS / HISTORY ──
async function fetchHistory(){
  try{
    const d=await fetch('/positions/closed').then(r=>r.json());
    const closed=d.closed||[];set('hist-cnt',closed.length);
    const body=document.getElementById('hist-body');
    if(!closed.length){body.innerHTML='<div class="empty" style="height:80px"><div>Henüz işlem yok</div></div>';return}
    // History stats
    const wins=closed.filter(x=>x.pnl>0);
    const losses=closed.filter(x=>x.pnl<=0);
    const winPnl=wins.reduce((s,x)=>s+x.pnl,0);
    const lossPnl=losses.reduce((s,x)=>s+x.pnl,0);
    const el1=document.getElementById('h-wins-pnl');
    const el2=document.getElementById('h-loss-pnl');
    const el3=document.getElementById('h-avg-dur');
    if(el1)el1.textContent='+$'+winPnl.toFixed(3);
    if(el2)el2.textContent='$'+lossPnl.toFixed(3);
    if(el3&&closed.length){
      const avgMs=closed.reduce((s,x)=>s+(new Date(x.closed_at)-new Date(x.opened_at)),0)/closed.length;
      el3.textContent=avgMs>3600000?Math.floor(avgMs/3600000)+'s ':Math.floor(avgMs/60000)+'d';
    }
    body.innerHTML=closed.slice(0,40).map(c=>{
      const pnlCls=c.pnl>=0?'pos-g':'pos-r';
      const sideCls=c.side==='long'?'ps-l':'ps-s';
      const rcls=c.close_reason&&c.close_reason.startsWith('TP')?'bg':c.close_reason==='SL'?'br':c.close_reason==='MANUAL'?'bp':'bb';
      const durMs=new Date(c.closed_at)-new Date(c.opened_at);
      const durStr=durMs>3600000?Math.floor(durMs/3600000)+'s':durMs>60000?Math.floor(durMs/60000)+'d':Math.floor(durMs/1000)+'s';
      return`<div class="tr-row" style="border-left:2px solid ${c.pnl>=0?'var(--g)':'var(--r)'}">
        <span class="tr-side ${sideCls}">${c.side.substring(0,1).toUpperCase()}</span>
        <span class="tr-sym">${shortSym(c.symbol)}</span>
        <span class="badge ${rcls}" style="font-size:.5rem;padding:.08rem .3rem">${c.close_reason}</span>
        <span class="tr-pnl ${pnlCls}">${c.pnl>=0?'+':''}$${(c.pnl||0).toFixed(4)}</span>
        <span style="font-size:.57rem;color:${(c.pnl_pct||0)>=0?'var(--g)':'var(--r)'};min-width:42px">${(c.pnl_pct||0)>=0?'+':''}${(c.pnl_pct||0).toFixed(1)}%</span>
        <span style="font-size:.55rem;color:var(--t2)">${durStr}</span>
        <span class="tr-time">${fT(c.closed_at)}</span>
      </div>`;
    }).join('');
  }catch(e){console.warn('history',e)}
}

// ── SYSTEM LOG ──
async function fetchLog(){
  try{
    const d=await fetch('/log').then(r=>r.json());
    const log=d.log||[];
    document.getElementById('sys-log').innerHTML=log.slice(0,30).map(l=>`
      <div class="log-row">
        <span class="log-ts">${fT(l.ts)}</span>
        <span class="log-lv ${l.level}">${l.level}</span>
        <span class="log-msg">${l.msg}</span>
      </div>`).join('')||'<div style="padding:.4rem .8rem;font-size:.62rem;color:var(--t2)">Log bekleniyor...</div>';
  }catch(e){}
}

// ── BOT CONTROLS ──
async function botAction(action){
  try{
    await fetch('/bot/'+action,{method:'POST'});
    await fetchStatus();
  }catch(e){console.error(e)}
}
async function closePos(symbol){
  if(!confirm(`${symbol} pozisyonunu manuel kapatmak istiyor musunuz?`))return;
  try{
    const r=await fetch('/positions/close/'+symbol,{method:'POST'}).then(r=>r.json());
    await Promise.all([fetchPositions(),fetchHistory(),fetchStatus()]);
    if(r.pnl!==undefined)alert(`${symbol} kapatıldı. PnL: $${r.pnl>=0?'+':''}${r.pnl.toFixed(4)}`);
  }catch(e){console.error(e)}
}

// ── SETTINGS MODAL ──
async function openSettings(){
  const s=await fetch('/settings').then(r=>r.json());
  document.getElementById('cfg-conf').value=s.min_confidence;
  document.getElementById('cfg-risk').value=s.risk_pct;
  document.getElementById('cfg-sl').value=s.stop_loss_pct;
  document.getElementById('cfg-tp').value=s.take_profit_pct;
  document.getElementById('cfg-maxpos').value=s.max_positions;
  document.getElementById('cfg-mktint').value=s.market_interval;
  document.getElementById('settings-modal').classList.add('open');
}
function closeSettings(){document.getElementById('settings-modal').classList.remove('open')}
async function saveSettings(){
  const payload={
    min_confidence:parseFloat(document.getElementById('cfg-conf').value),
    risk_pct:parseFloat(document.getElementById('cfg-risk').value),
    stop_loss_pct:parseFloat(document.getElementById('cfg-sl').value),
    take_profit_pct:parseFloat(document.getElementById('cfg-tp').value),
    max_positions:parseInt(document.getElementById('cfg-maxpos').value),
    market_interval:parseInt(document.getElementById('cfg-mktint').value),
  };
  await fetch('/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  closeSettings();await fetchStatus();
}
document.getElementById('settings-modal').addEventListener('click',e=>{if(e.target===e.currentTarget)closeSettings()});

// ── MANUAL TRADE ──
let tradeState={symbol:'',side:'long',leverage:1};

function openTradeModalDirect(sym, defaultSide='long'){
  openTradeModalFull(sym, defaultSide);
}
function openTradeModalDirectShort(sym){ openTradeModalDirect(sym, 'short'); }
function openTradeModal(sym, defaultSide='long'){
  const fullSym = sym.endsWith('USDT')||sym.endsWith('BUSD') ? sym : sym+'USDT';
  openTradeModalFull(fullSym, defaultSide);
}
function openTradeModalFull(fullSym, defaultSide='long'){
  const sym = shortSym(fullSym);
  tradeState={symbol:fullSym, side:defaultSide, leverage:1};
  const d=mktData[fullSym]||{};
  document.getElementById('tm-sym-title').textContent=shortSym(fullSym);
  document.getElementById('tm-price').textContent=fP(d.price||0);
  const chg=d.change_24h||0;
  const chgEl=document.getElementById('tm-change');
  chgEl.textContent=(chg>=0?'+':'')+chg.toFixed(2)+'%';
  chgEl.style.color=chg>=0?'var(--g)':'var(--r)';
  const rsi=d.rsi||50;
  const rsiEl=document.getElementById('tm-rsi');
  rsiEl.textContent=rsi.toFixed(1);
  rsiEl.style.color=rsi<30?'var(--g)':rsi>70?'var(--r)':'var(--y)';
  document.getElementById('tm-macd').textContent=(d.macd||0).toFixed(5);
  document.getElementById('tm-vol').textContent=fV(d.volume_24h||0);
  selectSide(defaultSide);
  document.getElementById('trade-modal').classList.add('open');
}
function openTradeModalShort(sym){ openTradeModal(sym, 'short'); } // legacy

function closeTradeModal(){ document.getElementById('trade-modal').classList.remove('open'); }

function selectSide(side){
  tradeState.side=side;
  document.getElementById('ts-long').classList.toggle('active', side==='long');
  document.getElementById('ts-short').classList.toggle('active', side==='short');
  const btn=document.getElementById('tm-exec-btn');
  if(side==='long'){
    btn.textContent='⚡ LONG AÇ';
    btn.style.background='rgba(0,195,130,0.15)';
    btn.style.borderColor='rgba(0,195,130,0.4)';
    btn.style.color='var(--g)';
  } else {
    btn.textContent='⚡ SHORT AÇ';
    btn.style.background='rgba(255,59,92,0.15)';
    btn.style.borderColor='rgba(255,59,92,0.4)';
    btn.style.color='var(--r)';
  }
  updateTradePreview();
}

function selectLev(lev){
  tradeState.leverage=lev;
  document.querySelectorAll('.lev-btn').forEach(b=>{
    b.classList.toggle('active', parseInt(b.textContent)===lev);
  });
  updateTradePreview();
}

function updateTradePreview(){
  const d=mktData[tradeState.symbol]||{};
  const price=d.price||0;
  if(!price) return;
  const riskUsd=1000*0.02; // 2% risk
  const posSize=riskUsd*tradeState.leverage;
  const slPct=0.03;const tpPct=0.06;
  let sl,tp1,tp2,tp3;
  if(tradeState.side==='long'){
    sl=price*(1-slPct); tp1=price*(1+tpPct); tp2=price*(1+tpPct*2); tp3=price*(1+tpPct*3);
  } else {
    sl=price*(1+slPct); tp1=price*(1-tpPct); tp2=price*(1-tpPct*2); tp3=price*(1-tpPct*3);
  }
  document.getElementById('tp-size').textContent='$'+posSize.toFixed(2);
  document.getElementById('tp-sl').textContent=fP(sl)+' (-'+( slPct*100).toFixed(0)+'%)';
  document.getElementById('tp-tp1').textContent=fP(tp1)+' (+'+( tpPct*100).toFixed(0)+'%)';
  document.getElementById('tp-tp2').textContent=fP(tp2)+' (+'+(tpPct*200).toFixed(0)+'%)';
  document.getElementById('tp-tp3').textContent=fP(tp3)+' (+'+(tpPct*300).toFixed(0)+'%)';
  document.getElementById('tp-risk').textContent='$'+(riskUsd*slPct).toFixed(2)+' maks. kayıp';
}

async function executeTrade(){
  const btn=document.getElementById('tm-exec-btn');
  btn.textContent='⏳ Gönderiliyor...';btn.disabled=true;
  try{
    const r=await fetch('/trade/manual',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({symbol:tradeState.symbol, side:tradeState.side, leverage:tradeState.leverage})
    }).then(r=>r.json());
    if(r.error){alert('Hata: '+r.error);}
    else if(r.action==='opened'){
      closeTradeModal();
      await Promise.all([fetchPositions(),fetchStatus(),fetchLog()]);
    } else if(r.action==='closed'){
      alert('Pozisyon kapatıldı. PnL: $'+(r.pnl>=0?'+':'')+r.pnl.toFixed(4));
      closeTradeModal();
      await Promise.all([fetchPositions(),fetchHistory(),fetchStatus(),fetchLog()]);
    }
  }catch(e){alert('Bağlantı hatası: '+e);}
  finally{btn.disabled=false;}
}

document.getElementById('trade-modal').addEventListener('click',e=>{if(e.target===e.currentTarget)closeTradeModal()});

// ── MAIN REFRESH ──
async function refresh(){
  await Promise.all([fetchStatus(),fetchMarket(),fetchSignals(),fetchPositions(),fetchHistory(),fetchLog()]);
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

    app = FastAPI(title="Aurora AI Pro Terminal", version="3.0.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.get("/", response_class=HTMLResponse)
    def root():
        return DASHBOARD_HTML

    @app.get("/health")
    def health():
        return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

    @app.get("/status")
    def status():
        s = shared_state.get_summary()
        return {"status": "running", **s, "rl_metrics": shared_state.rl_metrics}

    @app.get("/market")
    def market():
        return {"symbols": shared_state.market_data}

    @app.get("/signals")
    def signals():
        sigs = shared_state.signals[-30:]
        return {"count": len(sigs), "signals": [
            {"symbol": s.symbol, "direction": s.direction,
             "confidence": s.confidence, "strategy": s.strategy,
             "reason": s.reason, "timestamp": s.timestamp.isoformat()}
            for s in reversed(sigs)
        ]}

    @app.get("/positions")
    def positions():
        return {"open": shared_state.get_positions_detail()}

    @app.get("/positions/closed")
    def closed_positions():
        return {"closed": shared_state.get_closed_positions()}

    @app.get("/metrics")
    def metrics():
        return shared_state.rl_metrics

    @app.get("/log")
    def syslog():
        with shared_state._lock:
            return {"log": list(reversed(shared_state.system_log[-100:]))}

    @app.get("/settings")
    def get_settings():
        return shared_state.settings.to_dict()

    @app.post("/settings")
    async def update_settings(req: Request):
        data = await req.json()
        shared_state.settings.update(data)
        with shared_state._lock:
            shared_state.system_log.append({
                "ts": datetime.utcnow().isoformat(), "level": "INFO",
                "msg": f"Ayarlar guncellendi: {list(data.keys())}"
            })
        return {"ok": True, "settings": shared_state.settings.to_dict()}

    @app.post("/bot/start")
    def bot_start():
        shared_state.start_bot()
        return {"status": "started"}

    @app.post("/bot/stop")
    def bot_stop():
        shared_state.stop_bot()
        return {"status": "stopped"}

    @app.post("/bot/pause")
    def bot_pause():
        shared_state.pause_bot()
        return {"status": "paused" if shared_state.bot_paused else "resumed"}

    @app.post("/positions/close/{symbol}")
    async def close_pos(symbol: str):
        market = shared_state.market_data.get(symbol, {})
        price = market.get("price", 0)
        if price <= 0:
            return {"error": "Fiyat verisi yok"}
        pnl = await shared_state.close_position(symbol, price, "MANUAL")
        return {"ok": True, "pnl": pnl}

    @app.post("/trade/manual")
    async def manual_trade(req: Request):
        from utils.state import Position
        data = await req.json()
        symbol   = data.get("symbol", "").upper()
        side     = data.get("side", "long")    # "long" | "short"
        leverage = int(data.get("leverage", 1))

        if not symbol:
            return {"error": "Sembol gerekli"}

        market = shared_state.market_data.get(symbol, {})
        price  = market.get("price", 0)
        if price <= 0:
            return {"error": f"{symbol} için fiyat verisi yok"}

        # Close if already open
        if symbol in shared_state.positions:
            pnl = await shared_state.close_position(symbol, price, "MANUAL")
            return {"ok": True, "action": "closed", "pnl": pnl}

        if len(shared_state.positions) >= shared_state.settings.max_positions:
            return {"error": "Maksimum pozisyon sayısına ulaşıldı"}

        sl_pct = shared_state.settings.stop_loss_pct
        tp_pct = shared_state.settings.take_profit_pct
        risk_usd = 1000.0 * shared_state.settings.risk_pct
        qty = round(risk_usd / price, 8)

        if side == "long":
            sl = round(price * (1 - sl_pct), 8)
            tp_levels = [
                round(price * (1 + tp_pct), 8),
                round(price * (1 + tp_pct * 2), 8),
                round(price * (1 + tp_pct * 3), 8),
            ]
        else:
            sl = round(price * (1 + sl_pct), 8)
            tp_levels = [
                round(price * (1 - tp_pct), 8),
                round(price * (1 - tp_pct * 2), 8),
                round(price * (1 - tp_pct * 3), 8),
            ]

        pos = Position(
            symbol=symbol, side=side, qty=qty,
            entry_price=price, current_price=price,
            stop_loss=sl,
            take_profit=tp_levels[0],
            take_profit_levels=tp_levels,
            tp_hit_count=0,
            value_usd=round(qty * price, 4),
            reason=f"Manuel işlem ({side.upper()} {leverage}x)",
            ai_summary=f"Manuel olarak açıldı. {side.upper()} @ ${price:.4f} | {leverage}x kaldıraç",
            indicators_at_open=market,
        )
        # Store leverage in indicators for display
        pos.indicators_at_open["leverage"] = leverage
        await shared_state.open_position(pos)
        shared_state._log("TRADE", f"🖐 Manuel {side.upper()} {symbol} @ ${price:.4f} | {leverage}x")
        return {"ok": True, "action": "opened", "symbol": symbol, "side": side, "price": price, "qty": qty, "sl": sl, "tp": tp_levels}

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

    logger.info(f"🚀 Aurora AI Hedge Fund v3 başlatılıyor...")
    logger.info(f"🌐 PORT={PORT} (env: {os.getenv('PORT', 'YOK — varsayılan 8000')})")

    agent_thread = threading.Thread(target=run_agents, name="AgentThread", daemon=True)
    agent_thread.start()
    logger.info("✅ Agent thread başlatıldı")

    app = create_app()

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        log_level="info",
        proxy_headers=True,
        forwarded_allow_ips="*",
        access_log=True,
    )

    shutdown_event.set()
    agent_thread.join(timeout=10)
    logger.info("✅ Kapatma tamamlandı.")
