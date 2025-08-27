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
    "price_change": st.column_config.NumberColumn(
        "Price Δ", width="small",
        help="Closing Price",
        default=None  # <- ensures empty shown for NaN
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
        "Day Δ%", width="small",
        help="Day price Change Percentage",
        default=None  # <- ensures empty shown for NaN
    ),
    "day_change_val": st.column_config.NumberColumn(
        "Day Δ Val", width="small",
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
    "avail opening_balance": st.column_config.NumberColumn(label="Cash",width="small"),
    "avail collateral": st.column_config.NumberColumn(label="Collateral",width="small"),
    "util debits": st.column_config.NumberColumn(label="Used Margin", width="small"),
    "net": st.column_config.NumberColumn(label="Avail Margin", width="small"),

}
