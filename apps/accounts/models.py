from django.contrib.auth.models import User
from django.db import models


class UserProfile(models.Model):
    ROLE_ADMIN = "admin"
    ROLE_MANAGER = "manager"
    ROLE_STAFF = "staff"
    ROLE_CHOICES = [
        (ROLE_ADMIN, "Admin"),
        (ROLE_MANAGER, "Manager"),
        (ROLE_STAFF, "Staff"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_STAFF)
    phone = models.CharField(max_length=40, blank=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)

    def __str__(self) -> str:
        return f"{self.user.get_username()} ({self.get_role_display()})"

    @property
    def is_admin(self) -> bool:
        return self.role == self.ROLE_ADMIN or self.user.is_superuser
