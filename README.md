# 🚀 Aurora AI Hedge Fund — Railway Production Edition

---

## ⚡ HIZLI BAŞLANGIÇ (3 adım)

### Adım 1 — GitHub'a yükle
```bash
git init && git add . && git commit -m "aurora v2"
git remote add origin https://github.com/KULLANICI/aurora.git
git push -u origin main
```

### Adım 2 — Railway'e deploy et
1. [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub Repo**
2. Repoyu seç → otomatik build başlar

### Adım 3 — ⚠️ KRİTİK: Port ayarını yap
Railway dashboard'da:
1. **Aurora** servisine tıkla
2. **Settings** sekmesi → **Networking** bölümü
3. **"Generate Domain"** butonuna tıkla  
   *(Zaten domain varsa bu adımı atla)*
4. **"Add Port"** veya **"Expose Port"** → `8000` gir
5. **Save** → birkaç saniye bekle → URL'yi aç

> **Not:** Railway bazen portu otomatik algılar, bazen algılamaz.
> Deploy loglarında `PORT=8000` yazıyorsa port doğru okunuyor demektir.

---

## 🔧 Ortam Değişkenleri

Railway Dashboard → **Variables** bölümüne ekle:

| Değişken | Varsayılan | Açıklama |
|----------|-----------|----------|
| `PAPER_TRADING` | `true` | `false` yapma — önce test et |
| `WATCH_SYMBOLS` | `bitcoin,ethereum,...` | İzlenecek coinler |
| `MIN_CONFIDENCE` | `0.55` | Sinyal güven eşiği |
| `PORTFOLIO_USD` | `1000` | Toplam bütçe ($) |
| `RISK_PCT` | `0.02` | İşlem başına risk (%2) |
| `STOP_LOSS_PCT` | `0.03` | Stop-loss (%3) |
| `TAKE_PROFIT_PCT` | `0.06` | Take-profit (%6) |
| `BINANCE_API_KEY` | *(boş)* | Gerçek trading için |
| `BINANCE_API_SECRET` | *(boş)* | Gerçek trading için |

---

## 📡 API Endpointleri

| Endpoint | Açıklama |
|----------|----------|
| `GET /` | HTML Dashboard (15s auto-refresh) |
| `GET /health` | Railway health probe → `{"status":"ok"}` |
| `GET /status` | Sistem özeti |
| `GET /market` | Anlık fiyat + RSI/MACD/BB |
| `GET /signals` | Son 20 sinyal |
| `GET /positions` | Açık pozisyonlar |
| `GET /metrics` | RL agent metrikleri |
| `GET /performance` | PnL özeti |
| `GET /docs` | Swagger UI |

---

## 🏗️ Mimari

```
main thread                     daemon thread
──────────────────────────      ──────────────────────────────
uvicorn (FastAPI)               asyncio event loop
  GET /health   ✅ Railway        MarketAgent  (15s)
  GET /         📊 Dashboard      StrategyAgent (20s)
  GET /market   📈 Fiyatlar       RLMetaAgent   (60s)
  GET /signals  📡 Sinyaller      ExecutionAgent (10s)
        │                                │
        └──────── SharedState ───────────┘
                  (threading.Lock)
```

---

## 🐛 Sorun Giderme

**404 Not Found:**
→ Railway Settings → Networking → Port `8000` ekle

**Healthcheck Failed:**  
→ Deploy loglarında `PORT=` değerini kontrol et  
→ `PORT` değişkenini Railway Variables'a manuel ekle: `PORT=8000`

**Uygulama çalışıyor ama veri gelmiyor:**  
→ CoinGecko rate limit — `MARKET_INTERVAL=30` yap
