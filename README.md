# 🎯 Fırsat Avcısı (Opportunity Hunter)

Reddit'i günde iki kez tarayıp indie/side-project fikirlerini yapay zekayla analiz eden ve
sonuçları Telegram'a anlık bülten olarak gönderen, tamamen **ücretsiz** altyapı üzerinde
çalışan bir bot.

## Ne yapıyor?

- Belirlenen 10 subreddit'i (`SideProject`, `startups`, `Entrepreneur`, `micro_saas` vb.)
  Reddit'in kimlik doğrulama gerektirmeyen RSS uçlarından tarar.
- Bulduğu gönderileri Google Gemini ile analiz eder; her fikir için özet, mantık gerekçesi,
  teknik zorluk puanı, gereken teknolojiler, rakip analizi ve hedef kitle/monetizasyon
  önerisi çıkarır.
- Sonucu Telegram'a biçimlendirilmiş bir bülten olarak yollar.
- Günde iki kez (09:00 / 21:00) otomatik çalışır; ayrıca Telegram komutlarıyla anlık
  tetiklenebilir.

## Komutlar

| Komut | Açıklama |
|---|---|
| `/tara` | Şimdi anlık tarama başlat |
| `/rakipbul <fikir>` | Verilen fikir için rakip ve pazar boşluğu analizi |
| `/maliyet <fikir>` | İlk 6 aylık altyapı maliyeti + önerilen minimum abonelik ücreti |
| `/trendler` | Son 1 haftanın şikayet/fırsat taraması |
| `/help` | Komut listesi |

## Mimari

Tamamen sunucusuz ve ücretsiz katmanlar üzerine kurulu:

- **GitHub Actions** — zamanlanmış tarama (`schedule`) ve komut çalıştırma
  (`workflow_dispatch`), sınırsız outbound ağ erişimiyle Reddit RSS + Gemini çağrılarını yapar.
- **Cloudflare Workers** — Telegram webhook'unu anında karşılar, `/help` gibi komutları
  doğrudan yanıtlar, ağır işlemleri GitHub Actions'a devreder.
- **Google Gemini (ücretsiz katman)** — fikir analizi, rakip araştırması, maliyet hesabı.
- **Telegram Bot API** — bildirim ve komut arayüzü.

Sürekli çalışan bir sunucu veya polling döngüsü yok; her tetiklenme kendi işini yapıp kapanır.

```
Telegram mesajı → Cloudflare Worker (anlık) → GitHub Actions workflow_dispatch → Reddit RSS + Gemini → Telegram bülteni
```

## Kurulum

1. `requirements.txt` bağımlılıklarını kurun: `pip install -r requirements.txt`
2. `.env.example` dosyasını `.env` olarak kopyalayıp kendi anahtarlarınızı girin
   (`GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `REDDIT_USER_AGENT`).
3. GitHub reposunda aynı değerleri **Settings → Secrets and variables → Actions** altına ekleyin.
4. `worker/telegram-webhook.js` dosyasını Cloudflare Workers'a deploy edip gerekli ortam
   değişkenlerini (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `WEBHOOK_SECRET`, `GH_PAT`,
   `GH_REPO`, `GH_WORKFLOW_FILE`) tanımlayın.
5. Telegram `setWebhook` çağrısıyla webhook'u Worker'a bağlayın.

## Teknik notlar

- Reddit'in resmi API'si yerine kimlik doğrulama gerektirmeyen `.rss` / `search.rss` uçları
  kullanılır; hız sınırına karşı otomatik backoff/retry uygulanır.
- Gemini yanıtları `response_mime_type: application/json` ile yapılandırılmış JSON olarak alınır.
- Telegram'ın eski Markdown ayrıştırıcısı kırılgan olduğu için gönderim başarısız olursa
  otomatik olarak düz metne düşülür.
