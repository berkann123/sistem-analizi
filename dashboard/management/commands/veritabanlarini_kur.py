from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

# Django'nun kendi tabloları. Sıra önemli değil; hepsi tek komutla birlikte taşınır.
SYSTEM_TABLES = [
    "django_content_type", "auth_permission", "auth_group", "auth_group_permissions",
    "auth_user", "auth_user_groups", "auth_user_user_permissions", "django_admin_log", "django_session",
]


class Command(BaseCommand):
    help = ("İki veritabanını (otel verisi + Django sistem tabloları) kurar ve günceller. `migrate` yerine "
            "bu komutu kullanın; ilk kurulumda da, güncellemede de aynı komut çalışır. Tekrar çalıştırmak zararsızdır.")

    def handle(self, *args, **options):
        hotel = connections["default"].settings_dict["NAME"]
        system = connections["sistem"].settings_dict["NAME"]
        if hotel == system:
            raise CommandError("DB_NAME ve DB_SYSTEM_NAME aynı olamaz; iki ayrı veritabanı adı verin.")
        for name in (hotel, system):
            self._create_database(name)

        hotel_tables = set(connections["default"].introspection.table_names())
        system_tables = set(connections["sistem"].introspection.table_names())
        to_move = [table for table in SYSTEM_TABLES if table in hotel_tables]

        if to_move:
            # Eski düzen: Django tabloları otel veritabanının içinde. Verileriyle birlikte taşınır.
            if len(to_move) != len(SYSTEM_TABLES):
                missing = sorted(set(SYSTEM_TABLES) - set(to_move))
                raise CommandError(f"'{hotel}' içinde Django tablolarının yalnızca bir kısmı var (eksik: "
                                   f"{', '.join(missing)}). Otomatik taşıma yapılmadı.")
            clash = sorted(set(to_move) & system_tables)
            if clash:
                raise CommandError(f"Bu tablolar iki veritabanında da var: {', '.join(clash)}. "
                                   "Hangisinin geçerli olduğu belli olmadığı için taşıma yapılmadı.")
            renames = ", ".join(f"`{hotel}`.`{table}` TO `{system}`.`{table}`" for table in to_move)
            with connections["default"].cursor() as cursor:
                # RENAME TABLE veriyi kopyalamaz, tabloyu olduğu gibi diğer veritabanına taşır;
                # kullanıcılar, parolalar ve tablolar arası ilişkiler aynen korunur.
                cursor.execute(f"RENAME TABLE {renames}")
            self.stdout.write(f"{len(to_move)} Django tablosu '{hotel}' -> '{system}' taşındı.")
            # Tablolar hazır geldiği için migration'lar yeniden çalıştırılmaz, yalnızca "uygulandı" diye işaretlenir.
            call_command("migrate", database="sistem", fake=True, verbosity=0)
        else:
            call_command("migrate", database="sistem", verbosity=0)

        call_command("migrate", database="default", verbosity=0)

        hotel_tables = connections["default"].introspection.table_names()
        system_tables = connections["sistem"].introspection.table_names()
        leftovers = sorted(set(hotel_tables) & set(SYSTEM_TABLES))
        self.stdout.write(f"  {hotel:<18} {len(hotel_tables):>3} tablo (otel verisi)")
        self.stdout.write(f"  {system:<18} {len(system_tables):>3} tablo (Django: kullanıcı, oturum, yetki)")
        if leftovers:
            raise CommandError(f"'{hotel}' içinde hâlâ Django tablosu var: {', '.join(leftovers)}")
        self.stdout.write(self.style.SUCCESS("Veritabanları hazır."))
        if not get_user_model().objects.filter(is_superuser=True).exists():
            self.stdout.write(self.style.WARNING(
                "Henüz yönetici kullanıcı yok. Oluşturmak için:  python manage.py createsuperuser --database=sistem"))

    def _create_database(self, name):
        """Veritabanı yoksa oluşturur. Django var olmayan veritabanına bağlanamadığı için
        sunucuya veritabanı seçmeden, doğrudan sürücüyle bağlanılır."""
        connection = connections["default"]
        params = connection.get_connection_params()
        params.pop("database", None)
        params.pop("db", None)
        server = connection.Database.connect(**params)
        try:
            cursor = server.cursor()
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            cursor.close()
        finally:
            server.close()
