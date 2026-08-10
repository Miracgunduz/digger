/**
 * Firsat Avcisi - Telegram webhook -> GitHub Actions dispatcher.
 *
 * Cloudflare Worker (ucretsiz katman). Telegram'dan gelen her mesaji
 * aninda karsilar; /help ve /start'i direkt yanitlar, diger komutlari
 * (/tara, /trendler, /rakipbul, /maliyet) GitHub Actions'ta dispatch_command.yml
 * workflow'unu workflow_dispatch ile tetikleyerek calistirir (agir islem -
 * Reddit taramasi + Gemini analizi - GitHub'in sinirsiz outbound agina
 * sahip runner'inda yapilir, Worker sadece yonlendirir).
 *
 * Gerekli ortam degiskenleri (Cloudflare dashboard -> Settings -> Variables):
 *   TELEGRAM_BOT_TOKEN   - Telegram bot token'i
 *   TELEGRAM_CHAT_ID     - izinli tek kullanicinin chat id'si
 *   WEBHOOK_SECRET        - setWebhook'ta secret_token olarak verilen deger
 *   GH_PAT                 - digger reposuna Actions:write izni olan fine-grained PAT
 *   GH_REPO                 - "Miracgunduz/digger"
 *   GH_WORKFLOW_FILE         - "dispatch_command.yml"
 */

const HELP_TEXT =
  "🤖 *Fırsat Avcısı Bot*\n\n" +
  "Kullanılabilir komutlar:\n" +
  "/tara veya /scan — şimdi anlık tarama başlat\n" +
  "/rakipbul <fikir> — verilen fikir için rakip ve pazar boşluğu analizi yap\n" +
  "  örnek: /rakipbul Notion benzeri sade not alma uygulaması\n" +
  "/maliyet <fikir> — verilen fikir için altyapı maliyeti ve minimum abonelik ücreti hesapla\n" +
  "  örnek: /maliyet Notion benzeri sade not alma uygulaması\n" +
  "/trendler — son 1 haftanın şikayet/fırsat taramasını yap\n" +
  "/help — bu mesajı göster\n\n" +
  "Otomatik bültenler her gün 09:00 ve 21:00'de kendiliğinden gönderilir.";

const SCAN_COMMANDS = new Set(["/tara", "/scan"]);
const COMPETITOR_COMMANDS = new Set(["/rakipbul"]);
const COST_COMMANDS = new Set(["/maliyet"]);
const TREND_COMMANDS = new Set(["/trendler"]);
const HELP_COMMANDS = new Set(["/start", "/help"]);

function parseCommand(text) {
  const trimmed = text.trim();
  const spaceIdx = trimmed.indexOf(" ");
  const rawCommand = spaceIdx === -1 ? trimmed : trimmed.slice(0, spaceIdx);
  const argument = spaceIdx === -1 ? "" : trimmed.slice(spaceIdx + 1).trim();
  const command = rawCommand.split("@")[0].toLowerCase();
  return { command, argument };
}

async function sendTelegramMessage(env, chatId, text) {
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`;
  await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId,
      text,
      parse_mode: "Markdown",
      disable_web_page_preview: true,
    }),
  });
}

async function triggerWorkflow(env, command, argument) {
  const url = `https://api.github.com/repos/${env.GH_REPO}/actions/workflows/${env.GH_WORKFLOW_FILE}/dispatches`;
  const resp = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GH_PAT}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "firsat-avcisi-worker",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      ref: "master",
      inputs: { command, argument: argument || "" },
    }),
  });
  return resp;
}

async function handleUpdate(update, env) {
  const message = update.message || update.edited_message;
  if (!message || !message.text) return;

  const chatId = String(message.chat && message.chat.id);
  if (chatId !== String(env.TELEGRAM_CHAT_ID)) {
    return; // yetkisiz chat, sessizce yoksay
  }

  const text = message.text;
  if (!text.startsWith("/")) return;

  const { command, argument } = parseCommand(text);

  if (HELP_COMMANDS.has(command)) {
    await sendTelegramMessage(env, chatId, HELP_TEXT);
    return;
  }

  if (SCAN_COMMANDS.has(command)) {
    await sendTelegramMessage(env, chatId, "⏳ Tarama başlatıldı, Reddit hız sınırı nedeniyle ~15-20 dakika sürebilir.");
    const resp = await triggerWorkflow(env, "tara", "");
    if (!resp.ok) {
      await sendTelegramMessage(env, chatId, `❌ Tarama tetiklenemedi (GitHub yanıtı: ${resp.status}).`);
    }
    return;
  }

  if (TREND_COMMANDS.has(command)) {
    await sendTelegramMessage(env, chatId, "⏳ Haftalık şikayet/fırsat taraması başlatıldı, ~15-20 dakika sürebilir.");
    const resp = await triggerWorkflow(env, "trendler", "");
    if (!resp.ok) {
      await sendTelegramMessage(env, chatId, `❌ Tarama tetiklenemedi (GitHub yanıtı: ${resp.status}).`);
    }
    return;
  }

  if (COMPETITOR_COMMANDS.has(command)) {
    if (!argument) {
      await sendTelegramMessage(
        env,
        chatId,
        "⚠️ Kullanım: /rakipbul <fikir veya proje adı>\nÖrnek: /rakipbul Notion benzeri sade not alma uygulaması"
      );
      return;
    }
    await sendTelegramMessage(env, chatId, "🔍 Rakip analizi yapılıyor, birazdan sonuç gelecek...");
    const resp = await triggerWorkflow(env, "rakipbul", argument);
    if (!resp.ok) {
      await sendTelegramMessage(env, chatId, `❌ Analiz tetiklenemedi (GitHub yanıtı: ${resp.status}).`);
    }
    return;
  }

  if (COST_COMMANDS.has(command)) {
    if (!argument) {
      await sendTelegramMessage(
        env,
        chatId,
        "⚠️ Kullanım: /maliyet <fikir veya proje adı>\nÖrnek: /maliyet Notion benzeri sade not alma uygulaması"
      );
      return;
    }
    await sendTelegramMessage(env, chatId, "💸 Maliyet analizi yapılıyor, birazdan sonuç gelecek...");
    const resp = await triggerWorkflow(env, "maliyet", argument);
    if (!resp.ok) {
      await sendTelegramMessage(env, chatId, `❌ Analiz tetiklenemedi (GitHub yanıtı: ${resp.status}).`);
    }
    return;
  }

  // Bilinmeyen komut: sessizce yoksay
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("OK", { status: 200 });
    }

    const secretHeader = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
    if (secretHeader !== env.WEBHOOK_SECRET) {
      return new Response("Forbidden", { status: 403 });
    }

    let update;
    try {
      update = await request.json();
    } catch (err) {
      return new Response("Bad Request", { status: 400 });
    }

    try {
      await handleUpdate(update, env);
    } catch (err) {
      // Hata olsa da Telegram'a 200 donuyoruz ki webhook'u sonsuz tekrar denemesin;
      // hata detayi Cloudflare Worker loglarinda gorulebilir.
      console.error("handleUpdate hatasi:", err);
    }

    return new Response("OK", { status: 200 });
  },
};
