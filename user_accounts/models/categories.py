# user_accounts/models/categories.py
from django.db import models
from django.utils.text import slugify


class ServiceCategory(models.Model):
    """
    Hierarchical categories for ticket routing + wizard UI:

    Industry (Automotive)
      -> Group (Roadside Assistance)
          -> Leaf Service (Dead Battery / Jump Start)

    Only LEAF categories should be used for:
      - Business.services_offered
      - Ticket.category
    """

    name = models.CharField(max_length=120)
    key = models.SlugField(max_length=140, unique=True)

    # NEW: hierarchy
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="children",
        on_delete=models.CASCADE,
    )

    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "name"]
        indexes = [
            models.Index(fields=["key"]),
            models.Index(fields=["parent"]),
        ]

    def __str__(self):
        return f"{self.parent.name} → {self.name}" if self.parent else self.name

    @property
    def is_leaf(self) -> bool:
        return not self.children.filter(is_active=True).exists()

    def save(self, *args, **kwargs):
        # Auto-generate key if blank
        if not self.key:
            base = slugify(self.name)[:120] or "category"
            candidate = base
            i = 2
            while ServiceCategory.objects.filter(key=candidate).exclude(pk=self.pk).exists():
                candidate = f"{base}-{i}"
                i += 1
            self.key = candidate
        super().save(*args, **kwargs)
