import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(name, default=None):
    """Ortam değişkenini okur; tanımlı değilse varsayılanı döndürür."""
    return os.getenv(name, default)


# Güvenli varsayılan: .env yoksa DEBUG kapalıdır. Geliştirirken .env içinde DJANGO_DEBUG=True yazın.
DEBUG = env("DJANGO_DEBUG", default="False").lower() == "true"

SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY tanımlı değil. .env.example dosyasını .env olarak kopyalayıp doldurun.")
    SECRET_KEY = "yalnizca-gelistirme-icin-degistirin"

ALLOWED_HOSTS = [x.strip() for x in env("DJANGO_ALLOWED_HOSTS", default="127.0.0.1,localhost").split(",") if x.strip()]

INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "dashboard",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware", "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware", "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "hotel_costs.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request", "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "hotel_costs.wsgi.application"
ASGI_APPLICATION = "hotel_costs.asgi.application"

# İKİ MYSQL VERİTABANI (aynı sunucuda):
#   default -> otelin iş verisi (odalar, stok, maliyet). phpMyAdmin Tasarımcı'da yalnızca bunlar görünür.
#   sistem  -> Django'nun kendi tabloları (kullanıcılar, oturumlar, yetkiler, admin geçmişi).
# Hangi tablonun nereye gideceğine hotel_costs/db_router.py karar verir.
def mysql_database(name):
    return {
        "ENGINE": "django.db.backends.mysql",
        "NAME": name,
        "USER": env("DB_USER", default="root"),
        "PASSWORD": env("DB_PASSWORD", default=""),
        "HOST": env("DB_HOST", default="127.0.0.1"),
        "PORT": env("DB_PORT", default="3306"),
        "OPTIONS": {
            "charset": "utf8mb4",
            "init_command": "SET default_storage_engine=INNODB, sql_mode='STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'",
        },
        "TEST": {"CHARSET": "utf8mb4", "COLLATION": "utf8mb4_unicode_ci"},
    }


DATABASES = {
    "default": mysql_database(env("DB_NAME", default="pasaport_otel")),
    "sistem": mysql_database(env("DB_SYSTEM_NAME", default="pasaport_sistem")),
}
DATABASE_ROUTERS = ["hotel_costs.db_router.SystemDatabaseRouter"]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "tr"
# Büyük sayılar binlik ayırıcıyla yazılır (Türkçe: 1.346.492,70). Form kutuları ve kimlik numaraları etkilenmez.
USE_THOUSAND_SEPARATOR = True
TIME_ZONE = "Europe/Istanbul"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]   # logo gibi proje geneli dosyalar
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Dönem kapanışı: biten ay, sonraki ayın bu kadar günü geçince ekranlardan biri açıldığında kendiliğinden kapatılır.
# Ayın son faturaları (enerji, bakım) birkaç gün geç gelir; bu süre onların girilmesi içindir.
PERIOD_CLOSE_GRACE_DAYS = int(env("DONEM_KAPANIS_GUN", default="5"))

# Normal doluluk: fiyat takviminde ortak gider payı bu dolulukla dağıtılır (TMS 2 md. 13, normal kapasite).
# Son 12 biten ayın en az 6'sında konaklama verisi varsa gerçekleşen ortalama kullanılır; yoksa bu varsayım.
NORMAL_OCCUPANCY_DEFAULT = env("NORMAL_DOLULUK", default="0.70")

