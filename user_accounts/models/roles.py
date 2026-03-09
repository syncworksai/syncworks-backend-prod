from django.db import models


class Roles(models.TextChoices):
    CUSTOMER = "CUSTOMER", "Customer"
    SBO = "SBO", "Small Business Owner"
    SUBCONTRACTOR = "SUBCONTRACTOR", "Subcontractor"

    # business-member/employee style roles (if you use them)
    OWNER = "OWNER", "Owner"
    MANAGER = "MANAGER", "Manager"
    DISPATCH = "DISPATCH", "Dispatch"
    TECHNICIAN = "TECHNICIAN", "Technician"
    ACCOUNTING = "ACCOUNTING", "Accounting"
    ADMIN = "ADMIN", "Admin"
