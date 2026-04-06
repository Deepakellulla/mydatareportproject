import os
import asyncio
from datetime import datetime, timedelta
from pyrogram import Client, filters
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pymongo import MongoClient

# -------- ENV --------
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
MONGO_URI = os.getenv("MONGO_URI")

app = Client("ott-bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# -------- DB --------
mongo = MongoClient(MONGO_URI)
db = mongo["ott_bot"]

sales = db["sales"]
customers = db["customers"]

# -------- START --------
@app.on_message(filters.command("start"))
async def start(client, message):
    user = message.from_user

    customers.update_one(
        {"user_id": user.id},
        {"$set": {"user_id": user.id, "name": user.first_name}},
        upsert=True
    )

    if user.id == OWNER_ID:
        await message.reply("👑 Admin Panel Active")
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Send ID to Admin", callback_data="send_id")],
            [InlineKeyboardButton("📊 My Subscription", callback_data="my_plan")]
        ])

        await message.reply(
            "✅ You will receive subscription updates.",
            reply_markup=keyboard
        )

# -------- SEND ID --------
@app.on_callback_query(filters.regex("send_id"))
async def send_id(client, callback_query):
    user = callback_query.from_user

    await app.send_message(
        OWNER_ID,
        f"📥 New Customer\n\n👤 {user.first_name}\n🆔 {user.id}"
    )

    await callback_query.answer("✅ Sent!")

# -------- MY PLAN --------
@app.on_callback_query(filters.regex("my_plan"))
async def my_plan(client, callback_query):
    user_id = callback_query.from_user.id

    user_sale = sales.find_one(
        {"user_id": user_id},
        sort=[("expiry_date", -1)]
    )

    if not user_sale:
        return await callback_query.answer("No active plan", show_alert=True)

    await callback_query.message.reply(
        f"📺 {user_sale['platform']}\n📅 Expiry: {user_sale['expiry_date'].date()}"
    )

# -------- ADD SALE --------
@app.on_message(filters.command("addsale") & filters.user(OWNER_ID))
async def addsale(client, message):
    try:
        data = message.text.split("\n")

        name = data[1].split(":")[1].strip()
        user_id = int(data[2].split(":")[1].strip())
        platform = data[3].split(":")[1].strip()
        days = int(data[4].split(":")[1].strip())
        sell = int(data[5].split(":")[1].strip())
        cost = int(data[6].split(":")[1].strip())

        start = datetime.now()
        expiry = start + timedelta(days=days)

        sales.insert_one({
            "name": name,
            "user_id": user_id,
            "platform": platform,
            "start_date": start,
            "expiry_date": expiry,
            "sell_price": sell,
            "cost_price": cost,
            "profit": sell - cost,
            "status": "active"
        })

        await message.reply(f"✅ Added\n👤 {name}\n📺 {platform}")

    except Exception as e:
        await message.reply(f"❌ Error: {e}")

# -------- RENEW --------
@app.on_message(filters.command("renew") & filters.user(OWNER_ID))
async def renew(client, message):
    try:
        parts = message.text.split()
        user_id = int(parts[1])
        days = int(parts[2])

        user_sale = sales.find_one(
            {"user_id": user_id},
            sort=[("expiry_date", -1)]
        )

        new_expiry = datetime.now() + timedelta(days=days)

        sales.update_one(
            {"_id": user_sale["_id"]},
            {"$set": {"expiry_date": new_expiry, "status": "active"}}
        )

        # ✅ Auto thank you
        try:
            await app.send_message(
                user_id,
                f"✅ Renewed Successfully!\n📅 Expiry: {new_expiry.date()}\n\n❤️ Thank you for choosing us!"
            )
        except:
            pass

        await message.reply("✅ Renewed")

    except Exception as e:
        await message.reply(f"❌ {e}")

# -------- CUSTOMER REPLY FORWARD --------
@app.on_message(filters.private & ~filters.user(OWNER_ID))
async def reply_forward(client, message):
    if message.text and message.text.startswith("/"):
        return
    await message.forward(OWNER_ID)

# -------- EXPIRY --------
async def check_expiry():
    today = datetime.now().date()

    for r in sales.find({"status": "active"}):
        if r["expiry_date"].date() == today:

            await app.send_message(OWNER_ID, f"⚠️ Expired: {r['name']}")

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Renew Now", callback_data="renew_req")]
            ])

            try:
                await app.send_message(
                    r["user_id"],
                    f"⚠️ Your {r['platform']} expired!",
                    reply_markup=keyboard
                )
            except:
                pass

            sales.update_one({"_id": r["_id"]}, {"$set": {"status": "expired"}})

# -------- RENEW REQUEST BUTTON --------
@app.on_callback_query(filters.regex("renew_req"))
async def renew_req(client, callback_query):
    user = callback_query.from_user

    await app.send_message(
        OWNER_ID,
        f"🔥 Renewal Request\n👤 {user.first_name}\n🆔 {user.id}"
    )

    await callback_query.answer("Admin will contact you!")

# -------- SCHEDULER --------
scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")
scheduler.add_job(check_expiry, "interval", hours=6)

@app.on_message(filters.command("start_scheduler") & filters.user(OWNER_ID))
async def start_scheduler(client, message):
    scheduler.start()
    await message.reply("Scheduler started")

# -------- RUN --------
app.run()
