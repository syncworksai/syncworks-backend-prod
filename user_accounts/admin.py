from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from user_accounts.models import User, PromoCode, PromoRedemption


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ("email",)
    list_display = ("email", "role", "is_active", "is_staff", "is_superuser")
    search_fields = ("email",)
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Role", {"fields": ("role",)}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "password1", "password2", "role", "is_staff", "is_superuser")}),
    )
    filter_horizontal = ("groups", "user_permissions")


@admin.register(PromoCode)
class PromoCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "is_active", "billing_exempt", "expires_at", "max_redemptions", "redemption_count", "created_at")
    list_filter = ("is_active", "billing_exempt")
    search_fields = ("code",)
    readonly_fields = ("redemption_count", "created_at")

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(PromoRedemption)
class PromoRedemptionAdmin(admin.ModelAdmin):
    list_display = ("promo", "business", "user", "redeemed_at")
    list_filter = ("promo",)
    search_fields = ("promo__code", "business__name", "user__email")
    readonly_fields = ("redeemed_at",)
