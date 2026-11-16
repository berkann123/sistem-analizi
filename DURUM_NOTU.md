# Durum notu — 17 Ekim 2026

Yeni bir konuşmada devam ederken: "DURUM_NOTU.md'yi oku" de. Önce bu dosya, sonra `README.md` (mimari, kurallar,
komutlar) okunur. Proje haritası (Claude Docs): https://claude.ai/code/artifact/af5be7d6-75c9-43a0-8bb9-6115465b0365

## Durum: yaklaşık %90 hazır, proje sunuma kadar beklemede

Proje 17.10.2026'da kenara alındı; sunum yaklaşık iki ay sonra (Aralık 2026 ortası). İki ana hedef tamam:

- **Bir oda-gecenin maliyeti:** değişken maliyet (kahvaltı, oda paketi, tekstil, enerjinin değişken kısmı) + ortak
  gider payı (personel, kira, amortisman, enerji tabanı; oda tipi katsayısıyla) ÷ normal doluluk (son 12 biten ayın
  ortalaması, bugün %65,5; TMS 2 md. 13 mantığı, yöntem olarak). Atıl kapasite iki ölçüyle ayrı raporlanır.
- **Dinamik fiyatlandırma:** gece fiyatı = temel fiyat (oda tipi × mevsim) × gecenin etkisi (etkinlik / hafta günü /
  otel fiyat kararı) × anlık doluluk etkisi. Konaklamaya erken rezervasyon ve süre indirimi; KDV, konaklama vergisi,
  kanal komisyonu ayrı. Her gece ve her rezervasyon 4 renkle değerlendirilir (hedefte / kârlı / katkı / zarar) ve
  sebebi düz cümleyle yazar.

Eksik olan kod değil, sunum hazırlığı (aşağıdaki liste).

## Bilgisayarda çalıştırma

cmd'de proje klasöründe (önce phpMyAdmin'den iki veritabanını Dışa aktar ile yedekle):

```
.venv\Scripts\python.exe manage.py veritabanlarini_kur
.venv\Scripts\python.exe manage.py test
.venv\Scripts\python.exe manage.py runserver
```

Beklenen: `test` 105 test OK. Tarayıcı: http://127.0.0.1:8000/ . `.venv` başka klasöre taşınırsa bozulur; yeni
klasörde yeniden kurulur: `python -m venv .venv` ve `.venv\Scripts\python.exe -m pip install -r requirements.txt`.
`.env` dosyası (veritabanı şifreleri) proje klasöründe olmalı; paylaşılmaz.

## Son yapılanlar (16–17 Ekim 2026)

- v36: sol menülü yeni yerleşim, otelin logosu (`static/img/pasaport-pier-logo.png`), "Veri girişi" → "Admin paneli".
- v37: oda maliyeti ayın beklenen doluluğuyla değil NORMAL dolulukla (boş odaların bedeli fiyata binmez);
  "Başabaşın altında" → "Katkı sağlıyor (zarar değil)", "Zararına" → "Zarar: satılmamalı".
- v38–39: etkinlik türü "Otel fiyat kararı" (otomatik kuralın yerine geçer, açıklaması zorunlu); takvimde
  açıklamalı geceler. Örnek kararlar Ekim ve Kasım 2026'da (migration 0027, 0028).
- v40–41: doluluk etkisi (ANLIK doluluk: o gece için satılmış oda ÷ aktif oda; tahmin yok), erken rezervasyon ve
  konaklama süresi indirimi; "Rezervasyon fiyatı" ekranı (gece gece fiyat, indirimler, vergiler, maliyet, kâr).
- v42: fiyat takviminde her gün büyük bir kartta bütün metrikler.
- v43: rezervasyon ekranından "beklenen doluluk" alanı kaldırıldı (iç politika, müşteriye gösterilmez).
- v44: "Rezervasyonlar" ekranı; fiyat kararında "Yayında" alanı (taslak karar rezervasyona uygulanmaz, migration
  0029); `ileri_rezervasyonlar` komutu (Yılbaşı gala +%80 ve 7–10 Aralık fırtına haftası −%85 kararları, 21
  rezervasyon, 31.01.2027'ye kadar bütün rezervasyonları kurallarla yeniden fiyatlar).
- v45: kâr ve renk kanal komisyonu düşülmüş tutara göre (Rezervasyon fiyatı ekranına kanal seçimi); Maliyet
  analizinde iki atıl kapasite ölçüsü (%100'e göre ve normal kapasiteye göre); fiyat kuralları Admin › Fiyat
  kuralları ekranından değişir (`fiyat_kurallari` tek satırlık tablo, migration 0030). Toplam 23 iş tablosu.

## Sadeleştirme (26 Ekim 2026, v46)

- Sol menü: "Ana Sayfa", hemen altında "Rezervasyon" (eski "Rezervasyon yap"); başlıkların üstündeki küçük üst yazılar kaldırıldı.
- Bütün ekranlarda tekrar eden açıklama paragrafları, kartlar ve tablolar kaldırıldı. Fiyat takvimi: gün kartı tarih, fiyat,
  durum, etki, doluluk ve kârdan ibaret; kanal, etkinlik listesi, oda tipi karşılaştırması ve "nasıl hesaplanıyor" çıktı.
  Rezervasyon ekranında maliyet ayrıntısı artık tam maliyetle aynı esasta (ortak gider normal dolulukla).
- Veritabanı denetimi: birebir tekrar eden satır, doğal anahtar tekrarı ve aynı oda/gece çakışması yok; saklanan stok
  hareketlerle tutarlı. Tekrar eden iki kolon kaldırıldı (migration 0031): `envanter_urunleri.urun_tipi` (kategoriyi
  tekrarlıyordu), `oda_tipleri.temel_kapasite` (her tipte 2, hiçbir hesapta kullanılmıyordu). Öncesi yedek:
  `_yedek/v46_sadelestirme_oncesi.tar.gz` ve `_yedek/pasaport_otel_v46_oncesi.sql`.

## Dönem kapanışı kaldırıldı (26 Ekim 2026, v47)

- Kullanıcı kararıyla `donem_kapanislari`, `donem_giderleri`, `donem_maliyetleri` tabloları kaldırıldı (migration 0032);
  otomatik kapanış, `donemi_kapat` komutu, Admin › Dönem kapanışları ve "Kapandı" etiketleri de çıktı. Otel veritabanı:
  20 iş tablosu.
- Kaldırmadan önce karşılaştırıldı: 9 kapanmış ayın doluluk, gelir, komisyon, sonuç ve oda maliyetleri güncel hesapla
  birebir aynıydı; bugünkü hiçbir rakam değişmedi.
- Bedeli: geçmiş aylar artık donmuyor; gider ya da ürün fiyatı değişirse geçmiş ayın maliyeti de değişir.
- Yedek: `_yedek/v47_donem_kapanisi_kaldirma_oncesi.tar.gz`, `_yedek/pasaport_otel_v47_oncesi.sql`. Test sayısı 102.

## Sade dönem kapanışı (26 Ekim 2026, v48)

- Kullanıcı kararı: kapanış geri geldi ama sade. Üç tablo yerine iki tablo (migration 0033): `donem_kapanislari`
  (ay başına 1 satır, 10 kolon) ve `donem_maliyetleri` (oda tipi × kişi, 6 kolon: değişken maliyet + ortak gider payı).
  `donem_giderleri` geri gelmedi: gider kayıtları zaten aya göre tarihli.
- Otomatik: biten ay sonraki ayın 5. gününden sonra ilk açılan ekranda kapanır. Yeni ekran: Maliyet › Dönem kapanışları
  (Yeniden kapat butonu). Kapanmış ayda Satış ve kârlılık, Maliyet analizi, doluluk ve fiyat takvimi o ayın değerlerini kullanır.
- Ocak–Eylül 2026 kapatıldı: değerler eski kapanış yedeğiyle (v47 öncesi) birebir aynı. Test sayısı 105.
- Yedek: `_yedek/v48_sade_kapanis_oncesi.tar.gz`, `_yedek/pasaport_otel_v48_oncesi.sql`.

## İyileştirme dönemi (12 Kasım 2026)

- Bilgisayarda `.venv` yoktu; Python 3.12 ile yeniden kuruldu. Kurulum öncesi SQL yedeği:
  `_yedek/pasaport_kurulum_oncesi_2026-11-12.sql`. Ekim 2026 otomatik kapandı.
- v49: Ana Sayfa genel özet oldu: Maliyet, Fiyat ve satış, Stok kartları; tıklanınca ilgili ekran açılır
  (`services.home_summary`). Test sayısı 106. Yedek: `_yedek/v49_ana_sayfa_oncesi.tar.gz`.
- v50: Maliyet analizi özeti kartlara döndü: ortak gider geniş kartta gruplara dağılımıyla (personel, bina, enerji...)
  ve düz açıklamayla; doluluk, boş odaların payı, olağan dışı boşluk maliyeti ayrı kartlarda. Örnek oda başlığı
  "en ucuz tip" olduğunu ve kapanmış ayda kalem kırılımı olmadığını söyler. Yedek: `_yedek/v50_maliyet_kartlari_oncesi.tar.gz`.
- v51 (kullanıcı kararı): Maliyet analizi tablosu ve örnek oda da ortak gider payını NORMAL doluluğa böler (önceden
  ayın gerçek doluluğuna bölüyordu). Bütün ekranlar aynı esasta: Ekim Standart 2 kişi 3.826 ₺ (eskiden 3.846);
  Kasım %31 dolulukta 3.921 ₺ (eski hesapla ~7.900 olurdu). Test 107. Yedek: `_yedek/v51_normal_doluluk_tablo_oncesi.tar.gz`.
- v52: Maliyet analizindeki "Örnek oda" bölümü "Bir oda bir gece otele kaça mal oluyor?" kartlarına döndü: oda tipi
  seçimi (`?oda=KOD`, varsayılan en ucuz tip), toplam maliyet kartında zarar / katkı / kâr sınırları, "Misafir gelince
  harcanan" (açık ayda kalem listesi) ve "Otelin sabit giderlerinden düşen pay" kartları. Test 108.
  Yedek: `_yedek/v52_ornek_oda_kartlari_oncesi.tar.gz`.
- v53: Örnek oda kartlarına açılır "Nasıl hesaplandı?" bölümleri: misafir gideri (odaya / kişiye bağlı kısım, açık ayda;
  1 kişi + ek kişi her ayda) ve sabit gider payı (aylık tutar ÷ oda-gece kapasitesi × oda tipi katsayısı ÷ normal
  doluluk). Yedek: `_yedek/v53_nasil_hesaplandi_oncesi.tar.gz`.
- v54 (kullanıcı kararı, "hepsini düzelt"): ortak gider hesabı denetlendi ve dört düzeltme yapıldı.
  1. Gece payı YILLIK esas: aylık tutar ÷ (oda × 365/12 gün). Şubat gecesi artık Mart'tan pahalı değil (ikisi de
     Standart 1.963 ₺/müsait gece). `average_month_days`.
  2. Her oda tipi KENDİ normal doluluğuyla (son 12 ay): Standart %70,4 … Executive Oda %56,0. `type_normal_occupancy`.
     Ekim Standart 2 kişi 3.826 → 3.677 ₺; Executive Suite 8.514 → 9.646 ₺.
  3. Olağan dışı boşluk ay ay değil 12 ayda: her ay "sabit giderin satışla karşılanması" farkı (kış −, yaz +);
     12 ayın net eksiği olağan dışı boşluktur. 11.2025–10.2026: eksik 5,67 M, fazla 6,24 M, net +0,57 M → yok.
     `month_absorption`, `absorption_window`. Aylık tablo sütunu "Sabit giderin karşılanma farkı".
  4. Gider kayıtları 2025'e uzatıldı (migration 0034: başlangıç ayları bir yıl geri; kapanmış ayların payı yıllık
     esasa çevrildi). 2025'in 12 ayı kapandı: gelir 72,8 M, sonuç −4,57 M (2025 fiyatları simülasyonda %80).
  Rezervasyon renkleri: hedefte 2, kârlı 35, katkı 124, zarar 4 (önce 3/32/126/4). Test 110.
  Yedek: `_yedek/v54_ortak_gider_duzeltme_oncesi.tar.gz`, `_yedek/pasaport_otel_v54_oncesi.sql`.
- v55 (kullanıcı kararı): Executive Suite 4 kişilik (migration 0035). 4 kişilik oda paketi 2 kişilikten türetildi
  (iki çift kişilik yatak: çift çarşaf, çift nevresim, alez, yorgan 2'şer; 35 kalem). Kapanmış 22 aya EXS 4 kişi
  satırı eklendi (`complete_closed_costs`, `auto_close_months` her açılışta eksik birleşimi tamamlar; sabit pay aynı
  tipin dondurulmuş payı). Ekim EXS 4 kişi: değişken 1.936 ₺, toplam 10.501 ₺. Fiyat: temel + 2 × ek kişi ücreti.
  Test 111. Yedek: `_yedek/v55_exs_4_kisi_oncesi.tar.gz`, `_yedek/pasaport_otel_v55_oncesi.sql`.
- v56: Maliyet analizi aylık özet tablosu (varsayılan açık): "Oda geliri" ve "Ayın sonucu" (gelir − komisyon −
  değişken − sabit) sütunları; toplam satırı ve kâr/zarar yorumu (`overview_totals`, seçilen yıla göre değişir).
  Devam eden ayda bütün sütunlar aynı döneme göre (ilk N gün; sabit gider de orantılı). "Ortak gider" ifadeleri
  "otelin sabit gideri" oldu (maliyet, ana sayfa, dönem kapanışları, rezervasyon). Kış tadilatları (migration 0036,
  kalem "Tadilat ve yenileme", tek seferlik): Aralık 2025 kahvaltı salonu ve lobi 680.000 ₺, Şubat 2026 Kordon
  cephesi ve doğramalar 1.150.000 ₺; kapanışlara eklendi. Şubat sabit gideri 5.979.000 ₺, sonucu −2,89 M; Standart
  gece payı 1.963 → 2.430 ₺. 2026 Ocak–Kasım: +12,57 M kâr (7 ay kâr, 4 ay zarar); 2025: −5,25 M.
  Test 113. Yedek: `_yedek/v56_toplam_tadilat_oncesi.tar.gz`, `_yedek/pasaport_otel_v56_oncesi.sql`.
- v57 (kullanıcı kararı): "Dönem kapanışları" ekranı menüden ve projeden kaldırıldı (URL, view'lar, şablon;
  şablon `_yedek/kaldirilanlar/period_closings_v56.html`). "Yeniden kapat" seçeneği hiçbir yerde yok. Kapanış
  mekanizması arka planda aynen çalışır (ekran açılınca biten ay donar); kapanmış aylar Maliyet analizindeki aylık
  özet tablosunda "Kapandı" etiketiyle görünür. Bedeli: kapanmış aya geç gelen faturanın girilmesi o ayı değiştirmez.
  Test 113. Yedek: `_yedek/v57_kapanis_ekrani_kaldirma_oncesi.tar.gz`.
- v58 (kullanıcı kararı): 2026 yaz doluluğu Mayıs %91, Haziran %95, Temmuz %93, Ağustos %97, Eylül %99. Yeni komut
  `doluluk_hedefi` (yalnız ekler, ay dışına taşmaz; `--onizle`, `--sil`, `--hedef 5=91,...`, `--yil`); 831 konaklama /
  1.152 oda-gece eklendi (not: "Doluluk hedefi"), 5 ay yeniden kapatıldı. Etki: otel normal doluluğu %65,5 → %71,3;
  2 kişi tam maliyet 3.500–8.697 ₺ (önce 3.677–9.646); 2026 Ocak–Kasım sonucu +12,57 M → +19,53 M. 2025 yazı
  değişmedi. Eklenen geceler gün sonu yapılmış dönemde olduğu için stoktan düşülmedi. Test 114.
  Yedek: `_yedek/v58_yaz_dolulugu_oncesi.tar.gz`, `_yedek/pasaport_otel_v58_oncesi.sql`.
- v59 (kullanıcı kararı): 2025 yazı da aynı oranlara getirildi (`doluluk_hedefi --yil 2025`; komut 2025'te fiyatı
  üreticideki gibi × %80 alır). 963 konaklama / 1.390 oda-gece eklendi, 5 ay yeniden kapatıldı. 2025: doluluk %70,2,
  gelir 81,49 M, sonuç −5,25 M → +1,18 M (5 ay kâr, 7 ay zarar). Normal doluluk (son 12 ay, 11.2025–10.2026) ve güncel
  oda maliyetleri değişmedi. Yedek: `_yedek/pasaport_otel_v59_oncesi.sql`, `_yedek/doluluk_hedefi_v58.py`.
- v60 (kullanıcı kararı): "Sabit giderin satışla karşılanması" kartı yalnızca seçilen ayın farkını gösterir; 12 aylık
  eksik/fazla/net ve "olağan dışı boşluk maliyeti" satırı kaldırıldı (hesap `absorption_window` serviste duruyor).
  Aylık farklar ve yıl toplamı aylık özet tablosunda.
- v61 (kullanıcı kararı): kart "Satışların toplam gideri karşılaması" oldu: seçilen ayın gerçek sonucu = oda geliri −
  komisyon − misafir gelince harcanan − sabit gider (aylık özetteki "Ayın sonucu" ile aynı), kırılımıyla. Eski değer
  yalnız sabit gideri ölçüyordu (fiyattaki sabit pay × satılan gece − gerçek sabit gider); o ölçü tablodaki
  "Sabit giderin karşılanma farkı" sütununda kaldı (sütun adı v61b ile değişti). Ağustos 2026: +5.031.913 ₺. Yedek: `_yedek/cost_report_v60.html`, `_yedek/views_v60.py`.
- v62 (kullanıcı kararı: "bizi toplam giderler ilgilendiriyor"): aylık özet tablosunda yalnız sabit gidere bakan
  karşılanma farkı sütunu kaldırıldı; yerine "Toplam gider" (komisyon + misafir gelince harcanan + sabit gider) ve
  "Karşılama oranı" (oda geliri ÷ toplam gider) geldi; yorum satırı da toplam gidere göre. 2026 Ocak–Kasım: toplam
  gider 73,76 M, karşılama %126; Ağustos %164, Şubat %60. Sabit gider karşılama ölçüsü ekranda yok (servis duruyor).
  Yedek: `_yedek/cost_report_v61.html`, `_yedek/services_v61.py`.
- v63: Maliyet analizi sayfası yeniden düzenlendi: üstte yıl düğmeleri + 12 ay sekmesi (durum: kapandı / devam ediyor /
  gelecek ve ayın sonucu); altında 5 renkli açılır kart (ay özeti [seçilen ayda açık], bir odanın maliyeti, oda tipi
  tablosu, yıl özeti, ayrıntılı döküm). Kart başlığında ana rakamlar; açık/kapalı durumu tarayıcıda hatırlanır
  (localStorage). İçerik ve hesaplar aynı. Yedek: `_yedek/v63_renkli_kartlar_oncesi.tar.gz`.
- v64 FİYAT MOTORU (kullanıcı kararları: karma çapa, onay yok — onay "karar destek sistemi" projesine kaldı, kademeli
  alt sınır): `dashboard/fiyat_motoru.py`. Gece fiyatı = max(alt sınır, min(hedef, piyasa) × talep). Hedef = tam maliyet
  × (1 + marj); piyasa = temel fiyat (kişiye göre); talep = etkinlik/hafta günü × anlık doluluk. Alt sınır: normalde tam
  maliyet; son dakikada (≤7 gün, o gece doluluk <%50) değişken × 1,20 (ayarlar `fiyat_kurallari`, migration 0037, Admin ›
  Fiyat kuralları). Otel kararı son söz (alt sınır yok, değişkenin altındaysa uyarı). Konaklamada indirimler gecelerin
  alt sınırı toplamının altına inemez. Kanal fiyatı = net ÷ (1 − komisyon) (`channel_price`). Takvim ve rezervasyon
  teklifi motoru kullanıyor; teklifte "Fiyat nasıl oluştu?" tablosu, takvim kartında çapa/alt sınır.
  BULGU: mevcut marjlarla (%62–80) hedef her oda tipinde piyasanın üstünde (Standart 6.465 > 4.695) → çapa hep piyasa,
  alt sınır gerçek veride devreye girmiyor; fiyatlar öncekiyle aynı. Test 116. Yedek: `_yedek/v64_fiyat_motoru_oncesi.tar.gz`,
  `_yedek/pasaport_otel_v64_oncesi.sql`. Sırada: menü düzeni (Maliyet / Fiyatlandırma / Satış analizi), Fiyat stratejisi
  sayfası, geriye dönük test.
- v65 (kullanıcı kararı): hedef marjlar fiyat motoruna göre: her tipte hedef fiyat = GEÇİŞ mevsimi piyasa fiyatı
  (migration 0038): STD %50, SUP %42, JRS %39, LUX %39, DLX %41, EXR %26, EXS %27 (önce %80…%62). Sonuç: kışın çapa
  piyasa, yazın maliyet (2027 takviminde gecelerin %53'ü); 2027 ortalama gece fiyatı ~%4,6 düşük (8.083 → 7.711 ₺).
  Alternatif ölçüldü: hedef = yaz piyasası (%44–70) gelir etkisi ±0 ama maliyet gecelerin yalnız %14'ünde belirleyici.
  Rezervasyon renkleri: hedefte 6, kârlı 50, katkı 105, zarar 4. Kayıtlı rezervasyon fiyatları değişmedi.
  Yedek: `_yedek/pasaport_otel_v65_oncesi.sql`.
- v66: fiyat motoru ekranda görünür: fiyat takviminde "Fiyatı belirleyen" kutusu (maliyet / piyasa / otel kararı gece
  sayısı, alt sınır) ve açıklama; her gün kartında "Maliyetten / Piyasadan / Otel kararı" etiketi; üstteki dört rakamın
  adları yeni modele göre (son dakika tabanı, normal alt sınır, maliyetten hedef, piyasa tavanı). Rezervasyonda
  "Fiyat nasıl oluştu?" açık gelir. Not: Kasım–Mart'ta fiyatı piyasa belirler (fark yalnız yaz/geçiş aylarında görünür).
- v67 SUNUM ÇEŞİTLİLİĞİ (kullanıcı isteği: "her gün aynı sonuç çıkmasın"):
  1. Motor: son dakika boş otel indirimi %30 (≤7 gün, o gece doluluk <%50; `fiyat_kurallari.son_dakika_indirim`,
     migration 0039). Alt sınır değişken × 1,20 korur → fiyat tam maliyetin altına inebilir ("Katkı").
  2. Ön satış (`doluluk_hedefi --aralik ... `, rezervasyon tarihi ≤ bugün, not "Doluluk hedefi · ön satış"):
     18–21.01.2027 %85, 01–05.02 %72, 12–15.04 %80, 14–19.05 %95, Temmuz %60, Ağustos %74, 02–12.09 %92 (1.462 konaklama).
  3. Kararlar (migration 0040, kaynak "örnek senaryo (sunum)"): Ocak sessiz hafta 11–14.01.2027 −%35, Şubat flaş
     kampanya 22–25.02 −%80, Ağustos zirve haftası 09–15.08 +%35.
  4. İndirimler alt sınıra takılınca teklif "Başabaş: alt sınırda" der (önce "Kârlı, kâr 0 ₺").
  SUNUM TARİHLERİ (Rezervasyon ekranı, 2 kişi, 2 gece, bugünden itibaren):
    Hedefte: 18–20.01.2027 (IF Wedding), 15–17.05 (Kurban), Ağustos'un her günü (zirve ayı), 05–07.09 (İEF)
    Kârlı, hedefin altında: 13–15.07.2027, 12–14.10.2027 (Standart)
    Katkı sağlıyor: 11–13.01.2027 (sessiz hafta), 14–16.11.2026 son dakika (Deluxe / Executive Suite)
    Zarar: 20–28.02.2027 ilk 4 kategori (flaş kampanya; büyük odalar kâr korumasıyla kârlı), 07–09.12.2026 (fırtına kampanyası, Standart)
    Başabaş: 02–04.03.2027 Executive Suite (erken rezervasyon indirimi alt sınıra takılır)
    Kanal etkisi: 13–15.07.2027 Executive Suite + Booking.com → Katkı
  Not: son dakika örneği tarihe bağlı (bugünden 7 gün içi); sunum günü o haftanın tarihleri seçilmeli.
  Test 117. Yedek: `_yedek/v67_cesitlilik_oncesi.tar.gz`, `_yedek/pasaport_otel_v67_oncesi.sql`.
- v68 ŞUBAT ZARAR / AĞUSTOS HEDEF (kullanıcı isteği, migration 0041):
  Şubat flaş kampanya 20–28.02.2027, endeks 0,07 (%93 indirim; önce 22–25.02, 0,20). Misafir gelince harcanan piyasa
  fiyatının yalnız %8–21'i olduğu için 0,20 sadece Standart'ı zarara düşürüyordu. Ölçüm: 7 oda tipi × tüm kişi sayıları
  "Zarar: satılmamalı"; takvimde her tipte 9 gece kırmızı.
  Ağustos zirve ayı 01–31.08.2027, endeks 1,35 (önce "Ağustos zirve haftası" 09–15.08). Gereken en yüksek endeks 0,92;
  erken (%15) + uzun konaklama (%12) indirimleriyle 1,23. Ölçüm: 1/2/7 gece, tüm tipler, tüm kanallar (Booking %17,
  acenta %20 dahil) "Hedefte"; takvimde 31 gecenin hepsi yeşil.
  Not: 30 Ağustos bayramı ve ön satış artık Ağustos fiyatını etkilemez (otel kararı son sözdür).
  Test 117. Yedek: `_yedek/v68_subat_agustos_oncesi.tar.gz`, `_yedek/pasaport_otel_v68_oncesi.sql`.
- v69 FİYAT TAKVİMİ ÖZET KARTI (kullanıcı isteği: "525–7.346 ₺ aralığı anlamsız, açılır kart olsun"):
  Takvimin üstündeki özet tek açılır kart (details#ozet, açık/kapalı localStorage "takvim-ozet"). Başlıkta: sıradan
  gecelerin aralığı (otel kararı olmayan geceler), ay ortalaması, durum sayıları. İçerik: 3 kutu (sıradan geceler /
  ay ortalaması / özel fiyatlı günler), özel günler tablosu (karar adına göre art arda geceler gruplu, taslak notu),
  4 sonuç kartı (hedefte/kârlı/katkı/zarar gece sayısı + anlamı), renk bölgeli fiyat çubuğu (ortalama işaretli),
  ①–④ sınır kartları sade açıklamalı, "Fiyatı kim belirledi?". Servis: `price_overview()` (price_calendar types[].overview).
  Test 118. Yedek: `_yedek/v69_takvim_ozet_oncesi.tar.gz`.
- v70 KÂR KORUMASI (kullanıcı kararı: "büyük ve lüks odalar zararına satılmasın, her gün biraz kâr etsin"):
  Oda tipine `min_markup` (Asgari kâr marjı, sütun asgari_kar_marji, Admin › Oda tipleri'nde düzenlenir; migration 0042).
  Deluxe, Executive Oda, Executive Suite %5; ilk 4 kategori (Standart, Superior, Junior Suite, Luxury) 0 = koruma yok.
  Korumalı tipte alt sınır her gün tam maliyet × 1,05: son dakikada (değişken × 1,2 yerine), otel kararında (Şubat flaş
  kampanyası dahil) ve konaklama toplamında. Kanal komisyonundan sonra otele kalan tutar da bu sınırın altına inmez.
  Ölçüm (13.11.2026–2027 sonu): korumalı tiplerde 0 katkı / 0 zarar gecesi; 1.323 konaklama teklifi (9 tarih × 1/2/7
  gece × 7 kanal × kişi sayıları) hepsi kârlı ya da hedefte, en düşük kâr %5,0. İlk 4 kategori: 15 zarar, 7–9 katkı gecesi.
  Sunum örnekleri (2 kişi, 2 gece, bugün 13.11.2026): 22–24.02.2027 Standart/Luxury ZARAR ↔ Deluxe/Exec. Suite KÂRLI;
  11–13.01.2027 ve 15–17.11.2026 Standart/Luxury KATKI ↔ büyük odalar KÂRLI; 02–04.03.2027 Luxury BAŞABAŞ.
  (v67 listesindeki "Deluxe/EXS son dakika katkı", "EXS başabaş", "EXS + Booking katkı" örnekleri artık geçersiz.)
  Test 119. Yedek: `_yedek/v70_kar_korumasi_oncesi.tar.gz`, `_yedek/pasaport_otel_v70_oncesi.sql`.
- v71 DOLULUK İZMİR VERİSİNE GÖRE (kullanıcı isteği: "oranlar TÜİK/Bakanlık turizm verisine uygun olsun"):
  Kaynak: Kültür ve Turizm Bakanlığı konaklama istatistikleri, İzmir 2024 aylık doluluk (tüm belgeli tesisler, yatak
  doluluğu; yıllık ~%41, 2025 yıllık %38,5). Bakanlık bülteninde İzmir'de otel türü tesisler genel ortalamanın ~1,21 katı
  (Oca–Tem 2025: otel %61,04 / genel %50,33). Hedef = İzmir aylık × 1,21:
  Oca 29 Şub 30 Mar 32 Nis 45 May 51 Haz 60 Tem 75 Ağu 86 Eyl 63 Eki 58 Kas 35 Ara 30 (yıllık ~%49).
  `doluluk_hedefi --hedef izmir --azalt` (yeni): hedefin üstündeki ayda yalnız örnek veri konaklamaları (notu "Örnek veri"
  ya da "Doluluk hedefi") rastgele silinir, eksik kalan tamamlanır. 2025 tüm aylar ve 2026 Ocak–Ekim uygulandı (~3.900
  konaklama silindi); tüm kapanmış aylar yeniden kapatıldı. 2026 Kasım–Aralık ve 2027 ön satışları değişmedi.
  Etki: normal doluluk %70 → %49,7; gece başına sabit gider payı ~%40 arttı (Standart tam maliyet ~3.500 → ~4.760 ₺).
  2025 sonucu −15,9 M ₺ (gelir 57,9 M / gider 73,9 M), 2026 (bugüne kadar) −1,1 M ₺. Kışın tam maliyet piyasa fiyatının
  üstünde: ilk 4 kategori çoğu gece tam maliyette (alt sınırda) satılıyor; korumalı büyük odalar piyasanın %10–30 üstünde.
  Gün sonu stok hareketleri silinen konaklamalara göre geri alınmadı (stok ekranı eski tüketimi gösterir).
  Test 119. Yedek: `_yedek/v71_tuik_doluluk_oncesi.tar.gz`, `_yedek/pasaport_otel_v71_oncesi.sql`.
- v72 PİYASA FİYATLARI YENİ MALİYETE GÖRE (kullanıcı onayı, migration 0043): geçiş mevsimi piyasa fiyatı = maliyetten
  hedef fiyat (v65 kuralı), kış ve yaz aynı oranla (+%31–43), 50 ₺ yuvarlak. Kış/geçiş/yaz (2 kişi, KDV hariç):
  STD 6.250/6.950/8.050 · SUP 6.850/7.600/8.650 · JRS 8.400/9.150/10.700 · LUX 9.250/10.400/11.850 ·
  DLX 10.400/11.550/13.400 · EXR 12.600/13.800/16.150 · EXS 13.600/15.100/17.700. Ek kişi ücreti değişmedi.
  Sonuç: kışın piyasa yine tam maliyetin üstünde; takvimde çeşitlilik geri geldi (ör. Kasım 2026 STD 9 hedefte, 16 kârlı,
  3 katkı, 2 zarar). Sunum tarih listesi aynı sonuçları veriyor. Geçmiş konaklamaların fiyatı değişmedi: 2025 ve 2026
  zararı (v71) duruyordu; v73'te düzeltildi.
  Test 119. Yedek: `_yedek/v72_fiyat_ayari_oncesi.tar.gz`, `_yedek/pasaport_otel_v72_oncesi.sql`.
- v73 GEÇMİŞ KONAKLAMA FİYATLARI (kullanıcı isteği): örnek veri konaklamalarının (notu "Örnek veri", "Doluluk hedefi",
  "Doluluk hedefi · ön satış"; 10.231 kayıt) gecelik fiyatı oda tipi × giriş mevsimine göre yeni/eski piyasa oranıyla
  (×1,31–1,43) çarpıldı, 10 ₺ yuvarlak. 2025'in ×0,80 kur farkı korunur. Elle girilen 23 konaklamaya dokunulmadı.
  Tüm kapanmış aylar yeniden kapatıldı. Betik: `_yedek/v73_gecmis_fiyat_betigi.py`.
  Sonuç: 2025 gelir 78,05 M / gider 76,11 M → +1,94 M (karşılama %102,6); 2026 (13.11'e kadar) 89,16 M / 69,94 M →
  +19,22 M (%127,5). Aylık desen: Kasım–Mart zarar, Nisan/Mayıs başabaş civarı, Haziran–Ekim kâr (Ağustos en yüksek).
  Test 119. Yedek: `_yedek/v73_gecmis_fiyat_oncesi.tar.gz`, `_yedek/pasaport_otel_v73_oncesi.sql`.
- v74 2025 GİDERLERİ 2025 FİYAT SEVİYESİNE (kullanıcı sorusu: "2025 1,94 M, 2026 19,22 M kâr gerçekçi değil"):
  Neden: 2025 konaklama fiyatları 2026'nın %80'i (PRICE_2025) ama 2025 giderleri 2026 tutarlarıyla aynıydı (migration
  0034); ayrıca 2026'da Aralık yok, Kasım yarım. Migration 0044: her tekrarlayan kalemin 2025 kaydı × 0,80 (sabit tutar
  ve değişken birim tutar); eski tutarlar 2026'dan geçerli yeni kayıtlara taşındı (mevsimli kalemde kış Ocak, geçiş
  Nisan, yaz Haziran 2026). Amortisman ve tek seferlik tadilatlar değişmedi. 2026+ ve fiyat motoru etkilenmez.
  Kahvaltı, tekstil ve oda paketi birim fiyatlarının tarih geçmişi yok: 2025'te de bugünkü fiyatla hesaplanır (etkisi
  küçük, yılda ~1 M ₺). Tüm kapanmış aylar yeniden kapatıldı.
  Sonuç: 2025 gelir 78,05 / gider 64,88 → +13,17 M (%120,3). Ocak–Ekim: 2025 +15,91 M (marj %22,5), 2026 +19,81 M
  (marj %22,7) → kâr fiyatlarla aynı oranda (~%25) büyüyor.
  Test 119. Yedek: `_yedek/v74_2025_gider_oncesi.tar.gz`, `_yedek/pasaport_otel_v74_oncesi.sql`.
- v75 2025 = 2026 × 0,75 (kullanıcı kararı: hammadde ve bütün sabit giderler 2025'te %25 düşük):
  Yeni tablo `hammadde_fiyat_endeksi` (MaterialPriceIndex, Admin › Hammadde fiyat endeksleri; migration 0045): 2025 = 0,75.
  `material_index(yil)`; calculate_monthly_room_cost ve calculate_stay_quote kahvaltı, restoran sarfı, oda paketi ve
  tekstili o yılın endeksiyle çarpar (kaydı olmayan yıl 1). Migration 0046: her tekrarlayan kalemin 2025 kaydı = 2026
  kaydı × 0,75 (v74'teki 0,80'in yerine); amortisman da dahil (2026 kaydı 300.000 açıldı, 2025 225.000). Tadilatlar aynı.
  Tüm kapanmış aylar yeniden kapatıldı. Sonuç: 2025 gelir 78,05 / gider 59,44 → +18,62 M (%131,3).
  Ocak–Ekim: 2025 +20,55 M (marj %29,1; değişken 6,19 M), 2026 +19,81 M (marj %22,7; değişken 8,28 M).
  (2025 oda fiyatları v76'da 0,75'e çekildi.)
  Test 120. Yedek: `_yedek/v75_hammadde_endeksi_oncesi.tar.gz`, `_yedek/pasaport_otel_v75_oncesi.sql`.
- v76 2025 ODA FİYATLARI = 2026 × 0,75 (kullanıcı onayı): 2025 girişli 4.468 örnek konaklamanın fiyatı × 0,9375
  (0,75 ÷ 0,80), 10 ₺ yuvarlak; üreticideki PRICE_2025 = 0,75. Betik: `_yedek/v76_2025_fiyat_betigi.py`. Kapanışlar yenilendi.
  Böylece 2025'te fiyat, sabit gider ve hammadde aynı oranda (2026 × 0,75, yani 2026'da ~%33 artış).
  Sonuç: 2025 gelir 73,18 / gider 58,89 → +14,29 M (%124,3). Ocak–Ekim: 2025 +16,64 M (marj %25,2), 2026 +19,79 M
  (marj %22,7). Marj farkı Şubat 2026'daki tek seferlik 1,15 M tadilattan; o hariç 2026 marjı ~%24 ve kâr artışı ~%26.
  Test 120. Yedek: `_yedek/v76_2025_fiyat_oncesi.tar.gz`, `_yedek/pasaport_otel_v76_oncesi.sql`.
- v77 TURİZM ÖZEL GÜNLERİ 2025–2026 (kullanıcı listesi, migration 0047, kaynak "Turizm takvimi (kullanıcı listesi, v77)"):
  Motor kontrolü: gecenin endeksi = etkinlik ve hafta günü endekslerinin en yükseği × doluluk çarpanı (otel kararı varsa
  karar). Eksik günler eklendi (1 Ocak 2025, Sevgililer 2025/2026, 23 Nisan 2025, 1 Mayıs 2025, 15 Temmuz 2025/2026,
  30 Ağustos 2025, Yılbaşı uzun hafta sonu 2026, Anneler Günü 2026); 19 Mayıs 2026 köprüyle 16–18'e genişledi.
  Endeks (talep etkisi): Yılbaşı gecesi 1,80 · Sevgililer 1,55/1,60 · Kurban 1,40 · Ramazan 1,30 · 1 Ocak 1,25 ·
  resmi tatil uzun hafta sonu 1,15 · tek gün / Anneler Günü / 15 Temmuz 1,05–1,10.
  Veri (`_yedek/v77_ozel_gun_betigi.py`, eski endeksler `_yedek/v77_endeks_eski.json`): endeksi değişen 49 geceye değen
  895 örnek konaklamanın fiyatı × (yeni ÷ eski ortalama endeks); 59 özel gece %100 dolduruldu (54/54 oda; 31.12.2026 ön
  satış); aylar özel gecelere değmeyen konaklamalar silinerek İzmir hedefinde tutuldu (`doluluk_hedefi.reduce(keep=...)`).
  Ortalama gece fiyatı (2026): Yılbaşı gecesi 13.187, Sevgililer 12.543, Kurban 12.399, Ramazan 10.615, 23 Nisan 10.348 ₺.
  Sonuç: 2025 +15,93 M (Oca–Eki +18,13 M, %26,7); 2026 (13.11'e kadar) +21,44 M (Oca–Eki +22,04 M, %24,6).
  Test 121. Yedek: `_yedek/v77_ozel_gunler_oncesi.tar.gz`, `_yedek/pasaport_otel_v77_oncesi.sql`.
- v78 TURİZM ÖZEL GÜNLERİ 2027 (migration 0048, kaynak "Turizm takvimi 2027 (v78)", v77 endeks kuralları):
  1–2 Ocak 1,25 · Sevgililer 13–14 Şubat 1,55 (yeni) · Ramazan 8–11 Mart 1,30 · 23 Nisan 22–24 Nisan 1,15 · 1 Mayıs
  30 Nisan–1 Mayıs 1,10 · Anneler Günü 8 Mayıs 1,10 (yeni) · Kurban 15–19 Mayıs 1,40 · 19 Mayıs (yeni, Kurban içinde)
  · 15 Temmuz köprüyle 15–17 Temmuz 1,10 · 30 Ağustos 28–29 Ağustos 1,10 (Ağustos zirve ayı kararı geçerli) ·
  Cumhuriyet 28–30 Ekim 1,15 · Yılbaşı gecesi 31 Aralık 1,80. Yalnız takvim; 2027 için ek ön satış yapılmadı.
  Örnek Standart 2 kişi gece fiyatı: 13 Şubat 9.203 ₺ (normal Cumartesi 6.531), 16 Mayıs Kurban 12.649 ₺, 31 Aralık 10.688 ₺.
  Test 121. Yedek: `_yedek/v78_2027_ozel_gunler_oncesi.tar.gz`, `_yedek/pasaport_otel_v78_oncesi.sql`.
- v79 ÖZEL GÜNLERDE İNDİRİM YOK (kullanıcı kararı): özel gün = etkinlik türü milli_bayram, dini_bayram, ozel_gun
  (`services.SPECIAL_DAY_KINDS`). O gecelerde: doluluk çarpanı 1'in altına inmez, son dakika indirimi yok, indirim
  yönlü otel kararı (endeks < 1) yok sayılır (night["skipped_decision"]; artış kararı, ör. Yılbaşı gala 1,80, geçerli),
  takvimde erken rezervasyon fiyatı gösterilmez. Konaklama teklifinde erken rezervasyon ve uzun konaklama indirimi
  yalnız özel olmayan gecelerin toplamına uygulanır (special_subtotal, special_nights). Ekranlar: rezervasyon teklifinde
  "Özel gün: N gecede hiçbir indirim uygulanmaz" satırı ve "(özel geceler hariç)"; takvim kutusunda "İndirim yok".
  Geçmiş (kayıtlı) konaklamaların fiyatı değişmedi. Örnek (STD 2 kişi, bugün): Sevgililer 13–15.02.2027 19.375 ₺ indirimsiz;
  11–15.02 → indirim yalnız 2 normal geceye (2.400 ₺); normal Mart 2 gece %15 erken indirimli.
  Test 123. Yedek: `_yedek/v79_ozel_gun_indirimsiz_oncesi.tar.gz` (yalnız kod; veri değişmedi).
- v80 2027 OCAK–MART ÖZEL GECELERİ TAM DOLU (kullanıcı isteği, "diğer rezervasyonlara dokunma"): yalnız ekleme,
  `doluluk_hedefi --aralik "2027-01-01:2027-01-03=100;2027-02-13:2027-02-15=100;2027-03-08:2027-03-12=100" --tohum 80`
  → 229 ön satış konaklaması (rezervasyon tarihi ≤ 13.11.2026), 1–2 Ocak, 13–14 Şubat, 8–11 Mart 54/54 oda.
  Silme ya da dengeleme yapılmadı. Doldurma fiyatı: özel gecede erken rezervasyon indirimi yok (doluluk_hedefi.price).
  Nisan dahil edilmedi ("Nisan'a kadar"); 23 Nisan, Kurban vb. eklenmedi.
  Test 123. Yedek: `_yedek/v80_2027_ozel_dolu_oncesi.tar.gz`, `_yedek/pasaport_otel_v80_oncesi.sql`.
- v81 23 NİSAN 2027 UZUN HAFTA SONU TAM DOLU: `--aralik "2027-04-22:2027-04-25=100" --tohum 81` → 91 ön satış,
  22–24 Nisan 54/54 (yalnız ekleme). Yedek: `_yedek/pasaport_otel_v81_oncesi.sql`.
- v82 REZERVASYON SAYFASI DÜZELTMELERİ (denetim: 7.104 gece fiyatı + 1.140 teklif; hesap hatası yoktu, eksikler vardı):
  1. MÜSAİTLİK (`services.room_availability`): oda bazında, yalnız aktif odalar. Durumlar: available (en az bir oda tüm
     geceler boş; boş oda numaraları, "son N oda" uyarısı), room_change (her gece boş oda var ama tek oda yok: oda
     değişikliği uyarısı), unavailable (bir gece hiç boş yok), no_rooms (aktif oda yok). Dolu/kapalıda FİYAT VERİLMEZ;
     gece gece "x / y boş" kutuları ve `availability_alternatives`: aynı tarihte boş diğer tipler (kişi kapasitesi
     uygun, fiyat ve sonuçla, "Bu tiple hesapla") ve aynı tipte ±14 gün içinde en yakın 3 boş tarih.
  2. ODA TİPİ TALEBİ (FiyatMotoru): tipin anlık doluluğu (rezervasyon anına kadar satılan ÷ tipin aktif odası). Tip otelden
     daha doluysa doluluk çarpanı tipe göre ölçülür; YALNIZ ARTIRIR (eski fiyatın altına inmez). Son dakika kararı da
     daha dolu olana göre. Alanlar: type_occupancy, occupancy_basis ("otel"/"oda tipi"). Ölçüm: 7.104 gecenin 194'ünde tipe göre.
  3. FORM: Satış kanalı açılır listesi ("Booking.com (komisyon %17)", varsayılan Web sitesi), Rezervasyon tarihi (boşsa
     bugün; bugünden sonra ve girişten sonra olamaz). Giriş tarihi bugünden önce olamaz.
  4. EK KİŞİ ÜCRETİ: 3./4. kişi ücreti sabit; talep, etkinlik, karar ve son dakika çarpanları yalnız 1–2 kişilik kısma
     (motor = model açıklaması = örnek veri üreticisi).
  Test 128 (ReservationAvailabilityTests +5). Yedek: `_yedek/v82_rezervasyon_duzeltme_oncesi.tar.gz` (yalnız kod).
- v83 REZERVASYON SAYFASI TASARIMI (kullanıcı isteği: alanlar alt alta, renkli, aynı hizada): geniş ekranda solda
  yapışkan form kartı (380 px), sağda sonuçlar; 1100 px altında alt alta. Form: degrade başlık, "Konaklama" (yeşil) ve
  "Satış" (mor) grupları, her alanın renkli simgesi, bütün girişler aynı genişlik/yükseklik (46 px), canlı gece sayısı
  ("2 gece · 2 Mar → 4 Mar"; giriş seçilince çıkış en az ertesi gün), turuncu "Müsaitlik ve fiyatı hesapla" düğmesi,
  hatalar alanın altında kırmızı kutuda. Boş sayfada 3 adımlı yönlendirme kartı. Tarih kutuları artık başlangıç
  değerlerini gösteriyor (DateInput format %Y-%m-%d). Uzun indirim/koruma satırları alt satıra kayıyor (tablo taşmıyor).
  Eski şablon: `_yedek/reservation_cost_v82.html`. Test 128.
- v84 REZERVASYON TARİHİ ALANI KALDIRILDI (kullanıcı kararı: "ekstradan tarih istemeyelim"): formda yalnız oda tipi,
  misafir, giriş, çıkış ve satış kanalı. Rezervasyon günü her zaman bugün (form.clean → cleaned_data["booked_on"]);
  erken rezervasyon (≥30 gün) ve son dakika (≤7 gün) kuralları giriş tarihine kalan güne göre arka planda çalışır.
  Öneri bağlantılarından booked_on parametresi çıkarıldı. Yedekler: `_yedek/forms_v83.py`, `_yedek/views_v83.py`,
  `_yedek/reservation_cost_v83.html`. Test 128.
- v85 REZERVASYON = PERSONEL KONTROL EKRANI (kullanıcı: "müşteri rezervasyonu değil, personel kontrol sistemi"):
  Dolu tarihte de fiyat, maliyet ve kâr hesaplanır ("Fiyat ve kâr · bilgi amaçlı", "Bu oda bu tarihlerde satılamaz"
  notu). Yeni `services.night_sales_summary`: seçilen gecelerde o tipte ZATEN SATILMIŞ odalar — satılan oda-gece /
  kapasite, tip ve otel doluluğu, ortalama satış fiyatı, gelir, komisyon, otele kalan, tahmini tam maliyet (kişi sayısına
  göre gecenin maliyeti) ve kâr, marj, kanal dağılımı, gece gece tablo. Örnek 14.02.2027 Superior: 12/12, ort. 10.443 ₺,
  otele kalan 102.741 ₺, kâr 36.966 ₺ (Booking 6, Expedia 3, acenta 3).
  Sonuçlar açılır renkli kartlar (maliyet analiziyle aynı stil): Müsaitlik (yeşil/sarı/turuncu/kırmızı, açık),
  Fiyat ve kâr (turuncu, açık), Gece gece fiyat (mavi), Bu gecelerde yapılmış satışlar (mor; dolu tarihte açık),
  Fiyat nasıl oluştu? (yeşil, kapalı), Maliyet ayrıntısı (gri, kapalı). Açık/kapalı durumu localStorage "rez-kart-*".
  Yedekler: `_yedek/reservation_cost_v84.html`, `_yedek/views_v84.py`, `_yedek/services_v84.py`. Test 128.
- v86 MALİYET ANALİZİ KARTLARI KAPALI AÇILIR (kullanıcı isteği): ay özeti artık varsayılan açık değil, oda kartı oda
  parametresiyle kendiliğinden açılmıyor, localStorage'daki eski açık/kapalı durumu okunmuyor (eski "maliyet-kart-*"
  anahtarları silinir). Yalnız adreste #işaret varsa (ay/yıl sekmesi → #ay, oda tipi çipi → #oda-maliyeti, aylar
  tablosundaki ay bağlantısı) o kart açılır. Menüden gelince bütün kartlar kapalı. Yedek: `_yedek/cost_report_v85.html`.
- v87 FİYAT TAKVİMİ TASARIMI (kullanıcı isteği): günlük takvim açılır pencere (details.sec.cal #takvim, mavi; durumu
  localStorage "takvim-pencere"), başlıkta durum rozetleri. Her gün açılır kart (details.day): kapalıyken gün, fiyat,
  sonuç rozeti; tıklayınca kaynak (maliyet/piyasa/otel kararı), etki, özel gün, doluluk, oda tipi, alt sınır, kâr,
  misafirin ödeyeceği ve açıklama. "Tümünü aç / Tümünü kapat" düğmeleri. Canlı palet (:root): yeşil #16a34a, sarı
  #facc15 (koyu yazı), turuncu #f97316, kırmızı #dc2626; gün kartları, rozetler, sonuç kartları, fiyat çubuğu ve
  açıklama aynı paleti kullanır. Sekmeler ve araç çubuğu yeşil-lacivert temaya uyumlu. Geçmiş günler hafif soluk
  (opaklık .9, "geçti"). Yedek: `_yedek/price_calendar_v86.html`. Test 128.
- v88 HER AY 5 REZERVASYON ZARARINA SATIŞ (kullanıcı isteği; betik `_yedek/v88_zararina_satis_betigi.py`, tohum 88):
  En ucuz 4 tip (STD, SUP, JRS, LUX), her ay 3 sıradan gün (özel gün ve otel kararı yok; önce hafta içi etkinliksiz,
  aday azsa hafta sonu ve fuar günü), o günlerde girişli ≤3 gecelik 5 mevcut rezervasyon (2+2+1). Otele kalan = tam
  maliyet × 0,45–0,65 (en az odanın gideri × 1,3) → gece ~2.100–4.400 ₺ (kullanıcı: 600 ₺ çok düşük, kırmızı kart olsun).
  Not: "Zararına satış: <aya göre gerekçe>" (Ocak sessiz dönem, Şubat düşük sezon, … Kasım indirimi (talep azlığı) …;
  bazılarına ek: fiyat eşleştirme, şikâyet telafisi, tanıtım konaklaması, personel yakını). `reservation_overview`:
  LOSS_SALE_PREFIX notlu ve tam maliyetin altındaki konaklama kırmızı "Zararına satış" + gerekçe (deliberate_loss);
  diğer etiketler değişmedi. 152 rezervasyon: 01.2025–01.2027 her ay 5 (12.2026: 4), 02.2027 5, 03.2027 2, 04–05.2027
  5, 06.2027 1, 07.2027 5, 08.2027 0 (zirve ayı kararı), 09.2027 5. Toplam bilinçli zarar 593 bin ₺. Kapanışlar yenilendi.
  2025 +15,65 M, 2026 (13.11'e kadar) +21,10 M. Test 129. Yedek: `_yedek/pasaport_otel_v88_oncesi.sql`.
- v89 ODA DAĞILIMI + FİYAT SIRASI + TAKVİMDE ODA SAYISI (kullanıcı kararı; 54. oda Executive Suite):
  Odalar: STD 10 (101–110), SUP 10 (201–210), JRS 10 (601–610), LUX 10 (401–410), DLX 6 (301–306), EXR 6 (501–506),
  EXS 2 (701, 703). Taşınan: 111–114→605–608 ve 211–212→609–610 (JRS), 307–309→408–410 (LUX), 702→506 (EXR).
  Konaklamalar odayla gitti; fiyatları yeni/eski tip piyasa fiyatı oranıyla (giriş mevsimi) ayarlandı (2.062 kayıt).
  702'deki 3–4 kişilik 30 konaklama: 10'u boş EXS'e taşındı, 20'si 2 kişiye indirildi (ek kişi ücreti düşüldü).
  Betik `_yedek/v89_oda_dagilimi_betigi.py`. Kapanışlar yenilendi. 2025 +16,64 M, 2026 +22,31 M; 152 zararına satış kırmızı.
  FİYAT SIRASI (FiyatMotoru.night, ORDER_STEP %2): tipler maliyet payı katsayısına göre sıralı; pahalı tip bir alttakinin
  fiyatı × 1,02 (+ fazla kişi ücreti) altına inmez (order_applied, order_below). Önce 414 gecenin 14'ünde sıra bozuluyordu,
  şimdi 0; kâr koruması ihlali 0. Gece hesapları önbellekli (_cache).
  TAKVİM: sekmelerde oda sayısı, pencere başlığında "otelde N oda · bu ay X / Y oda-gece satıldı", her gün kartında
  "X / N oda satıldı" çubuğu (dolu gün kırmızı "Dolu"), ayrıntıda boş oda ve "Sıra koruması" satırı.
  Test 130 (PriceOrderTests). Yedekler: `_yedek/pasaport_otel_v89_oncesi.sql`, `_yedek/v89_oda_dagilimi_oncesi.tar.gz`.
- v90 5 ODA TİPİ + MANZARA (kullanıcı kararı; betik `_yedek/v90_bes_oda_tipi_betigi.py`):
  Standart 10 manzarasız (101–110) · Superior 20 kara (201–210, 401–410) · Junior Suite 10 şehir (601–610) ·
  Executive Oda 10 deniz (501–510; 507–508 eski DLX 305–306, 509–510 eski EXS 701/703) · Deluxe 4 deniz (301–304, EN PAHALI).
  Luxury ve Executive Suite satışa kapalı (active=False; geçmiş için silinmedi). Maliyet payı katsayısı (sıra):
  STD 0,85 < SUP 1,00 < JRS 1,20 < EXR 1,50 < DLX 1,80. Kâr koruması %5: EXR, DLX.
  Piyasa (kış/geçiş/yaz, 2 kişi): STD 6.250/6.950/8.050 · SUP 6.850/7.600/8.650 · JRS 8.400/9.150/10.700 ·
  EXR 9.800/10.750/12.600 · DLX 11.350/12.599/14.600. Hedef marj (geçiş = hedef): STD %38, SUP %29, JRS %33, EXR %18, DLX %27.
  Konaklamalar odayla yeni tipe geçti, fiyat yeni/eski (tip, mevsim) piyasa oranıyla (~4.700 kayıt); EXS'teki 79 kalabalık
  konaklama 2 kişiye indi (ek kişi ücreti düşüldü). Kapanışlar yenilendi. 3–4 kişilik oda tipi artık yok.
  Tarama: fiyat sırası bozulan 0, kâr koruması ihlali 0, 152 zararına satış kırmızı. Sonuç: 2025 +10,23 M, 2026 +14,33 M
  (eski Luxury odaları Superior fiyatına, EXR 13.800→10.750 indiği için gelir düştü).
  Takvim: sekme başlığında ve pencere başlığında manzara. Üretici TYPE_PREFERENCE 5 tipe uyarlandı.
  ESKİ SUNUM ÖRNEKLERİNDEKİ "Executive Suite", "Luxury" tarihleri artık geçersiz; Deluxe ve Executive Oda kullanılmalı.
  Test 130. Yedekler: `_yedek/pasaport_otel_v90_oncesi.sql`, `_yedek/v90_bes_oda_tipi_oncesi.tar.gz`.
- v91 ESKİ TİPLER SİLİNDİ + REZERVASYONLAR YIL › AY (kullanıcı isteği):
  Luxury ve Executive Suite oda tipleri, piyasa fiyatları (6) ve yalnız EXS'in kullandığı 3–4 kişilik oda paketi
  kalemleri (72) silindi. Oda, konaklama ve kapanış kaydı kalmamıştı (geçmiş zaten 5 tipe göre). Yedek
  `_yedek/pasaport_otel_v91_oncesi.sql`.
  Rezervasyonlar sayfası: "Önümüzdeki aylar · durum özeti" açılır kart (4 durum kartı, tıklayınca süzgeç) ve "Bütün
  rezervasyonlar · yıllara ve aylara göre" açılır kart; içinde yıl kartları (2025, 2026, 2027) ve ay kartları, hepsi kapalı.
  Ay açılınca tablo ayrı istekle yüklenir (?parca=ay&ay=YYYY-MM, şablon reservations_month.html; bütün yıllar tek
  seferde ~14 sn, bir ay ~1 sn). Ayın durum özeti, durum süzgeci (?durum=), oda satırında manzara. Kırmızı grubun
  etiketi bilinçli zararına satış varsa "Zarar / zararına satış". Eski şablon `_yedek/reservations_v90.html`. Test 131.
- v92 "SATIŞ VE KÂRLILIK" SAYFASI KALDIRILDI (kullanıcı kararı): /fiyatlandirma/ adresi, `pricing_dashboard` görünümü,
  pricing.html şablonu ve menü bağlantısı silindi; ana sayfadaki "Fiyat ve satış" kartı artık Fiyat takvimine gider.
  `services.pricing_overview` hesap fonksiyonu duruyor (aylık satış testleri kullanıyor; ekranda yok). Eski şablon
  `_yedek/kaldirilanlar/pricing_v91.html`; eski views/base/home `_yedek/*_v91.*`. Menü: Ana Sayfa, Rezervasyon, Maliyet
  analizi, Fiyat takvimi, Rezervasyonlar, Stok analizi, Siparişler. Test 131.
- v93 TABLO SADELEŞTİRME 23 → 16 (kullanıcı kararı; migration 0049_tablolari_birlestir, yedek
  `_yedek/pasaport_otel_v93_oncesi.sql` ve `_yedek/v93_tablo_birlestirme_oncesi.tar.gz`):
  temel_fiyatlar → oda_tipleri.kis/gecis/yaz_fiyati (RoomType.winter/transition/summer_rate, market_rate(); services.market_rates()).
  envanter_kategorileri → envanter_urunleri.kategori (InventoryItem.Category; cost_center ve is_food koddaki eşlemeden).
  tekstil_varliklari → envanter_urunleri.tekstil_omru_oda_gece / tekstil_hurda_degeri / tekstil_oda_basi_set
  (is_textile, textile_cost(kişi)). kahvalti_bufesi_urunleri + oda_paketi → standart_tuketim (ConsumptionRecipe:
  esas kahvalti / oda_gecesi / kisi_gecesi, misafir_sayisi, miktar, fire); BreakfastBuffetItem ve RoomPackageItem aynı
  tablonun proxy modelleri (Admin'de iki ayrı ekran). hammadde_fiyat_endeksi → oranlar (eski vergi_oranlari; tür
  "hammadde", geçerlilik yılın 1 Ocak'ı). mevsim_aylari → fiyat_kurallari.mevsim_aylari (season_map/season_of/months_of
  ortak.py). donem_maliyetleri → donem_kapanislari.maliyetler (JSON; ClosedPeriod.cost_rows()/set_cost()).
  kahvalti_bufesi_gorunumu silindi. Siparişler ve tedarikçiler duruyor (sayfa çalışsın diye).
  DOĞRULAMA: değişiklik öncesi/sonrası 13 bölümlük ölçüm (maliyet satırları 6 ay, 300 gece fiyatı, teklif, rezervasyon
  durumları, yıl sonuçları, hammadde endeksi) birebir aynı. 17 admin ekranı, 7 sayfa, veri_denetimi çalışıyor.
  seed_demo 5 oda tipine uyarlandı. Test 132. README tablo bölümü güncellendi.
- v94 STOK ANALİZİ BAŞLIKLARI (kullanıcı isteği): ürün tablosu kategoriye göre 4 açılır karta ayrıldı (hepsi kapalı açılır):
  Mutfak ve bar (yiyecek, içecek, restoran malzemeleri; 31 ürün; v94b adı kullanıcı isteğiyle) · Tekstil (13) · Temizlik malzemeleri (10) ·
  Buklet ve oda malzemeleri (12; kullanıcının saydığı üç başlığa girmediği için ayrı kart). Başlıkta ürün sayısı, stok
  değeri ve kritik ürün sayısı (kırmızı rozet). services.STOCK_GROUPS, get_stock_summary()["groups"]. Üstteki kritik stok
  uyarısı ve özet kartları aynı. Eski şablon _yedek/stock_analysis_v93.html. Test 132.
- v95 GERÇEKÇİ STOK HAREKETLERİ + RENKLİ DURUM (kullanıcı isteği; betik _yedek/v95_stok_hareketleri_betigi.py, tohum 95,
  yedek _yedek/pasaport_otel_v95_oncesi.sql): 13.10–12.11.2026 her gece gün sonu tüketimi ve firesi gerçek konaklamalardan
  (consumption_day dolu; son gün sonu artık 12.11.2026), tekstilde ara sıra yıpranma, stok kritik seviyeye yaklaşınca
  tedarikçiye sipariş ve 1–4 gün sonra teslim (145 teslim edilmiş sipariş + alım hareketi; paket miktarı, fiyat -%1,5…+%3),
  31.10 ay sonu sayımı, kritik seviyeler ürüne göre ×0,8–1,3. Toplam 3.215 hareket.
  Bugün: 7 tükenmiş (%11), 14 kritik (%21; bir kısmının açık siparişi var), 45 yeterli; 8 açık sipariş.
  Stok analizi: Durum sütunu düğmeleri kırmızı "Stok bitti · sipariş verilmeli", koyu turuncu "Kritik · sipariş ver",
  turuncu çerçeveli "Kritik · siparişte", yeşil "Yeterli"; satır renkleri; kart başlıklarında "X tükendi / X kritik";
  özet kartları "Stokta bitmiş" ve "Kritik seviyede" ayrı. Sıralama: tükenmiş, kritik, yeterli.
  Etki: kapanmış aylar değişmedi (2025 aynı); alım fiyatı artışıyla misafir başı değişken maliyet ~+13 TL/gece, gelecek
  gece fiyatlarının 111/300'ünde ortalama +34 TL; 2026 sonucu -5 bin TL (açık Kasım). Test 132.
- Bekleyen: gün sonu 12.10.2026'dan beri çalıştırılmadı (kullanıcı şimdilik ertelendi).

## Sunum öncesi yapılacaklar (sunumdan 1–2 hafta önce, sırayla)

1. **Tarihe bağlı veriyi yenile.** Ekranlar "bugün"e göre çalışır. Aralık ortasında: fiyat takvimi Aralık'ı açar
   (fırtına haftası kırmızı, Yılbaşı yeşil: iyi), ama Rezervasyonlar ekranı Aralık–Mart'ı gösterir ve rezervasyon
   verisi 31.01.2027'de bittiği için Şubat ve Mart BOŞ görünür; Ekim–Kasım senaryoları geçmişte kalır. Yapılacak:
   sunum tarihine göre yeni dönem için rezervasyon ve fiyat kararları (`ileri_rezervasyonlar` benzeri, `--bitis`
   ileri alınır), gün sonu (`gun_sonu`) çalıştırılır, biten aylar otomatik kapanır.
2. **İki bulgu için karar ver ve savunmayı hazırla:**
   - Hedef kâr marjları (%62–80) piyasaya göre yüksek; takvim çoğunlukla sarı. Ya marjlar düşürülür ya da
     "zorlayıcı hedef" olarak savunulur.
   - Komisyon düşülünce 393 rezervasyonun 196'sı turuncu (Booking %17, Expedia %18, acenta %20). Kışın erken
     rezervasyon + süre + düşük doluluk indirimleri üst üste biniyor. Bulgu olarak sunulabilir ya da kural
     eklenebilir (ör. OTA'da daha yüksek fiyat, kışın indirim tavanı).
3. **Demo senaryosu ve slaytlar:** ekran sırası (ör. takvimde kırmızı geceyi göster → sebebini oku → Rezervasyon
   fiyatı ekranında aynı geceyi fiyatla → Rezervasyonlar'da renk dağılımı → Maliyet analizinde atıl kapasite).
4. **Jüriye söylenecekler:** veriler simülasyon (yöntem gerçek, rakamlar varsayım); TMS 2 stoklar içindir, burada
   normal kapasite mantığı yöntem olarak uygulandı; rezervasyon kaydı kapsam dışı (otelin kendi sistemi yapar).
5. **Son kontrol:** kurulum, `test`, bütün ekranlar, phpMyAdmin yedeği.

## Bilinçli kapsam dışı

- Rezervasyon modülü (kayıt, oda atama, iptal, müşteri bilgisi): otel yönetim yazılımının işi; yapılmayacak.
- Gerçek otel verisi yok; konaklamalar `gercekci_konaklama_olustur` simülasyonu + `ileri_rezervasyonlar`.
  Not: elle/komutla eklenen rezervasyonlar olduğu için `gercekci_konaklama_olustur` artık çalışmaz (elle girilmiş
  kayıtları korur); yeniden üretmek gerekirse önce `ileri_rezervasyonlar --sil`.

## Önemli yerler

- Fiyat kuralları: Admin paneli › Fiyat kuralları (doluluk bantları, erken rezervasyon, süre indirimi).
- Otel fiyat kararları: Admin paneli › Etkinlik takvimi, tür "Otel fiyat kararı" ("Yayında" işaretsizse taslak).
- Hesap motoru: `dashboard/services.py`; kuralları uygulayan: `dashboard/fiyat_kurallari.py`.
- Kod yedekleri: `_yedek/` (v35 … v45 tar.gz, her değişiklik öncesi).

---

# Tarihçe (16 Ekim 2026 ve öncesi; güncel durum yukarıda)

## Alınmış kararlar

- Bütün tutarlar KDV hariç. Veriler varsayıma dayalı model verisidir; sunumda varsayımlar tablosuyla verilecek.
- Personel: tek kalem, 3.000.000 TL/ay (12.10.2026'da 3,5 milyondan indirildi, piyasa fiyatı karşılaştırması sonrası), tamamen sabit, departman kırılımı yok. Muhasebe, pazarlama ve çamaşırhane
  çalışanları bu kalemin içinde.
- Bakım ve onarım: yarı değişken, 20 TL / satılan oda-gece.
- Enerji (Elektrik, Su ve atık su, Doğalgaz): yarı değişken, mevsim başına TEK kayıt (13.10.2026). Mevsimler
  `mevsim_aylari` tablosunda: Kış 12-1-2-3, Geçiş 4-5-10-11, Yaz 6-7-8-9. Mevsimli kayıt her yıl yalnız
  kendi aylarında geçerli; Ekim ve Aralık için ayrı satır gerekmez (eski 13 enerji satırı 9'a indi, migration 0019).
  Mevsimler fiyatlandırmada da kullanılacak.
- Doğalgaz değişken kısmı şimdilik oda başına (35 TL/oda-gece, geçiş dönemi). Sorun görülürse kişi başına alınacak
  (öneri: yaklaşık 23 TL/kişi-gece).
- Bina kiralık (800.000 TL/ay; 12.10.2026'da 1.527.600'den indirildi); bu yüzden bina amortismanı ve emlak vergisi yok.
- Mobilya ve demirbaş amortismanı: 300.000 TL/ay = 36 milyon TL yatırım ÷ 10 yıl ÷ 12 ay (varsayım).
- Bilgi işlem ve iletişim tek kalem (43.000 TL). Reklam ve tanıtım yalnızca dışarıya ödenen reklam harcaması (120.000 TL).
- Çamaşırhane otelin içinde; ayrı yıkama gideri yok (suyu ve elektriği enerjide, çalışanı personelde).
- Ortak giderler oda tipinin maliyet payı katsayısıyla ağırlıklı dağıtılır (toplam değişmez).
- Bütün oda tipleri en az 2 kişilik. Yatak düzeni: 1 kişi tek kişilik, 2 kişi çift kişilik, 3 kişi çift + tek,
  4 kişi iki çift kişilik yatak. Alez ve yorgan yatak başına.
- Misafirin kullandığı her şey kişi başına (kahvaltı, buklet, minibar, havlu, bornoz, yastık). Oda başına kalanlar:
  yatak takımları, ayak havlusu, banyo paspası.
- Yıllık doluluk varsayımı: Ocak %45 … Ağustos %88, yıl ortalaması yaklaşık %65 (örnek konaklamalar).

## Satış bilgisi, dönem kapanışı, fiyatlandırma dashboard'u (13.10.2026)

- Konaklamaya eklendi: gecelik satış fiyatı (TL, KDV hariç), satış kanalı (`satis_kanallari`), rezervasyon tarihi,
  durum (Onaylandı / İptal / Gelmedi). Yalnızca onaylı konaklama doluluğa ve gün sonuna girer.
- Kur tablosu YOK (kullanıcı kararı). Örnek fiyat: 85 € × 55,2325 (ECB 13.10.2026) = 4.694,76 TL, bütün konaklamalara.
- Dönem kapanışı OTOMATİK: biten ay, sonraki ayın 5. gününden sonra ana dashboard / maliyet analizi / fiyatlandırma
  ekranı açılınca kapanır (`donem_kapanislari`, `donem_giderleri`, `donem_maliyetleri`). Düzeltme sonrası admin >
  Dönem kapanışları > "güncel kayıtlarla yeniden kapat". `donemi_kapat` komutu yalnızca beklemeden kapatmak için.
- `/fiyatlandirma/`: ADR, RevPAR, oda-gece başına maliyet, sonuç, başabaş doluluğu; mevsim, oda tipi, kanal kırılımı.
- **Konuşulacak (kullanıcı ertelendi):** örnek konaklamaların yeni alanlarla (kanal, rezervasyon tarihi, oda tipine
  göre fiyat) yeniden üretilmesi. Şu an kanal ve rezervasyon tarihi boş, fiyat tek (85 €).

## Fiyat takvimi (13.10.2026)

- Kullanıcı kararları: temel fiyat = piyasa (elle, oda tipi × mevsim) + maliyet koruması; hedef marj (16.10.2026 güncel) standart %80,
  her üst oda tipinde -%3 (maliyet + marj); takvim Ekim 2026 – Aralık 2027; çakışmada en yüksek endeks.
- Tablolar: `temel_fiyatlar`, `etkinlikler` (42 kayıt; bazı 2027 tarihleri "tahmini"), `oda_tipleri.hedef_kar_marji`.
- Ekranlar: `/fiyat-takvimi/` (renkli gün kutuları, düz cümleli özet), `/fiyatlandirma/` "Satış ve kârlılık" oldu
  (teknik tablolar katlanır bölümlerde).
- 13.10.2026 eklendi: hafta günü endeksi (`hafta_gunu_endeksleri`: Cuma/Cmt +%10, Pazar -%5; etkinlikle en yüksek
  geçerli), kişi sayısı fiyatı (oda tipinde tek kişi indirimi %10, ek kişi 25 €), vergiler (`vergi_oranlari`: KDV %10;
  konaklama vergisi 1.5–31.12.2026 %1, 2027 %2), kanal komisyonu (Booking %17, Expedia %18, acenta %20; varsayım),
  maliyet analizi sayfası sadeleşti (düz cümleli özet, sade tablo, teknik döküm katlanır).
- 13.10.2026: oda tipleri otelin gerçek adlarına çevrildi (Standart, Superior, Luxury, Junior Suite, Deluxe,
  Executive Oda, Executive Suite); manzara odada (deniz / şehir / manzarasız), migration 0023. Temel fiyatlar
  kademeli (standart kış 85 € … Executive Suite yaz 235 €). Geçmiş etkinlikler (2025-2026 bayramlar, İEF) eklendi.
- `gercekci_konaklama_olustur`: 2025-01 – 2027-06 rezervasyon simülasyonu (kanal, rezervasyon tarihi, iptal,
  gelmedi, takvim fiyatı). Eski örnek konaklamaları siler, gün sonu ve kapanışları yeniden hesaplar.
- Rezervasyon hızı (bu yıl bugüne kadar satılan / geçen yıl aynı güne kadar) fiyat takviminde; beklenen doluluk
  bununla düzeltiliyor (±%25).
- 16.10.2026 kullanıcı bilgisi: ucuzdan pahalıya Standart (en küçük, manzarasız) < Superior (manzarasız; sırası
  varsayım) < Junior Suite (KARA manzaralı) < Luxury (şehir) < Deluxe (deniz) < Executive Oda / Suite (deniz,
  jakuzili; fiyatı teklifle). Manzara seçenekleri: deniz / şehir / kara / manzarasız. Migration 0024.
- 16.10.2026 hedef kâr marjı ters sıra (kullanıcı kararı): Standart %80, her üst tipte -%3 ... Executive Suite %62
  (migration 0025).
- Sıradaki adaylar: gerçek PMS verisi gelirse aktarım komutu; tahmini etkinlik tarihlerinin güncellenmesi.

## Açık işler

1. **Bitti (12.10.2026):** deterjan ve temizlik malzemeleri oda paketlerine bağlandı (`temizlik_sarfini_uygula`):
   oda temizliği oda başına, çamaşırhane sarfı kişi başına. Stok konaklamalara bağlandı: `gun_sonu` her gecenin
   tüketimini (kahvaltı + paket sarfı) stoktan düşer, fire ayrı hareket olarak yazılır.
   **Bitti:** stok sayfasında kritik stok uyarısı (tedarikçiye göre gruplu) ve tedarikçiye "Sipariş ver";
   Siparişler sayfasında "Teslim al" siparişi alım hareketi olarak stoğa işler (`siparisler`, `siparis_kalemleri`).
2. **Kararlar:** otel tek konseptle satar (oda + kahvaltı), paketlerin oda tipine göre aynı olması bilinçlidir.
   Varsayımların gerekçesi şimdilik yazılmayacak; bütün veriler doğru kabul ediliyor. Fiyatlandırmaya henüz geçilmeyecek.
3. Doğalgaz şimdilik oda başına; boş "Diğer giderler" grubu bekliyor.
4. Sonra: teorik tüketim ile sayım karşılaştırması (standart maliyet sapması), dinamik fiyatlandırma modülü.

Gün sonu düzenli çalıştırılmalı: `.venv\Scripts\python.exe manage.py gun_sonu` (stok azalınca alım girilir ya da `--ikmal`).

## Yedekler

`_yedek` klasöründe: her değişiklik öncesi proje kodu (`proje_*.tar.gz`) ve veri dökümü
(`veri_2026-10-11_maliyet_tamamlama_oncesi.json`, `veri.json`).

## Piyasa karşılaştırması (12.10.2026)

Sitedeki fiyatlar: standart oda 80-100 €, diğer odalar 120-130 € (1 € ≈ 55,2 TL). Kira 800 bin ve personel 3 milyonla
yıllık ortak gider 61,0 milyon TL, satılan oda-gece başına 4.775 TL. 2 kişilik tam maliyet (KDV hariç, kâr ve komisyon yok):
Standart 4.394 TL (80 €), Üst sınıf 4.990 (90 €), Deluxe 5.785 (105 €), Lüks 6.580 (119 €), Yönetici odası 7.375 (134 €),
Küçük süit 8.369 (152 €), Yönetici süiti 9.760 (177 €). Kahvaltı maliyeti (382 TL/kişi) otelin kahvaltı satış fiyatının
(9,62 € ≈ 531 TL) %72'si; sıradaki düzeltme adayı.

## Restoran sarfı (12.10.2026)

Kahvaltının servis edildiği restoranın sarfı (peçete, ıslak mendil, kürdan, amerikan servis, bulaşık deterjanı ve
parlatıcı) "Restoran malzemeleri" kategorisinde (gider merkezi: Restoran) envantere eklendi ve büfeye kişi başı kalem
olarak bağlandı (`restoran_sarfini_uygula`). Kişi başı ~6,83 TL. Raporlarda "Kahvaltı (gıda)" ve "Restoran sarfı" ayrı
sütun; ayrım ürünün kategorisinden gelir. Kahvaltı gıda fiyatlarını kullanıcı tek tek inceleyecek.

## Kahvaltı fiyatları (13.10.2026)

Kullanıcının güncel fiyat listesi (Kitap1.xlsx) gıda listesine işlendi; `gida_fiyatlarini_guncelle` stoktaki fiyatı
düzeltir. Miktarlar önceki düzeltmelerdeki gibi (70 g, çay 5 g, pastırma 30 g). Kahvaltı gıda maliyeti kişi başı
381,68 TL'den 303,98 TL'ye indi; restoran sarfı 6,83 TL.
