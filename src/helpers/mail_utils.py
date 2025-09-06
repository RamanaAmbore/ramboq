import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from src.helpers.utils import secrets, ramboq_deploy


def send_email(name, email_id, subject, html_body):
    """
    Email a single recipient, CC to the smtp_user.
    - to_email: str (single email address)
    """

    smtp_server = secrets['smtp_server']
    smtp_port = secrets['smtp_port']
    smtp_user = secrets['smtp_user']
    smtp_pass = secrets['smtp_pass']
    smtp_user_name = secrets['smtp_user_name']


    # --- Build message ---
    msg = MIMEMultipart()

    msg["From"] = formataddr((smtp_user_name, smtp_user))
    email_id = email_id
    msg["To"] = formataddr((name, email_id)) if name else email_id
    msg["Cc"] = msg["From"]
    msg["Subject"] = subject

    msg.attach(MIMEText(html_body, "html"))

    # Final recipient list for SMTP
    recipients = email_id

    try:
        if ramboq_deploy['prod'] or ramboq_deploy['mail']:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, recipients, msg.as_string())  # ✅ send to both To & CC
            return True, '✅ Your message has been sent successfully!'
        else:
            print(msg.as_string())
            return True, "Non-prod mode only"

    except Exception as e:
        err_msg = f"Email send error: {e}"
        return False, err_msg


if __name__ == "__main__":
    # Test run
    name = "Rambo"
    recipients = "ramboquant@gmail.com"
    phone = "9876543210"
    query = "Testing multiple recipient email functionality."

    success, msg = send_email(name, recipients, query)
    if success:
        print("✅ Email sent successfully!")
    else:
        print("❌ Failed to send email:", msg)
