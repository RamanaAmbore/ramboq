from openai import OpenAI
from src.helpers.utils import secrets, ramboq_config, ramboq_deploy

from datetime import datetime

# Get current day, date, and time in formatted string
now = datetime.now()
formatted_datetime = now.strftime('%A, %B %d, %Y, %I:%M %p')



# --- Replace this with your actual Perplexity API key ---
def get_market_update():
    if ramboq_deploy['test']:
        # Prepare the message text
        message = f"Market Report — {formatted_datetime}"
        report =  ramboq_config['market'].replace("Market Report", message)
        return report

    client = OpenAI(
        api_key=secrets["pplx_api_key"],
        base_url="https://api.perplexity.ai",  # Perplexity OpenAI-compatible endpoint
    )

    # Optional: You may include a system message for consistent persona
    system_message = {
        "role": "system",
        "content": ramboq_config["pplx_system_msg"]
    }

    # Your market report prompt (user message)
    user_message = {
        "role": "user",
        "content":  ramboq_config["pplx_user_msg"] # Paste your full portfolio as in the previous message
    }

    # Compose the messages list (system message optional)
    messages = [system_message, user_message]

    # Call the Perplexity API via the OpenAI-compatible client
    response = client.chat.completions.create(
        model="sonar-pro",              # Or another supported Perplexity model
        messages=messages,
        temperature=float(ramboq_config['pplx_temperature']),
        max_tokens=int(ramboq_config['pplx_max_tokens'])
    )


    # Print only the response text
    return response.choices[0].message.content

if __name__ == "__main__":
    print(get_market_update())
