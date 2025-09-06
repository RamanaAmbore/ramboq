import streamlit as st

holdings_config = {
    "tradingsymbol": st.column_config.TextColumn(
        "Symbol", width="small",
        help="Trading Symbol"
    ),
    "opening_quantity": st.column_config.NumberColumn(
        "Qty", width="small",
        help="Quantity",
        default=None  # <- ensures empty shown for NaN
    ),
    "average_price": st.column_config.NumberColumn(
        "Inv Price", width="small",
        help="Average Investment Price",
        default=None  # <- ensures empty shown for NaN
    ),
    "close_price": st.column_config.NumberColumn(
        "Cur Price", width="small",
        help="Closing Price",
        default=None  # <- ensures empty shown for NaN
    ),
    "cash": st.column_config.NumberColumn(
        "Cash", width="small",
        help="Cash balance"
    ),

    "inv_val": st.column_config.NumberColumn(
        "Inv Val", width="small",
        help="Profit & Loss",
        default=None  # <- ensures empty shown for NaN
    ),
    "cur_val": st.column_config.NumberColumn(
        "Cur Val", width="small",
        help="Profit & Loss",
        default=None  # <- ensures empty shown for NaN
    ),
    "pnl": st.column_config.NumberColumn(
        "P&L", width="small",
        help="Profit & Loss",
        default=None  # <- ensures empty shown for NaN
    ),
    "net": st.column_config.NumberColumn(
        "Hold+Cash", width="small",
        help="Holdings plus cash"
    ),
    "price_change": st.column_config.NumberColumn(
        "Price Δ", width="small",
        help="Closing Price",
        default=None  # <- ensures empty shown for NaN
    ),
    "pnl_percentage": st.column_config.NumberColumn(
        "P&L %", width="small",
        help="Profit & Loss",
        default=None  # <- ensures empty shown for NaN
    ),

    "day_change": st.column_config.NumberColumn(
        "Day Δ", width="small",
        help="Day price Change",
        default=None  # <- ensures empty shown for NaN
    ),
    "day_change_percentage": st.column_config.NumberColumn(
        "DayΔ%", width="small",
        help="Day price Change Percentage",
        default=None  # <- ensures empty shown for NaN
    ),
    "day_change_val": st.column_config.NumberColumn(
        "Day ΔVal", width="small",
        help="Profit & Loss",
        default=None  # <- ensures empty shown for NaN
    ),
    "authorised_date": st.column_config.TextColumn(
        "Date", width="small",
        help="When it the report generated?"
    ),
    "account": st.column_config.TextColumn(
        "Account", width="small",
        help="Account Number with Broker"
    )
}

positions_config = {
    "tradingsymbol": st.column_config.TextColumn(
        "Symbol", width="small",
        help="Trading Symbol"
    ),
    "quantity": st.column_config.NumberColumn(
        "Qty", width="small",
        help="Quantity",
        default=None
    ),
    "average_price": st.column_config.NumberColumn(
        "Inv Price", width="small",
        help="Average Investment Price",
        default=None
    ),
    "pnl": st.column_config.NumberColumn(
        "P&L", width="small",
        help="Profit & Loss",
        default=None
    ),
    "close_price": st.column_config.NumberColumn(
        "Cur Price", width="small",
        help="Closing Price",
        default=None
    ),
    "account": st.column_config.TextColumn(
        "Account", width="small",
        help="Account Number with Broker"
    ),
}

margins_config = {
    "account": st.column_config.TextColumn(label="Account", width="small"),
    "avail opening_balance": st.column_config.NumberColumn(label="Cash", width="small"),
    "net": st.column_config.NumberColumn(label="Avail Margin", width="small"),
    "util debits": st.column_config.NumberColumn(label="Used Margin", width="small"),
    "avail collateral": st.column_config.NumberColumn(label="Collateral", width="small"),

}

email_contact_tmpl = """
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
              <li><b>ISD:</b> {ph_country}</li>
              <li><b>Phone:</b> {ph_num}</li>
              <li><b>Email:</b> {email_id}</li>
              <li><b>Subject:</b> {subject}</li>
              <li><b>Message/Query:</b> {query}</li>
            </ul>

            <p>Best regards,<br>[RamboQ team]</p>
          </body>
        </html>
        """

email_reg_tmpl = """
        <html>
          <body>
            <p>Dear sir/madam,</p>
            <p>
              Thank you for registering with us using {email_id}! Your sign-up was successful, and your details have been received.

            To complete your onboarding, please follow these steps:
            
            <ol> <li><b>Sign in</b> to your account using your registered email and password.</li> <li><b>Update your profile</b> with the required information.</li> <li>Your registration details will be <b>reviewed and validated by a member of the RamboQ team</b>.</li> <li>Once your profile is approved, you will receive a confirmation. <b>You will then be able to access and use all features of your account.</b></li> </ol>
            If you have any questions, feel free to contact us.
            </p>
            
            <p>Best regards,<br>[RamboQ team]</p>
          </body>
        </html>
        """

email_prof_updated_tmpl = """
        <html>
          <body>
            <p>Dear sir/madam,</p>
            <p>
              Thank you for updating your profile for your account registered with {email_id}!<br>
              Your updated details have been received successfully.
            </p>
            <p>
              <b>What happens next?</b>
              <ol>
                <li>Your registration and profile information will now be <b>reviewed and validated by a member of the RamboQ team</b>.</li>
                <li>Once your profile is approved, you will receive a confirmation by email.</li>
                <li>After approval, you will have full access to your account and all platform features.</li>
              </ol>
              If you have any questions, feel free to contact us at any time.
            </p>
            <p>Best regards,<br>[RamboQ team]</p>
          </body>
        </html>
        """

email_prof_approval_tmpl = """
        <html>
          <body>
            <p>Dear sir/madam,</p>
            <p>
              We are pleased to inform you that your profile associated with the account registered under {email_id} has been <b>approved</b>.
            </p>
            <p>
              You now have full access to your account and all features on our platform. If you have any questions or need assistance, please feel free to reach out to us at any time.
            </p>
            <p>Thank you for choosing Rambo!</p>
            <p>Best regards,<br>[RamboQ team]</p>
          </body>
        </html>
        """

email_update_tmpl = """
<html>
  <body>
    <p>Dear sir/madam,</p>
    <p>
      Your password for the account registered with {email_id} has been successfully updated.
    </p>
    <p>
      You can now sign in using your new password.<br>
      If you did not initiate this change or if you face any issues, please contact our support team immediately.
    </p>
    <p>
      For security, we recommend updating your profile information if necessary and reviewing your account settings.
    </p>
    <p>
      Thank you for being a valued member of the Rambo community.
    </p>
    <p>Best regards,<br>[RamboQ team]</p>
  </body>
</html>
"""
