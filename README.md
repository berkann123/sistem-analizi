# İzmir Pasaport Pier Otel — Maliyet Muhasebesi

54 odalı butik otel için oda-gece maliyetini hesaplayan Django uygulaması. İçinde küçük bir stok takip modülü vardır. Uygulama konaklamaları ve doluluğu izler ama satış fiyatı belirlemez; fiyatlandırma modülünün ihtiyaç duyacağı **maliyet tabanını** üretir.

**Tüm tutarlar TL ve KDV hariçtir.** Otel KDV mükellefi olduğu için alış KDV'sini indirir; KDV maliyet değildir.

## Mimari

| Katman | Dosya | Görev |
|---|---|---|
| Veri | `dashboard/models/` | Tablolar, doğrulama kuralları, ilişkiler. Dört modüle bölünmüştür: `stok.py`, `maliyet.py`, `satis.py`, `kapanis.py` (+ ortak parçalar `ortak.py`) |
| Yönlendirme | `hotel_costs/db_router.py` | Hangi tablonun hangi veritabanında duracağı |
| Stok çekirdeği | `dashboard/stock.py` | Hareketli ağırlıklı ortalama (saf fonksiyon) |
| Otomasyon | `dashboard/signals.py` | Hareket kaydedilince ürünün stok ve maliyetini günceller |
| İş mantığı | `dashboard/services.py` | Maliyet motoru; view'lar yalnızca buradan veri alır |
| Ekranlar | `dashboard/views.py`, `templates/` | Dört dashboard + giriş sayfası |
| Veri girişi | `dashboard/admin.py` | Django admin |
| Testler | `dashboard/tests.py` | `python manage.py test` |

## Veritabanları

Aynı MySQL sunucusunda iki veritabanı vardır. Hangi tablonun nereye gideceğine `hotel_costs/db_router.py` karar verir.

| Veritabanı | İçerik | `.env` değişkeni |
|---|---|---|
| `pasaport_otel` | Otelin iş verisi: odalar, stok, reçeteler, giderler | `DB_NAME` |
| `pasaport_sistem` | Django'nun kendi tabloları: kullanıcılar, oturumlar, yetkiler, admin geçmişi | `DB_SYSTEM_NAME` |

Amaç, otel şemasını temiz tutmaktır: phpMyAdmin **Tasarımcı** ekranında yalnızca otel tabloları ve aralarındaki ilişkiler görünür. Bedeli: iki ayrı veritabanındaki tablolar arasında yabancı anahtar kurulamadığı için iş kayıtları kullanıcı tablosuna ilişkiyle bağlanamaz.

`pasaport_otel` içinde `django_migrations` adlı tek bir Django tablosu kalır. Django, hangi şema değişikliklerinin uygulandığını her veritabanında bu tabloda tutar; kaldırılamaz.

### Otel şemasının düzeni

- Her tablonun kimliği otomatik artan sayıdır (`id` = 1, 2, 3…). İlişki kolonları (`oda_tipi_id`, `urun_id`…) bu sayıyı taşır.
- Kolon sırası her tabloda aynı mantığı izler: kimlik → ilişkiler ve tanımlayıcı alanlar → sayısal değerler → açıklama → aktif/pasif.
- Otel veritabanında 22 tablo ve 1 görünüm vardır. Modüllere göre:
  - *Stok* (5): `tedarikciler`, `envanter_urunleri` (kategori ve tekstil yıpranma bilgileri dahil), `envanter_hareketleri`, `siparisler`, `siparis_kalemleri`
  - *Maliyet* (5): `oda_tipleri` (kış / geçiş / yaz piyasa fiyatları dahil), `odalar`, `aylik_gider_kategorileri`, `aylik_otel_giderleri`, `standart_tuketim` (reçete: kahvaltı büfesi ve oda paketi aynı tabloda; esas = kahvalti / oda_gecesi / kisi_gecesi)
  - *Satış* (5): `satis_kanallari`, `konaklamalar`, `etkinlikler`, `oranlar` (KDV, konaklama vergisi, yıllık hammadde fiyat endeksi; geçerlilik tarihli), `fiyat_kurallari` (tek satırlık ayar: mevsim ayları, doluluk bantları, erken rezervasyon, konaklama süresi ve son dakika indirimleri; Admin › Fiyat kuralları)
  - *Kapanış* (1): `donem_kapanislari` (ay başına bir satır; oda tipi × kişi birim maliyetleri `maliyetler` alanında)
  - v93 sadeleştirmesi: 23 → 16 tablo (temel_fiyatlar, envanter_kategorileri, tekstil_varliklari, kahvalti_bufesi_urunleri + oda_paketi, hammadde_fiyat_endeksi, mevsim_aylari, donem_maliyetleri birleştirildi; kahvalti_bufesi_gorunumu silindi). Admin'de kahvaltı büfesi ve oda paketi yine ayrı ekranlardır.
- Sabit, birkaç değerli listeler ayrı tablo değil seçim alanıdır: ürün birimi (adet, demet, kg, lt), gider grubu (Personel, Enerji, Bina, Bakım, Genel yönetim, Pazarlama, Amortisman, Diğer) ve mevsim (Kış, Geçiş, Yaz). Ürün kategorisi de sabit bir listedir; gider merkezi (mutfak, bar, restoran, kat hizmetleri) kategoriden türetilir. Tek kahvaltı büfesi vardır; büfe = `standart_tuketim` tablosunun esas = kahvalti satırları. Oda paketi oda tipine değil kişi sayısına bağlıdır (`standart_tuketim.misafir_sayisi`), çünkü bütün oda tiplerinde aynıdır. Hafta günü çarpanları `etkinlikler` tablosunda tür = *haftalık* kayıtlardır.
- Tablolar arası 17 yabancı anahtar vardır. Ürün → kategori, tedarikçi; hareket, tekstil varlığı, büfe satırı → ürün; oda, temel fiyat → oda tipi; konaklama → oda, satış kanalı; paket satırı → ürün veya tekstil; sipariş → tedarikçi; sipariş kalemi → sipariş, ürün; gider → gider kalemi; dönem maliyeti → dönem, oda tipi.
- Gider tabloları (kalem → aylık gider) yalnızca kendi aralarında bağlıdır; otelin geneline ait oldukları için bir odaya ya da ürüne bağlanmazlar. Bu bir eksik değil, verinin doğası.

**Görünüm:** v93'te `kahvalti_bufesi_gorunumu` silindi; kahvaltı büfesinin kişi başı maliyeti Admin › Kahvaltı büfesi ekranında ve Maliyet analizinde görünür.

## Kurulum (WampServer)

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`.env.example` dosyasını `.env` olarak kopyalayın, sonra:

```powershell
python manage.py veritabanlarini_kur
python manage.py createsuperuser --database=sistem
python manage.py seed_demo        # isteğe bağlı örnek veri
python manage.py runserver
```

`veritabanlarini_kur`, `migrate` komutunun yerini alır: iki veritabanını yoksa oluşturur ve her birinin tablolarını kurar ya da günceller. Kod güncellendikten sonra da aynı komut çalıştırılır.

Kullanıcılar `sistem` veritabanında durduğu için kullanıcıyla ilgili Django komutlarına `--database=sistem` eklenir:

```powershell
python manage.py createsuperuser --database=sistem
python manage.py changepassword berkan --database=sistem
```

### Ayrı veritabanı kullanıcısı (önerilir)

`root` ve boş parola yalnızca kendi bilgisayarınızda kabul edilebilir. Sunum veya paylaşım öncesi:

```sql
CREATE USER 'pasaport'@'localhost' IDENTIFIED BY 'guclu-bir-parola';
GRANT ALL PRIVILEGES ON pasaport_otel.* TO 'pasaport'@'localhost';
GRANT ALL PRIVILEGES ON pasaport_sistem.* TO 'pasaport'@'localhost';
GRANT ALL PRIVILEGES ON `test_pasaport_%`.* TO 'pasaport'@'localhost';  -- testler için
```

Sonra `.env` içinde `DB_USER` ve `DB_PASSWORD` değerlerini güncelleyin.

## Ekranlar

Bütün ekranlar giriş ister (`/giris/`).

- `/` — Ana Sayfa: üç özet kartı, kartın tamamı ilgili ekrana götürür (`services.home_summary`). **Maliyet** (son tamamlanan ay: 2 kişilik oda-gece tam maliyeti en ucuz–en pahalı tip, aylık ortak gider, doluluk / normal doluluk, boş odaların maliyeti) → Maliyet analizi; **Fiyat ve satış** (içinde bulunulan ay: oda geliri, komisyon, bugün dolu oda, doluluk, ADR, son kapanan ayın sonucu) → Satış ve kârlılık; **Stok** (stok değeri, kritik ürün, açık sipariş, son gün sonu; gün sonu geride kaldıysa uyarı) → Stok analizi.
- `/rezervasyon-maliyeti/` — Rezervasyon (menüde Ana Sayfa'nın altında): oda tipi, kişi sayısı ve tarihler girilir; gece gece fiyat, indirimler, misafirin ödeyeceği tutar, otele kalan ve kâr. Maliyet ayrıntısı katlanır bölümdedir ve tam maliyetle aynı esastadır.
- `/maliyet/` — Aylık analiz. Üstte düz cümleli özet (ortak gider, doluluk, satılan oda başına pay, boş odaların maliyeti) ve örnek bir odanın maliyet dağılımı; altta oda tipi × kişi sayısına göre sade tablo (oda satılınca oluşan gider, ortak gider payı, otele maliyeti). Yılın aylık özeti ve kalem kalem teknik döküm katlanır bölümlerdedir. Açılınca son **tamamlanmış** ay gösterilir (doluluk ve atıl kapasite ay bitince kesinleşir). Üstte yılın aylık özeti: her ay için doluluk, ortak gider, satılan oda-gece başına pay, karşılanan kısım ve atıl kapasite maliyeti; aya tıklanınca o ayın oda tipi × kişi sayısı tablosu açılır.
- `/rezervasyonlar/` — Rezervasyonlar: içinde bulunulan ay ve sonraki 3 ayda giriş yapacak onaylı rezervasyonlar; satış fiyatı, kanal komisyonu, tam maliyet, kâr (satış − komisyon − tam maliyet), renk (otele kalan tutara göre: hedefte / kârlı / katkı / zarar) ve fiyatı etkileyen sebepler (otel kararı, etkinlik, erken rezervasyon, konaklama süresi, komisyon). Üstteki kutular renge göre süzer, ay seçilebilir.
- `/fiyat-takvimi/` — Fiyat takvimi: ay, oda tipi ve kişi sayısı seçilir; üstte fiyat aralığı ve dört maliyet sınırı (temel fiyat, oda gideri, tam maliyet, hedef fiyat). Her gece için kart: önerilen fiyat, durum rengi, gecenin etkisi, doluluk ve gecelik kâr; zarar ve hedefteki gecelerde kısa sebep. Karta gelince misafirin vergilerle ödeyeceği tutar görünür.
- `/fiyatlandirma/` — Satış ve kârlılık: yıl seçilir; düz cümleli yıl özeti; aylık doluluk, oda geliri, ADR (ortalama gecelik fiyat), RevPAR (müsait oda başına gelir), satılan oda-gece başına maliyet, sonuç, marj ve başabaş doluluğu. Fiyat ile maliyetin aylara göre grafiği; mevsim, oda tipi ve satış kanalı kırılımları. Kapanmış aylar o ayın fiyatlarıyla dondurulmuş değerlerle, diğerleri güncel kayıtlarla hesaplanır; gelecek aylar eldeki onaylı konaklamalardır.
- `/stok/` — Eldeki miktar, stok değeri ve kritik seviyedeki ürünler. Kritik seviyeye inen ürünler sayfanın başında tedarikçiye göre gruplanmış bir uyarıda listelenir; her tedarikçi için **Sipariş ver** butonu vardır.
- `/stok/siparis/<tedarikçi>/` — Sipariş formu: tedarikçinin ürünleri, kritik olanlarda önerilen miktar (stoğu 3 × kritik seviyeye tamamlayan, açık siparişler düşülmüş) ve son alım fiyatı dolu gelir.
- `/stok/siparisler/` — Siparişler: açık siparişler **Teslim al** ile stoğa girer, **İptal** edilebilir; tedarikçinin e-postası varsa sipariş e-postayla gönderilebilir.
- `/admin/` — Veri girişi.

## Maliyet kuralları

**Değişken maliyet** (oda satılmazsa oluşmaz):

- Kahvaltı: büfedeki aktif satırların kişi başı miktar × (1 + fire) × ürün maliyeti × kişi sayısı. Büfe satırları iki türdür: ürün kategorisi mutfak/bar ise **gıda**, değilse **restoran sarfı** (peçete, ıslak mendil, bulaşık deterjanı vb.). Tür ayrıca saklanmaz, ürünün kategorisinden gelir; raporlarda iki ayrı sütun olarak gösterilir. Kaynak: Admin → *Kahvaltı büfesi* (tek büfe; satır pasif yapılırsa hesaba girmez).
- Buklet/minibar: oda paketindeki miktar × (1 + fire) × ürün maliyeti. Paket kişi sayısına göre seçilir (Admin → *Oda paketi*); bütün oda tiplerinde aynıdır.
- Kişi başına / oda başına ayrımı: misafirin kullandığı her şey (kahvaltı, buklet, minibar, havlu, bornoz, yastık) kişi sayısıyla çarpılır. Oda başına kalanlar yalnızca odaya, banyoya ya da yatağa bağlı olanlardır (yatak takımları, ayak havlusu, banyo paspası). Yeni paket bileşeninin varsayılan esası kişi başınadır.
- Yatak düzeni kişi sayısına bağlıdır: oda 1 kişilik satılırsa tek kişilik, 2 kişilik satılırsa çift kişilik yatak takımıyla hazırlanır; 3 kişide çift + tek, 4 kişide iki çift kişilik yatak vardır. Bütün oda tipleri en az 2 kişiliktir. Pakette yalnızca o kişi sayısında kullanılan takımlar bulunur.
- Tekstil: (stok kartındaki ortalama maliyet − hurda değeri) × set adedi ÷ kullanım ömrü (oda-gece).
- Enerji: ayrı bir tarife tablosu yoktur. Elektrik, su ve doğalgazın misafirle artan kısmı, aşağıdaki aylık giderlerin değişken birim tutarı olarak girilir.

Fire oranı olarak satırdaki ve ürün kartındaki oranlardan **büyük olanı** alınır.

**Aylık giderler** üç maliyet davranışından birini taşır (Admin → *Aylık gider kategorileri*):

| Davranış | Anlamı | Odaya nasıl yüklenir | Örnek |
|---|---|---|---|
| Sabit | Otel boş da olsa oluşur | Aylık tutar ÷ (aktif oda × ayın günü) | Kira, sigorta |
| Yarı değişken | Sabit taban + dolulukla artan kısım | Taban sabit gibi bölünür; değişken tutar satılan her oda-geceye (ya da kişi-geceye) eklenir | Elektrik, su, doğalgaz, bakım |
| Değişken | Yalnızca oda satılınca oluşur | Satılan her oda-geceye doğrudan eklenir, bölünmez | Dışarıdan alınan, satışa bağlı bir hizmet |

Gider kaydında iki tutar alanı vardır: **aylık sabit tutar** ve **değişken birim tutar**. Sabit kalemde yalnızca ilki, değişken kalemde yalnızca ikincisi, yarı değişken kalemde ikisi doldurulur. Değişken birim tutarın neyle çarpılacağını kalemin **değişken tutar esası** belirler:

| Esas | Ne zaman | Örnek |
|---|---|---|
| Oda-gece | Tüketim odaya bağlıysa | Oda kliması, bakım |
| Kişi-gece | Tüketim kişiye bağlıysa | Su |
| Konaklama | Gece sayısından bağımsız, her giriş-çıkışta bir kez oluşuyorsa | Dışarıya yıkatılan çarşaf (şu an kullanan kalem yok) |

Konaklama başına giderler rezervasyon hesabına bir kez eklenir; bu yüzden uzun konaklamanın gecelik maliyeti kısa konaklamadan düşüktür. Aylık tabloda bu giderler, o ay giriş yapan konaklamaların ortalama gece sayısına bölünerek geceye çevrilir (konaklama kaydı yoksa 2 gece varsayılır).

**Tekrar bitiş tarihi** çoğu giderde boş bırakılır. Doldurulursa gider o tarihten sonraki aylarda hesaba girmez.

**Oda tipi payı:** ortak giderler bütün odalara eşit bölünmez. Her oda tipinin bir **maliyet payı katsayısı** vardır (Admin → *Oda tipleri*; odanın büyüklük ve donanım ölçüsü). Hesap iki adımdır:

1. Ortalama oda payı = aylık tutar ÷ (aktif oda × 365/12 gün). Yıllık esas: ayın 28 ya da 31 gün çekmesi gecenin maliyetini değiştirmez; yıl boyunca tam tutar dağıtılır.
2. Oda tipinin payı = ortalama oda payı × katsayı ÷ aktif odaların ortalama katsayısı.

Odaların oranlarının ortalaması 1 olduğu için dağıtılan toplam gider değişmez; yalnızca süit, standart odadan daha fazla pay alır. Aynı oran giderlerin oda-gece başına değişken kısmına da uygulanır; kişi-gece ve konaklama başına olanlara uygulanmaz. Manzara maliyeti değil fiyatı etkiler; paya girmez.

Her gider kaleminin bir **grubu** vardır (kalemde seçilir): Personel, Enerji, Bina, Bakım ve onarım, Genel yönetim, Pazarlama ve satış, Amortisman, Diğer. Maliyet analizi sayfası giderleri bu sırayla grup grup gösterir.

**Enerji giderleri** grubu üç kalemden oluşur: Elektrik, Su ve atık su, Doğalgaz. Her biri yarı değişkendir: *aylık sabit tutar* otel boşken de gelen faturadır (lobi, asansör, soğutucular, ısıtma); *değişken birim tutar* misafirle artan tüketim × birim fiyattır. İkisini ayırırken dikkat: sektör ölçütleri (ör. 45 kWh/oda-gece) otelin tamamının tüketimidir; bunu değişken tutar olarak girip üstüne bir de sabit taban eklemek ortak alan enerjisini iki kez saymak olur.

Enerji **mevsime** göre değişir. Mevsimler fiyat kurallarındaki "mevsim ayları" alanındadır (her ayın mevsimi; Admin › Fiyat kuralları): Kış (Aralık–Mart), Geçiş (Nisan–Mayıs, Ekim–Kasım), Yaz (Haziran–Eylül). Gider kaydında **Mevsim** seçilirse kayıt yalnızca o mevsimin aylarında ve **her yıl** geçerli olur; bu yüzden her enerji kalemi için mevsim başına tek kayıt yeterlidir (Elektrik, Doğalgaz, Su: 3'er kayıt). Mevsim seçilmeyen kayıt eskisi gibi, aynı kalemin sonraki kaydına kadar her ay geçerlidir. Mevsimli kayıt 'her ay tekrarlar' olmalı ve ayı mevsimin aylarından biri olmalıdır (admin bunu denetler).

Yarı değişken bir gideri parçalarına ayırmak için yüksek-düşük yöntemi kullanılabilir: en dolu ve en boş ayın gider farkı, satılan oda-gece farkına bölünür (değişken birim tutar); kalan kısım sabit tabandır.

Hangi ayda hangi kaydın geçerli olduğu:

- Bir gider kaleminin bir ayda en fazla bir kaydı olur; aynı kalem aynı aya ikinci kez girilemez.
- Aynı kalemin farklı aylara ait kayıtları tekrar değil, tutarın geçmişidir. Admin listesindeki "Bu ay geçerli" sütunu hangisinin hesaba girdiğini gösterir.
- Kalemin o aya ait kaydı varsa o ay için o geçerlidir.
- Yoksa aynı kategorideki en son "her ay tekrarlar" kaydı devreder.
- Sonuç: Kasım'a zamlı kira girildiğinde Ekim'deki tekrarlayan kira ile birlikte iki kez sayılmaz.

**Doluluk ve atıl kapasite:** Doluluk elle girilen bir sayı değildir; **konaklama** kayıtlarından hesaplanır (Admin → *Konaklamalar*: oda, giriş tarihi, çıkış tarihi, misafir sayısı). Giriş günü dahil, çıkış günü hariçtir. Aynı oda aynı gece iki konaklamaya verilemez.

- Bir odanın bugün dolu olup olmadığı Admin → *Odalar* listesindeki "Bugün" sütununda görünür. Bu, odada saklanan bir alan değildir; konaklamalardan türetilir. Odanın **durum** alanı ise yalnızca satılabilirliği söyler (aktif, bakımda, pasif).
- Ayın doluluğu = dolu oda-gece ÷ müsait oda-gece. İçinde bulunulan ayda yalnızca bugüne kadar geçen günler sayılır.
- Konaklama kaydı olan aylarda rapor üç şey daha gösterir: gerçekleşen doluluk, satılan oda başına sabit pay (pay ÷ doluluk) ve atıl kapasite maliyeti: (sabit giderler + yarı değişken tabanlar) × (1 − doluluk). Değişken kısım atıl kapasiteye girmez; oda satılmadıysa o gider oluşmamıştır.

Fiyatlandırma için iki eşik:

1. **Kısa vadeli taban = değişken maliyet** (reçeteler ve giderlerin değişken kısmı). Bunun altındaki her satış zarar yazar.
2. **Uzun vadeli hedef = normal dolulukta tam maliyet.** Sabit giderlerin de karşılanması için ortalama fiyatın ulaşması gereken düzey. Normal kapasite kullanılır (TMS 2 md. 13): boş geçen bir ayın atıl kapasite maliyeti dönem gideridir, dolu odaların fiyatına yüklenmez. Aradaki fiyatlar (değişken maliyetin üstü, tam maliyetin altı) zarar değil **katkıdır**: oda boş kalmasından iyidir.

**Sabit giderin satışla karşılanması (v54):** her ay, satılan oda-gecelerin normal dolulukla fiyatlanmış ortak gider payı toplamı ayın ortak gideriyle karşılaştırılır: kışın eksik (−), yazın fazla (+) karşılanır. Mevsimsellik normal kabul edildiği için olağan dışı boşluk ay ay değil, seçilen ayla biten 12 ayın NET eksiği olarak söylenir (`absorption_window`). Aşağıdaki aylık olağan dışı atıl kapasite tanımı eskidir.

**Atıl kapasite iki ölçüyle gösterilir** (Maliyet analizi): *boş kapasitenin payı* = ortak gider × (1 − doluluk), kapasitenin %100'üne göre boş kalan bütün oda-gecelerin payı (yönetim göstergesi); *olağan dışı atıl kapasite* = ortak gider × (1 − doluluk ÷ normal doluluk), yalnızca normal doluluğun altında kalan boşluğun payı (TMS 2 md. 13'teki normal kapasite mantığı; TMS 2 stoklar içindir, burada yöntem olarak uygulanır). Ayın normal doluluğu o ayın sonu itibarıyla son 12 biten ayın ortalamasıdır; doluluk normalin üstündeyse olağan dışı atıl kapasite sıfırdır.

### Satış bilgisi ve dönem kapanışı

Konaklama kaydında satış bilgisi vardır: **gecelik satış fiyatı** (TL, KDV hariç; bütün misafirler için oda fiyatı), **satış kanalı** (`satis_kanallari` tablosu: web sitesi, telefon, kapıdan, Booking.com, Expedia, acenta; admin'den eklenebilir), **rezervasyon tarihi** (giriş tarihinden sonra olamaz) ve **durum**. Toplam tutar saklanmaz (gecelik fiyat × gece). Durum yalnızca *Onaylandı*, *İptal edildi* ve *Misafir gelmedi* değerlerini alır; konaklamanın geçmişte mi gelecekte mi olduğu tarihlerden bellidir. Doluluğa, gün sonu stok tüketimine ve satışa yalnızca onaylı konaklamalar girer; iptal edilen konaklama odayı tutmaz. Sistemde kur tablosu yoktur: euro fiyat bir kez TL'ye çevrilip girilir (85 € × 55,2325).

**Dönem kapanışı:** biten ay, sonraki ayın 5. gününden sonra bir ekran açılınca kendiliğinden kapanır (süre `.env` içinde `DONEM_KAPANIS_GUN`). Kapanışta o ayın fiyatlarıyla `donem_kapanislari` tablosuna ay başına bir satır yazılır: müsait ve satılan oda-gece, oda geliri, kanal komisyonu, değişken gider toplamı, ortak gider toplamı ve `maliyetler` alanında oda tipi × kişi sayısı birim maliyetleri (oda satılınca oluşan gider ve ortak gider payı). Doluluk, sonuç ve oda başı maliyet saklanmaz, bu sayılardan hesaplanır. Giderler kopyalanmaz; gider kayıtları zaten aya göre tarihlidir. Kapanmış ayda ürün fiyatı, komisyon oranı ya da oda sayısı sonradan değişse de doluluk, maliyet ve sonuç değişmez. Kalem kırılımı (kahvaltı, sarf, tekstil...) saklanmadığı için kapanmış ayda yalnızca iki toplam gösterilir. Kapanış yalnızca arka planda çalışır: ayrı bir ekranı ve "Yeniden kapat" seçeneği yoktur (v57, kullanıcı kararı). Kapanmış ayların sonuçları Maliyet analizindeki aylık özet tablosunda "Kapandı" etiketiyle görünür.

### Oda tipleri ve manzara

Oda tipleri otelin adlarıyla, ucuzdan pahalıya: Standart Oda (en küçük ve en ucuz), Superior Oda, Junior Suite, Luxury Oda, Deluxe Oda, Executive Oda (jakuzili), Executive Suite (jakuzili). Executive odaların sitede sabit fiyatı yoktur, teklifle satılır; temel fiyatları teklif için başlangıç önerisidir. **Manzara oda tipinin adında değil, odada** tutulur (`odalar.manzara_tipi`: deniz / şehir / kara manzaralı / manzarasız): Standart ve Superior manzarasız, Junior Suite kara, Luxury şehir, Deluxe ve Executive odalar deniz manzaralı. Maliyet payı katsayıları ve hedef kâr marjları bu kalite sırasına göre dağıtılmıştır.

### Rezervasyon hızı

Fiyat takviminde içinde bulunulan ve gelecek aylar için: bu ay için **bugüne kadar** satılan oda-gece, geçen yıl **aynı güne kadar** satılanla karşılaştırılır (rezervasyon tarihine göre). Beklenen doluluk, geçen yılın aynı ayının doluluğu bu hızla düzeltilerek bulunur (en fazla ±%25). Beklenen doluluk talebi ve atıl kapasiteyi gösterir; başabaş ve hedef fiyat bununla değil, normal dolulukla hesaplanır. Önde olmak talebin güçlü olduğunu, geride olmak fiyatın yüksek ya da talebin zayıf olduğunu gösterir.

### Fiyat takvimi

Üç katman: **maliyet sınırları** (sistem hesaplar), **temel fiyat** (piyasaya göre elle girilir) ve **etkinlik endeksi**.

- *Oda satılınca oluşan gider* (değişken maliyet, 2 kişi): bunun altındaki fiyat her satışta zarar yazar.
- *Tam maliyet (başabaş)* = değişken maliyet + oda tipinin ortak gider payı ÷ **oda tipinin normal doluluğu** (son 12 ayda o tipin satılan ÷ müsait oda-gecesi; veri yetersizse otelin normal doluluğu). Az satılan tip boş gecelerinin payını kendi fiyatında taşır.
- *Normal doluluk*: son 12 biten ayın dolu oda-gece toplamı ÷ müsait oda-gece toplamı. Bu 12 ayın en az 6'sında konaklama verisi yoksa varsayım kullanılır: %70 (`.env` içinde `NORMAL_DOLULUK=0.70` ile değiştirilebilir).
- *Hedef fiyat* = başabaş × (1 + oda tipinin **hedef kâr marjı**). Marj oda tiplerinde (`oda_tipleri.hedef_kar_marji`): en ucuz oda en yüksek marjla başlar: Standart Oda %80, her üst oda tipinde %3 azalır (Superior %77, Junior Suite %74, Luxury %71, Deluxe %68, Executive Oda %65, Executive Suite %62).
- *Beklenen doluluk*: biten ayda gerçekleşen; içinde bulunulan ve gelecek ayda geçen yılın aynı ayı (rezervasyon hızıyla düzeltilir), o da yoksa eldeki onaylı konaklamalar. Maliyete girmez; normalin altındaysa takvim atıl kapasite uyarısı verir.
- *Durumlar*: fiyat değişken maliyetin altında → **Zarar: satılmamalı**; değişken maliyet ile tam maliyet arasında → **Katkı sağlıyor** (zarar değil); tam maliyet ile hedef arasında → **Kârlı, hedefin altında**; hedefin üstünde → **Hedefte**.
- *Doluluk etkisi* (oranlar `fiyat_kurallari` tablosunda, Admin › Fiyat kuralları ekranından değiştirilir; `dashboard/fiyat_kurallari.py` yalnızca uygular): gece fiyatı ayrıca gecenin doluluğuna göre çarpılır. Başlangıç: %0–50 → %5 indirim, %50–70 → %5 artış, %70–90 → %15 artış, %90–100 → %30 artış. Doluluk **anlıktır**: rezervasyon anında o gece için satılmış oda ÷ aktif oda (fiyat takviminde bugün itibarıyla, rezervasyon ekranında girilen rezervasyon tarihi itibarıyla). Tahmin ya da geçmiş yıl verisi kullanılmaz; geçmiş gecede sonuç gerçekleşen dolulukta. Uzak tarihler henüz az satıldığı için çoğunlukla %0–50 bandına düşer ve %5 indirim alır; erken rezervasyon indirimiyle üst üste biner. Otelin fiyat kararı olan gecelerde doluluk etkisi uygulanmaz. **Gece fiyatı = temel fiyat × gecenin endeksi × doluluk çarpanı**, sonra kişi sayısına göre.
- *Konaklama indirimleri* (Rezervasyon fiyatı ekranı, `stay_price_quote`; oranlar Admin › Fiyat kuralları): gece fiyatlarının toplamına sırayla uygulanır. İsteğe bağlı satış kanalı seçilirse komisyon düşülür; kâr ve renk otele kalan tutara göre verilir. Başlangıç oranları: erken rezervasyon (girişten en az 30 gün önce) %15; konaklama süresi 3–5 gece %5, 6–14 gece %8, 15 gece ve üzeri %12. İkisi çarpılır (%15 ve %12 birlikte %25,2). Ekran gece gece fiyatı, indirimleri, misafirin ödeyeceğini (vergiler dahil) ve konaklamanın tam maliyete göre durumunu (hedefte / kârlı / katkı / zarar) gösterir. Örnek konaklama üreticisi (`gercekci_konaklama_olustur`) kendi basit indirim kurallarını kullanır; bu kurallar yalnızca öneri fiyatına uygulanır.
- *Otel fiyat kararı* (`etkinlikler`, tür *Otel fiyat kararı*; `yayinda` işaretsizse taslaktır: takvimde görünür, rezervasyon fiyatına uygulanmaz): dış etkinlik değil, otelin kendi kararı (talep artışı, kampanya, indirim). Girildiği gecede otomatik "en yüksek endeks" kuralının yerine geçer; endeks 0,00–3,00 olabilir (dış etkinliklerde en az 0,50). Açıklaması zorunludur ve takvimde gecenin gerekçesi olarak yazılır. Örnek konaklama üreticisi bu kararları talep tahminine katmaz. Ekim 2026 (migration 0028: Fashion Prime fuarı +%40 20–22 Ekim, flash kampanya taslağı −%90 24–25 Ekim, son dakika indirimi −%30 26–27 Ekim) ve Kasım 2026 için üçer örnek karar yüklüdür (kaynak: "örnek senaryo"). Kasım: MOTTA fuarı yoğun talep fiyatı +%40 (4–7 Kasım, hedefte), hafta içi son dakika indirimi −%30 (17–18 Kasım, katkı sağlıyor), Black Friday kampanyası taslağı −%90 (27–28 Kasım, zarar).
- *Açıklamalı geceler*: takvim kutusunda hedefte, katkı sağlayan ve zarar yazan gecelerin kısa sebebi yazar; takvimin altındaki tabloda sebep, sonucu ve "indirim en fazla %… olmalı" önerisi düz cümleyle verilir. Kârlı ama hedefin altındaki geceler olağan durum sayılır, gerekçe yazılmaz.
- *Temel (piyasa) fiyat* (`oda_tipleri.kis_fiyati / gecis_fiyati / yaz_fiyati`): oda tipi × mevsim, 2 kişi oda + kahvaltı, TL, KDV hariç. Başlangıç değerleri sitedeki fiyat aralığından (standart 80/90/100 €, diğerleri 120/125/130 €; kış/geçiş/yaz) 55,2325 kurla çevrildi; admin'de listeden düzenlenir.
- *Hafta günü endeksi* (`etkinlikler`, tür *haftalık*, hafta günü seçili): her gece için çarpan (başlangıç: Cuma ve Cumartesi +%10, Pazar −%5, diğer geceler etkisiz). Etkinliklerle birlikte değerlendirilir: o gecenin hafta günü ve etkinlik endekslerinden **en yüksek olanı** uygulanır.
- *Kişi sayısı*: temel fiyat 2 kişiliktir. Oda tipinde *tek kişi indirimi* (başlangıç %10) ve *ek kişi ücreti* (2'den sonraki her kişi için gecelik, başlangıç 25 € = 1.380,81 TL, endeksle çarpılmaz) vardır. Takvimde kişi sayısı seçilir; maliyetler de o kişi sayısına göre hesaplanır.
- *Vergiler* (`oranlar`, geçerlilik tarihli; aynı tabloda yıllık hammadde fiyat endeksi): KDV %10; konaklama vergisi %2, 1.5.2026–31.12.2026 arası geçici %1, 1.1.2027'den %2 (geçici indirim uzatılırsa güncellenmeli). İkisi de KDV hariç bedel üzerinden ayrı hesaplanır; takvim kutusunun üstüne gelince misafirin ödeyeceği vergiler dahil fiyat görünür.
- *Kanal komisyonu* (`satis_kanallari.komisyon_orani`, varsayım): doğrudan satış %0, Booking.com %17, Expedia %18, acenta %20. Takvim, temel fiyatla satışta her kanaldan otele kalan tutarı ve bunun maliyete göre durumunu gösterir; satış ve kârlılık hesabında ödenen komisyon gider olarak düşülür.
- *Etkinlik takvimi* (`etkinlikler`): ad, tür (fuar, milli bayram, dini bayram, festival, spor, özel gün), ilk ve son gece, fiyat endeksi (1,40 = +%40), tarih tahmini mi, kaynak. Tarihler GECE olarak girilir; fuarlarda katılımcılar bir gün önce geldiği için geceler fuar açılışından bir gün önce başlar. Aynı geceye birden çok etkinlik denk gelirse en yüksek endeks geçerlidir. Ekim 2026 – Aralık 2027 takvimi yüklüdür: dini bayram tarihleri Diyanet takviminden, fuarlar İZFAŞ (Fuar İzmir) takviminden; 2027 tarihi henüz açıklanmamış etkinlikler (İEF, caz festivali, maraton, kitap fuarı, İzmir Festivali, TTI) "tahmini" işaretlidir ve açıklanınca güncellenmelidir. Endeksler varsayımdır.

## Stok kuralları

Stok ve birim maliyet elle yazılmaz; **stok hareketlerinden** hesaplanır.

- Yöntem: **hareketli ağırlıklı ortalama.** Her alımda ortalama, o an depoda kalan stok ile yeni gelen malın değerinden yeniden hesaplanır. Tüketim ortalamayı değiştirmez.
- Miktar her zaman pozitif girilir; yönü hareket türü belirler. Yalnızca *sayım düzeltmesi* eksi olabilir.
- Stok eksiye düşürülemez; birim maliyet negatif olamaz.
- Hareket tarihi elle seçilebilir (geçmiş tarihli fatura). Kaydın girildiği an ayrıca saklanır.
- Hareketi olan ürün silinemez. Kullanılmayan ürünün "Aktif" işaretini kaldırın.
- Tedarikçi serbest metin değil, ayrı bir tablodur (Admin → *Tedarikçiler*); ürün kartında listeden seçilir.
- Tekstil de bir envanter ürünüdür (stok kartı vardır). Yıpranma bilgileri (kullanım ömrü, hurda değeri, oda başı set sayısı) v93'ten beri doğrudan stok kartındadır (`envanter_urunleri.tekstil_*`); ömrü girilmiş ürün tekstil sayılır. Set maliyeti stok kartındaki ortalama maliyettir.

**Sipariş (satın alma):** `siparisler` (tedarikçi, tarih, durum: açık / teslim alındı / iptal) ve `siparis_kalemleri` (ürün, miktar, birim fiyat) tablolarında tutulur. Sipariş stoğu değiştirmez; açık siparişteki miktar stok sayfasında "siparişte" olarak görünür ve aynı ürünün yeniden sipariş edilmesini önler. **Teslim al** her kalem için siparişteki fiyatla bir alım hareketi yazar; stok ve hareketli ortalama maliyet bu hareketlerden güncellenir. Teslim alınmış ya da iptal edilmiş sipariş tekrar teslim alınamaz.

**Gün sonu (konaklamadan stok tüketimi):** `gun_sonu` komutu her gece için o gece konaklayan odaların tüketimini reçeteye göre hesaplar ve stoktan düşer:

- Kahvaltı: büfedeki kişi başı miktar × o gece konaklayan kişi sayısı.
- Oda paketi: buklet, minibar, oda temizliği (oda başına) ve çamaşırhane sarfı (kişi başına).
- Tekstil düşülmez: tüketilmez, yıpranır; maliyete yıpranma payıyla girer.

Her ürün için gecede bir *tüketim* ve bir *fire* hareketi yazılır; hareketin `tuketim_gunu` kolonunda o gecenin tarihi durur. Aynı ürünün aynı gecesi ikinci kez düşülemez (veritabanı kuralı). Bir ürün, ilk alımından önceki gecelerden düşülmez. Stok yetmezse o ürün o gece için işlenmez ve uyarılır; alım girildikten sonra gün sonu yeniden çalıştırılınca kalan geceler işlenir. `--ikmal` ile stok kritik seviyenin altına inecekken otomatik alım girilir (örnek veri için). Gün sonu yapılmış geceye sonradan eklenen konaklama stoktan düşülmez (gün kapanmıştır).

İlişki kolonlarında yalnızca kimlik numarası durur (ör. `urun_id = 7`); ürün adı, kategori ve birim başka tablolara kopyalanmaz. Okunurluk için tek görünüm `kahvalti_bufesi_gorunumu`dur; tetikleyici (TRIGGER) yoktur. Görünüm ve tetikleyiciler bir migration içinde `RunSQL` ile tanımlanır ki veritabanı sıfırdan kurulduğunda da oluşsunlar.

## Komutlar

| Komut | Ne yapar |
|---|---|
| `python manage.py test` | Otomatik testleri geçici bir veritabanında çalıştırır |
| `python manage.py seed_demo` | 54 oda ve örnek veri. Tekrar çalıştırılabilir; Admin'de düzenlenmiş büfe/paketlerin üzerine yazmaz |
| `python manage.py gercekci_konaklama_olustur` | **Önerilen örnek veri.** 2025-01-01 – 2027-06-30 için rezervasyon sürecini taklit eder: hedef doluluk (mevsim × hafta günü × etkinlik), oda tipi tercihi, kişi sayısı, satış kanalı (Booking %42, web %20, acenta %12, Expedia %10, telefon %10, kapıdan %6), kanala göre ne kadar önceden rezervasyon yapıldığı, iptal (Booking %18 … doğrudan %5) ve gelmeme kayıtları, fiyat takviminden fiyat (web sitesinde %5 doğrudan indirim, erken/son dakika indirimi, 2025 fiyatları kur farkıyla %80). Bugünden sonrası için yalnızca bugüne kadar alınmış rezervasyonlar kalır. Eski örnek konaklamaları siler, gün sonu tüketimini ve kapanmış ayları yeni veriyle yeniden hesaplar; elle girilmiş konaklama varsa çalışmaz. `--tohum` aynı veriyi üretir, `--onizle` |
| `python manage.py gun_sonu` | Gün sonu: bugüne kadar işlenmemiş gecelerin konaklama tüketimini stoktan düşer. `--kadar 2026-10-31` ile belirli bir geceye kadar (ileri tarih simülasyondur), `--ikmal` ile stok azalınca otomatik alım, `--onizle` ile önizleme |
| `python manage.py ornek_kritik_stok` | Gösterim için 10 ürünün stoğunu kritik seviyenin %70'ine indirir (eksi sayım düzeltmesi, model verisi); stok sayfasındaki uyarı ve sipariş akışı görünür olsun diye |
| `python manage.py veri_denetimi --yil 2026` | Maliyet hesabını etkileyen veri eksiklerini listeler (paket, büfe, ürün, gider, doluluk). Hiçbir şeyi değiştirmez |
| `python manage.py ileri_rezervasyonlar` | Önümüzdeki dönemin rezervasyonları: iki otel fiyat kararını (Yılbaşı gala gecesi +%80, Aralık fırtına haftası kampanyası −%85) ve 21 rezervasyonu ekler, sonra bugünden `--bitis` tarihine (varsayılan 2027-02-01) kadar giriş yapacak bütün onaylı rezervasyonların gecelik fiyatını fiyat kurallarıyla yeniden hesaplar (rezervasyon anındaki doluluk, erken rezervasyon, konaklama süresi; taslak kararlar uygulanmaz). Tekrar çalıştırılabilir; `--onizle`, `--sil` |
| `python manage.py veritabanlarini_kur` | İki veritabanını kurar/günceller (`migrate` yerine) |

Verinin bir kez kurulmasına yarayan eski yükleme komutları (gıda listesi, temizlik sarfı, yatak düzeni, piyasa fiyatı tahmini vb.) işini bitirdiği için kaldırıldı; `_yedek` klasöründe durur. Veritabanını geri getirmenin yolu artık bu komutlar değil, phpMyAdmin'den alınan SQL yedeğidir (Dışa aktar → içe aktar).

Örnek fiyatlar perakende/liste fiyatlarından türetilmiş tahminlerdir; gerçek otel maliyeti değildir, gerçek faturalar girildikçe anlam kazanır.

## Sürüm kontrolü

`.gitignore` hazırdır (`.env`, sanal ortam ve yedekler dışarıda kalır):

```powershell
git init
git add .
git commit -m "Maliyet muhasebesi: veri bütünlüğü ve hesap düzeltmeleri"
```

## Bilinen sınırlar

- Konaklama kayıtları doluluğu izler ama fiyat, gelir ve rezervasyon durumu (onaylı, iptal) tutmaz; dinamik fiyatlandırma modülü bunların üzerine kurulacaktır. Eski tasarım taslağı `docs/eski_taslak/` altındadır (sezon, doluluk çarpanı ve fiyat planı tabloları için başlangıç noktası).
- Kayıtları kimin girdiği yalnızca Django admin geçmişinde (`pasaport_sistem`) tutulur; iş tablolarında kullanıcı ilişkisi yoktur.
- Enerjinin sabit tabanları, mevsim çarpanları ve oda içi tüketimler varsayımdır. Otelin sayaç ya da fatura verisi değildir.
- Gider tutarları, oda tipi katsayıları, aylık doluluk oranları, porsiyonlar ve tekstil ömürleri varsayıma dayalı model verisidir. Sunumda bir varsayımlar tablosuyla birlikte verilmelidir.
- Personel gideri tek kalemdir ve tamamen sabittir; departman kırılımı bilinçli olarak yapılmamıştır. Muhasebe, pazarlama ve çamaşırhane çalışanları bu kalemin içindedir.
- Çamaşırlar otelin kendi çamaşırhanesinde yıkanır; ayrı bir yıkama gideri yoktur. Çamaşırhanenin suyu ve elektriği enerji giderindedir; deterjan gibi sarf malzemesi henüz maliyete girmez.
- Satış kanalı komisyonu ve konaklama vergisi fiyatın yüzdesidir; maliyet tarafında yer almaz, fiyatlandırma modülünde ele alınacaktır.
- Temizlik malzemelerinin stok kartı vardır ama hiçbir reçetede kullanılmaz; oda maliyetine girmez (`veri_denetimi` listeler).
