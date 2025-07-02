import os.path

TEST_ROOT = os.path.dirname(__file__)

TEST_SETTINGS = {
    'INSTALLED_APPS': [
        'django.contrib.staticfiles',
    ],
    'STATICFILES_STORAGE': 'compress_staticfiles.storage.CompressStaticFilesStorage',
    'STATICFILES_DIRS': [
        ('test',  os.path.join(TEST_ROOT, 'static')),
    ],
}
