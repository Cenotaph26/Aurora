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
        s = shared_state.get_summary()
        uptime = int(s["uptime_seconds"])
        h, m, sec = uptime // 3600, (uptime % 3600) // 60, uptime % 60
        pnl_color = "#4ade80" if s["total_pnl"] >= 0 else "#f87171"
        agents_rows = "".join(
            f'<tr><td>{n}</td><td style="color:#4ade80">● Aktif</td><td>{ts}</td></tr>'
            for n, ts in s.get("agent_heartbeats", {}).items()
        )
        return f"""<!DOCTYPE html><html><head>
        <title>Aurora AI</title><meta charset="utf-8">
        <meta http-equiv="refresh" content="15">
        <style>
          *{{box-sizing:border-box;margin:0;padding:0}}
          body{{font-family:'Courier New',monospace;background:#0a0f1e;color:#cbd5e1;min-height:100vh;padding:2rem}}
          .container{{max-width:960px;margin:auto}}
          h1{{color:#34d399;font-size:1.6rem;margin-bottom:.25rem}}
          h2{{color:#64748b;font-size:.85rem;text-transform:uppercase;letter-spacing:.1em;margin:1.5rem 0 .5rem}}
          .badge{{display:inline-block;background:#064e3b;color:#34d399;padding:.2rem .6rem;border-radius:9999px;font-size:.7rem;margin-left:.5rem}}
          .grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem;margin:1rem 0}}
          .card{{background:#0f172a;border:1px solid #1e293b;border-radius:.5rem;padding:1rem}}
          .card-label{{color:#64748b;font-size:.7rem;text-transform:uppercase;letter-spacing:.05em}}
          .card-value{{font-size:1.4rem;font-weight:bold;margin-top:.25rem}}
          table{{width:100%;border-collapse:collapse;font-size:.85rem}}
          td,th{{border:1px solid #1e293b;padding:.4rem .75rem;text-align:left}}
          th{{background:#0f172a;color:#475569;font-size:.7rem;text-transform:uppercase}}
          .dim{{color:#334155;font-size:.7rem;margin-top:1.5rem}}
          a{{color:#34d399;text-decoration:none}} a:hover{{text-decoration:underline}}
        </style></head><body><div class="container">
        <h1>🚀 Aurora AI Hedge Fund <span class="badge">● CANLI</span></h1>
        <p class="dim">{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')} — otomatik yenileme: 15s</p>
        <div class="grid">
          <div class="card"><div class="card-label">Çalışma Süresi</div><div class="card-value" style="color:#34d399">{h:02d}:{m:02d}:{sec:02d}</div></div>
          <div class="card"><div class="card-label">Toplam PnL</div><div class="card-value" style="color:{pnl_color}">${s['total_pnl']:+.4f}</div></div>
          <div class="card"><div class="card-label">Kazanma Oranı</div><div class="card-value">{s['win_rate']}%</div></div>
          <div class="card"><div class="card-label">İşlem Sayısı</div><div class="card-value">{s['trade_count']}</div></div>
          <div class="card"><div class="card-label">Açık Pozisyonlar</div><div class="card-value">{s['open_positions']}</div></div>
          <div class="card"><div class="card-label">İzlenen Semboller</div><div class="card-value">{s['market_symbols']}</div></div>
        </div>
        <h2>Ajan Durumları</h2>
        <table><tr><th>Ajan</th><th>Durum</th><th>Son Aktif</th></tr>{agents_rows}</table>
        <p class="dim" style="margin-top:1rem">
          API: <a href="/docs">/docs</a> &nbsp;|&nbsp; <a href="/status">/status</a> &nbsp;|&nbsp;
          <a href="/market">/market</a> &nbsp;|&nbsp; <a href="/signals">/signals</a> &nbsp;|&nbsp;
          <a href="/positions">/positions</a>
        </p>
        </div></body></html>"""

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
