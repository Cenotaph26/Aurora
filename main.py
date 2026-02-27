"""
Aurora AI Hedge Fund - Production Entry Point

MİMARİ:
- uvicorn (FastAPI) → ana thread'de çalışır → Railway port'u doğru görür
- Tüm ajanlar → ayrı bir thread'de asyncio event loop ile çalışır
- Bu sayede Railway port binding sorunsuz çalışır
"""
import threading
import asyncio
import signal
import os
import time

from agents.market_agent import MarketAgent
from agents.strategy_agent import StrategyAgent
from rl_engine.meta_agent import RLMetaAgent
from execution.executor import ExecutionAgent
from utils.state import SharedState
from utils.logger import setup_logger

logger = setup_logger("main")

# Global state — her iki thread tarafından erişilir
shared_state = SharedState()
shutdown_event = threading.Event()


# ─────────────────────────────────────────────────────────────
#  AJAN THREAD'İ  (arka planda asyncio loop)
# ─────────────────────────────────────────────────────────────

def run_agents():
    """Tüm trading ajanlarını ayrı bir thread'de çalıştır."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    aio_shutdown = asyncio.Event()

    # Ana thread kapanınca asyncio event'i de tetikle
    def monitor_shutdown():
        while not shutdown_event.is_set():
            time.sleep(0.5)
        loop.call_soon_threadsafe(aio_shutdown.set)

    threading.Thread(target=monitor_shutdown, daemon=True).start()

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

        tasks = [
            asyncio.create_task(fn(), name=name)
            for name, fn in RESTART_MAP.items()
        ]
        logger.info("✅ Trading ajanları başlatıldı")

        while not aio_shutdown.is_set():
            done, _ = await asyncio.wait(tasks, timeout=30, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task.cancelled():
                    continue
                exc = task.exception()
                if exc and task.get_name() in RESTART_MAP:
                    logger.error(f"❌ {task.get_name()} çöktü: {exc}")
                    tasks.remove(task)
                    new = asyncio.create_task(
                        RESTART_MAP[task.get_name()](), name=task.get_name()
                    )
                    tasks.append(new)
                    logger.info(f"♻️  {task.get_name()} yeniden başlatıldı")

        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("✅ Ajanlar durduruldu")

    try:
        loop.run_until_complete(agent_main())
    except Exception as e:
        logger.error(f"Agent thread hatası: {e}", exc_info=True)
    finally:
        loop.close()


# ─────────────────────────────────────────────────────────────
#  ANA THREAD: uvicorn (FastAPI) burada çalışır
# ─────────────────────────────────────────────────────────────

def create_app():
    """FastAPI uygulamasını oluştur — shared_state'i kullanır."""
    import uvicorn
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
        agents_html = "".join(
            f'<tr><td>{name}</td><td style="color:#4ade80">● Aktif</td></tr>'
            for name in s.get("agent_heartbeats", {})
        )
        pnl_color = "#4ade80" if s["total_pnl"] >= 0 else "#f87171"
        return f"""<!DOCTYPE html><html><head>
        <title>Aurora AI</title><meta charset="utf-8">
        <meta http-equiv="refresh" content="30">
        <style>
          body{{font-family:monospace;background:#0f172a;color:#e2e8f0;padding:2rem;max-width:900px;margin:auto}}
          h1{{color:#6ee7b7;margin-bottom:.25rem}} h2{{color:#94a3b8;font-size:1rem;margin-top:1.5rem}}
          table{{border-collapse:collapse;width:100%;margin:.5rem 0}}
          td,th{{border:1px solid #1e293b;padding:.5rem 1rem;text-align:left}}
          th{{background:#1e293b;color:#64748b;font-size:.8rem;text-transform:uppercase}}
          .stat{{font-size:1.4rem;font-weight:bold}} .badge{{background:#064e3b;color:#6ee7b7;padding:.15rem .5rem;border-radius:9999px;font-size:.7rem}}
          a{{color:#6ee7b7}} .dim{{color:#475569;font-size:.75rem}}
        </style></head><body>
        <h1>🚀 Aurora AI Hedge Fund</h1>
        <span class="badge">● CANLI</span> <span class="dim">— {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} — otomatik yenileme: 30s</span>
        <table style="margin-top:1rem">
          <tr><th>Metrik</th><th>Değer</th></tr>
          <tr><td>Çalışma Süresi</td><td class="stat">{h:02d}:{m:02d}:{sec:02d}</td></tr>
          <tr><td>Toplam PnL</td><td class="stat" style="color:{pnl_color}">${s['total_pnl']:+.4f}</td></tr>
          <tr><td>İşlem Sayısı</td><td>{s['trade_count']}</td></tr>
          <tr><td>Kazanma Oranı</td><td>{s['win_rate']}%</td></tr>
          <tr><td>Açık Pozisyonlar</td><td>{s['open_positions']}</td></tr>
          <tr><td>İzlenen Semboller</td><td>{s['market_symbols']}</td></tr>
        </table>
        <h2>Ajan Durumları</h2>
        <table><tr><th>Ajan</th><th>Durum</th></tr>{agents_html}</table>
        <p class="dim">API: <a href="/docs">/docs</a> | <a href="/status">/status</a> | <a href="/market">/market</a> | <a href="/signals">/signals</a> | <a href="/positions">/positions</a></p>
        </body></html>"""

    @app.get("/health")
    def health():
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


def handle_signal(sig, frame):
    logger.warning(f"Signal {sig} alındı, kapatılıyor...")
    shutdown_event.set()


if __name__ == "__main__":
    import uvicorn

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    PORT = int(os.getenv("PORT", "8000"))

    logger.info("🚀 Aurora AI Hedge Fund başlatılıyor...")
    logger.info(f"🌐 Dashboard → http://0.0.0.0:{PORT}")

    # Ajanları arka thread'de başlat
    agent_thread = threading.Thread(target=run_agents, name="AgentThread", daemon=True)
    agent_thread.start()
    logger.info("✅ Agent thread başlatıldı")

    # uvicorn ANA THREAD'DE çalışır — Railway portu böyle görür
    app = create_app()
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        log_level="warning",
        proxy_headers=True,
        forwarded_allow_ips="*",
        access_log=False,
    )

    # uvicorn durduğunda ajanları da durdur
    logger.info("uvicorn durdu, ajanlar kapatılıyor...")
    shutdown_event.set()
    agent_thread.join(timeout=10)
    logger.info("✅ Temiz kapatma tamamlandı.")
