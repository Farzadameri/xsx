import json
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
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

# حافظه موقت برای ذخیره پیام‌های گروه (برای بازسازی زنجیره ریپلای)
# کلید: message_id, مقدار: متن پیام و فرستنده
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
- پاسخ‌ها کوتاه، خلاصه و متناسب با چت‌های تلگرامی باشد (طومار ننویسید، مگر اینکه موضوع نیاز به کل‌کل یا توضیح باحال داشته باشد).
- اگر به تاریخچه پیام‌های قبلی نگاه می‌کنی، جوری جواب بده که انگار کاملاً در جریان بحث بوده‌ای.
"""

def save_to_history(chat_id, message_id, text, user_name):
    """ذخیره پیام‌ها در حافظه برای استفاده در ریپلای‌های بعدی"""
    if chat_id not in message_history:
        message_history[chat_id] = {}
    
    # ذخیره متن پیام به همراه نام فرستنده
    message_history[chat_id][message_id] = f"{user_name}: {text}"
    
    # محدود کردن حجم حافظه هر گروه برای جلوگیری از مصرف بیش از حد رم (مثلاً ۱۰۰ پیام آخر)
    if len(message_history[chat_id]) > 100:
        first_key = next(iter(message_history[chat_id]))
        del message_history[chat_id][first_key]

def build_reply_chain(chat_id, current_reply_to_id):
    """بازسازی زنجیره ریپلای‌ها برای فهمیدن موضوع بحث"""
    chain = []
    current_id = current_reply_to_id
    
    # تا جایی که پیام قبلی در حافظه موجود باشد، زنجیره را دنبال می‌کند
    while current_id and chat_id in message_history and current_id in message_history[chat_id]:
        chain.insert(0, message_history[chat_id][current_id])
        # در این ساختار ساده، فقط پیام مستقیم قبلی را می‌آوریم، 
        # اگر می‌خواهید زنجیره‌های طولانی‌تر داشته باشید باید شناسه ریپلایِ پیامِ قبلی را هم ذخیره کنید.
        break 
    
    return chain

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat_id = update.message.chat_id
    message_id = update.message.message_id
    text = update.message.text
    user = update.message.from_user
    user_name = user.first_name if user else "کاربر"

    # ۱. ذخیره پیام جاری در حافظه گروه
    save_to_history(chat_id, message_id, text, user_name)

    # ۲. بررسی اینکه آیا ربات باید پاسخ دهد یا خیر؟
    is_reply_to_bot = False
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        if update.message.reply_to_message.from_user.username == config['BOT_USERNAME']:
            is_reply_to_bot = True

    is_mentioned = f"@{config['BOT_USERNAME']}" in text

    # اگر تگ شده بود یا ریپلای شده بود، پردازش شروع می‌شود
    if is_mentioned or is_reply_to_bot:
        # حذف منشن از متن برای ارسال تمیزتر به هوش مصنوعی
        clean_text = text.replace(f"@{config['BOT_USERNAME']}", "").strip()
        
        # ساخت پیام‌های ورودی برای مدل
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        # بررسی وجود ریپلای و بازسازی بافتار بحث
        if update.message.reply_to_message:
            reply_id = update.message.reply_to_message.message_id
            reply_text = update.message.reply_to_message.text
            reply_user = update.message.reply_to_message.from_user.first_name if update.message.reply_to_message.from_user else "کاربر"
            
            # اضافه کردن پیام قبلی که ریپلای شده به عنوان کانتکست
            messages.append({"role": "user", "content": f"پیام قبلی در گروه از {reply_user}: {reply_text}"})
            messages.append({"role": "assistant", "content": "متوجه شدم. حالا منتظر پاسخ یا واکنش بعدی هستم."})

        # اضافه کردن پیام فعلی کاربر
        messages.append({"role": "user", "content": f"{user_name}: {clean_text}"})

        try:
            # ارسال درخواست به API هوش مصنوعی
            response = await ai_client.chat.completions.create(
                model=config['AI_MODEL'],
                messages=messages,
                temperature=0.85 # دمای بالاتر برای خلاق‌تر و فان‌تر شدن لحن
            )
            
            bot_response = response.choices[0].message.content.strip()
            
            # ارسال پاسخ به صورت ریپلای روی پیام کاربر
            bot_msg = await update.message.reply_text(bot_response)
            
            # ذخیره پاسخ خود ربات در حافظه
            save_to_history(chat_id, bot_msg.message_id, bot_response, "حمید هدشی")

        except Exception as e:
            logging.error(f"Error in AI Service: {e}")
            # پاسخ فان در صورت بروز خطا بدون لو دادن ماهیت فنی
            await update.message.reply_text("آقا این ماشین حساب ما قاطی کرده، یه لحظه فیوزام پرید! دوباره بگو.")

def main():
    """راه‌اندازی ربات تلگرام"""
    app = Application.builder().token(config['TELEGRAM_BOT_TOKEN']).build()

    # مدیریت تمام پیام‌های متنی در گروه‌ها و چت‌های شخصی
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("ربات آقا حمید هدشی روشن شد و آماده تراز کردنه...")
    app.run_polling()

if __name__ == '__main__':
    main()
