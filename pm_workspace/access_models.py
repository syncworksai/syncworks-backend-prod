"""Workspace-native PM access controls. Distinct from legacy Business PMEmployee."""
from django.conf import settings
from django.db import models

class PMWorkspaceStaff(models.Model):
    class Status(models.TextChoices):
        INVITED="INVITED","Invited"
        ACTIVE="ACTIVE","Active"
        REVOKED="REVOKED","Revoked"
    workspace=models.ForeignKey("pm_workspace.PMWorkspace",on_delete=models.CASCADE,related_name="team_members")
    user=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="pm_workspace_staff")
    email=models.EmailField()
    name=models.CharField(max_length=180,blank=True)
    role=models.CharField(max_length=32,default="VIEW_ONLY")
    permissions=models.JSONField(default=list,blank=True)
    properties=models.ManyToManyField("pm_workspace.PMProperty",blank=True,related_name="assigned_pm_staff")
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.INVITED)
    invite_token_hash=models.CharField(max_length=64,blank=True)
    invite_expires_at=models.DateTimeField(null=True,blank=True)
    accepted_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=["workspace","email"],name="uniq_pm_workspace_staff_email")]
        indexes=[models.Index(fields=["workspace","status"])]

class PMStaffTask(models.Model):
    class Status(models.TextChoices):
        TODO="TODO","To do"
        IN_PROGRESS="IN_PROGRESS","In progress"
        WAITING="WAITING","Waiting on response"
        REVIEW="REVIEW","Ready for review"
        DONE="DONE","Completed"
        CANCELED="CANCELED","Canceled"
    workspace=models.ForeignKey("pm_workspace.PMWorkspace",on_delete=models.CASCADE,related_name="staff_tasks")
    property=models.ForeignKey("pm_workspace.PMProperty",on_delete=models.CASCADE,related_name="staff_tasks")
    assignee=models.ForeignKey(PMWorkspaceStaff,null=True,blank=True,on_delete=models.SET_NULL,related_name="assigned_tasks")
    category=models.CharField(max_length=32)
    title=models.CharField(max_length=180)
    notes=models.TextField(blank=True)
    status=models.CharField(max_length=20,choices=Status.choices,default=Status.TODO)
    due_date=models.DateField(null=True,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="created_pm_staff_tasks")
    completed_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        ordering=["due_date","-created_at"]
        indexes=[models.Index(fields=["workspace","status"]),models.Index(fields=["workspace","assignee","status"])]

class PMInvestorGrant(models.Model):
    class Status(models.TextChoices):
        INVITED="INVITED","Invited"
        ACCEPTED="ACCEPTED","Accepted"
        REVOKED="REVOKED","Revoked"
    workspace=models.ForeignKey("pm_workspace.PMWorkspace",on_delete=models.CASCADE,related_name="investor_grants")
    property_owner=models.ForeignKey("pm_workspace.PMPropertyOwner",on_delete=models.CASCADE,related_name="portal_grants")
    user=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="pm_investor_grants")
    email=models.EmailField()
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.INVITED)
    invite_token_hash=models.CharField(max_length=64,blank=True)
    invite_expires_at=models.DateTimeField(null=True,blank=True)
    accepted_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=["workspace","property_owner"],name="uniq_pm_investor_grant_owner")]
        indexes=[models.Index(fields=["workspace","status"])]

class PMInvestorStatement(models.Model):
    class Status(models.TextChoices):
        DRAFT="DRAFT","Draft"
        SHARED="SHARED","Shared with investor"
        PAID="PAID","Payout recorded"
    workspace=models.ForeignKey("pm_workspace.PMWorkspace",on_delete=models.CASCADE,related_name="investor_statements")
    property_owner=models.ForeignKey("pm_workspace.PMPropertyOwner",on_delete=models.CASCADE,related_name="investor_statements")
    property=models.ForeignKey("pm_workspace.PMProperty",on_delete=models.CASCADE,related_name="investor_statements")
    period=models.CharField(max_length=7)
    rent_received=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    management_fees=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    expenses=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    reserve_change=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    owner_payout=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    payout_date=models.DateField(null=True,blank=True)
    payout_reference=models.CharField(max_length=120,blank=True)
    notes=models.TextField(blank=True)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.DRAFT)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=["workspace","property_owner","property","period"],name="uniq_pm_investor_statement_period")]
        ordering=["-period","property_id"]

class PMInvestorDocumentShare(models.Model):
    workspace=models.ForeignKey("pm_workspace.PMWorkspace",on_delete=models.CASCADE,related_name="investor_document_shares")
    property_owner=models.ForeignKey("pm_workspace.PMPropertyOwner",on_delete=models.CASCADE,related_name="shared_documents")
    document=models.ForeignKey("pm_workspace.PMPropertyDocument",on_delete=models.CASCADE,related_name="investor_shares")
    shared_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=["property_owner","document"],name="uniq_pm_investor_doc_share")]
