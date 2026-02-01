from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

# NOTE:
# This project uses JWT (SimpleJWT). We do not create DRF authtoken Token rows.
# Creating tokens here breaks deploy because Token auth is not part of this setup.

# @receiver(post_save, sender=settings.AUTH_USER_MODEL)
# def create_auth_token(sender, instance=None, created=False, **kwargs):
#     if created:
#         Token.objects.create(user=instance)
