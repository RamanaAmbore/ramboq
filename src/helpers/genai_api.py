from google import genai
from google.genai import types

from src.helpers.date_time_utils import timestamp_indian
from src.helpers.ramboq_logger import get_logger
from src.helpers.utils import secrets, ramboq_config, ramboq_deploy

logger = get_logger(__name__)


def get_market_update():
    now = timestamp_indian()
    formatted_datetime = now.strftime('%A, %B %d, %Y, %I:%M %p')
    logger.info(f'GenAI for market update invoked at {formatted_datetime}')

    message = f"Market Report — {formatted_datetime} IST"
    fallback = ramboq_config['market'].replace("Market Report", message)

    if not ramboq_deploy['perplexity']:
        return fallback

    try:
        client = genai.Client(api_key=secrets["gemini_api_key"])

        prompt = (
            f"Current date and time: {formatted_datetime} IST\n\n"
            f"{ramboq_config['pplx_user_msg']}"
        )

        response = client.models.generate_content(
            model=ramboq_config.get('genai_model', 'gemini-2.5-flash'),
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=ramboq_config['pplx_system_msg'],
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=float(ramboq_config['pplx_temperature']),
                max_output_tokens=int(ramboq_config['pplx_max_tokens']),
            ),
        )

        resp = response.text
        logger.info(resp)
        return resp

    except Exception as e:
        logger.error(f"Gemini market update failed: {e}")
        return fallback


if __name__ == "__main__":
    print(get_market_update())
