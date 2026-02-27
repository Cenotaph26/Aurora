# 🚀 Aurora AI Hedge Fund — Railway Production Edition

**7/24 çalışan, pekiştirmeli öğrenme destekli kripto ticaret ajanı.**

---

## 🏗️ Mimari

```
┌─────────────────────────────────────────────────┐
│              Aurora AI Hedge Fund               │
├──────────────┬──────────────┬───────────────────┤
│ MarketAgent  │StrategySwarm │  RLMetaAgent       │
│ CoinGecko    │ RSI+MACD+BB  │  Q-Learning        │
│ RSI/MACD/BB  │ Composite    │  ε-greedy          │
│ hesaplar     │ Vote         │  Ağırlık günceller  │
└──────┬───────┴──────┬───────┴────────────────────┘
       │              │
       ▼              ▼
┌─────────────────────────┐    ┌───────────────────┐
│    ExecutionAgent       │    │  FastAPI Dashboard │
│  Paper / Binance Live   │    │  /status /market   │
│  Stop-Loss / Take-Profit│    │  /signals /metrics │
└─────────────────────────┘    └───────────────────┘
```

### Ajanlar

| Ajan | Görev | Varsayılan Aralık |
|------|-------|-------------------|
| **MarketAgent** | CoinGecko'dan fiyat çeker, RSI/MACD/Bollinger hesaplar | 15s |
| **StrategyAgent** | 3 strateji + composite vote ile sinyal üretir | 20s |
| **RLMetaAgent** | Q-learning ile strateji ağırlıklarını günceller | 60s |
| **ExecutionAgent** | Sinyallere göre emir verir, SL/TP takip eder | 10s |
| **Dashboard** | FastAPI REST API + HTML panel | sürekli |

---

## 🚂 Railway'e Deploy Etme

### 1. Repo Oluştur

```bash
cd aurora_production
git init
git add .
git commit -m "Aurora AI v2 - Railway production"
```

### 2. Railway'e Bağla

1. [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub**
2. Repoyu seç
3. Railway otomatik `railway.toml`'u okur ve yapılandırır

### 3. Ortam Değişkenlerini Ayarla

Railway Dashboard → **Variables** bölümüne `.env.example`'daki değişkenleri ekle.

**Minimum zorunlu:**
```
PORT=8000          # Railway otomatik sağlar
PAPER_TRADING=true # Güvenli başlangıç için
```

### 4. Deploy

```bash
railway up
# veya GitHub push yeterli
```

### 5. Public URL

Railway → **Settings** → **Networking** → **Generate Domain**

`https://your-app.up.railway.app` adresinden panele erişin.

---

## 🔌 API Endpointleri

| Endpoint | Açıklama |
|----------|----------|
| `GET /` | HTML Dashboard |
| `GET /health` | Railway health probe |
| `GET /status` | Sistem özeti |
| `GET /market` | Anlık piyasa verisi + indikatörler |
| `GET /signals` | Son 20 sinyal |
| `GET /positions` | Açık pozisyonlar |
| `GET /metrics` | RL metrikleri |
| `GET /performance` | PnL performansı |
| `GET /docs` | Swagger UI |

---

## 💰 Gerçek Trading (Binance)

> ⚠️ **Risk uyarısı:** Gerçek para kaybedebilirsiniz. Test edin.

1. `PAPER_TRADING=false` yap
2. Binance API anahtarlarını ekle:
   ```
   BINANCE_API_KEY=xxx
   BINANCE_API_SECRET=yyy
   ```
3. Risk parametrelerini ayarla:
   ```
   PORTFOLIO_USD=500    # Toplam bütçe
   RISK_PCT=0.01        # İşlem başına %1
   STOP_LOSS_PCT=0.02   # %2 stop-loss
   TAKE_PROFIT_PCT=0.04 # %4 take-profit
   ```

---

## 📊 Strateji Mantığı

### RSI Mean Reversion
- RSI < 30 → BUY sinyali (güven = 0.5 + (30-RSI)/100)
- RSI > 70 → SELL sinyali

### MACD Momentum  
- MACD > Signal + yukarı trend → BUY
- MACD < Signal + aşağı trend → SELL

### Bollinger Breakout
- Fiyat < Alt bant → BUY
- Fiyat > Üst bant → SELL

### Composite Vote
3 strateji ağırlıklı oy verir. Minimum güven eşiğini (`MIN_CONFIDENCE`) geçen sinyaller işleme alınır.

---

## 🤖 RL Meta Agent

Q-learning algoritması strateji ağırlıklarını sürekli günceller:

```
Q(s,a) ← Q(s,a) + α[r + γ·max Q(s',a') - Q(s,a)]
```

- **α (alpha):** Öğrenme oranı (varsayılan: 0.1)
- **γ (gamma):** İndirim faktörü (varsayılan: 0.95)  
- **ε (epsilon):** Keşif oranı, zamanla azalır (0.15 → 0.01)

---

## 📁 Proje Yapısı

```
aurora_production/
├── main.py                 # Giriş noktası
├── railway.toml            # Railway yapılandırması
├── Procfile                # Process tanımı
├── requirements.txt        # Python bağımlılıkları
├── .env.example            # Ortam değişkenleri şablonu
├── agents/
│   ├── market_agent.py     # Veri toplama + indikatörler
│   └── strategy_agent.py   # Sinyal üretimi
├── rl_engine/
│   └── meta_agent.py       # Q-learning ağırlık güncelleyici
├── execution/
│   └── executor.py         # Emir uygulama (paper/live)
├── api/
│   └── dashboard.py        # FastAPI REST API
└── utils/
    ├── state.py             # Paylaşılan durum yöneticisi
    └── logger.py            # Yapılandırılmış loglama
```
