import discord
from discord.ext import commands, tasks
import json
import os
import asyncio
import aiofiles
import time
from dotenv import load_dotenv

async def ensure_file_exists(filename):
    if not os.path.exists(filename):
        async with aiofiles.open(filename, 'w') as f:
            await f.write('{}')

load_dotenv()  # .env dosyasından TOKEN vs yüklenir


DATA_FILE = "MAINBank.json"
COMPANY_FILE = "MAINCompanies.json"
STOCK_FILE = "MAINStockMarket.json"
USER_STOCK_FILE = "MAINUserStocks.json"

# Mesaj gönderilecek kanallar (kanal ID'lerini kendi sunucuna göre ayarla)
STOCK_MARKET_CHANNEL_ID = 1390260591091908640
13902605910919086401
INCOME_REPORT_CHANNEL_ID = 1399484671288414208

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Dosya erişim kilitleri
data_lock = asyncio.Lock()
company_lock = asyncio.Lock()
stock_lock = asyncio.Lock()
user_stock_lock = asyncio.Lock()

async def ensure_file_exists(path):
    if not os.path.exists(path):
        async with aiofiles.open(path, 'w') as f:
            await f.write('{}')

async def read_json(path, lock):
    async with lock:
        await ensure_file_exists(path)
        async with aiofiles.open(path, 'r') as f:
            content = await f.read()
            if content.strip() == '':
                return {}
            return json.loads(content)

async def write_json(path, data, lock):
    async with lock:
        async with aiofiles.open(path, 'w') as f:
            await f.write(json.dumps(data, indent=4))

async def init_user(user_id):
    data = await read_json(DATA_FILE, data_lock)
    if str(user_id) not in data:
        data[str(user_id)] = {
            "bank_points": 500,
            "loan_amount": 0,
            "loan_timestamp": None
        }
        await write_json(DATA_FILE, data, data_lock)

async def take_loan(user_id, amount):
    await init_user(user_id)
    data = await read_json(DATA_FILE, data_lock)
    user = data[str(user_id)]

    if amount > user["bank_points"]:
        return False, "You don't have enough bank points!"

    user["loan_amount"] += amount
    user["bank_points"] -= amount
    user["loan_timestamp"] = time.time()

    await write_json(DATA_FILE, data, data_lock)
    return True, f"You borrowed ${amount}. You must repay it soon."

@bot.command()
async def pay(ctx, member: discord.Member, amount: int):
    sender_id = str(ctx.author.id)
    receiver_id = str(member.id)

    if sender_id == receiver_id:
        return await ctx.send("❌ You cannot send money to yourself.")

    if amount <= 0:
        return await ctx.send("❌ The amount to send must be positive.")

    await init_user(sender_id)
    await init_user(receiver_id)

    data = await read_json(DATA_FILE, data_lock)

    if data[sender_id]["bank_points"] < amount:
        return await ctx.send("💸 You don't have enough money.")

    # Transfer money
    data[sender_id]["bank_points"] -= amount
    data[receiver_id]["bank_points"] += amount

    await write_json(DATA_FILE, data, data_lock)

    await ctx.send(f"✅ {ctx.author.mention} sent **${amount}** to {member.mention}!")


async def pay_loan(user_id, amount):
    await init_user(user_id)
    data = await read_json(DATA_FILE, data_lock)
    user = data[str(user_id)]

    if user["loan_amount"] <= 0:
        return False, "You have no loan to pay!"

    paid = min(amount, user["loan_amount"])
    user["loan_amount"] -= paid
    user["bank_points"] += paid

    if user["loan_amount"] == 0:
        user["loan_timestamp"] = None

    await write_json(DATA_FILE, data, data_lock)
    return True, f"You paid ${paid} from your loan."

async def apply_loan_penalties():
    data = await read_json(DATA_FILE, data_lock)
    current_time = time.time()

    changed = False
    for user_id, user in data.items():
        if user["loan_amount"] > 0 and user["loan_timestamp"] is not None:
            hours_passed = int((current_time - user["loan_timestamp"]) // 3600)
            if hours_passed > 0:
                penalty_stages = [0.25, 0.25, 0.25, 0.25]
                total_penalty = 0
                reduced_debt = 0

                for i in range(min(hours_passed, 4)):
                    p = penalty_stages[i]
                    amount = user["loan_amount"] * p
                    total_penalty += amount
                    reduced_debt += amount

                user["loan_amount"] -= reduced_debt
                user["bank_points"] = max(0, user["bank_points"] - total_penalty)

                if hours_passed >= 4:
                    user["loan_amount"] = 0
                    user["loan_timestamp"] = None
                changed = True

    if changed:
        await write_json(DATA_FILE, data, data_lock)

@tasks.loop(hours=1)
async def run_penalty_check():
    await apply_loan_penalties()
    print("Penalties applied.")

async def create_company(user_id, name):
    await init_user(user_id)
    bank = await read_json(DATA_FILE, data_lock)
    if bank[str(user_id)]["bank_points"] < 150000:
        return False, "You don't have enough money to start a company."

    companies = await read_json(COMPANY_FILE, company_lock)

    if str(user_id) in companies:
        return False, "You already own a company."

    bank[str(user_id)]["bank_points"] -= 150000
    companies[str(user_id)] = {
        "company_name": name,
        "office_level": 1,
        "employees": []
    }

    await write_json(DATA_FILE, bank, data_lock)
    await write_json(COMPANY_FILE, companies, company_lock)

    return True, f"Company '{name}' created successfully!"

OFFICE_UPGRADES = {
    2: {"cost": 75000, "max_employees": 15},
    3: {"cost": 150000, "max_employees": 20},
    4: {"cost": 350000, "max_employees": 30},
    5: {"cost": 700000, "max_employees": 50},
    6: {"cost": 2000000, "max_employees": 75},
    7: {"cost": 5000000, "max_employees": 100},
}

async def upgrade_office(user_id):
    companies = await read_json(COMPANY_FILE, company_lock)
    bank = await read_json(DATA_FILE, data_lock)

    if str(user_id) not in companies:
        return False, "You don't own a company yet."

    company = companies[str(user_id)]
    level = company["office_level"]

    if level >= 7:
        return False, "You already have the max level office."

    next_level = level + 1
    upgrade = OFFICE_UPGRADES[next_level]

    if bank[str(user_id)]["bank_points"] < upgrade["cost"]:
        return False, "Not enough funds to upgrade your office."

    bank[str(user_id)]["bank_points"] -= upgrade["cost"]
    company["office_level"] = next_level

    await write_json(DATA_FILE, bank, data_lock)
    await write_json(COMPANY_FILE, companies, company_lock)

    return True, f"Office upgraded to level {next_level}!"

async def hire_employee(user_id: str) -> tuple[bool, str]:
    companies = await read_json(COMPANY_FILE, company_lock)
    bank = await read_json(DATA_FILE, data_lock)

    if user_id not in companies:
        return False, "❌ You don't own a company yet."

    company = companies[user_id]
    level = company.get("office_level", 1)
    max_employees_list = [10, 15, 20, 30, 50, 75, 100]
    max_employees = max_employees_list[min(level - 1, len(max_employees_list) - 1)]

    if len(company.get("employees", [])) >= max_employees:
        return False, "🏢 Your office is full. Upgrade it to hire more employees."

    cost = 2000
    if bank[user_id]["bank_points"] < cost:
        return False, f"💸 Not enough money to hire. You need ${cost}."

    # Düşür para
    bank[user_id]["bank_points"] -= cost

    # Yeni çalışan ekle
    company.setdefault("employees", []).append({"level": 1, "xp": 0})

    # JSON'lara yaz
    await write_json(DATA_FILE, bank, data_lock)
    await write_json(COMPANY_FILE, companies, company_lock)

    return True, "👨‍💼 New employee hired successfully!"




@bot.command()
async def buycompany(ctx, *, company_name: str):
    user_id = str(ctx.author.id)
    companies = await read_json("MAINStockMarket.json", asyncio.Lock())  # <--- BURAYA DİKKAT
    bank = await read_json(DATA_FILE, data_lock)

    # Normalize input (lowercase + underscore)
    normalized_input = company_name.casefold().replace(" ", "_")

    matched_key = None
    for key in companies:
        normalized_key = key.casefold().replace(" ", "_")
        if normalized_key == normalized_input:
            matched_key = key
            break

    if not matched_key:
        return await ctx.send("❌ This company does not exist.")

    company = companies[matched_key]
    price = company["stock_value"] * 1000

    if company.get("owner") is not None:
        return await ctx.send("❌ This company is already owned by someone else.")

    if bank[user_id]["bank_points"] < price:
        return await ctx.send(f"💸 You need ${price:,} to purchase this company.")

    bank[user_id]["bank_points"] -= price
    company["owner"] = user_id

    await write_json(DATA_FILE, bank, data_lock)
    await write_json("MAINStockMarket.json", companies, asyncio.Lock())  # <--- BURAYA DİKKAT

    await ctx.send(f"🏢 You successfully purchased **{matched_key}** for ${price:,}!")





@tasks.loop(minutes=2)
async def company_income_loop():
    companies = await read_json("MAINStockMarket.json", asyncio.Lock())  # <- Doğru dosya
    bank = await read_json(DATA_FILE, data_lock)

    log_channel = bot.get_channel(1399484671288414208)  # Kanal ID doğru olmalı
    if not log_channel:
        return

    summary = []

    for name, info in companies.items():
        owner_id = info.get("owner")
        if owner_id:
            income = info["stock_value"] * 50  # Hisse değeri x50 kazanç
            owner_id = str(owner_id)

            # Kullanıcı kaydı yoksa oluştur
            if owner_id not in bank:
                bank[owner_id] = {
                    "bank_points": 0,
                    "wallet_points": 0
                }

            bank[owner_id]["bank_points"] += income
            summary.append(f"🏢 **{name.title()}** → <@{owner_id}> earned **${income:,}**")

    await write_json(DATA_FILE, bank, data_lock)

    if summary:
        embed = discord.Embed(
            title="💰 Company Income Report",
            description="\n".join(summary),
            color=0x00ff99
        )
        await log_channel.send(embed=embed)





async def buy_stock(user_id, stock_name, amount: int):
    if amount <= 0:
        return False, "Please enter a valid amount of shares to buy."

    market = await read_json(STOCK_FILE, stock_lock)
    bank = await read_json(DATA_FILE, data_lock)

    if stock_name not in market:
        return False, "That stock doesn't exist."

    stock_price = market[stock_name]["stock_value"]  # hisse başı fiyat
    cost = stock_price * amount  # toplam maliyet

    user_id_str = str(user_id)

    if bank[user_id_str]["bank_points"] < cost:
        return False, f"You can't afford {amount} shares of {stock_name} (cost: ${cost})."

    userstocks = await read_json(USER_STOCK_FILE, user_stock_lock)

    if user_id_str not in userstocks:
        userstocks[user_id_str] = {}

    # Kullanıcı zaten bu hisseden varsa miktarı artır, yoksa yeni kayıt oluştur
    if stock_name in userstocks[user_id_str]:
        userstocks[user_id_str][stock_name] += amount
    else:
        userstocks[user_id_str][stock_name] = amount

    bank[user_id_str]["bank_points"] -= cost

    await write_json(DATA_FILE, bank, data_lock)
    await write_json(USER_STOCK_FILE, userstocks, user_stock_lock)

    return True, f"You bought {amount} shares of {stock_name} for ${cost}."

import random

def update_stock_values_sync(market):
 
    for name, data in market.items():
        change_percent = random.uniform(-25, 25)  # -5% to +10%
        original = data["stock_value"]
        new_value = round(original * (1 + change_percent / 100))
        market[name]["stock_value"] = max(100, new_value)
    return market

async def update_stock_values():
    async with stock_lock:
        async with aiofiles.open(STOCK_FILE, 'r') as f:
            content = await f.read()
            market = json.loads(content) if content else {}

        for name, data in market.items():
            old_value = data.get("stock_value", 1000)
            change_percent = random.uniform(-25, 25)  # -5% to +10%
            new_value = round(old_value * (1 + change_percent / 100))
            new_value = max(100, new_value)

            data["previous_value"] = old_value
            data["stock_value"] = new_value

        async with aiofiles.open(STOCK_FILE, 'w') as f:
            await f.write(json.dumps(market, indent=4))

@bot.command()
async def leaderstats(ctx):
    data = await read_json(DATA_FILE, data_lock)

    # Kullanıcıları bank_points'e göre sırala
    sorted_users = sorted(data.items(), key=lambda x: x[1].get("bank_points", 0), reverse=True)

    embed = discord.Embed(
        title="💰 Leaderboard - Richest Players",
        description="Top 20 users with the most bank points.",
        color=0xf1c40f
    )

    for i, (user_id, user_data) in enumerate(sorted_users[:20], start=1):
        user = await bot.fetch_user(int(user_id))
        username = user.name if user else f"User {user_id}"
        balance = user_data.get("bank_points", 0)
        embed.add_field(name=f"#{i} - {username}", value=f"${balance}", inline=False)

    await ctx.send(embed=embed)


async def post_stock_market(channel):
    with open(STOCK_FILE, "r") as f:
        market = json.load(f)

    embed = discord.Embed(title="📈 Stock Market", color=0x00ff00)
    for name, data in market.items():
        old = data.get("previous_value", data["stock_value"])
        new = data["stock_value"]
        diff = new - old
        diff_percent = (diff / old) * 100 if old != 0 else 0

        # Renk ve simge ayarı (artış mı azalış mı)
        if diff > 0:
            sign = "📈"
            diff_str = f"+${diff} (+{diff_percent:.2f}%)"
            field_color = 0x00ff00  # yeşil
        elif diff < 0:
            sign = "📉"
            diff_str = f"-${abs(diff)} ({diff_percent:.2f}%)"
            field_color = 0xff0000  # kırmızı
        else:
            sign = "⏸️"
            diff_str = "No change"
            field_color = 0x999999  # gri

        embed.add_field(
            name=f"{name} {sign}",
            value=f"Current value: ${new}\nChange: {diff_str}",
            inline=False
        )

    await channel.send(embed=embed)

COMPANY_INCOME_CHANNEL_ID = 1399484671288414208  # Gelir raporu için kanal ID'nizi buraya koyun

async def post_company_income_report(channel):
    reports = await process_company_income()
    if not reports:
        return
    embed = discord.Embed(
        title="🏢 Company Income Report",
        description="Updated every 2 minutes",
        color=0x3498db
    )
    for rep in reports:
        embed.add_field(
            name=f"{rep['company_name']} ({rep['user_id']})",
            value=f"💵 Income: ${rep['income']}",
            inline=False
        )
    await channel.send(embed=embed)

@tasks.loop(minutes=2)
async def company_income_report_loop():
    channel = bot.get_channel(COMPANY_INCOME_CHANNEL_ID)
    if channel:
        await post_company_income_report(channel)

@tasks.loop(minutes=2)
async def stock_market_loop():
    await update_stock_values()
    channel = bot.get_channel(STOCK_MARKET_CHANNEL_ID)
    if channel:
        await post_stock_market(channel)

async def process_company_income():
    companies = await read_json(COMPANY_FILE, company_lock)
    bank = await read_json(DATA_FILE, data_lock)

    company_reports = []

    for user_id, company in companies.items():
        total_income = 0
        for emp in company["employees"]:
            level = emp["level"]
            if level < 10:
                emp["xp"] += 15
                if emp["xp"] >= 100:
                    emp["xp"] = 0
                    emp["level"] += 1
                    if emp["level"] > 10:
                        emp["level"] = 10

            income = int(250 * (1.5 * (emp["level"] - 1)))
            total_income += income

        if user_id in bank:
            bank[user_id]["bank_points"] += total_income

        company_reports.append({
            "user_id": user_id,
            "company_name": company["company_name"],
            "income": total_income,
            "employee_count": len(company["employees"])
        })

    await write_json(DATA_FILE, bank, data_lock)
    await write_json(COMPANY_FILE, companies, company_lock)

    return company_reports

async def post_income_report(channel):
    reports = await process_company_income()
    if not reports:
        return
    embed = discord.Embed(
        title="🏢 Company Income Report",
        description="Updated every 2 minutes",
        color=0x3498db
    )
    for rep in reports:
        embed.add_field(
            name=f"{rep['company_name']} ({rep['user_id']})",
            value=f"💵 Income: ${rep['income']}\n👨‍💼 Employees: {rep['employee_count']}",
            inline=False
        )
    await channel.send(embed=embed)

async def sell_stock(user_id, stock_name, amount: int):
    if amount <= 0:
        return False, "Please enter a valid amount of shares to sell."

    user_id_str = str(user_id)

    userstocks = await read_json(USER_STOCK_FILE, user_stock_lock)
    bank = await read_json(DATA_FILE, data_lock)
    market = await read_json(STOCK_FILE, stock_lock)

    if user_id_str not in userstocks or stock_name not in userstocks[user_id_str]:
        return False, f"You don't own any shares of {stock_name}."

    owned_amount = userstocks[user_id_str][stock_name]

    if amount > owned_amount:
        return False, f"You only own {owned_amount} shares of {stock_name}."

    if stock_name not in market:
        return False, "That stock doesn't exist."

    stock_price = market[stock_name]["stock_value"]  # hisse fiyatı
    earnings = stock_price * amount  # satıştan elde edilecek para

    # Hisseden düş
    userstocks[user_id_str][stock_name] -= amount

    # Eğer hisse miktarı sıfır ise kaydı temizle
    if userstocks[user_id_str][stock_name] == 0:
        del userstocks[user_id_str][stock_name]

    # Para ekle
    bank[user_id_str]["bank_points"] += earnings

    await write_json(USER_STOCK_FILE, userstocks, user_stock_lock)
    await write_json(DATA_FILE, bank, data_lock)

    return True, f"You sold {amount} shares of {stock_name} for ${earnings}."

@bot.command()
async def portfolio(ctx):
    user_id = str(ctx.author.id)
    userstocks = await read_json(USER_STOCK_FILE, user_stock_lock)
    market = await read_json(STOCK_FILE, stock_lock)

    if user_id not in userstocks or len(userstocks[user_id]) == 0:
        return await ctx.send("📭 Your portfolio is empty.")

    embed = discord.Embed(title=f"📊 {ctx.author.display_name}'s Portfolio", color=0x3498db)

    total_value = 0

    for stock_name, amount in userstocks[user_id].items():
        if stock_name not in market:
            continue

        current_price = market[stock_name]["stock_value"]
        previous_price = market[stock_name].get("previous_value", current_price)
        change = current_price - previous_price
        change_percent = (change / previous_price) * 100 if previous_price != 0 else 0

        stock_value = current_price * amount
        total_value += stock_value

        # Kar/zarar durumu için emoji
        if change > 0:
            emoji = "📈"
            change_str = f"+${change} (+{change_percent:.2f}%)"
        elif change < 0:
            emoji = "📉"
            change_str = f"-${abs(change)} ({change_percent:.2f}%)"
        else:
            emoji = "⏸️"
            change_str = "No change"

        embed.add_field(
            name=f"{stock_name} {emoji} — {amount} shares",
            value=f"Price: ${current_price}\nChange: {change_str}\nTotal value: ${stock_value}",
            inline=False
        )

    embed.set_footer(text=f"Total portfolio value: ${total_value}")

    await ctx.send(embed=embed)


@tasks.loop(minutes=2)
async def income_report_loop():
    channel = bot.get_channel(1399484671288414208)
    if channel:
        await post_income_report(channel)

@bot.command()
async def sellstock(ctx, stock_name: str, amount: int):
    success, msg = await sell_stock(ctx.author.id, stock_name, amount)
    await ctx.send(msg)

@bot.command()
async def openbankacc(ctx):
    await init_user(ctx.author.id)
    await ctx.send("You have been registered with 500 bank points.")

@bot.command()
async def loan(ctx, amount: int):
    success, msg = await take_loan(ctx.author.id, amount)
    await ctx.send(msg)

@bot.command()
async def payloan(ctx, amount: int):
    success, msg = await pay_loan(ctx.author.id, amount)
    await ctx.send(msg)

@bot.command()
async def createcompany(ctx, *, name):
    success, msg = await create_company(str(ctx.author.id), name)
    await ctx.send(msg)

@bot.command()
async def upgradeoffice(ctx):
    success, msg = await upgrade_office(ctx.author.id)
    await ctx.send(msg)

@bot.command()
async def office(ctx):
    user_id = str(ctx.author.id)

    companies = await read_json(COMPANY_FILE, company_lock)
    bank = await read_json(DATA_FILE, data_lock)

    if user_id not in companies:
        return await ctx.send("❌ You don't own a company yet.")

    company = companies[user_id]
    office_level = company.get("office_level", 1)
    employees = company.get("employees", [])

    max_employees_list = [10, 15, 20, 30, 50, 75, 100]
    max_employees = max_employees_list[min(office_level - 1, len(max_employees_list) - 1)]

    # Ofisteki doluluk oranı
    current_count = len(employees)

    # Bir sonraki ofis seviyesi ve fiyatı
    next_level = office_level + 1
    if next_level <= 7:
        next_office_cost = OFFICE_UPGRADES[next_level]["cost"]
    else:
        next_office_cost = None  # Maksimum seviyede

    # Çalışan seviyelerinin sayısı
    level_counts = {}
    for emp in employees:
        lvl = emp.get("level", 1)
        level_counts[lvl] = level_counts.get(lvl, 0) + 1

    # Şirket geliri (toplam çalışan gelirleri)
    total_income = 0
    for emp in employees:
        level = emp.get("level", 1)
        income = int(250 * (1.5 ** (level - 1)))
        total_income += income

    embed = discord.Embed(title=f"🏢 Company Office: {company['company_name']}", color=0x3498db)

    embed.add_field(name="Office Level", value=str(office_level), inline=True)
    if next_office_cost:
        embed.add_field(name="Next Office Cost", value=f"${next_office_cost}", inline=True)
    else:
        embed.add_field(name="Next Office Cost", value="Max level reached", inline=True)

    embed.add_field(name="Employees", value=f"{current_count} / {max_employees}", inline=True)

    # Çalışan seviyeleri
    levels_str = "\n".join([f"Level {lvl}: {count}" for lvl, count in sorted(level_counts.items())]) or "No employees"
    embed.add_field(name="Employee Levels", value=levels_str, inline=False)

    embed.add_field(name="Current Income (per 2 min)", value=f"${total_income}", inline=False)

    if ctx.author.avatar:
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url)
    else:
        embed.set_author(name=ctx.author.display_name)

    await ctx.send(embed=embed)


@bot.command()
async def hire(ctx, amount: int = 1):
    user_id = str(ctx.author.id)
    hired_count = 0
    messages = []

    for _ in range(amount):
        success, msg = await hire_employee(user_id)
        messages.append(msg)
        if success:
            hired_count += 1
        else:
            # Eğer başarısızsa örn: para yok veya ofis dolu, döngüyü kırabiliriz
            break

    summary = f"👷 You hired {hired_count} employee(s)."
    if hired_count < amount:
        summary += f"\nStopped early: {messages[-1]}"

    await ctx.send(summary)

@bot.command()
async def buystock(ctx, stock_name: str, amount: int):
    success, msg = await buy_stock(ctx.author.id, stock_name, amount)
    await ctx.send(msg)

@bot.command()
async def money(ctx):
    await init_user(ctx.author.id)
    data = await read_json(DATA_FILE, data_lock)
    user_data = data.get(str(ctx.author.id), {})

    bank_points = user_data.get("bank_points", 0)
    loan = user_data.get("loan_amount", 0)

    embed = discord.Embed(
        title="🏦 Your Bank Info",
        color=0x00ff88
    )
    embed.add_field(name="💰 Balance", value=f"${bank_points}", inline=True)
    embed.add_field(name="💳 Loan", value=f"${loan}", inline=True)

    if ctx.author.avatar:
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url)
    else:
        embed.set_author(name=ctx.author.display_name)

    await ctx.send(embed=embed)

from discord.ext.commands import cooldown, BucketType

@bot.command()
async def slot(ctx, amount: int):
    await init_user(ctx.author.id)
    data = await read_json(DATA_FILE, data_lock)
    user_id = str(ctx.author.id)

    if amount < 50:
        return await ctx.send("🪙 Minimum bet is $50.")
    if data[user_id]["bank_points"] < amount:
        return await ctx.send("💸 You don't have enough money to bet that much.")

    data[user_id]["bank_points"] -= amount

    symbols = ["🍒", "🍋", "🍇", "🔔", "💎", "🔴", "💲", "♠️", "7️⃣"]
    result = [random.choice(symbols) for _ in range(3)]
    await ctx.send(f"🎰 {' | '.join(result)}")

    if len(set(result)) == 1:
        win = amount * 5
        data[user_id]["bank_points"] += win
        await ctx.send(f"🎉 Jackpot! You won ${win}!")
    elif len(set(result)) == 2:
        win = int(amount * 2.5)
        data[user_id]["bank_points"] += win
        await ctx.send(f"👍 You matched two symbols and won ${win}.")
    else:
        await ctx.send("😢 No match. Better luck next time!")

    await write_json(DATA_FILE, data, data_lock)

active_blackjacks = {}

@bot.command()
async def blackjack(ctx, amount: int):
    await init_user(ctx.author.id)
    user_id = str(ctx.author.id)
    data = await read_json(DATA_FILE, data_lock)

    if user_id in active_blackjacks:
        return await ctx.send("⏳ You already have an ongoing blackjack game.")

    if amount < 100:
        return await ctx.send("🪙 Minimum bet is $100.")

    if data[user_id]["bank_points"] < amount:
        return await ctx.send("💸 You don't have enough money to bet that much.")

    # Para düşüldü
    data[user_id]["bank_points"] -= amount
    await write_json(DATA_FILE, data, data_lock)

    def draw():
        return random.randint(2, 11)  # As simplification

    player_hand = [draw(), draw()]
    dealer_hand = [draw(), draw()]

    active_blackjacks[user_id] = {
        "bet": amount,
        "player": player_hand,
        "dealer": dealer_hand,
        "doubled": False,
        "channel": ctx.channel
    }

    await ctx.send(
        f"🃏 You drew {player_hand} (Total: {sum(player_hand)}). Dealer shows [{dealer_hand[0]}, ❓].\n"
        "Type `hit`, `stand`, or `double`."
    )


async def finish_blackjack(user_id):
    if user_id not in active_blackjacks:
        return

    game = active_blackjacks.pop(user_id)
    player = game["player"]
    dealer = game["dealer"]
    bet = game["bet"]
    channel = game["channel"]

    def total(hand): 
        return sum(hand)

    player_total = total(player)
    dealer_total = total(dealer)

    data = await read_json(DATA_FILE, data_lock)

    if player_total > 21:
        result = f"💥 You busted with {player_total}. You lost ${bet}."
    elif dealer_total > 21 or player_total > dealer_total:
        data[user_id]["bank_points"] += bet * 2
        await write_json(DATA_FILE, data, data_lock)
        result = f"🎉 You win! Dealer had {dealer_total}. You earned ${bet * 2}."
    elif player_total == dealer_total:
        data[user_id]["bank_points"] += bet
        await write_json(DATA_FILE, data, data_lock)
        result = f"🤝 It's a tie. Both had {player_total}. Your ${bet} is returned."
    else:
        result = f"😢 Dealer wins with {dealer_total}. You lost ${bet}."

    await channel.send(
        f"🧑 Your hand: {player} (Total: {player_total})\n"
        f"🤖 Dealer hand: {dealer} (Total: {dealer_total})\n"
        f"{result}"
    )


@bot.command()
async def roulette(ctx, color: str, amount: int):
    await init_user(ctx.author.id)
    color = color.lower()
    if color not in ["red", "black"]:
        return await ctx.send("Please choose a color: `red` or `black`.")

    data = await read_json(DATA_FILE, data_lock)
    user = data[str(ctx.author.id)]

    if amount > user["bank_points"] or amount <= 0:
        return await ctx.send("Invalid amount.")

    result = random.choice(["red", "black"])
    if result == color:
        user["bank_points"] += amount
        await ctx.send(f"🎡 The wheel landed on {result.upper()}! You won +${amount}!")
    else:
        user["bank_points"] -= amount
        await ctx.send(f"🎡 The wheel landed on {result.upper()}! You lost -${amount}.")

    await write_json(DATA_FILE, data, data_lock)


@bot.command()
async def dice(ctx, guess: int, amount: int):
    await init_user(ctx.author.id)
    if guess < 1 or guess > 6:
        return await ctx.send("Please guess a number between 1 and 6.")
    
    data = await read_json(DATA_FILE, data_lock)
    user = data[str(ctx.author.id)]

    if amount > user["bank_points"] or amount <= 0:
        return await ctx.send("Invalid amount.")

    roll = random.randint(1, 6)
    if roll == guess:
        reward = amount * 5
        user["bank_points"] += reward
        await ctx.send(f"🎲 Dice rolled: {roll} | You guessed correctly! +${reward}")
    else:
        user["bank_points"] -= amount
        await ctx.send(f"🎲 Dice rolled: {roll} | You lost -${amount}")

    await write_json(DATA_FILE, data, data_lock)

@bot.command()
@cooldown(1, 60, BucketType.user)  # 1 kullanım, 60 saniye cooldown, kullanıcı bazlı
async def crime(ctx):
    await init_user(ctx.author.id)
    data = await read_json(DATA_FILE, data_lock)
    user_id = str(ctx.author.id)

    if data[user_id]["bank_points"] < 100:
        return await ctx.send("You need at least $100 to attempt a crime.")

    success = random.random() < 0.5  # %50 başarı şansı
    amount = random.randint(50, 3500)

    if success:
        data[user_id]["bank_points"] += amount
        await ctx.send(f"🚨 Crime successful! You earned ${amount}.")
    else:
        penalty = random.randint(20, 700)
        data[user_id]["bank_points"] = max(0, data[user_id]["bank_points"] - penalty)
        await ctx.send(f"🚔 You got caught! You lost ${penalty}.")

    await write_json(DATA_FILE, data, data_lock)


@bot.command()
async def coinflip(ctx, choice: str, amount: int):
    await init_user(ctx.author.id)
    choice = choice.lower()
    if choice not in ["heads", "tails"]:
        return await ctx.send("Please choose either `heads` or `tails`.")

    data = await read_json(DATA_FILE, data_lock)
    user = data[str(ctx.author.id)]

    if amount > user["bank_points"] or amount <= 0:
        return await ctx.send("Invalid amount.")

    result = random.choice(["heads", "tails"])
    if result == choice:
        user["bank_points"] += amount
        await ctx.send(f"🪙 It's {result.upper()}! You won +${amount}.")
    else:
        user["bank_points"] -= amount
        await ctx.send(f"🪙 It's {result.upper()}! You lost -${amount}.")

    await write_json(DATA_FILE, data, data_lock)    

from datetime import datetime

@bot.command()
@commands.cooldown(1, 86400, commands.BucketType.user)  # 24 saat bekleme
async def daily(ctx):
    await init_user(ctx.author.id)
    data = await read_json(DATA_FILE, data_lock)
    user_id = str(ctx.author.id)

    reward = random.randint(500, 1000)
    data[user_id]["bank_points"] += reward

    await write_json(DATA_FILE, data, data_lock)
    await ctx.send(f"🎁 You claimed your daily reward of **${reward}**!")

SHOP_ITEMS = {
    "coffee": {"price": 500, "description": "Increases work earnings by 10%."},
    "laptop": {"price": 1500, "description": "Increases work earnings by 50%."},
    "car": {"price": 10000, "description": "Increases work earnings by 350%."},
    "briefcase": {"price": 5000, "description": "Increases work earnings by 200%."},
    "suit": {"price": 2500, "description": "Increases work earnings by 100%."},
    "watch": {"price": 800, "description": "Increases work earnings by 25%."},
    "smartphone": {"price": 3000, "description": "Increases work earnings by 120%."},
    "assistant": {"price": 15000, "description": "Increases work earnings by 500%."}
}

INVENTORY_FILE = "MAINUserInventory.json"
inventory_lock = asyncio.Lock()

async def init_inventory(user_id):
    data = await read_json(INVENTORY_FILE, inventory_lock)
    if str(user_id) not in data:
        data[str(user_id)] = {}
        await write_json(INVENTORY_FILE, data, inventory_lock)

@bot.command()
async def inventory(ctx):
    await init_inventory(ctx.author.id)
    data = await read_json(INVENTORY_FILE, inventory_lock)
    user_id = str(ctx.author.id)
    inv = data.get(user_id, {})

    if not inv:
        await ctx.send("Your inventory is empty.")
        return

    embed = discord.Embed(title=f"{ctx.author.display_name}'s Inventory", color=0x3498db)
    for item, amount in inv.items():
        embed.add_field(name=item, value=f"Quantity: {amount}", inline=False)

    await ctx.send(embed=embed)

@bot.command()
async def shop(ctx):
    embed = discord.Embed(title="🛒 Shop", description="Use `!buy <item>` to purchase.", color=0x00ff00)
    for item, info in SHOP_ITEMS.items():
        embed.add_field(name=item.capitalize(), value=f"${info['price']} - {info['description']}", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def buy(ctx, item_name: str):
    item_name = item_name.lower()
    if item_name not in SHOP_ITEMS:
        return await ctx.send("Item not found in shop.")

    await init_user(ctx.author.id)
    await init_inventory(ctx.author.id)

    data = await read_json(DATA_FILE, data_lock)
    inventory = await read_json(INVENTORY_FILE, inventory_lock)

    user_id = str(ctx.author.id)
    price = SHOP_ITEMS[item_name]["price"]

    if data[user_id]["bank_points"] < price:
        return await ctx.send("You don't have enough money.")

    data[user_id]["bank_points"] -= price
    inventory[user_id][item_name] = inventory[user_id].get(item_name, 0) + 1

    await write_json(DATA_FILE, data, data_lock)
    await write_json(INVENTORY_FILE, inventory, inventory_lock)

    await ctx.send(f"You bought 1 {item_name}!")

@bot.command()
async def sell(ctx, item_name: str, amount: int):
    item_name = item_name.lower()
    if item_name not in SHOP_ITEMS:
        return await ctx.send("Item not found in your inventory.")

    await init_inventory(ctx.author.id)
    inventory = await read_json(INVENTORY_FILE, inventory_lock)

    user_id = str(ctx.author.id)

    if amount <= 0:
        return await ctx.send("Invalid amount.")

    if inventory.get(user_id, {}).get(item_name, 0) < amount:
        return await ctx.send("You don't have that many items.")

    await init_user(ctx.author.id)
    data = await read_json(DATA_FILE, data_lock)

    sell_price = SHOP_ITEMS[item_name]["price"] // 2
    total_price = sell_price * amount

    inventory[user_id][item_name] -= amount
    if inventory[user_id][item_name] <= 0:
        del inventory[user_id][item_name]

    data[user_id]["bank_points"] += total_price

    await write_json(DATA_FILE, data, data_lock)
    await write_json(INVENTORY_FILE, inventory, inventory_lock)

    await ctx.send(f"You sold {amount} {item_name}(s) for ${total_price}.")


trade_offers = {}

@bot.command()
async def trade(ctx, target: discord.Member, amount: int):
    user_id = str(ctx.author.id)
    target_id = str(target.id)

    if user_id == target_id:
        return await ctx.send("You can't trade with yourself!")

    await init_user(ctx.author.id)
    await init_user(target.id)

    data = await read_json(DATA_FILE, data_lock)

    if amount <= 0 or data[user_id]["bank_points"] < amount:
        return await ctx.send("Invalid amount or insufficient funds.")

    trade_offers[target_id] = {"from": user_id, "amount": amount}

    await ctx.send(f"{target.mention}, {ctx.author.display_name} wants to trade ${amount} with you. Type `!accept` to accept or `!decline` to decline.")

@bot.command()
async def accept(ctx):
    user_id = str(ctx.author.id)
    if user_id not in trade_offers:
        return await ctx.send("You have no trade offers.")

    offer = trade_offers.pop(user_id)
    from_id = offer["from"]
    amount = offer["amount"]

    data = await read_json(DATA_FILE, data_lock)

    if data[from_id]["bank_points"] < amount:
        return await ctx.send("The offerer no longer has enough money.")

    data[from_id]["bank_points"] -= amount
    data[user_id]["bank_points"] += amount

    await write_json(DATA_FILE, data, data_lock)

    await ctx.send(f"Trade accepted! {ctx.author.mention} received ${amount} from <@{from_id}>.")

@bot.command()
async def decline(ctx):
    user_id = str(ctx.author.id)
    if user_id in trade_offers:
        trade_offers.pop(user_id)
        await ctx.send("Trade declined.")
    else:
        await ctx.send("You have no trade offers.")

# Kullanıcı statları için JSON dosyası
STATS_FILE = "MAINUserStats.json"
stats_lock = asyncio.Lock()

async def init_stats(user_id):
    data = await read_json(STATS_FILE, stats_lock)
    if str(user_id) not in data:
        data[str(user_id)] = {
            "strength": 1,
            "endurance": 1,
            "level": 1,
            "xp": 0
        }
        await write_json(STATS_FILE, data, stats_lock)

@bot.command()
@cooldown(1, 30, BucketType.user)  # 1 kullanım, 30 saniye cooldown, kullanıcı bazlı
async def workout(ctx):
    await init_stats(ctx.author.id)  # stats için kayıt oluştur
    stats = await read_json(STATS_FILE, stats_lock)
    user_id = str(ctx.author.id)

    # XP kazan
    gained_xp = random.randint(10, 20)
    stats[user_id]["xp"] += gained_xp

    leveled_up = False
    if stats[user_id]["xp"] >= 100:
        stats[user_id]["xp"] -= 100
        stats[user_id]["level"] += 1
        stats[user_id]["strength"] += 1
        stats[user_id]["endurance"] += 1
        leveled_up = True

    await write_json(STATS_FILE, stats, stats_lock)

    msg = f"🏋️ You worked out and gained {gained_xp} XP!"
    if leveled_up:
        msg += f"\n🎉 You leveled up to level {stats[user_id]['level']}! Strength and Endurance increased!"

    await ctx.send(msg)


@bot.command()
@cooldown(1, 120, BucketType.user)  # 1 kullanım, 120 saniye, kullanıcıya özel
async def work(ctx):
    await init_user(ctx.author.id)
    await init_stats(ctx.author.id)        # Statları başlat
    await init_inventory(ctx.author.id)    # Envanteri başlat

    data = await read_json(DATA_FILE, data_lock)
    stats = await read_json(STATS_FILE, stats_lock)
    inventory = await read_json(INVENTORY_FILE, inventory_lock)

    user_id = str(ctx.author.id)

    base_earned = random.randint(250, 540)
    strength_multiplier = stats[user_id]["strength"]

    # Item bazlı bonus
    item_bonus_percent = 0
    user_items = inventory.get(user_id, {})

    if "coffee" in user_items:
        item_bonus_percent += 0.10
    if "laptop" in user_items:
        item_bonus_percent += 0.50
    if "car" in user_items:
        item_bonus_percent += 3.50
    if "briefcase" in user_items:
        item_bonus_percent += 2.00
    if "suit" in user_items:
        item_bonus_percent += 1.00
    if "watch" in user_items:
        item_bonus_percent += 0.25
    if "smartphone" in user_items:
        item_bonus_percent += 1.20
    if "assistant" in user_items:
        item_bonus_percent += 5.00

    total_multiplier = strength_multiplier * (1 + item_bonus_percent)
    earned = int(base_earned * total_multiplier)

    data[user_id]["bank_points"] += earned

    await write_json(DATA_FILE, data, data_lock)

    await ctx.send(f"🛠️ You worked hard and earned **${earned}**! (Base: ${base_earned}, Multiplier: x{total_multiplier:.2f})")

GUARD_FILE = "MAINGuards.json"
guard_lock = asyncio.Lock()
GUARD_PRICE = 4500
GUARD_LIMIT = 25

async def init_guards(user_id):
    guards = await read_json(GUARD_FILE, guard_lock)
    if str(user_id) not in guards:
        guards[str(user_id)] = {
            "guards": 0
        }
        await write_json(GUARD_FILE, guards, guard_lock)

user_zones = {}

@bot.command()
async def buyguard(ctx, amount: int = 1, guard_type: str = "normal"):
    user_id = str(ctx.author.id)
    await init_user(user_id)

    guard_type = guard_type.lower()
    if guard_type not in ["normal", "shielder", "sniper"]:
        return await ctx.send("❌ Invalid guard type. Choose one: `normal`, `shielder`, or `sniper`.")

    # Bölge slotlarını oku (5, 10 veya 15 olabilir)
    zoneslots = await read_json("MAINZoneSlots.json", asyncio.Lock())
    zone_count = zoneslots.get(user_id, 5)

    # Maksimum koruma sayısını bölge sayısına göre hesapla
    if zone_count == 5:
        max_guards = 25
    elif zone_count == 10:
        max_guards = 65
    elif zone_count == 15:
        max_guards = 95
    elif zone_count == 20:
        max_guards = 135
    else:
        max_guards = 25  # fallback

    guard_prices = {
        "normal": 4500,
        "shielder": 9000,
        "sniper": 12000
    }
    cost_per_guard = guard_prices[guard_type]
    total_cost = cost_per_guard * amount

    guards = await read_json("MAINGuards.json", asyncio.Lock())
    bank = await read_json(DATA_FILE, data_lock)

    current_guard_count = len(guards.get(user_id, []))

    if current_guard_count >= max_guards:
        return await ctx.send(f"🛡️ You already have the maximum number of guards ({max_guards}) for your zones.")

    if bank[user_id]["bank_points"] < total_cost:
        return await ctx.send(f"💸 You don't have enough money. Total cost: ${total_cost:,}")

    bank[user_id]["bank_points"] -= total_cost

    import random
    guards.setdefault(user_id, [])
    added = 0
    for _ in range(amount):
        if len(guards[user_id]) >= max_guards:
            break
        # Bölge numarasını 1 ile zone_count arasında ata
        guards[user_id].append({
            "zone": random.randint(1, zone_count),
            "type": guard_type
        })
        added += 1

    await write_json("MAINGuards.json", guards, asyncio.Lock())
    await write_json(DATA_FILE, bank, data_lock)

    await ctx.send(f"🛡️ You hired {added} `{guard_type}` guard(s) for ${total_cost:,}. Max guards for your zones: {max_guards}")


@bot.command()
async def buyzoneslot(ctx, slot: int):
    user_id = str(ctx.author.id)
    bank = await read_json(DATA_FILE, data_lock)
    zoneslots = await read_json("MAINZoneSlots.json", asyncio.Lock())

    if slot not in [10, 15, 20]:
        return await ctx.send("❌ You can only buy `10`, `15` or '20' zone slots.")

    current_slot = zoneslots.get(user_id, 5)

    if current_slot >= slot:
        return await ctx.send(f"🛑 You already have {slot} or more zones.")

    
    if slot == 10:
        price = 150000
    elif slot == 15:
        price = 350000
    elif slot == 20:
        price = 750000
    if bank[user_id]["bank_points"] < price:
        return await ctx.send(f"💸 You need ${price} for this transaction.")

    bank[user_id]["bank_points"] -= price
    zoneslots[user_id] = slot

    await write_json(DATA_FILE, bank, data_lock)
    await write_json("MAINZoneSlots.json", zoneslots, asyncio.Lock())

    await ctx.send(f"✅ You now own {slot} zones! This also grants you more guard slots.")


@bot.command()
async def zones(ctx):
    user_id = str(ctx.author.id)
    zoneslots = await read_json("MAINZoneSlots.json", asyncio.Lock())
    slot = zoneslots.get(user_id, 5)
    await ctx.send(f"🗺️ You currently own {slot} zones.")


@bot.command()
async def guards(ctx):
    user_id = str(ctx.author.id)
    guards = await read_json("MAINGuards.json", asyncio.Lock())
    zoneslots = await read_json("MAINZoneSlots.json", asyncio.Lock())

    if user_id not in guards or not guards[user_id]:
        return await ctx.send("🛡️ You don't have any guards.")

    zone_count = zoneslots.get(user_id, 5)

    zone_counts = [0] * zone_count  # zone sayısına göre liste oluştur

    for guard in guards[user_id]:
        zone = guard.get("zone", 1)
        if 1 <= zone <= zone_count:
            zone_counts[zone - 1] += 1

    desc = "\n".join([f"Zone {i+1}: {count} guard(s)" for i, count in enumerate(zone_counts)])
    embed = discord.Embed(title="🛡️ Your Guards", description=desc, color=0x00aa88)
    await ctx.send(embed=embed)

ASSASSIN_TYPES = {
    "solo": {"cost": 20_000, "team_size": 1},
    "squad": {"cost": 100_000, "team_size": 5},
    "army": {"cost": 350_000, "team_size": 10},
    "platoon": {"cost": 900_000, "team_size": 20},
    "taskforce": {"cost": 1_500_000, "team_size": 30},
    "division": {"cost": 4_500_000, "team_size": 40},
    "brigade": {"cost": 7_500_000, "team_size": 50},
    "battalion": {"cost": 23_000_000, "team_size": 75},
    "regiment": {"cost": 42_500_000, "team_size": 100}
}


assassination_state = {}  # user_id -> suikast bilgisi

@bot.command()
async def assassinate(ctx, target: discord.Member, method: str):
    attacker_id = str(ctx.author.id)
    target_id = str(target.id)

    if attacker_id == target_id:
        return await ctx.send("❌ You cannot assassinate yourself.")

    method = method.lower()
    if method not in ASSASSIN_TYPES:
        return await ctx.send("❌ Invalid method. Choose one: `solo`, `squad`, `army`, `platoon`, `taskforce`, `division`, `brigade`, `battalion` or `regiment`.")

    if method == "solo":
        await ctx.invoke(bot.get_command('assassinate_solo'), target=target)
        return

    team_size = ASSASSIN_TYPES[method]["team_size"]
    cost = ASSASSIN_TYPES[method]["cost"]

    bank = await read_json(DATA_FILE, data_lock)
    if bank.get(attacker_id, {}).get("bank_points", 0) < cost:
        return await ctx.send(f"💸 You need ${cost:,} to start this assassination.")

    bank[attacker_id]["bank_points"] -= cost
    await write_json(DATA_FILE, bank, data_lock)

    # Hedefin bölge sayısını oku
    zone_data = await read_json("MAINZoneSlots.json", asyncio.Lock())
    region_count = zone_data.get(target_id, 5)

    # Koruma listesini oku
    guards_data = await read_json("MAINGuards.json", asyncio.Lock())
    target_guards = guards_data.get(target_id, [])

    # Koruma bölgelerini oluştur
    zones = [[] for _ in range(region_count)]
    for guard in target_guards:
        zone = guard.get("zone", random.randint(1, region_count))
        zone = max(1, min(zone, region_count))
        if len(zones[zone - 1]) < 5:
            zones[zone - 1].append(guard)

    # 🟡 RAID DURUMU OLUŞTUR
    active_raids[attacker_id] = {
        "target_id": target_id,
        "team_size": team_size,
        "team_alive": team_size,
        "zones": zones,
        "current_zone": 0,
        "phase": "choose_tactic"
    }

    # 🟢 İSTATİSTİK: Giriş denemesi olarak kaydet
    data = await read_json("MAINAssassinationStats.json", asyncio.Lock())
    data.setdefault(attacker_id, {"attempts": 0, "success": 0, "fails": 0})
    data[attacker_id]["attempts"] += 1
    await write_json("MAINAssassinationStats.json", data, asyncio.Lock())

    await ctx.send(
        f"🚨 {ctx.author.mention}, you started a `{method}` assassination on {target.mention}!\n"
        f"🗺️ Target has `{region_count}` defensive zones.\n"
        f"Choose your tactic for zone 1: `!tactic siper` or `!tactic charge`"
    )



async def wipe_user(user_id, killer_id=None, channel=None):
    user_id = str(user_id)
    killer_id = str(killer_id) if killer_id else None

    # Ödül verisi
    bounties = await read_json("MAINBounties.json", asyncio.Lock())

    # Eğer bu oyuncunun başında ödül varsa ve biri öldürdüyse, parayı ona ver
    if killer_id and user_id in bounties:
        reward = bounties.pop(user_id)
        bank = await read_json(DATA_FILE, data_lock)
        bank.setdefault(killer_id, {"bank_points": 0})
        bank[killer_id]["bank_points"] += reward
        await write_json(DATA_FILE, bank, data_lock)
        await write_json("MAINBounties.json", bounties, asyncio.Lock())

        if channel:
            await channel.send(f"💰 <@{killer_id}> earned a **${reward:,}** bounty for eliminating <@{user_id}>!")

    # Oyuncunun tüm verilerini sil
    for path, lock in [
        (DATA_FILE, data_lock),
        (COMPANY_FILE, company_lock),
        ("MAINInventory.json", asyncio.Lock()),
        (USER_STOCK_FILE, user_stock_lock),
        ("MAINGuards.json", asyncio.Lock()),
        ("MAINZoneSlots.json", asyncio.Lock())
    ]:
        data = await read_json(path, lock)
        if user_id in data:
            del data[user_id]
            await write_json(path, data, lock)




active_raids = {}  # user_id -> raid info

GUARD_STRENGTH = {
    "normal": 1,
    "shielder": 1.5,
    "sniper": 2
}

async def process_raid_zone(channel, user_id):
    raid = active_raids.get(user_id)
    if not raid:
        return
    
    current_zone = raid["current_zone"]
    zones = raid["zones"]
    team_alive = raid["team_alive"]
    tactic = raid.get("tactic")

    if current_zone >= len(zones):
        # Suikast başarılı
        target_id = raid["target_id"]
        await channel.send(f"☠️ You eliminated your target <@{target_id}> successfully!")
        await wipe_user(target_id, killer_id=user_id, channel=channel)
        active_raids.pop(user_id, None)
                # İSTATİSTİK: başarı
        data = await read_json("MAINAssassinationStats.json", asyncio.Lock())
        data.setdefault(user_id, {"attempts": 0, "success": 0, "fails": 0})
        data[user_id]["success"] += 1
        await write_json("MAINAssassinationStats.json", data, asyncio.Lock())
        return

    zone_guards = zones[current_zone]
    if not zone_guards:
        await channel.send(f"✅ Zone {current_zone+1} is clear, moving to next zone...")
        raid["current_zone"] += 1
        raid["phase"] = "choose_tactic"
        await channel.send(f"Choose tactic for zone {raid['current_zone']+1}: `!tactic siper` or `!tactic charge`")
        return

    GUARD_STRENGTH = {
        "normal": 1,
        "shielder": 1.5,
        "sniper": 2.0
    }

    total_guard_strength = sum(GUARD_STRENGTH.get(g.get("type", "normal"), 1) for g in zone_guards)
    power_ratio = team_alive / (total_guard_strength + 1)  # +1 to avoid division by zero

    base_success = 0.5 if tactic == "charge" else 0.3
    success_chance = base_success * min(power_ratio, 2)  # max 2x etkisi

    sniper_count = sum(1 for g in zone_guards if g.get("type") == "sniper")
    success_chance -= sniper_count * 0.05
    success_chance = max(success_chance, 0.1)

    shielder_count = sum(1 for g in zone_guards if g.get("type") == "shielder")
    loss_rate = 0.35 if tactic == "charge" else 0.1
    loss_rate *= (1 - 0.1 * shielder_count)
    loss_rate /= max(power_ratio, 0.5)

    loss_rate_fail = 0.4 if tactic == "charge" else 0.2
    loss_rate_fail *= (1 - 0.1 * shielder_count)
    loss_rate_fail /= max(power_ratio, 0.5)

    if random.random() <= success_chance:
        raid["zones"][current_zone] = []
        await channel.send(f"✅ Zone {current_zone+1}: You defeated all {len(zone_guards)} guards with **{tactic}** tactic!")

        losses = max(1, int(team_alive * loss_rate))
        raid["team_alive"] -= losses
        raid["phase"] = "choose_tactic"
        raid["current_zone"] += 1

        if raid["team_alive"] <= 0:
            await channel.send("☠️ All your teammates died during the assault. Mission failed!")
            await wipe_user(user_id)
                        # İSTATİSTİK: başarısızlık
            data = await read_json("MAINAssassinationStats.json", asyncio.Lock())
            data.setdefault(user_id, {"attempts": 0, "success": 0, "fails": 0})
            data[user_id]["fails"] += 1
            await write_json("MAINAssassinationStats.json", data, asyncio.Lock())
            active_raids.pop(user_id, None)
            return

        await channel.send(f"⚠️ You lost {losses} teammates. {raid['team_alive']} remain alive.")
        await channel.send(f"Choose tactic for zone {raid['current_zone']+1}: `!tactic siper` or `!tactic charge`")
    else:
        losses = min(team_alive, max(1, int(team_alive * loss_rate_fail)))
        raid["team_alive"] -= losses

        if raid["team_alive"] <= 0:
            await channel.send(f"❌ Your tactic failed and you lost your entire team in zone {current_zone+1}. Mission failed!")
            await wipe_user(user_id)
                        # İSTATİSTİK: başarısızlık
            data = await read_json("MAINAssassinationStats.json", asyncio.Lock())
            data.setdefault(user_id, {"attempts": 0, "success": 0, "fails": 0})
            data[user_id]["fails"] += 1
            await write_json("MAINAssassinationStats.json", data, asyncio.Lock())
            active_raids.pop(user_id, None)
            return

        await channel.send(
            f"❌ Your attack failed in zone {current_zone+1}!\n"
            f"💥 You lost {losses} teammates. {raid['team_alive']} remain alive.\n"
            f"🔁 Choose a new tactic to retry zone {current_zone+1}: `!tactic siper` or `!tactic charge`"
        )
        raid["phase"] = "choose_tactic" 

@bot.command()
async def tactic(ctx, choice: str):
    user_id = str(ctx.author.id)

    if user_id not in active_raids:
        return await ctx.send("❌ You don't have an active assassination raid.")

    raid = active_raids[user_id]

    if raid["phase"] != "choose_tactic":
        return await ctx.send("❌ You cannot choose a tactic right now.")

    choice = choice.lower()
    if choice not in ["siper", "charge"]:
        return await ctx.send("❌ Invalid tactic. Choose `siper` or `charge`.")

    raid["tactic"] = choice
    raid["phase"] = "battle"

    await ctx.send(f"⚔️ You chose **{choice}** tactic for zone {raid['current_zone']+1}. Battle starting...")

    # Çatışmayı başlat
    await process_raid_zone(ctx.channel, user_id)


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    await bot.process_commands(message)

    user_id = str(message.author.id)

    # --- Suikast sistemi (taktik seçimi) ---
    if user_id in active_raids:
        raid = active_raids[user_id]

        if raid["phase"] == "choose_tactic":
            content = message.content.lower()
            if content not in ["siper", "charge"]:
                await message.channel.send("❌ Invalid tactic. Choose one: `siper` or `charge`.")
                return

            raid["tactic"] = content
            raid["phase"] = "battle"
            await message.channel.send(f"⚔️ You chose **{content}** tactic for zone {raid['current_zone']+1}. Battle starting...")

            await process_raid_zone(message.channel, user_id)

    # --- Blackjack oyunu ---
    if user_id in active_blackjacks:
        game = active_blackjacks[user_id]
        player = game["player"]
        dealer = game["dealer"]
        channel = game["channel"]
        doubled = game["doubled"]

        def total(hand):
            return sum(hand)

        def draw():
            return random.randint(2, 11)

        choice = message.content.lower()

        if choice == "hit":
            player.append(draw())
            if total(player) > 21:
                del active_blackjacks[user_id]
                await channel.send(f"💥 You busted with {player} (Total: {total(player)}). You lost ${game['bet']}.")
            else:
                await channel.send(f"🃏 You drew {player[-1]}. Your hand: {player} (Total: {total(player)}). Type `hit` or `stand`.")

        elif choice == "double":
            if doubled:
                return await channel.send("❌ You can only double once at the start.")

            data = await read_json(DATA_FILE, data_lock)
            bet = game["bet"]

            if data[user_id]["bank_points"] < bet:
                return await channel.send("💸 You don't have enough money to double.")

            data[user_id]["bank_points"] -= bet
            await write_json(DATA_FILE, data, data_lock)

            player.append(draw())
            game["doubled"] = True
            game["bet"] = bet * 2

            while total(dealer) < 17:
                dealer.append(draw())

            await finish_blackjack(user_id)

        elif choice == "stand":
            while total(dealer) < 17:
                dealer.append(draw())

            await finish_blackjack(user_id)


@bot.command()
async def bounty(ctx, target: discord.Member, amount: int):
    user_id = str(ctx.author.id)
    target_id = str(target.id)

    if user_id == target_id:
        return await ctx.send("❌ You cannot place a bounty on yourself.")

    if amount < 10000:
        return await ctx.send("💸 You must place a bounty of at least $10,000.")

    bank = await read_json(DATA_FILE, data_lock)

    if bank[user_id]["bank_points"] < amount:
        return await ctx.send(f"❌ You don’t have enough money. Required: ${amount:,}")

    # Bounty data
    bounties = await read_json("MAINBounties.json", asyncio.Lock())
    bounties[target_id] = bounties.get(target_id, 0) + amount

    # Deduct money
    bank[user_id]["bank_points"] -= amount

    await write_json("MAINBounties.json", bounties, asyncio.Lock())
    await write_json(DATA_FILE, bank, data_lock)

    await ctx.send(f"💰 {ctx.author.mention} placed a **${amount:,}** bounty on {target.mention}!")


@bot.command()
async def bounties(ctx):
    bounties = await read_json("MAINBounties.json", asyncio.Lock())
    if not bounties:
        return await ctx.send("🔍 There are currently no active bounties.")

    sorted_bounties = sorted(bounties.items(), key=lambda x: x[1], reverse=True)
    description = ""
    for user_id, amount in sorted_bounties[:10]:
        member = ctx.guild.get_member(int(user_id))
        name = member.display_name if member else f"<@{user_id}>"
        description += f"🎯 {name}: **${amount:,}**\n"

    embed = discord.Embed(title="🏆 Active Bounties", description=description, color=0xff4444)
    await ctx.send(embed=embed)


@bot.command()
async def attempted_assassinations(ctx, member: discord.Member = None):
    user = member or ctx.author
    user_id = str(user.id)

    data = await read_json("MAINAssassinationStats.json", asyncio.Lock())
    stats = data.get(user_id, {"attempts": 0, "success": 0, "fails": 0})

    embed = discord.Embed(
        title=f"🗡️ Assassination Stats for {user.display_name}",
        color=discord.Color.dark_red()
    )
    embed.add_field(name="🔁 Attempts", value=stats["attempts"])
    embed.add_field(name="✅ Successes", value=stats["success"])
    embed.add_field(name="❌ Fails", value=stats["fails"])

    await ctx.send(embed=embed)


@bot.command()
async def commands(ctx):
    embed = discord.Embed(
        title="📜 Economy Bot Commands",
        description="Here's a list of available commands:",
        color=0xFFD700
    )
    embed.add_field(name="💰 !money", value="Check your current balance.", inline=False)
    embed.add_field(name="🏦 !loan <amount>", value="Borrow money using your bank points.", inline=False)
    embed.add_field(name="💳 !pay <amount>", value="Pay back your loan.", inline=False)
    embed.add_field(name="🏢 !createcompany <name>", value="Start your own company (costs $150,000).", inline=False)
    embed.add_field(name="⬆️ !upgradeoffice", value="Upgrade your company office for more employees.", inline=False)
    embed.add_field(name="👨‍💼 !hire", value="Hire a new employee (costs $2,000).", inline=False)
    embed.add_field(name="📈 !buystock <company>", value="Buy a company's stock.", inline=False)
    embed.add_field(name="🛠️ !work", value="Work to earn money (2 min cooldown).", inline=False)
    embed.add_field(name="🎰 !slot <amount>", value="Spin the slot machine. Min bet: $50. Win up to 2x your bet.", inline=False)
    embed.add_field(name="🃏 !blackjack <amount>", value="Play blackjack. Min bet: $100. Commands during game: hit, stand, double.", inline=False)
    embed.add_field(name="🎡 !roulette <red/black> <amount>", value="Bet on red or black in roulette.", inline=False)
    embed.add_field(name="🎲 !dice <1-6> <amount>", value="Guess the dice roll number to win 5x your bet.", inline=False)
    embed.add_field(name="🪙 !coinflip <heads/tails> <amount>", value="Flip a coin and guess heads or tails.", inline=False)
    
    # Yeni eklenen komutlar:
    embed.add_field(name="🎯 !quest veya !mission", value="Complete missions to earn rewards. (not working for now sorry)", inline=False)
    embed.add_field(name="🔄 !trade <user> <item>", value="Trade items with other players.", inline=False)
    embed.add_field(name="💪 !workout veya !train", value="Train your character to earn more money later.", inline=False)
    embed.add_field(name="🛒 !shop", value="Buy items from the shop, some provide passive income.", inline=False)
    embed.add_field(name="💰 !sell <item>", value="Sell items from your inventory to earn money.", inline=False)
    embed.add_field(name="🚔 !crime", value="Commit risky crimes for high rewards (use with caution).", inline=False)
    embed.add_field(name="🎁 !daily", value="Claim your daily bank points reward.", inline=False)
    
    embed.add_field(name="📜 !commands", value="Show this help menu.", inline=False)
    embed.set_footer(text="New commands coming soon...")
    await ctx.send(embed=embed)


@bot.event
async def on_ready():
    print(f"[✓] Bot is online as {bot.user}")
    if not run_penalty_check.is_running():
        run_penalty_check.start()
    if not stock_market_loop.is_running():
        stock_market_loop.start()
    if not income_report_loop.is_running():
        income_report_loop.start()
    if not  company_income_loop.is_running():
        company_income_loop.start()

token = os.getenv("DISCORD_TOKEN")

async def main():
    try:
        for file, lock in [(DATA_FILE, data_lock), (COMPANY_FILE, company_lock), (STOCK_FILE, stock_lock), (USER_STOCK_FILE, user_stock_lock)]:
            await ensure_file_exists(file)
        await bot.start(token)
    except Exception as e:
        print(f"Bot stopped with exception: {e}")


asyncio.run(main())

