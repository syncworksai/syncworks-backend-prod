from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMultiAlternatives


def frontend_url():
    return str(
        getattr(settings, "SYNCWORKS_FRONTEND_URL", "")
        or getattr(settings, "FRONTEND_URL", "")
        or "https://syncworksapp.com"
    ).rstrip("/")


def team_invite_urls(token, email):
    invite_path = f"/sports/team-invite/{token}"
    base = frontend_url()
    return {
        "invite_url": f"{base}{invite_path}",
        "register_url": f"{base}/register?email={email}&next={invite_path}",
        "login_url": f"{base}/login?email={email}&next={invite_path}",
    }


def syncworks_team_invite_html(*, team_name, context_line, invite_url, account_exists):
    access_steps = (
        "After you join: open <b>SyncWorks → Personal → Social → Groups</b>, then choose "
        f"<b>{team_name}</b>. Your team dashboard keeps your player profile, schedule, RSVP, "
        "lineup, team chat, statistics and any fees you owe in one place."
    )
    account_copy = (
        "You already have a SyncWorks account. Sign in with the email that received this invite."
        if account_exists
        else "Your SyncWorks Personal account is free. Create it with the email that received this invitation, then the invite will bring you back to your team."
    )
    return f"""
    <div style="margin:0;background:#02060c;padding:28px 12px;font-family:Arial,Helvetica,sans-serif;color:#e5edf7">
      <div style="max-width:640px;margin:0 auto;border:1px solid #18314d;border-radius:24px;overflow:hidden;background:#07111f">
        <div style="padding:22px 24px;background:linear-gradient(135deg,#102849,#0b1731 58%,#24133f)">
          <div style="display:flex;align-items:center;gap:12px">
            <div style="width:42px;height:42px;border-radius:12px;background:#050b14;border:1px solid #1e6f99;color:#46d7ff;font-size:23px;line-height:42px;text-align:center;font-weight:900">S</div>
            <div>
              <div style="font-size:18px;font-weight:900;letter-spacing:4px;color:#ffffff">SYNCWORKS</div>
              <div style="margin-top:3px;font-size:11px;letter-spacing:2px;color:#7dd3fc">PERSONAL · SOCIAL</div>
            </div>
          </div>
        </div>

        <div style="padding:26px 24px">
          <div style="font-size:11px;font-weight:800;letter-spacing:2px;color:#5eead4;text-transform:uppercase">Team invitation</div>
          <h1 style="margin:8px 0 6px;font-size:28px;line-height:1.15;color:#ffffff">Join {team_name}</h1>
          <p style="margin:0;color:#94a3b8;font-size:14px">{context_line}</p>

          <div style="margin-top:20px;padding:16px;border:1px solid #1e293b;border-radius:16px;background:#050b14">
            <div style="font-weight:800;color:#ffffff">What this connects for you</div>
            <p style="margin:8px 0 0;color:#cbd5e1;font-size:14px;line-height:1.6">
              {access_steps}
            </p>
          </div>

          <p style="margin:18px 0 0;color:#cbd5e1;font-size:14px;line-height:1.6">{account_copy}</p>

          <p style="margin:22px 0">
            <a href="{invite_url}" style="display:inline-block;background:#67e8f9;color:#07111f;text-decoration:none;font-weight:900;padding:13px 20px;border-radius:12px">
              Open team invitation
            </a>
          </p>

          <div style="margin-top:20px;padding-top:18px;border-top:1px solid #1e293b">
            <div style="font-size:12px;font-weight:800;color:#ffffff">Your free SyncWorks Personal account also gives you:</div>
            <ul style="padding-left:18px;margin:10px 0 0;color:#94a3b8;font-size:13px;line-height:1.7">
              <li>Social Groups for teams, clubs, churches, book clubs, families and communities.</li>
              <li>Your personal calendar, group events, reminders and connected schedules.</li>
              <li>Service requests and the SyncWorks marketplace when you need work done.</li>
              <li>One account that can also add Business mode if you run a company.</li>
            </ul>
          </div>

          <div style="margin-top:18px;padding:14px;border-radius:14px;background:#0b1b2e;color:#94a3b8;font-size:12px;line-height:1.6">
            Business mode is separate from your free Personal account and adds business operations such as customers, scheduling, finance, team tools and more.
          </div>
        </div>

        <div style="padding:16px 24px;border-top:1px solid #18314d;color:#64748b;font-size:11px">
          SyncWorks · One account for Personal, Social and Business.
        </div>
      </div>
    </div>
    """.strip()


def send_syncworks_team_invite(*, to_email, team_name, context_line, invite_url, account_exists=False):
    subject = f"Join {team_name} on SyncWorks"
    text = (
        f"SYNCWORKS\n\n"
        f"You've been invited to {team_name}.\n"
        f"{context_line}\n\n"
        f"Open your invitation: {invite_url}\n\n"
        f"After joining, go to SyncWorks > Personal > Social > Groups > {team_name}.\n"
        "Your team dashboard includes your player profile, schedule, RSVP, lineup, statistics, chat and fees.\n\n"
        "SyncWorks Personal accounts are free. Social Groups can be used for teams, clubs, book clubs, churches, families and communities. "
        "If you run a company, Business mode is also available from the same SyncWorks account."
    )
    html = syncworks_team_invite_html(
        team_name=team_name,
        context_line=context_line,
        invite_url=invite_url,
        account_exists=account_exists,
    )
    message = EmailMultiAlternatives(
        subject=subject,
        body=text,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "SyncWorks <no-reply@syncworksapp.com>"),
        to=[to_email],
    )
    message.attach_alternative(html, "text/html")
    message.send(fail_silently=True)
    return True
