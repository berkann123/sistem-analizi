"""Veritabanı yönlendiricisi: Django'nun kendi tablolarını `sistem` veritabanında tutar.

Amaç, otel veritabanının (default) şemasını temiz tutmaktır: phpMyAdmin Tasarımcı'da yalnızca
otelin tabloları ve aralarındaki ilişkiler görünür.

Bedeli: MySQL iki ayrı veritabanındaki tablolar arasında Django üzerinden yabancı anahtar
kuramaz. Bu yüzden iş tabloları kullanıcı tablosuna (auth_user) ilişkiyle bağlanamaz.
"""

SYSTEM_APPS = {"auth", "contenttypes", "admin", "sessions"}


class SystemDatabaseRouter:
    @staticmethod
    def _database_for(app_label):
        return "sistem" if app_label in SYSTEM_APPS else "default"

    def db_for_read(self, model, **hints):
        return self._database_for(model._meta.app_label)

    def db_for_write(self, model, **hints):
        return self._database_for(model._meta.app_label)

    def allow_relation(self, obj1, obj2, **hints):
        # İlişki yalnızca aynı veritabanındaki kayıtlar arasında kurulabilir.
        return self._database_for(obj1._meta.app_label) == self._database_for(obj2._meta.app_label)

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # Her uygulamanın tabloları yalnızca kendi veritabanında oluşturulur.
        return db == self._database_for(app_label)
