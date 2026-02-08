# A small replacement of create_message to accept attachment bytes (used by worker)
import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import os

def create_message(sender, to, subject, html_body, attachment_bytes: bytes = None, attachment_name: str = "attachment.pdf"):
    message = MIMEMultipart()
    message['to'] = to
    message['from'] = sender
    message['subject'] = subject

    message.attach(MIMEText(html_body, 'html'))

    if attachment_bytes:
        part = MIMEApplication(attachment_bytes, _subtype="pdf")
        part.add_header('Content-Disposition', 'attachment', filename=attachment_name)
        message.attach(part)

    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {'raw': raw_message}