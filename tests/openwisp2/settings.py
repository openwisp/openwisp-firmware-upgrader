import os
import sys

TESTING = 'test' in sys.argv
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DEBUG = True

ALLOWED_HOSTS = ['*']

DATABASES = {
    'default': {
        'ENGINE': 'django.contrib.gis.db.backends.spatialite',
        'NAME': 'openwisp-firmware-upgrader.db',
    }
}

SPATIALITE_LIBRARY_PATH = 'mod_spatialite.so'

SECRET_KEY = 'fn)t*+$)ugeyip6-#txyy$5wf2ervc0d2n#h)qb)y5@ly$t*@w'

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.gis',
    # openwisp2 admin theme
    # (must be loaded here)
    'openwisp_utils.admin_theme',
    # all-auth
    'django.contrib.sites',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'django_extensions',
    'private_storage',
    # openwisp2 modules
    'openwisp_users',
    'openwisp_controller.pki',
    'openwisp_controller.config',
    'openwisp_controller.connection',
    'openwisp_controller.geo',
    'openwisp_firmware_upgrader',
    # admin
    'django.contrib.admin',
    'django.forms',
    # other dependencies
    'sortedm2m',
    'reversion',
    'leaflet',
    # rest framework
    'rest_framework',
    'rest_framework.authtoken',
    'rest_framework_gis',
    'django_filters',
    'drf_yasg',
    # channels
    'channels',
]

EXTENDED_APPS = [
    'django_netjsonconfig',
    'django_x509',
    'django_loci',
]

AUTH_USER_MODEL = 'openwisp_users.User'
SITE_ID = '1'

STATICFILES_FINDERS = [
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
    'openwisp_utils.staticfiles.DependencyFinder',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'openwisp2.urls'

ASGI_APPLICATION = 'openwisp_controller.geo.channels.routing.channel_routing'
CHANNEL_LAYERS = {
    'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'},
}


TIME_ZONE = 'Europe/Rome'
# TIME_ZONE = 'America/Lima'
LANGUAGE_CODE = 'en-gb'
USE_TZ = True
USE_I18N = False
USE_L10N = False
STATIC_URL = '/static/'
MEDIA_URL = '/media/'
MEDIA_ROOT = '{0}/media/'.format(BASE_DIR)

PRIVATE_STORAGE_ROOT = '{0}/firmware/'.format(BASE_DIR)

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(os.path.dirname(BASE_DIR), 'templates')],
        'OPTIONS': {
            'loaders': [
                'django.template.loaders.filesystem.Loader',
                'django.template.loaders.app_directories.Loader',
                'openwisp_utils.loaders.DependencyLoader',
            ],
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'openwisp_utils.admin_theme.context_processor.menu_items',
            ],
        },
    }
]

FORM_RENDERER = 'django.forms.renderers.TemplatesSetting'

EMAIL_PORT = '1025'  # for testing purposes
LOGIN_REDIRECT_URL = 'admin:index'
ACCOUNT_LOGOUT_REDIRECT_URL = LOGIN_REDIRECT_URL

# during development only
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

if TESTING:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'firmware-upgrader',
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': 'redis://localhost/0',
            'OPTIONS': {'CLIENT_CLASS': 'django_redis.client.DefaultClient'},
        }
    }

SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'default'

if not TESTING:
    CELERY_BROKER_URL = 'redis://localhost/2'
else:
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True
    CELERY_BROKER_URL = 'memory://'

LOGGING = {
    'version': 1,
    'filters': {'require_debug_true': {'()': 'django.utils.log.RequireDebugTrue'}},
    'handlers': {
        'console': {
            'level': 'DEBUG',
            'filters': ['require_debug_true'],
            'class': 'logging.StreamHandler',
        }
    },
    'loggers': {
        'py.warnings': {'handlers': ['console']},
        'celery': {'handlers': ['console'], 'level': 'DEBUG'},
        'celery.task': {'handlers': ['console'], 'level': 'DEBUG'},
    },
}

OPENWISP_CUSTOM_OPENWRT_IMAGES = (
    (
        'customimage-squashfs-sysupgrade.bin',
        {'label': 'Custom WAP-1200', 'boards': ('CWAP1200',)},
    ),
)
OPENWISP_USERS_AUTH_API = True
OPENWISP_FIRMWARE_UPGRADER_API = True

if os.environ.get('SAMPLE_APP', False):
    INSTALLED_APPS.remove('openwisp_firmware_upgrader')
    EXTENDED_APPS.append('openwisp_firmware_upgrader')
    INSTALLED_APPS.append('openwisp2.sample_firmware_upgrader')
    FIRMWARE_UPGRADER_CATEGORY_MODEL = 'sample_firmware_upgrader.Category'
    FIRMWARE_UPGRADER_BUILD_MODEL = 'sample_firmware_upgrader.Build'
    FIRMWARE_UPGRADER_FIRMWAREIMAGE_MODEL = 'sample_firmware_upgrader.FirmwareImage'
    FIRMWARE_UPGRADER_DEVICEFIRMWARE_MODEL = 'sample_firmware_upgrader.DeviceFirmware'
    FIRMWARE_UPGRADER_BATCHUPGRADEOPERATION_MODEL = (
        'sample_firmware_upgrader.BatchUpgradeOperation'
    )
    FIRMWARE_UPGRADER_UPGRADEOPERATION_MODEL = (
        'sample_firmware_upgrader.UpgradeOperation'
    )

TEST_RUNNER = 'openwisp_utils.tests.TimeLoggingTestRunner'

# local settings must be imported before test runner otherwise they'll be ignored
try:
    from openwisp2.local_settings import *
except ImportError:
    pass
