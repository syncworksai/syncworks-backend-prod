from django.conf import settings
from django.core.mail import EmailMultiAlternatives


def send_welcome_email(to_email: str, first_name: str | None = None):
    if not to_email:
        return

    name = (first_name or "").strip() or "there"

    subject = "Welcome to SyncWorks — Your new command center for service work"
    text = f"""
Hey {name},

Welcome to SyncWorks 👋

SyncWorks starts everyone as a Customer by default — so you can request work instantly.
Then if you run a business, you can upgrade to SBO (Small Business Owner) to manage jobs, tickets, scheduling, invoices, and your team.

How SyncWorks works (simple):
1) Customer Side (Everyone gets this):
   - Create a request (one-time or ongoing)
   - Add photos/details
   - Send to your favorite company OR send to Marketplace
   - Chat & updates stay inside the app

2) Favorite a company:
   - If you love a contractor, favorite them
   - Next time, route requests directly to them (faster, repeat business)

3) Marketplace:
   - If you don’t have a favorite yet, send to Marketplace
   - SBOs/contractors can accept and fulfill the job

Upgrade paths (osmosis growth):
- Upgrade to SBO:
  - Create & run your business inside SyncWorks
  - Add employees by role (Tech, Dispatch, PM, Accounting, HR, etc.)
  - Control permissions per employee (who can see what)
  - Manage tickets, scheduling, and invoices end-to-end

- Property Management (PM):
  - Invite tenants into a property (similar to employee invites)
  - Track issues/tickets per property
  - Add property investors/owners with visibility rules

Subcontractors:
- SBOs can add subcontractors to handle jobs
- Subcontractors can later upgrade to SBO and start advertising in the Marketplace

Next step:
Log in and create your first request.
If you own a business, upgrade to SBO and start adding your team.

Let’s build your operation,
SyncWorks
""".strip()

    html = f"""
    <div style="font-family: Arial, sans-serif; line-height: 1.5;">
      <h2 style="margin:0 0 8px 0;">Welcome to SyncWorks, {name} 👋</h2>
      <p style="margin:0 0 12px 0;">
        SyncWorks starts everyone as a <b>Customer</b> so you can request work immediately —
        then branches into <b>SBO</b>, <b>Property Management</b>, and more as you grow.
      </p>

      <h3 style="margin:18px 0 6px 0;">How it works</h3>
      <ol>
        <li><b>Customer Side (Everyone)</b>: create a request, add photos/details, and keep all chat/updates inside the app.</li>
        <li><b>Favorite a company</b>: route future requests directly to the same business for repeat service.</li>
        <li><b>Marketplace</b>: send requests publicly so available SBOs/contractors can accept them.</li>
      </ol>

      <h3 style="margin:18px 0 6px 0;">Upgrade paths (osmosis growth)</h3>
      <ul>
        <li><b>Upgrade to SBO</b>: manage tickets, scheduling, invoices, and add staff by role (Tech, Dispatch, PM, Accounting, HR).</li>
        <li><b>Property Management</b>: invite tenants, manage issues per property, add owners/investors with permission control.</li>
        <li><b>Subcontractors</b>: add subs to jobs; subs can later upgrade to SBO and advertise in Marketplace.</li>
      </ul>

      <p style="margin-top:16px;">
        <b>Next step:</b> Log in and create your first request. If you own a business, upgrade to SBO and add your team.
      </p>

      <p style="opacity:0.8; margin-top:18px;">— SyncWorks</p>
    </div>
    """.strip()

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to_email],
    )
    msg.attach_alternative(html, "text/html")
    msg.send(fail_silently=True)
