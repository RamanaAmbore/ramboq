import streamlit as st

small = "small"
smaller = 45

holdings_config = {
    "tradingsymbol": st.column_config.TextColumn(
        "Symbol", width="small",
        help="Trading Symbol"
    ),
    "opening_quantity": st.column_config.NumberColumn(
        "Qty", width=smaller,
        help="Quantity",
        default=None  # <- ensures empty shown for NaN
    ),
    "average_price": st.column_config.NumberColumn(
        "Inv Price", width=smaller,
        help="Average Investment Price",
        default=None  # <- ensures empty shown for NaN
    ),
    "close_price": st.column_config.NumberColumn(
        "Cur Price", width=smaller,
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
        "Price Δ", width=smaller,
        help="Closing Price",
        default=None  # <- ensures empty shown for NaN
    ),
    "pnl_percentage": st.column_config.NumberColumn(
        "P&L %", width=smaller,
        help="Profit & Loss",
        default=None  # <- ensures empty shown for NaN
    ),

    "day_change": st.column_config.NumberColumn(
        "Day Δ", width=smaller,
        help="Day price Change",
        default=None  # <- ensures empty shown for NaN
    ),
    "day_change_percentage": st.column_config.NumberColumn(
        "DayΔ%", width=smaller,
        help="Day price Change Percentage",
        default=None  # <- ensures empty shown for NaN
    ),
    "day_change_val": st.column_config.NumberColumn(
        "Day ΔVal", width="small",
        help="Profit & Loss",
        default=None  # <- ensures empty shown for NaN
    ),
    "authorised_date": st.column_config.TextColumn(
        "Date", width=smaller,
        help="When it the report generated?"
    ),
    "account": st.column_config.TextColumn(
        "Account", width=smaller,
        help="Account Number with Broker"
    )
}

positions_config = {
    "tradingsymbol": st.column_config.TextColumn(
        "Symbol", width="small",
        help="Trading Symbol"
    ),
    "quantity": st.column_config.NumberColumn(
        "Qty", width=smaller,
        help="Quantity",
        default=None
    ),
    "average_price": st.column_config.NumberColumn(
        "Inv Price", width=smaller,
        help="Average Investment Price",
        default=None
    ),
    "pnl": st.column_config.NumberColumn(
        "P&L", width="small",
        help="Profit & Loss",
        default=None
    ),
    "close_price": st.column_config.NumberColumn(
        "Cur Price", width=smaller,
        help="Closing Price",
        default=None
    ),
    "account": st.column_config.TextColumn(
        "Account", width=smaller,
        help="Account Number with Broker"
    ),
}

margins_config = {
    "account": st.column_config.TextColumn(label="Account", width=smaller),
    "avail opening_balance": st.column_config.NumberColumn(label="Cash", width=smaller),
    "net": st.column_config.NumberColumn(label="Avail Margin", width=smaller),
    "util debits": st.column_config.NumberColumn(label="Used Margin", width=smaller),
    "avail collateral": st.column_config.NumberColumn(label="Collateral", width=smaller),

}
