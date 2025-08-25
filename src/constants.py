import streamlit as st

holdings_config =         {
        "tradingsymbol": st.column_config.TextColumn(
            "Symbol",width="small",
            help="Trading Symbol"
        ),
        "opening_quantity": st.column_config.NumberColumn(
                    "Qty", width="small",
            help="Quantity",
            format="%d",  # integer with comma separator
            default=None  # <- ensures empty shown for NaN
        ),
        "average_price": st.column_config.NumberColumn(
            "Inv Price",width="small",
            help="Average Investment Price",
            format="%.2f",  # integer with comma separator
            default=None  # <- ensures empty shown for NaN
        ),
        "pnl": st.column_config.NumberColumn(
            "P&L",width="small",
            help="Profit & Loss",
            format="%.0f",  # integer with comma separator
            default=None  # <- ensures empty shown for NaN
        ),
        "close_price": st.column_config.NumberColumn(
            "Cur Price",width="small",
            help="Closing Price",
            format="%.1f",  # integer with comma separator
            default=None  # <- ensures empty shown for NaN
        ),
        "day_change": st.column_config.NumberColumn(
            "Day Δ",width="small",
            help="Day price Change",
            format="%.2f",  # integer with comma separator
            default=None  # <- ensures empty shown for NaN
        ),
        "day_change_percentage": st.column_config.NumberColumn(
            "Day Δ%",width="small",
            help="Day price Change Percentage",
            format="%.2f",  # integer with comma separator
            default=None  # <- ensures empty shown for NaN
        ),
        "authorised_date": st.column_config.TextColumn(
            "Date",width="small",
            help="When it the report generated?"
        ),
        "account": st.column_config.TextColumn(
            "Account",width="small",
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
        format="%d",
        default=None
    ),
    "average_price": st.column_config.NumberColumn(
        "Inv Price", width="small",
        help="Average Investment Price",
        format="%.2f",
        default=None
    ),
    "pnl": st.column_config.NumberColumn(
        "P&L", width="small",
        help="Profit & Loss",
        format="%.0f",
        default=None
    ),
    "close_price": st.column_config.NumberColumn(
        "Cur Price", width="small",
        help="Closing Price",
        format="%.1f",
        default=None
    ),
    "account": st.column_config.TextColumn(
        "Account", width="small",
        help="Account Number with Broker"
    ),
}


margins_config = {
    "avail opening_balance": st.column_config.NumberColumn(label="Cash", format="%d", width="small"),
    "avail collateral": st.column_config.NumberColumn(label="Collateral", format="%d", width="small"),
    "util debits": st.column_config.NumberColumn(label="Used Margin", format="%d", width="small"),
    "net": st.column_config.NumberColumn(label="Avail Margin", format="%d", width="small"),
}