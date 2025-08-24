import streamlit as st

holdings_config =         {
        "tradingsymbol": st.column_config.TextColumn(
            "Symbol",
            help="Trading Symbol"
        ),
        "opening_quantity": st.column_config.NumberColumn(
                    "Qty",
            help="Quantity",
            format=",.0f",  # integer with comma separator
            default=None  # <- ensures empty shown for NaN
        ),
        "average_price": st.column_config.NumberColumn(
            "Inv Price",
            help="Average Investment Price",
            format=",.2f",  # integer with comma separator
            default=None  # <- ensures empty shown for NaN
        ),
        "pnl": st.column_config.NumberColumn(
            "P&L",
            help="Profit & Loss",
            format=",.0f",  # integer with comma separator
            default=None  # <- ensures empty shown for NaN
        ),
        "close_price": st.column_config.NumberColumn(
            "C Price",
            help="Closing Price",
            format=",.1f",  # integer with comma separator
            default=None  # <- ensures empty shown for NaN
        ),
        "day_change": st.column_config.NumberColumn(
            "DayΔ",
            help="Day price Change",
            format=",.2f",  # integer with comma separator
            default=None  # <- ensures empty shown for NaN
        ),
        "day_change_percentage": st.column_config.NumberColumn(
            "DayΔ%",
            help="Day price Change Percentage",
            format=",.2f",  # integer with comma separator
            default=None  # <- ensures empty shown for NaN
        ),
        "authorised_date": st.column_config.TextColumn(
            "Date",
            help="When it the report generated?"
        ),
        "account": st.column_config.TextColumn(
            "Account",
            help="Account Number with Broker"
        )
    }


positions_map = {
    "rename": {"tradingsymbol": "Symbol",
             "opening_quantity": "Qty",
             "average_price": "I Price",
             "pnl": "P&L",
             "close_price": "C Price",
             "day_change": "ΔPrice",
             "day_change_percentage": "ΔPrice%",
             "authorised_date": "Date",
             "account": "Account"
             },
    "column_config": {
        "price": st.column_config.NumberColumn(
            "Price (in USD)",
            help="The price of the product in USD",

        )

    }

}

margin_map = {
    "rename": {"tradingsymbol": "Symbol",
             "opening_quantity": "Qty",
             "average_price": "I Price",
             "pnl": "P&L",
             "close_price": "C Price",
             "day_change": "ΔPrice",
             "day_change_percentage": "ΔPrice%",
             "authorised_date": "Date",
             "account": "Account"
             },
    "column_config": {
        "price": st.column_config.NumberColumn(
            "Price (in USD)",
            help="The price of the product in USD",
        )

    }

}
