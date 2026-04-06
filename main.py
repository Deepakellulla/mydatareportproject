import os
import asyncio
from datetime import datetime, timedelta
from pyrogram import Client, filters
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated
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

    await message.reply(
        "✅ You will receive updates.\nSend this ID to admin:\n"
        f"`{user.id}`"
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

        await message.reply(f"✅ Added\n👤 {name}\n📺 {platform}\n📅 {expiry.date()}")

    except Exception as e:
        await message.reply(f"❌ Error: {e}")

# -------- ACTIVE --------
@app.on_message(filters.command("active") & filters.user(OWNER_ID))
async def active(client, message):
    rows = sales.find({"status": "active"})

    text = "📺 Active:\n\n"
    found = False

    for r in rows:
        found = True
        text += f"{r['name']} | {r['platform']} | {r['expiry_date'].date()}\n"

    if not found:
        return await message.reply("No active subscriptions")

    await message.reply(text)

# -------- PROFIT --------
@app.on_message(filters.command("profit") & filters.user(OWNER_ID))
async def profit(client, message):
    total = sum(x["profit"] for x in sales.find())
    await message.reply(f"💰 Profit: ₹{total}")

# -------- PLATFORM STATS --------
@app.on_message(filters.command("platform_stats") & filters.user(OWNER_ID))
async def platform_stats(client, message):
    pipeline = [
        {"$group": {"_id": "$platform", "profit": {"$sum": "$profit"}, "count": {"$sum": 1}}},
        {"$sort": {"profit": -1}}
    ]

    res = list(sales.aggregate(pipeline))

    text = "📊 Platform Stats\n\n"
    for r in res:
        text += f"{r['_id']} → ₹{r['profit']} ({r['count']})\n"

    await message.reply(text)

# -------- RENEW --------
@app.on_message(filters.command("renew") & filters.user(OWNER_ID))
async def renew(client, message):
    try:
        parts = message.text.split()
        user_id = int(parts[1])
        days = int(parts[2])

        user_sale = sales.find_one({"user_id": user_id}, sort=[("expiry_date", -1)])

        if not user_sale:
            return await message.reply("User not found")

        new_expiry = datetime.now() + timedelta(days=days)

        sales.update_one(
            {"_id": user_sale["_id"]},
            {"$set": {"expiry_date": new_expiry, "status": "active"}}
        )

        try:
            await app.send_message(user_id, f"✅ Renewed!\n📅 {new_expiry.date()}")
        except:
            pass

        await message.reply(f"✅ Renewed\n📅 {new_expiry.date()}")

    except Exception as e:
        await message.reply(f"❌ {e}")

# -------- BROADCAST (PRO) --------
@app.on_message(filters.command("broadcast") & filters.user(OWNER_ID))
async def broadcast(client, message):
    users = list(customers.find())

    total = len(users)
    success = 0
    failed = 0
    blocked = 0

    status = await message.reply("📢 Broadcasting...")

    for i, user in enumerate(users, start=1):
        uid = user["user_id"]

        try:
            if message.reply_to_message:
                await message.reply_to_message.forward(uid)
            else:
                text = message.text.split(" ", 1)[1]
                await app.send_message(uid, text)

            success += 1

        except UserIsBlocked:
            blocked += 1
            customers.delete_one({"user_id": uid})

        except InputUserDeactivated:
            failed += 1
            customers.delete_one({"user_id": uid})

        except FloodWait as e:
            await asyncio.sleep(e.value)
            continue

        except:
            failed += 1

        await asyncio.sleep(0.08)

        if i % 50 == 0:
            await status.edit(f"{i}/{total} done")

    await status.edit(
        f"📢 Done\n\nTotal: {total}\nSent: {success}\nBlocked: {blocked}\nFailed: {failed}"
    )

# -------- CUSTOMER REPLIES --------
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

            try:
                await app.send_message(
                    r["user_id"],
                    f"⚠️ Your {r['platform']} expired!\nReply YES to renew"
                )
            except:
                pass

            sales.update_one({"_id": r["_id"]}, {"$set": {"status": "expired"}})

# -------- REPORTS --------
def calc(start, end):
    total = 0
    count = 0

    for r in sales.find({"start_date": {"$gte": start, "$lt": end}}):
        total += r["profit"]
        count += 1

    return total, count

async def daily():
    now = datetime.now()
    start = datetime(now.year, now.month, now.day)
    end = start + timedelta(days=1)

    p, c = calc(start, end)
    await app.send_message(OWNER_ID, f"📊 Daily\nSales: {c}\nProfit: ₹{p}")

async def weekly():
    now = datetime.now()
    start = now - timedelta(days=7)

    p, c = calc(start, now)
    await app.send_message(OWNER_ID, f"📊 Weekly\nSales: {c}\nProfit: ₹{p}")

async def monthly():
    now = datetime.now()
    start = datetime(now.year, now.month, 1)

    p, c = calc(start, now)
    await app.send_message(OWNER_ID, f"📊 Monthly\nSales: {c}\nProfit: ₹{p}")

# -------- SCHEDULER --------
scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")

scheduler.add_job(check_expiry, "interval", hours=6)
scheduler.add_job(daily, "cron", hour=23, minute=59)
scheduler.add_job(weekly, "cron", day_of_week="sun", hour=21)
scheduler.add_job(monthly, "cron", day=1, hour=10)

scheduler.start()

# -------- RUN --------
app.run()
