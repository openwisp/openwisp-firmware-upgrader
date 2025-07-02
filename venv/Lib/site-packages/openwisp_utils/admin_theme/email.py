import logging
from smtplib import SMTPRecipientsRefused

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from . import settings as app_settings

logger = logging.getLogger(__name__)


def send_email(
    subject,
    body_text,
    body_html,
    recipients,
    extra_context=None,
    html_email_template=app_settings.OPENWISP_EMAIL_TEMPLATE,
    **kwargs,
):
    extra_context = extra_context or {}
    mail = EmailMultiAlternatives(
        subject=subject,
        body=strip_tags(body_text),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=recipients,
        **kwargs,
    )
    if app_settings.OPENWISP_HTML_EMAIL and body_html:
        context = dict(
            subject=subject,
            message=body_html,
            logo_url=app_settings.OPENWISP_EMAIL_LOGO,
        )
        context.update(extra_context)

        html_message = render_to_string(
            html_email_template,
            context=context,
        )
        mail.attach_alternative(html_message, "text/html")
    try:
        mail.send()
    except SMTPRecipientsRefused as err:
        logger.warning(f"SMTP recipients refused: {err.recipients}")
