
from openai import OpenAI

from src.helpers.date_time_utils import timestamp_indian
from src.helpers.ramboq_logger import get_logger
from src.helpers.utils import secrets, ramboq_config, ramboq_deploy

logger = get_logger(__name__)


# --- Replace this with your actual Perplexity API key ---
def get_market_update():
    # Get current day, date, and time in formatted string
    now = timestamp_indian()
    formatted_datetime = now.strftime('%A, %B %d, %Y, %I:%M %p')
    logger.info(f'GenAI for market updated invoked at {formatted_datetime}')
    message = f"Market Report — {formatted_datetime} IST"
    fallback = ramboq_config['market'].replace("Market Report", message)

    if not ramboq_deploy['perplexity']:
        return fallback

    try:
        client = OpenAI(
            api_key=secrets["pplx_api_key"],
            base_url="https://api.perplexity.ai",
        )

        messages = [
            {"role": "system", "content": ramboq_config["pplx_system_msg"]},
            {"role": "user", "content": ramboq_config["pplx_user_msg"]},
        ]

        response = client.chat.completions.create(
            model="sonar-pro",
            messages=messages,
            temperature=float(ramboq_config['pplx_temperature']),
            max_tokens=int(ramboq_config['pplx_max_tokens'])
        )

        resp = response.choices[0].message.content
        logger.info(resp)
        return resp

    except Exception as e:
        logger.error(f"Perplexity API call failed: {e}")
        return fallback


if __name__ == "__main__":
    print(get_market_update())
