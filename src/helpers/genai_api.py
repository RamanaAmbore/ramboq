from google import genai
from google.genai import types

from src.helpers.date_time_utils import timestamp_indian, timestamp_est
from src.helpers.ramboq_logger import get_logger
from src.helpers.utils import secrets, ramboq_config, ramboq_deploy, is_prod_capable

logger = get_logger(__name__)


def get_market_update():
    now = timestamp_indian()
    now_est = timestamp_est()
    formatted_ist = now.strftime('%a, %B %d, %Y, %I:%M %p IST')
    formatted_est = now_est.strftime('%a, %B %d, %Y, %I:%M %p %Z')
    logger.info(f'GenAI for market update invoked at {formatted_ist}')

    message = f"Market Report — {formatted_ist} | {formatted_est}"
    fallback = ramboq_config['market'].replace("Market Report", message)

    if not ramboq_deploy['genai']:
        return fallback
    if not is_prod_capable():
        logger.info("GenAI skipped — not prod-capable (set cap_in_dev to True)")
        return fallback

    try:
        client = genai.Client(api_key=secrets["gemini_api_key"])

        prompt = (
            f"Current date and time: {formatted_ist} IST | {formatted_est} EST\n\n"
            f"{ramboq_config['genai_user_msg']}"
        )

        response = client.models.generate_content(
            model=ramboq_config.get('genai_model', 'gemini-2.5-flash'),
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=ramboq_config['genai_system_msg'],
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=float(ramboq_config['genai_temperature']),
                max_output_tokens=int(ramboq_config['genai_max_tokens']),
            ),
        )

        resp = response.text
        if not resp:
            logger.warning("Gemini returned empty response — using fallback")
            return fallback
        logger.info(resp)
        return resp

    except Exception as e:
        logger.error(f"Gemini market update failed: {e}")
        return fallback


if __name__ == "__main__":
    print(get_market_update())
