from rest_framework import serializers
from user_accounts.models import BusinessCustomer
class BusinessCustomerSerializer(serializers.ModelSerializer):
    lifetime_revenue=serializers.SerializerMethodField()
    class Meta:
        model=BusinessCustomer
        fields=["id","business","name","company_name","email","phone","normalized_phone","billing_address","service_address","unit","city","state","service_zip","access_notes","contact_preference","payment_preference","notes","tags","record_source","source_system","external_customer_id","is_imported","import_batch_id","exclude_from_kpis","first_service_at","last_service_at","ticket_count","completed_ticket_count","cancelled_ticket_count","lifetime_revenue_cents","lifetime_revenue","last_service_label","last_ticket","created_by","updated_by","created_at","updated_at"]
        read_only_fields=["business","normalized_phone","created_by","updated_by","created_at","updated_at","lifetime_revenue"]
    def get_lifetime_revenue(self,obj): return round((obj.lifetime_revenue_cents or 0)/100,2)
    def validate_tags(self,value):
        if not isinstance(value,list): raise serializers.ValidationError("Tags must be a list.")
        return [str(x).strip() for x in value if str(x).strip()][:50]
    def validate(self,attrs):
        vals=[attrs.get("name",getattr(self.instance,"name","")),attrs.get("company_name",getattr(self.instance,"company_name","")),attrs.get("email",getattr(self.instance,"email","")),attrs.get("phone",getattr(self.instance,"phone","")),attrs.get("external_customer_id",getattr(self.instance,"external_customer_id",""))]
        if not any(str(x or "").strip() for x in vals): raise serializers.ValidationError("Provide a name, company name, email, phone, or external customer ID.")
        return attrs
