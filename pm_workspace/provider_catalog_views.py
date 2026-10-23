"""Curated provider form links; registry is optional, not a claim of approval.

Never guess local PHA requirements from another jurisdiction. Official documents
remain owned by their issuers and may change; URLs are shown as reference links.
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

GENERAL_FORMS=[
 {"key":"hud_hcv_landlords","name":"HUD Housing Choice Voucher landlord guidance and forms",
  "url":"https://www.hud.gov/program_offices/public_indian_housing/programs/hcv/landlord/forms",
  "category":"HOUSING_VOUCHER","roles":["OWNER","PROGRAM_ADMINISTRATOR"],"form_type":"CATALOG","national":True},
]
LOCAL_CATALOG=[
 {"state":"AL","match_terms":["montgomery housing authority","mha montgomery","mhatoday"],"provider":"Montgomery Housing Authority",
  "forms":[
    {"key":"coo","name":"Local change-of-ownership and payee forms directory",
     "url":"https://apply.mhatoday.org/custompage.aspx?sectionid=309874",
     "category":"OWNERSHIP_TRANSFER","roles":["OWNER","PREVIOUS_MANAGER","PROGRAM_ADMINISTRATOR"],
     "form_type":"CATALOG"},
    {"key":"rent_increase","name":"Rent Increase Request and administrator determination",
     "url":"https://mhatoday.org/wp-content/uploads/2023/03/rental-increase-form.pdf",
     "category":"RENT_INCREASE","roles":["OWNER","TENANT","PROGRAM_ADMINISTRATOR"],
     "form_type":"PDF","notice_days":60,"notes":"Check the current HAP anniversary and local form instructions before submitting."},
 ]},
]
CHANNEL_FORMS={
 "FURNISHED_FINDER":[
    {"key":"midterm_documents","name":"Furnished Finder document types and state-specific lease guidance",
     "url":"https://support.furnishedfinder.com/hc/en-us/articles/36214726319643-What-Types-of-Documents-Are-Offered",
     "category":"MIDTERM_LEASING","roles":["OWNER","TENANT"],"form_type":"CATALOG","national":True},
 ],
}

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def provider_forms(request):
    state=str(request.query_params.get("state") or "").strip().upper()[:2]
    name=str(request.query_params.get("administrator") or "").strip().lower()
    channel=str(request.query_params.get("rental_channel") or "").strip().upper()
    assistance=str(request.query_params.get("assistance_type") or "NONE").strip().upper()
    result=[]
    if assistance=="HOUSING_VOUCHER":
        result.extend(GENERAL_FORMS)
    if name:
        for catalog in LOCAL_CATALOG:
            if catalog["state"]==state and any(term in name for term in catalog["match_terms"]):
                result.extend([{**f,"provider":catalog["provider"],"national":False} for f in catalog["forms"]])
    result.extend(CHANNEL_FORMS.get(channel,[]))
    return Response({"forms":result,"provider_match":any(not f.get("national",True) for f in result),
                     "notice":"Verify version, signature requirements and submission method with the issuing organization before use. Opening these forms does not submit them."})
