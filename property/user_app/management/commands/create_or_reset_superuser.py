import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = "Create or reset a superuser (Render free plan friendly)"

    def handle(self, *args, **options):
        if os.environ.get("CREATE_SUPERUSER") != "1":
            self.stdout.write("CREATE_SUPERUSER not enabled; skipping.")
            return

        username = os.environ.get("SU_USERNAME", "rentout_admin")
        password = os.environ.get("SU_PASSWORD", "rentout_admin_123")
        email = os.environ.get("SU_EMAIL", "admin@rentout.co.uk")

        User = get_user_model()

        # Works for standard username-based user models
        user = User.objects.filter(username=username).first()

        if not user:
            user = User.objects.create_superuser(
                username=username,
                email=email,
                password=password,
            )
            self.stdout.write(f"Superuser created: {username}")
            return

        user.email = email
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save()
        self.stdout.write(f"Superuser password reset: {username}")
