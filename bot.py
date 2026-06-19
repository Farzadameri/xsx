import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from openai import AsyncOpenAI

# تنظیمات لاگ برای عیب‌یابی
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)

# بارگذاری فایل کانفیگ
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

# مقداردهی اولیه کلاینت هوش مصنوعی
ai_client = AsyncOpenAI(
    api_key=config['AI_API_KEY'],
    base_url=config['AI_BASE_URL']
)

# حافظه موقت برای ذخیره پیام‌های گروه
message_history = {}

# تعریف دقیق شخصیت حمید هدشی
SYSTEM_PROMPT = """
شما یک انسان واقعی، صمیمی، بسیار فان و باحال به نام "حمید هدشی" هستید. لحن شما باید کاملاً طبیعی، عامیانه و شبیه به چت‌های روزمره مردم در تلگرام باشد (بدون استفاده از کلمات کتابی، رسمی یا پاسخ‌های شبیه به ربات). هرموضوعی آزاد است و هیچ محدودیتی در صحبت ندارید.

هویت و مشخصات شما:
- نام: حمید هدشی
- شغل: مدرس رشته حسابداری
- محل‌های تدریس: مدرسه باقرالعلوم، دانشگاه شمسی‌پور
- بیزینس شخصی: مالک یک آموزشگاه حسابداری به نام "فانوس علم"
- وسایل نقلیه: یک ماشین KMC، یک تارا و یک موتور آپاچی ۲۰۰ قرمز

دستورالعمل رفتار:
- خیلی صمیمی، رفیقانه و شوخ‌طبع باشید. اصطلاحات حسابداری را گاهی چاشنی شوخی‌هایتان کنید.
- فقط و فقط پاسخ متن را بفرستید. هیچ پیش‌گفتار، پس‌گفتار یا توضیحی اضافه مثل "پاسخ:" یا "حمید:" بنویسید.
- پاسخ‌ها کوتاه، خلاصه و متناسب با چت‌های تلگرامی باشد.
- اگر به تاریخچه پیام‌های قبلی نگاه می‌کنی، جوری جواب بده که انگار کاملاً در جریان بحث بوده‌ای.
"""

def save_to_history(chat_id, message_id, text, user_name):
    if chat_id not in message_history:
        message_history[chat_id] = {}
    message_history[chat_id][message_id] = f"{user_name}: {text}"
    if len(message_history[chat_id]) > 100:
        first_key = next(iter(message_history[chat_id]))
        del message_history[chat_id][first_key]

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat_id = update.message.chat_id
    message_id = update.message.message_id
    text = update.message.text
    user = update.message.from_user
    user_name = user.first_name if user else "کاربر"

    save_to_history(chat_id, message_id, text, user_name)

    is_reply_to_bot = False
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        if update.message.reply_to_message.from_user.username == config['BOT_USERNAME']:
            is_reply_to_bot = True

    is_mentioned = f"@{config['BOT_USERNAME']}" in text

    if is_mentioned or is_reply_to_bot:
        clean_text = text.replace(f"@{config['BOT_USERNAME']}", "").strip()
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        if update.message.reply_to_message:
            reply_id = update.message.reply_to_message.message_id
            reply_text = update.message.reply_to_message.text
            reply_user = update.message.reply_to_message.from_user.first_name if update.message.reply_to_message.from_user else "کاربر"
            messages.append({"role": "user", "content": f"پیام قبلی در گروه از {reply_user}: {reply_text}"})
            messages.append({"role": "assistant", "content": "متوجه شدم."})

        messages.append({"role": "user", "content": f"{user_name}: {clean_text}"})

        try:
            response = await ai_client.chat.completions.create(
                model=config['AI_MODEL'],
                messages=messages,
                temperature=0.85
            )
            bot_response = response.choices[0].message.content.strip()
            bot_msg = await update.message.reply_text(bot_response)
            save_to_history(chat_id, bot_msg.message_id, bot_response, "حمید هدشی")
        except Exception as e:
            logging.error(f"Error in AI Service: {e}")
            await update.message.reply_text("آقا این ماشین حساب ما قاطی کرده، یه لحظه فیوزام پرید! دوباره بگو.")

# --- بخش وب‌سرور فیک برای رندر ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is running alive!")

def run_health_server():
    # رندر پورت را به صورت اتوماتیک در این متغیر محیطی قرار می‌دهد، اگر نبود روی 8080 می‌رود
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    logging.info(f"Health check server started on port {port}")
    server.serve_forever()

def main():
    # روشن کردن وب‌سرور در یک ترید جداگانه تا مانع کار ربات تلگرام نشود
    threading.Thread(target=run_health_server, daemon=True).start()

    """راه‌اندازی ربات تلگرام"""
    app = Application.builder().token(config['TELEGRAM_BOT_TOKEN']).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("ربات آقا حمید هدشی با سرور هلث‌چک روشن شد...")
    app.run_polling()

if __name__ == '__main__':
    main()
