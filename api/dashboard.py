"""
Aurora AI Dashboard - FastAPI REST API

Endpointler:
GET /          - Sağlık kontrolü (Railway için)
GET /status    - Sistem durumu özeti
GET /market    - Anlık piyasa verisi
GET /signals   - Son sinyaller
GET /positions - Açık pozisyonlar
GET /metrics   - RL metrikleri
GET /performance - PnL + performans
"""
import asyncio
import os
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from datetime import datetime

from utils.state import SharedState
from utils.logger import setup_logger

logger = setup_logger("Dashboard")

PORT = int(os.getenv("PORT", "8000"))  # Railway PORT env var'ını kullanır


def create_app(state: SharedState) -> FastAPI:
    app = FastAPI(
        title="Aurora AI Hedge Fund",
        description="7/24 Kripto Ticaret Ajanı API",
        version="2.0.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/", response_class=HTMLResponse)
    async def root():
        summary = state.get_summary()
        uptime = int(summary["uptime_seconds"])
        h, m, s = uptime // 3600, (uptime % 3600) // 60, uptime % 60
        agents_html = "".join(
            f'<tr><td>{name}</td><td style="color:#4ade80">● Aktif</td></tr>'
            for name in summary.get("agent_heartbeats", {})
        )
        return f"""
        <!DOCTYPE html><html><head>
        <title>Aurora AI</title>
        <meta charset="utf-8">
        <style>
          body {{font-family:monospace;background:#0f172a;color:#e2e8f0;padding:2rem}}
          h1 {{color:#6ee7b7}} table {{border-collapse:collapse;width:100%;margin:1rem 0}}
          td,th {{border:1px solid #334155;padding:.5rem 1rem;text-align:left}}
          th {{background:#1e293b;color:#94a3b8}} .stat {{font-size:1.5rem;color:#6ee7b7}}
          .badge {{background:#065f46;color:#6ee7b7;padding:.2rem .6rem;border-radius:9999px;font-size:.75rem}}
        </style>
        </head><body>
        <h1>🚀 Aurora AI Hedge Fund</h1>
        <span class="badge">● CANLI</span>
        <table>
          <tr><th>Metrik</th><th>Değer</th></tr>
          <tr><td>Çalışma Süresi</td><td class="stat">{h:02d}:{m:02d}:{s:02d}</td></tr>
          <tr><td>Toplam PnL</td><td class="stat" style="color:{'#4ade80' if summary['total_pnl']>=0 else '#f87171'}">${summary['total_pnl']:+.4f}</td></tr>
          <tr><td>İşlem Sayısı</td><td>{summary['trade_count']}</td></tr>
          <tr><td>Kazanma Oranı</td><td>{summary['win_rate']}%</td></tr>
          <tr><td>Açık Pozisyonlar</td><td>{summary['open_positions']}</td></tr>
          <tr><td>İzlenen Semboller</td><td>{summary['market_symbols']}</td></tr>
        </table>
        <h2>Ajan Durumları</h2>
        <table><tr><th>Ajan</th><th>Durum</th></tr>{agents_html}</table>
        <p style="color:#475569;font-size:.75rem">API: 
          <a href="/docs" style="color:#6ee7b7">/docs</a> | 
          <a href="/status" style="color:#6ee7b7">/status</a> | 
          <a href="/market" style="color:#6ee7b7">/market</a> |
          <a href="/signals" style="color:#6ee7b7">/signals</a>
        </p>
        </body></html>
        """

    @app.get("/health")
    async def health():
        """Railway health probe"""
        return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

    @app.get("/status")
    async def status():
        return {
            "status": "running",
            **state.get_summary(),
            "rl_metrics": state.rl_metrics,
        }

    @app.get("/market")
    async def market():
        return {"symbols": state.market_data}

    @app.get("/signals")
    async def signals():
        sigs = await state.get_signals()
        return {
            "count": len(sigs),
            "signals": [
                {
                    "symbol": s.symbol,
                    "direction": s.direction,
                    "confidence": s.confidence,
                    "strategy": s.strategy,
                    "timestamp": s.timestamp.isoformat(),
                }
                for s in reversed(sigs[-20:])
            ],
        }

    @app.get("/positions")
    async def positions():
        return {
            "open": [
                {
                    "symbol": p.symbol,
                    "side": p.side,
                    "qty": p.qty,
                    "entry_price": p.entry_price,
                    "current_price": p.current_price,
                    "pnl": round((p.current_price - p.entry_price) * p.qty, 4),
                    "opened_at": p.opened_at.isoformat(),
                }
                for p in state.positions.values()
            ]
        }

    @app.get("/metrics")
    async def metrics():
        return state.rl_metrics

    @app.get("/performance")
    async def performance():
        s = state.get_summary()
        return {
            "total_pnl_usd": s["total_pnl"],
            "trade_count": s["trade_count"],
            "win_rate_pct": s["win_rate"],
            "open_positions": s["open_positions"],
            "sharpe_approx": round(s["total_pnl"] / max(s["trade_count"], 1), 4),
        }

    return app


async def start_dashboard(state: SharedState, shutdown: asyncio.Event):
    app = create_app(state)
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="warning")
    server = uvicorn.Server(config)

    logger.info(f"🌐 Dashboard başlatılıyor → http://0.0.0.0:{PORT}")

    serve_task = asyncio.create_task(server.serve())
    await shutdown.wait()
    server.should_exit = True
    await serve_task
