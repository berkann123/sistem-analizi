# Temiz başlangıç şeması: sayısal kimlikler ve mantıklı kolon sırası. (Django 5.2 ile üretildi.)
# Alanlar, tablolardaki kolon sırası modeldeki sırayla aynı olsun diye elle dizilmiştir:
# kimlik, ilişkiler ve tanımlayıcı alanlar başta; açıklama ve aktif/pasif işareti sonda.

import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='BreakfastBuffet',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(db_column='bufe_adi', max_length=120, unique=True)),
                ('notes', models.CharField(blank=True, db_column='aciklama', max_length=240)),
                ('active', models.BooleanField(db_column='aktif', default=True, help_text='Maliyet hesabı etkin olan tek büfeyi kullanır.')),
            ],
            options={
                'verbose_name': 'Kahvaltı büfesi',
                'verbose_name_plural': 'Kahvaltı büfeleri',
                'db_table': 'kahvalti_bufeleri',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='DailyHotelMetric',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('metric_date', models.DateField(db_column='metrik_tarihi', unique=True, verbose_name='Tarih')),
                ('available_rooms', models.PositiveSmallIntegerField(db_column='musait_oda_sayisi', default=54, verbose_name='Satışa açık oda')),
                ('occupied_rooms', models.PositiveSmallIntegerField(db_column='dolu_oda_sayisi', default=0, verbose_name='Dolu oda')),
                ('out_of_order_rooms', models.PositiveSmallIntegerField(db_column='kullanim_disi_oda_sayisi', default=0, verbose_name='Kullanım dışı oda')),
                ('guests', models.PositiveSmallIntegerField(db_column='misafir_sayisi', default=0, verbose_name='Misafir sayısı')),
                ('room_revenue', models.DecimalField(db_column='oda_geliri', decimal_places=2, default=0, max_digits=14, validators=[django.core.validators.MinValueValidator(Decimal('0'))], verbose_name='Oda geliri (KDV hariç)')),
            ],
            options={
                'verbose_name': 'Günlük doluluk kaydı',
                'verbose_name_plural': 'Günlük doluluk kayıtları',
                'db_table': 'gunluk_otel_metrikleri',
                'ordering': ['-metric_date'],
            },
        ),
        migrations.CreateModel(
            name='InventoryCategory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(db_column='kategori_adi', max_length=120, unique=True)),
                ('cost_center', models.CharField(choices=[('mutfak', 'Mutfak'), ('bar', 'Bar'), ('kat_hizmetleri', 'Kat hizmetleri'), ('camasirhane', 'Çamaşırhane'), ('diger', 'Diğer')], db_column='gider_merkezi', max_length=30)),
            ],
            options={
                'verbose_name': 'Envanter kategorisi',
                'verbose_name_plural': 'Envanter kategorileri',
                'db_table': 'envanter_kategorileri',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='MonthlyExpenseCategory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(db_column='gider_kalemi', max_length=120, unique=True)),
                ('cost_behavior', models.CharField(choices=[('sabit', 'Aylık sabit gider'), ('degisken', 'Aylık ortak gider / fatura')], db_column='gider_davranisi', default='sabit', max_length=12)),
                ('utility_type', models.CharField(blank=True, choices=[('', 'Enerji/su faturası değil'), ('elektrik', 'Elektrik faturası'), ('su', 'Su ve atık su faturası'), ('dogalgaz', 'Doğalgaz faturası')], db_column='bagli_hizmet_turu', default='', help_text='Aylık fatura buradan oda maliyetine ekleniyorsa seçin. Aynı ay için tüketim tarifesinden ikinci kez hesaplanmasını önler.', max_length=20, verbose_name='Bağlı hizmet faturası türü')),
                ('notes', models.CharField(blank=True, db_column='aciklama', max_length=240)),
                ('active', models.BooleanField(db_column='aktif', default=True)),
            ],
            options={
                'verbose_name': 'Aylık gider kategorisi',
                'verbose_name_plural': 'Aylık gider kategorileri',
                'db_table': 'aylik_gider_kategorileri',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='RoomType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(db_column='oda_kodu', max_length=30, unique=True)),
                ('name', models.CharField(db_column='oda_tipi_adi', max_length=120)),
                ('description', models.TextField(blank=True, db_column='aciklama', null=True)),
                ('base_capacity', models.SmallIntegerField(db_column='temel_kapasite', default=2, validators=[django.core.validators.MinValueValidator(1)])),
                ('max_guests', models.SmallIntegerField(db_column='azami_misafir', default=2, validators=[django.core.validators.MinValueValidator(1)])),
                ('standard_cost_factor', models.DecimalField(db_column='standart_maliyet_katsayisi', decimal_places=4, default=1, help_text='Şu an yalnızca oda tiplerini sıralamak için kullanılır; maliyet hesabına girmez. Fiyatlandırma modülünde oda tipi çarpanı olarak kullanılmak üzere tutulur.', max_digits=8, validators=[django.core.validators.MinValueValidator(Decimal('0.0001'))])),
                ('active', models.BooleanField(db_column='aktif', default=True)),
            ],
            options={
                'verbose_name': 'Oda tipi',
                'verbose_name_plural': 'Oda tipleri',
                'db_table': 'oda_tipleri',
                'ordering': ['code'],
            },
        ),
        migrations.CreateModel(
            name='TextileAsset',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(db_column='tekstil_adi', max_length=160, unique=True)),
                ('set_purchase_cost', models.DecimalField(db_column='set_alim_maliyeti', decimal_places=2, help_text='KDV hariç', max_digits=14, validators=[django.core.validators.MinValueValidator(Decimal('0'))])),
                ('salvage_value', models.DecimalField(db_column='hurda_degeri', decimal_places=2, default=0, max_digits=14, validators=[django.core.validators.MinValueValidator(Decimal('0'))])),
                ('useful_room_nights', models.PositiveIntegerField(db_column='tahmini_oda_gecesi_omru', help_text='Bir setin tahmini toplam oda-gece kullanım ömrü', validators=[django.core.validators.MinValueValidator(1)])),
                ('sets_per_room', models.DecimalField(db_column='oda_basi_set_sayisi', decimal_places=3, default=1, max_digits=8, validators=[django.core.validators.MinValueValidator(Decimal('0'))])),
                ('usage_basis', models.CharField(choices=[('oda_gecesi', 'Oda seti / gece'), ('kisi_gecesi', 'Kişi seti / gece')], db_column='tuketim_esasi', default='oda_gecesi', max_length=20)),
                ('notes', models.CharField(blank=True, db_column='aciklama', max_length=240)),
                ('active', models.BooleanField(db_column='aktif', default=True)),
            ],
            options={
                'verbose_name': 'Tekstil varlığı',
                'verbose_name_plural': 'Tekstil varlıkları',
                'db_table': 'tekstil_varliklari',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='Unit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(db_column='birim_kodu', max_length=20, unique=True)),
                ('name', models.CharField(db_column='birim_adi', max_length=80)),
            ],
            options={
                'verbose_name': 'Birim',
                'verbose_name_plural': 'Birimler',
                'db_table': 'birimler',
                'ordering': ['code'],
            },
        ),
        migrations.CreateModel(
            name='InventoryItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sku', models.CharField(db_column='urun_kodu', max_length=80, unique=True, verbose_name='Ürün kodu')),
                ('name', models.CharField(db_column='urun_adi', max_length=180, verbose_name='Ürün adı')),
                ('category', models.ForeignKey(db_column='kategori_id', on_delete=django.db.models.deletion.PROTECT, to='dashboard.inventorycategory', verbose_name='Kategori')),
                ('item_type', models.CharField(db_column='urun_tipi', default='Tüketim', max_length=80, verbose_name='Ürün türü')),
                ('unit', models.ForeignKey(db_column='birim_id', on_delete=django.db.models.deletion.PROTECT, to='dashboard.unit', verbose_name='Birim')),
                ('current_stock', models.DecimalField(db_column='mevcut_stok', decimal_places=3, default=0, help_text='Stok hareketlerinden otomatik hesaplanır.', max_digits=14, verbose_name='Mevcut stok')),
                ('reorder_level', models.DecimalField(db_column='kritik_stok', decimal_places=3, default=0, max_digits=14, validators=[django.core.validators.MinValueValidator(Decimal('0'))], verbose_name='Kritik stok')),
                ('average_unit_cost', models.DecimalField(db_column='birim_maliyeti', decimal_places=4, default=0, help_text='Hareketli ağırlıklı ortalama; alım hareketlerinden otomatik hesaplanır.', max_digits=14, validators=[django.core.validators.MinValueValidator(Decimal('0'))], verbose_name='Birim maliyeti (KDV hariç)')),
                ('wastage_rate', models.DecimalField(db_column='fire_orani', decimal_places=4, default=0, help_text='0 ile 1 arasında oran; ör. %5 için 0.05', max_digits=5, validators=[django.core.validators.MinValueValidator(Decimal('0')), django.core.validators.MaxValueValidator(Decimal('0.9999'))], verbose_name='Stok fire oranı')),
                ('is_perishable', models.BooleanField(db_column='bozulabilir', default=False, verbose_name='Bozulabilir')),
                ('preferred_supplier', models.TextField(blank=True, db_column='tedarikci', null=True, verbose_name='Tedarikçi')),
                ('active', models.BooleanField(db_column='aktif', default=True, verbose_name='Aktif')),
            ],
            options={
                'verbose_name': 'Envanter ürünü',
                'verbose_name_plural': 'Envanter ürünleri',
                'db_table': 'envanter_urunleri',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='MonthlyHotelExpense',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('expense_month', models.DateField(db_column='gider_ayi', help_text='İlgili aydan herhangi bir gün seçin; ayın ilk günü olarak kaydedilir.', verbose_name='Gider ayı')),
                ('category', models.ForeignKey(db_column='gider_kategorisi_id', on_delete=django.db.models.deletion.PROTECT, to='dashboard.monthlyexpensecategory', verbose_name='Gider kategorisi')),
                ('amount', models.DecimalField(db_column='tutar', decimal_places=2, max_digits=14, validators=[django.core.validators.MinValueValidator(Decimal('0'))], verbose_name='Tutar (TL, KDV hariç)')),
                ('recurs_monthly', models.CharField(choices=[('evet', 'Evet'), ('hayir', 'Hayır')], db_column='her_ay_tekrarlar', default='hayir', help_text='Evet seçilirse gider sonraki aylara da uygulanır. Aynı kategoride sonraki bir aya yeni kayıt girildiğinde o aydan itibaren yeni kayıt geçerli olur (iki kez sayılmaz).', max_length=5, verbose_name='Her ay tekrarlar mı?')),
                ('recurring_until', models.DateField(blank=True, db_column='tekrar_bitis_tarihi', null=True)),
                ('description', models.CharField(blank=True, db_column='aciklama', max_length=240)),
            ],
            options={
                'verbose_name': 'Aylık otel gideri',
                'verbose_name_plural': 'Aylık otel giderleri',
                'db_table': 'aylik_otel_giderleri',
                'ordering': ['-expense_month', 'category__name'],
            },
        ),
        migrations.CreateModel(
            name='RoomPackage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('room_type', models.ForeignKey(db_column='oda_tipi_id', on_delete=django.db.models.deletion.CASCADE, to='dashboard.roomtype')),
                ('guest_count', models.PositiveSmallIntegerField(db_column='misafir_sayisi', validators=[django.core.validators.MinValueValidator(1)])),
                ('name', models.CharField(db_column='paket_adi', max_length=160)),
                ('notes', models.CharField(blank=True, db_column='aciklama', max_length=240)),
                ('active', models.BooleanField(db_column='aktif', default=True)),
            ],
            options={
                'verbose_name': 'Oda paketi',
                'verbose_name_plural': 'Oda paketleri',
                'db_table': 'oda_paketleri',
                'ordering': ['room_type__code', 'guest_count'],
            },
        ),
        migrations.CreateModel(
            name='Room',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('room_number', models.CharField(db_column='oda_numarasi', max_length=30, unique=True)),
                ('room_type', models.ForeignKey(db_column='oda_tipi_id', on_delete=django.db.models.deletion.PROTECT, to='dashboard.roomtype')),
                ('floor', models.SmallIntegerField(blank=True, db_column='kat', null=True)),
                ('view_type', models.CharField(choices=[('deniz', 'Deniz manzaralı'), ('kara', 'Kara manzaralı')], db_column='manzara_tipi', default='kara', max_length=8)),
                ('status', models.CharField(choices=[('aktif', 'Aktif (satışa açık)'), ('bakimda', 'Bakımda'), ('pasif', 'Pasif')], db_column='durum', default='aktif', max_length=20)),
                ('opened_on', models.DateField(blank=True, db_column='acilis_tarihi', null=True)),
            ],
            options={
                'verbose_name': 'Oda',
                'verbose_name_plural': 'Odalar',
                'db_table': 'odalar',
                'ordering': ['room_number'],
            },
        ),
        migrations.CreateModel(
            name='RoomPackageItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('package', models.ForeignKey(db_column='oda_paketi_id', on_delete=django.db.models.deletion.CASCADE, related_name='components', to='dashboard.roompackage')),
                ('item', models.ForeignKey(blank=True, db_column='urun_id', null=True, on_delete=django.db.models.deletion.PROTECT, to='dashboard.inventoryitem')),
                ('textile_asset', models.ForeignKey(blank=True, db_column='tekstil_varligi_id', null=True, on_delete=django.db.models.deletion.PROTECT, to='dashboard.textileasset')),
                ('quantity_per_room_night', models.DecimalField(db_column='oda_gecesi_miktar', decimal_places=4, default=1, max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal('0'))])),
                ('usage_basis', models.CharField(choices=[('oda_gecesi', 'Oda başına / gece'), ('kisi_gecesi', 'Kişi başına / gece')], db_column='tuketim_esasi', default='oda_gecesi', help_text='Sarf ürünleri için geçerlidir. Tekstil bileşeninde esas, tekstil varlığının kendi kaydından alınır.', max_length=20)),
                ('waste_rate', models.DecimalField(db_column='fire_orani', decimal_places=4, default=0, max_digits=5, validators=[django.core.validators.MinValueValidator(Decimal('0')), django.core.validators.MaxValueValidator(Decimal('0.9999'))])),
                ('notes', models.CharField(blank=True, db_column='aciklama', max_length=240)),
                ('active', models.BooleanField(db_column='aktif', default=True)),
            ],
            options={
                'verbose_name': 'Paket bileşeni',
                'verbose_name_plural': 'Paket bileşenleri',
                'db_table': 'oda_paketi_bilesenleri',
                'ordering': ['item__name', 'textile_asset__name'],
            },
        ),
        migrations.CreateModel(
            name='UtilityRate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('utility_type', models.CharField(choices=[('elektrik', 'Elektrik'), ('su', 'Su'), ('dogalgaz', 'Doğalgaz')], db_column='hizmet_turu', max_length=20, verbose_name='Hizmet türü')),
                ('room_type', models.ForeignKey(blank=True, db_column='oda_tipi_id', help_text='Boşsa bütün oda tiplerinde geçerli ortak varsayılan değer.', null=True, on_delete=django.db.models.deletion.CASCADE, to='dashboard.roomtype', verbose_name='Oda tipi')),
                ('quantity_per_room_night', models.DecimalField(db_column='gecelik_tuketim_miktari', decimal_places=4, help_text='Kullanım esası oda-gece ise oda başına; kişi-gece ise kişi başına miktar.', max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal('0'))], verbose_name='Oda/kişi başına gecelik tüketim')),
                ('unit', models.CharField(db_column='olcu_birimi', help_text='Elektrik için kWh, su ve doğalgaz için m³/Sm³.', max_length=20, verbose_name='Ölçü birimi')),
                ('usage_basis', models.CharField(choices=[('oda_gecesi', 'Oda başına / gece'), ('kisi_gecesi', 'Kişi başına / gece')], db_column='tuketim_hesaplama_esasi', default='oda_gecesi', max_length=20, verbose_name='Tüketimin hesaplanma esası')),
                ('unit_cost', models.DecimalField(db_column='birim_fiyat_tl', decimal_places=5, help_text='Kaynak tarifedeki birim fiyat; fatura kalemleri ve vergiler sözleşmeye göre değişebilir.', max_digits=14, validators=[django.core.validators.MinValueValidator(Decimal('0'))], verbose_name='Vergiler hariç birim fiyat (TL)')),
                ('effective_from', models.DateField(db_column='tarife_gecerlilik_baslangici', verbose_name='Tarife geçerlilik başlangıcı')),
                ('active', models.BooleanField(db_column='kullanimda', default=True, verbose_name='Hesaplamada kullanılsın')),
                ('source_url', models.URLField(blank=True, db_column='tarife_kaynak_adresi', max_length=500, verbose_name='Tarife kaynağı')),
                ('source_note', models.CharField(blank=True, db_column='kaynak_ve_tuketim_notu', help_text='Birim fiyatın kaynağını ve tüketim miktarının ölçüm mü tahmin mi olduğunu açıklayın.', max_length=500, verbose_name='Kaynak ve tüketim açıklaması')),
            ],
            options={
                'verbose_name': 'Oda enerji, su ve doğalgaz tarifesi',
                'verbose_name_plural': 'Oda enerji, su ve doğalgaz tarifeleri',
                'db_table': 'oda_enerji_su_gaz_tarifeleri',
                'ordering': ['utility_type', '-effective_from'],
            },
        ),
        migrations.CreateModel(
            name='BreakfastBuffetItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('buffet', models.ForeignKey(db_column='kahvalti_bufesi_id', on_delete=django.db.models.deletion.CASCADE, related_name='items', to='dashboard.breakfastbuffet', verbose_name='Kahvaltı büfesi')),
                ('item', models.ForeignKey(db_column='urun_id', on_delete=django.db.models.deletion.PROTECT, to='dashboard.inventoryitem', verbose_name='Envanter ürünü (kod ve ad)')),
                ('quantity_per_guest', models.DecimalField(db_column='kisi_basi_miktar', decimal_places=4, max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal('0'))], verbose_name='Kişi başı büfe miktarı')),
                ('waste_rate', models.DecimalField(db_column='fire_orani', decimal_places=4, default=0, max_digits=5, validators=[django.core.validators.MinValueValidator(Decimal('0')), django.core.validators.MaxValueValidator(Decimal('0.9999'))], verbose_name='Fire oranı')),
                ('notes', models.CharField(blank=True, db_column='aciklama', max_length=240, verbose_name='Açıklama')),
                ('active', models.BooleanField(db_column='aktif', default=True, verbose_name='Aktif')),
            ],
            options={
                'verbose_name': 'Büfe ürünü',
                'verbose_name_plural': 'Büfe ürünleri',
                'db_table': 'kahvalti_bufesi_urunleri',
                'ordering': ['item__name'],
                'constraints': [models.UniqueConstraint(fields=('buffet', 'item'), name='uq_kahvalti_bufe_urun')],
            },
        ),
        migrations.CreateModel(
            name='InventoryMovement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('movement_at', models.DateTimeField(db_column='hareket_tarihi', default=django.utils.timezone.now, help_text='Fatura/işlem tarihi. Geçmiş tarihli kayıt girilebilir.', verbose_name='Hareket tarihi')),
                ('item', models.ForeignKey(db_column='urun_id', on_delete=django.db.models.deletion.PROTECT, related_name='movements', to='dashboard.inventoryitem', verbose_name='Envanter ürünü')),
                ('movement_type', models.CharField(choices=[('alim', 'Alım'), ('tuketim', 'Tüketim'), ('fire', 'Fire'), ('devir_giris', 'Depoya giriş'), ('devir_cikis', 'Depodan çıkış'), ('sayim_duzeltme', 'Sayım düzeltmesi')], db_column='hareket_turu_kodu', default='alim', max_length=30, verbose_name='Hareket türü')),
                ('quantity', models.DecimalField(db_column='hareket_miktari', decimal_places=3, help_text='Her zaman pozitif girin; yönü hareket türü belirler. Yalnızca sayım düzeltmesi eksi olabilir (sayımda eksik çıkan miktar).', max_digits=14, verbose_name='Miktar')),
                ('unit_cost', models.DecimalField(db_column='birim_maliyeti_tl', decimal_places=4, default=0, max_digits=14, validators=[django.core.validators.MinValueValidator(Decimal('0'))], verbose_name='Birim maliyeti (TL, KDV hariç)')),
                ('notes', models.TextField(blank=True, db_column='aciklama', null=True, verbose_name='İşlem açıklaması / kaynağı')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_column='kayit_zamani', verbose_name='Kayıt zamanı')),
            ],
            options={
                'verbose_name': 'Stok hareketi',
                'verbose_name_plural': 'Stok hareketleri',
                'db_table': 'envanter_hareketleri',
                'ordering': ['-movement_at', '-created_at'],
                'constraints': [models.CheckConstraint(condition=models.Q(('unit_cost__gte', 0)), name='ck_hareket_maliyet_negatif_olamaz'), models.CheckConstraint(condition=models.Q(('quantity__gt', 0), ('movement_type', 'sayim_duzeltme'), _connector='OR'), name='ck_hareket_miktar_pozitif')],
            },
        ),
        migrations.AddConstraint(
            model_name='roompackage',
            constraint=models.UniqueConstraint(fields=('room_type', 'guest_count'), name='uq_oda_paketi_tip_misafir'),
        ),
        migrations.AddConstraint(
            model_name='roompackageitem',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('item__isnull', False), ('textile_asset__isnull', True)), models.Q(('item__isnull', True), ('textile_asset__isnull', False)), _connector='OR'), name='ck_oda_paketi_tek_bilesen_kaynagi'),
        ),
        migrations.AddConstraint(
            model_name='roompackageitem',
            constraint=models.UniqueConstraint(fields=('package', 'item'), name='uq_oda_paketi_urun'),
        ),
        migrations.AddConstraint(
            model_name='roompackageitem',
            constraint=models.UniqueConstraint(fields=('package', 'textile_asset'), name='uq_oda_paketi_tekstil'),
        ),
    ]
