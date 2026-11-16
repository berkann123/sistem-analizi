from django.db import migrations

# Kahvaltı büfesi tablosu ürünü yalnızca kimliğiyle (urun_id) tutar; ürün adı envanter_urunleri tablosundadır.
# Bu görünüm (view) tabloyu ürün adı, birim ve maliyetle birlikte okunur hale getirir. Veri saklamaz:
# her açıldığında tablolardan yeniden hesaplanır, bu yüzden veri tekrarı yoktur ve hep günceldir.
# phpMyAdmin'de tablo gibi açılır; veri girişi yine Admin'den (ya da kahvalti_bufesi_urunleri tablosundan) yapılır.
CREATE_VIEW = """
CREATE OR REPLACE VIEW kahvalti_bufesi_gorunumu AS
SELECT
    s.id,
    s.kahvalti_bufesi_id,
    b.bufe_adi,
    s.urun_id,
    u.urun_kodu,
    u.urun_adi,
    s.kisi_basi_miktar,
    br.birim_kodu AS birim,
    u.birim_maliyeti AS birim_maliyeti_tl,
    GREATEST(s.fire_orani, u.fire_orani) AS uygulanan_fire_orani,
    ROUND(s.kisi_basi_miktar * (1 + GREATEST(s.fire_orani, u.fire_orani)) * u.birim_maliyeti, 2) AS kisi_basi_maliyet_tl,
    s.aciklama,
    s.aktif
FROM kahvalti_bufesi_urunleri s
JOIN kahvalti_bufeleri b ON b.id = s.kahvalti_bufesi_id
JOIN envanter_urunleri u ON u.id = s.urun_id
JOIN birimler br ON br.id = u.birim_id
"""


class Migration(migrations.Migration):
    dependencies = [("dashboard", "0014_gider_kalemi_birlestirme")]
    operations = [migrations.RunSQL(CREATE_VIEW, "DROP VIEW IF EXISTS kahvalti_bufesi_gorunumu")]
