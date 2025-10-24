# property/conftest.py
import os

# Point to the inner project's settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "property.settings")

# Initialize Django early so DRF test imports won't crash during collection
import django
django.setup()
