"""phpMyAdmin'de okunabilir görünümler (VIEW).

Tablolar normalize olduğu için ilişki kolonlarında yalnızca kimlik numarası durur
(ör. urun_id = 7). Bu görünümler tabloları JOIN ile birleştirip adları yan yana gösterir.
Veri kopyalanmaz: görünüm her açıldığında tablolardan yeniden üretilir.
"""
from django.db import migrations

VIEWS = {
    "v_odalar": """
        SELECT o.oda_numarasi, t.oda_kodu, t.oda_tipi_adi, o.kat, o.manzara_tipi, o.durum, t.azami_misafir
        FROM odalar o
        JOIN oda_tipleri t ON t.id = o.oda_tipi_id""",
    "v_stok_durumu": """
        SELECT u.urun_kodu, u.urun_adi, k.kategori_adi AS kategori, b.birim_adi AS birim,
               u.mevcut_stok, u.kritik_stok,
               CASE WHEN u.mevcut_stok <= u.kritik_stok THEN 'Kritik' ELSE 'Yeterli' END AS stok_durumu,
               u.birim_maliyeti AS ortalama_birim_maliyeti,
               ROUND(u.mevcut_stok * u.birim_maliyeti, 2) AS stok_degeri
        FROM envanter_urunleri u
        JOIN envanter_kategorileri k ON k.id = u.kategori_id
        JOIN birimler b ON b.id = u.birim_id
        WHERE u.aktif = 1""",
    "v_envanter_hareketleri": """
        SELECT h.id AS hareket_no, h.hareket_tarihi, u.urun_kodu, u.urun_adi, k.kategori_adi AS kategori,
               CASE h.hareket_turu_kodu
                    WHEN 'alim' THEN 'Alım' WHEN 'tuketim' THEN 'Tüketim' WHEN 'fire' THEN 'Fire'
                    WHEN 'devir_giris' THEN 'Depoya giriş' WHEN 'devir_cikis' THEN 'Depodan çıkış'
                    WHEN 'sayim_duzeltme' THEN 'Sayım düzeltmesi' ELSE h.hareket_turu_kodu END AS hareket_turu,
               h.hareket_miktari, b.birim_adi AS birim, h.birim_maliyeti_tl,
               ROUND(h.hareket_miktari * h.birim_maliyeti_tl, 2) AS tutar_tl, h.aciklama
        FROM envanter_hareketleri h
        JOIN envanter_urunleri u ON u.id = h.urun_id
        JOIN envanter_kategorileri k ON k.id = u.kategori_id
        JOIN birimler b ON b.id = u.birim_id""",
    "v_kahvalti_bufesi": """
        SELECT f.bufe_adi, u.urun_kodu, u.urun_adi, b.birim_adi AS birim,
               s.kisi_basi_miktar, GREATEST(s.fire_orani, u.fire_orani) AS gecerli_fire_orani,
               u.birim_maliyeti AS ortalama_birim_maliyeti,
               ROUND(s.kisi_basi_miktar * (1 + GREATEST(s.fire_orani, u.fire_orani)) * u.birim_maliyeti, 4) AS kisi_basi_maliyet,
               s.aktif
        FROM kahvalti_bufesi_urunleri s
        JOIN kahvalti_bufeleri f ON f.id = s.kahvalti_bufesi_id
        JOIN envanter_urunleri u ON u.id = s.urun_id
        JOIN birimler b ON b.id = u.birim_id""",
    "v_oda_paketleri": """
        SELECT t.oda_kodu, p.paket_adi, p.misafir_sayisi,
               CASE WHEN c.urun_id IS NOT NULL THEN 'Sarf ürünü' ELSE 'Tekstil' END AS bilesen_turu,
               COALESCE(u.urun_adi, x.tekstil_adi) AS bilesen,
               c.oda_gecesi_miktar,
               CASE c.tuketim_esasi WHEN 'kisi_gecesi' THEN 'Kişi başına / gece' ELSE 'Oda başına / gece' END AS tuketim_esasi,
               c.fire_orani, c.aktif
        FROM oda_paketi_bilesenleri c
        JOIN oda_paketleri p ON p.id = c.oda_paketi_id
        JOIN oda_tipleri t ON t.id = p.oda_tipi_id
        LEFT JOIN envanter_urunleri u ON u.id = c.urun_id
        LEFT JOIN tekstil_varliklari x ON x.id = c.tekstil_varligi_id""",
    "v_aylik_giderler": """
        SELECT g.gider_ayi, c.gider_kalemi,
               CASE c.gider_davranisi WHEN 'sabit' THEN 'Sabit' ELSE 'Ortak / fatura' END AS gider_davranisi,
               g.tutar, g.her_ay_tekrarlar, g.tekrar_bitis_tarihi, g.aciklama
        FROM aylik_otel_giderleri g
        JOIN aylik_gider_kategorileri c ON c.id = g.gider_kategorisi_id""",
}

CREATE_VIEWS = [f"CREATE OR REPLACE VIEW {name} AS {body}" for name, body in VIEWS.items()]
DROP_VIEWS = [f"DROP VIEW IF EXISTS {name}" for name in VIEWS]


class Migration(migrations.Migration):

    dependencies = [("dashboard", "0001_initial")]

    operations = [migrations.RunSQL(sql=CREATE_VIEWS, reverse_sql=DROP_VIEWS)]
