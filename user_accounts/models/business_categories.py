from django.db import models


class BusinessCategory(models.Model):
    """
    Categories/verticals for businesses (HVAC, Plumbing, Cleaning, etc).
    Used for filtering, matching, and display.
    """

    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True, default="")
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
