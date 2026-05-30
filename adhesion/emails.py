from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def send_confirmation_email(adhesion):
    formulaire = adhesion.formulaire
    from_email = settings.DEFAULT_FROM_EMAIL
    reply_to = None
    if formulaire and formulaire.email_contact:
        reply_to = [formulaire.email_contact]

    context = {'adhesion': adhesion, 'formulaire': formulaire}
    subject = f"Confirmation d'adhésion – {adhesion.site.name}"
    text_body = render_to_string('adhesion/email_confirmation.txt', context)
    html_body = render_to_string('adhesion/email_confirmation.html', context)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_email,
        to=[adhesion.email],
        reply_to=reply_to,
    )
    msg.attach_alternative(html_body, 'text/html')
    msg.send(fail_silently=False)


def send_relance_email(adhesion):
    formulaire = adhesion.formulaire
    from_email = settings.DEFAULT_FROM_EMAIL
    reply_to = None
    if formulaire and formulaire.email_contact:
        reply_to = [formulaire.email_contact]

    context = {'adhesion': adhesion, 'formulaire': formulaire}
    subject = f"Rappel : votre adhésion au {adhesion.site.name}"
    text_body = render_to_string('adhesion/email_relance.txt', context)
    html_body = render_to_string('adhesion/email_relance.html', context)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_email,
        to=[adhesion.email],
        reply_to=reply_to,
    )
    msg.attach_alternative(html_body, 'text/html')
    msg.send(fail_silently=False)
