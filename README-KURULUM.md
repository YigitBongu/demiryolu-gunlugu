# 🚆 Demiryolu Günlüğü — Kurulum Rehberi

Her sabah ~06:47'de (Türkiye saati) çalışıp son 24 saatin demiryolu gelişmelerini tarayan ve Türkçe bir bülten üreten sistem. Bülten **iki kanaldan** sunulur:

1. **Web sitesi (ana kanal):** Kendi adresin `https://KULLANICI_ADIN.github.io/demiryolu-gunlugu/` her sabah otomatik güncellenir; altında son 30 günün arşiv linkleri durur.
2. **E-posta (opsiyonel eklenti):** Gmail bilgilerini girersen aynı bülten sabah gelen kutuna da düşer. Girmezsen sistem yine tam çalışır.

**Akış:** Google News (TR + EN + FR sorguları) + sektör siteleri (Railway Gazette, Railway Age, Railway Pro, RT&S, RayHaber) + akademik kaynaklar (arXiv, Crossref) taranır → dil modeli (ücretsiz Gemini) mükerrerleri ayıklayıp Türkçe bülteni yazar → site güncellenir → (varsa) e-posta gönderilir.

**Bülten bölümleri:** Öne Çıkanlar · Türkiye · Dünya · Akademik · İhale & Yatırım · Radar (Yapı Merkezi & frankofon Afrika).

---

## Bölüm A — Site kurulumu (≈20 dakika, çekirdek)

### 1. GitHub deposu oluştur
1. github.com → **New repository** → isim: `demiryolu-gunlugu` → **Public** seç → Create.
   - Neden Public? Ücretsiz GitHub Pages yalnızca public depolarda çalışır. Secret'ların (API anahtarı vb.) her durumda şifreli kalır; sitede yalnızca haber özetleri yayınlanır. Depoyu illa private tutmak istersen Pages çalışmaz; o zaman yalnızca e-posta kanalını (Bölüm B) kullanırsın.
2. Bu klasördeki dosyaları depoya yükle:
   ```bash
   cd demiryolu-gunlugu
   git init
   git add .
   git commit -m "ilk kurulum"
   git branch -M main
   git remote add origin https://github.com/KULLANICI_ADIN/demiryolu-gunlugu.git
   git push -u origin main
   ```
   (Web arayüzünden "Add file → Upload files" ile de olur; `.github/workflows/gunluk-rapor.yml` dosyasının klasör yapısıyla yüklendiğinden emin ol.)

### 2. Özetleme anahtarı al — ÜCRETSİZ (önerilir)
Bültenin düzgün Türkçe özet halinde gelmesi için bir dil modeli anahtarı gerekir. **Google AI Studio bunu kredi kartı istemeden, ücretsiz veriyor** — günde 1.500 istek hakkı var, bizim ihtiyacımız günde 1.
1. https://aistudio.google.com/apikey → Google hesabınla giriş yap → **Create API key**.
2. Kredi kartı sorulmaz, süresi dolmaz. Anahtarı kopyala.
3. Not: Ücretsiz katmanda Google, gönderilen içeriği model eğitiminde kullanabilir. Biz yalnızca kamuya açık haber başlıkları gönderdiğimiz için bu bir sorun değil.

*(Alternatif — istersen:* Anthropic API anahtarı da kullanabilirsin; kalitesi benzer, maliyeti ~1 $/ay. `ANTHROPIC_API_KEY` secret'ı olarak eklemen yeterli. Hiç anahtar eklemezsen sistem yine çalışır ama özet yerine ham başlık listesi üretir.)

### 3. Secret'ı tanımla
Depoda: **Settings → Secrets and variables → Actions → New repository secret**
- `GEMINI_API_KEY` = 2. adımdaki ücretsiz anahtar

### 4. İlk çalıştırma (test)
1. **Actions** sekmesi → soldan **Demiryolu Günlüğü** → sağda **Run workflow** → Run.
2. 1-2 dakikada iş yeşile döner; depoda `docs/` klasörü ve içinde `index.html` oluşur.

### 5. Pages'i aç
1. **Settings → Pages → Build and deployment → Source: "Deploy from a branch"** → Branch: `main`, klasör: `/docs` → **Save**.
2. 1-2 dakika sonra siten yayında: `https://KULLANICI_ADIN.github.io/demiryolu-gunlugu/`

### 6. Telefona sabitle
Siteyi telefonda aç → tarayıcı menüsü → **Ana Ekrana Ekle**. Sabah tek dokunuşla bülten.

Bu kadar. Artık her sabah ~06:47'de site kendiliğinden yenilenir.

---

## Bölüm B — Sabah e-postası (opsiyonel, +5 dakika)

Siteyi açmayı unutmak mümkün; gelen kutusu ise alışkanlık istemez. İstediğin an ekleyebilirsin:

1. Google hesabında **2 Adımlı Doğrulama** açık olmalı (Google Hesabı → Güvenlik).
2. https://myaccount.google.com/apppasswords → uygulama adı `demiryolu` → **Oluştur** → 16 haneli şifreyi kopyala. (Bu, normal Gmail şifren **değildir**; sadece bu bot içindir, istediğin an iptal edebilirsin.)
3. Depoya iki secret daha ekle:
   - `GMAIL_ADDRESS` = Gmail adresin
   - `GMAIL_APP_PASSWORD` = 16 haneli şifre (boşluksuz)
   - `DIGEST_TO` = farklı bir alıcı istersen (opsiyonel)
4. Ertesi sabahtan itibaren bülten ayrıca maille gelir. İlk e-posta spam klasörüne düşebilir → "Spam değil" işaretle.

---

## Ayarlar ve kişiselleştirme

**Saati değiştirmek:** `.github/workflows/gunluk-rapor.yml` içindeki cron satırı UTC'dir (Türkiye saati − 3). Örn. 08:00 TRT için: `"0 5 * * *"`. GitHub zamanlanmış işleri ±15-30 dk kaydırabilir.

**Sorguları/kaynakları değiştirmek:** `railway_digest.py` en üstündeki `FEEDS` listesi. Yeni Google News sorgusu eklemek tek satırdır; herhangi bir RSS adresi de eklenebilir. Bozuk feed sistemi durdurmaz, sessizce atlanır.

**Bülten üslubunu değiştirmek:** `PROMPT_SABLONU` değişkeni. "Daha kısa yaz", "P1/P2 kuvvetleri gibi konuları önceliklendir" tarzı talimatları doğrudan buraya yaz.

**Model değiştirmek:** `GEMINI_MODEL` (ücretsiz) veya `CLAUDE_MODEL` satırı. Ücretsiz yolda daha güçlü model istersen `gemini-2.5-pro` deneyebilirsin (ücretsiz katmanda günlük limiti düşüktür ama bizim 1 istek/güne fazlasıyla yeter).

---

## Bilinen sınırlar (dürüst liste)

- **Site herkese açıktır.** Adresi bilen görebilir (arama motorlarına özellikle tanıtılmaz ama gizli de değildir). İçerik kamuya açık haber özetlerinden ibaret olduğu için pratikte sorun değildir; rahatsız edici gelirse e-posta kanalı + private repo kombinasyonuna geçilebilir.
- **EKAP entegrasyonu yok.** Türk kamu ihaleleri EKAP'tan doğrudan çekilmiyor. Pratikte RayHaber'in ihale bültenleri ve Google News ihale sorgusu büyük ihaleleri yakalar. EKAP kazıyıcı istersen Faz 2 işidir.
- **Dakik değil.** GitHub zamanlayıcısı yoğun saatlerde 15-30 dk gecikebilir.
- **60 gün kuralı.** GitHub, 60 gün hareketsiz depolarda zamanlanmış işleri durdurur. Sistem her gün commit attığı için pratikte yaşanmaz; yine de GitHub'dan uyarı maili gelirse içindeki butona bas.
- **Ücretli duvar.** Paywall arkasındaki içeriğin yalnızca başlık/özeti gelir.

## Sorun giderme

- **Site 404 veriyor:** Önce workflow'u en az bir kez çalıştırıp `docs/` klasörünün oluştuğundan emin ol; sonra Settings → Pages ayarını (main + /docs) kontrol et. İlk yayın 1-2 dk sürebilir.
- **İş kırmızı:** Actions logunda "Bülteni üret ve gönder" adımını aç; hata Türkçe yazar. `Username and Password not accepted` → uygulama şifresi yanlış (boşluksuz yapıştır).
- **İş yeşil ama site eskisini gösteriyor:** Tarayıcı önbelleği; sayfayı yenile. Logda "Yeni kayıt yok" yazıyorsa o gün gerçekten yeni içerik bulunamamıştır (nadir).
- **Bülten şişkin/alakasız:** `FEEDS` ve `PROMPT_SABLONU`'nu birlikte kalibre edelim — ilk haftadan sonra bir tur ayar normaldir.
