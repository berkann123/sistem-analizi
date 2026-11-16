-- Demo başlangıç verileri. Fiyatlar ve katsayılar örnektir; gerçek otel verileriyle güncellenmelidir.
INSERT INTO hotels(name,room_count) VALUES ('İzmir Pasaport Pier Otel',54);
INSERT INTO room_types(code,name,description,max_guests,base_capacity,standard_cost_factor) VALUES
 ('STD','Standart','Örnek standart oda',2,2,1.0000),
 ('DLX','Deluxe','Örnek deniz/şehir manzaralı oda',3,2,1.2500),
 ('STE','Suit','Örnek suit oda',4,2,1.6500);
INSERT INTO rooms(hotel_id,room_type_id,room_number,floor)
SELECT h.id,t.id,n.room_no::text,v.floor
FROM hotels h CROSS JOIN (VALUES
 ('STD',101,118,1),('DLX',201,224,2),('STE',301,312,3)
) v(type_code,first_no,last_no,floor)
JOIN room_types t ON t.code=v.type_code
CROSS JOIN LATERAL generate_series(v.first_no,v.last_no) AS n(room_no);

INSERT INTO units(code,name) VALUES ('kg','Kilogram'),('lt','Litre'),('pcs','Adet'),('portion','Porsiyon'),('kwh','Kilowatt saat'),('m3','Metreküp');
INSERT INTO inventory_categories(name,cost_center) VALUES
 ('Kahvaltı gıda','breakfast'),('Kat hizmetleri sarf','housekeeping'),('Teknik bakım','maintenance'),('Misafir ikramı','other');
INSERT INTO cost_centers(code,name,allocation_method) VALUES
 ('ROOM','Oda operasyonu','occupied_room_nights'),('BFST','Kahvaltı','guests'),
 ('HK','Kat hizmetleri','occupied_room_nights'),('ADMIN','Genel yönetim','available_room_nights'),
 ('TECH','Teknik bakım','available_room_nights');
INSERT INTO fixed_expense_categories(name) VALUES
 ('Kira'),('Personel yan hakları'),('Sigorta'),('Yazılım ve lisans'),('Muhasebe ve danışmanlık'),('Bakım sözleşmeleri'),('Amortisman'),('Lisans ve vergiler'),('Diğer sabit gider');
INSERT INTO room_packages(code,name,description,includes_breakfast) VALUES
 ('RO','Sadece oda','Kahvaltı hariç',false),('BB','Oda + kahvaltı','Kahvaltı dahil',true);
INSERT INTO seasons(name,starts_on,ends_on) VALUES
 ('Düşük sezon','2026-01-01','2026-03-31'),('Omuz sezon','2026-04-01','2026-06-14'),
 ('Yüksek sezon','2026-06-15','2026-09-15'),('Omuz sezon 2','2026-09-16','2026-10-31'),('Düşük sezon 2','2026-11-01','2026-12-31');
INSERT INTO occupancy_price_multipliers(min_occupancy,max_occupancy,multiplier) VALUES
 (0.0000,0.3000,0.8500),(0.3000,0.6000,1.0000),(0.6000,0.8000,1.1000),(0.8000,1.0000,1.2000);
