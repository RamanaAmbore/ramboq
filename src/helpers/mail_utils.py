import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.helpers.utils import secrets, ramboq_deploy


def send_contact_email(name, to_email, query, phone="", subject=""):
    """
    Email a single recipient, CC to the smtp_user.
    - to_email: str (single email address)
    """

    smtp_server = secrets['smtp_server']
    smtp_port = secrets['smtp_port']
    smtp_user = secrets['smtp_user']
    smtp_pass = secrets['smtp_pass']

    # --- Subject ---
    subject = f"New Contact Form Submission from {name}" if subject == "" else f"{subject} from {name}"
    subject = f"{subject} on {date.today()}"

    # --- Body ---
    body = f"""
    <html>
      <body>
        <p>Dear {name},</p>
        <p>
          Thank you for reaching out to us. We have successfully received your message, 
          and our team is currently reviewing the details.<br>
          We will get back to you at the earliest possible time.
        </p>

        <p><b>Details you submitted:</b></p>
        <ul>
          <li><b>Name:</b> {name}</li>
          <li><b>Phone:</b> {phone}</li>
          <li><b>Email:</b> {to_email}</li>
          <li><b>Subject:</b> {subject}</li>
          <li><b>Message/Query:</b> {query}</li>
        </ul>

        <p>Best regards,<br>[Rambo team]</p>
      </body>
    </html>
    """

    # --- Build message ---
    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = to_email.strip()
    msg["Cc"] = smtp_user
    msg["Subject"] = f'Acknowledgement: {subject}'
    msg.attach(MIMEText(body, "html"))

    # Final recipient list for SMTP
    recipients = to_email.strip()

    try:
        if  ramboq_deploy['prod'] or ramboq_deploy['mail']:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, recipients, msg.as_string())  # ✅ send to both To & CC
            return True, ''
        else:
            print(msg.as_string())
            return True, "Test mode only"

    except Exception as e:
        err_msg = f"Email send error: {e}"
        return False, err_msg
if __name__ == "__main__":
    # Test run
    name = "Rambo"
    recipients = "ramboquant@gmail.com"
    phone = "9876543210"
    query = "Testing multiple recipient email functionality."

    success, msg = send_contact_email(name, recipients, query)
    if success:
        print("✅ Email sent successfully!")
    else:
        print("❌ Failed to send email:", msg)