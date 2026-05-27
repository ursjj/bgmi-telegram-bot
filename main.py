import html
import json
import logging
import os
import asyncio
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
)

# Enable Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- 1. CONFIGURATION ---
ADMIN_GROUP_ID = int(os.environ.get("ADMIN_GROUP_ID", -1003976507364))
TOKEN = os.environ.get("TELEGRAM_TOKEN", "8914813080:AAHt7fWiePcCZrvH4_IMB92BSglgTmcPhek")
BACKUP_FILE = "/tmp/market_backup.json" if os.environ.get("RENDER") else "market_backup.json"

# --- 2. DATA STRUCTURE ---
TIERS = {
    "Gold": [
        "Evacuation Master", "Melody Strongest Team", "Raging Rush Team",
        "Jujutsu Kaisen", "Ryomen Sukuna", "Suguru Geto",
        "Bat", "Jester of Fate", "Ancient Secret: Arise"
    ],
    "Blue": [
        "Music Hall", "Racing Hall", "Dynamic Slide Rail", "Parachute Challenge", "Racing Challenge", "S-Rank Vault",
        "Satoru Gojo", "Yuji Itadori", "Megumi Fushiguro", "Nue", "Nobara Kugisaki",
        "Golden Age", "Arcade Time", "Rhythm Hero", "Vibrant World", "Dinoground", "Ocean Odyssey", "Golden Dynasty", "Temporal Vault",
        "Ray", "Your Old Friends", "Fool Juggling", "Sacred Fire Trial", "Scorpion Crate", "Ancient Secret Battle"
    ],
    "Basic": [
        "A-Rank Vault", "B-Rank Vault", "Special Lucky Spin", "Energy Shield", "Spatial Zone 1", "Spatial Zone 2", "Floating Thruster",
        "Cathy", "Cursed Corpse Bear", "Inverted Spear",
        "Garand", "Tracked Amphicarrier"
    ]
}

CARD_SETS = {
    "Evolving Universe": ["Evacuation Master", "Melody Strongest Team", "Raging Rush Team", "Music Hall", "Racing Hall", "Dynamic Slide Rail", "Parachute Challenge", "Racing Challenge", "S-Rank Vault", "A-Rank Vault", "B-Rank Vault", "Special Lucky Spin", "Energy Shield", "Spatial Zone 1", "Spatial Zone 2", "Floating Thruster"],
    "Jujutsu Kaisen": ["Jujutsu Kaisen", "Ryomen Sukuna", "Suguru Geto", "Satoru Gojo", "Yuji Itadori", "Megumi Fushiguro", "Nue", "Nobara Kugisaki", "Cursed Corpse Bear", "Inverted Spear"],
    "Special": ["Legendary Journey", "Aspiring Collector", "Golden Age", "Arcade Time", "Rhythm Hero", "Vibrant World", "Dinoground", "Ocean Odyssey", "Golden Dynasty", "Temporal Vault"],
    "Playful Battleground": ["Jester of Fate", "Ancient Secret: Arise", "Your Old Friends", "Fool Juggling", "Sacred Fire Trial", "Scorpion Crate", "Ancient Secret Battle", "Ray", "Garand", "Tracked Amphicarrier"]
}

HAVE_TIER, HAVE_SET, HAVE_CARD, WANT_SET, WANT_CARD, GET_CODE, GET_TIME = range(7)

# --- 3. PERSISTENT BACKUP HELPERS ---
def save_market_backup(market_data):
    try:
        with open(BACKUP_FILE, "w", encoding="utf-8") as f:
            json.dump(market_data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Error saving backup: {e}")

def init_market_data(context: ContextTypes.DEFAULT_TYPE):
    if "market" in context.bot_data:
        return
    if os.path.exists(BACKUP_FILE):
        try:
            with open(BACKUP_FILE, "r", encoding="utf-8") as f:
                context.bot_data["market"] = json.load(f)
                return
        except Exception as e:
            logger.error(f"Backup tracking data corrupted: {e}")

    context.bot_data["market"] = {}
    for card_list in CARD_SETS.values():
        for card in card_list:
            context.bot_data["market"][card] = {"supply": 0, "demand": 0}
    save_market_backup(context.bot_data["market"])

def get_card_tier(card_name):
    for tier, cards in TIERS.items():
        if card_name in cards:
            emoji = "🟡" if tier == "Gold" else "🔵" if tier == "Blue" else "⚪"
            return tier, emoji
    return "Unknown", "❓"

# --- 4. KEYBOARD UI HELPERS ---
def get_tier_keyboard():
    keyboard = [[InlineKeyboardButton(f"✨ {t} Tier", callback_data=f"tier_{t}")] for t in TIERS.keys()]
    keyboard.append([InlineKeyboardButton("❌ Cancel Process", callback_data="stop_exchange")])
    return InlineKeyboardMarkup(keyboard)

def get_set_keyboard(tier, prefix, back_data):
    keyboard = []
    for set_name in CARD_SETS.keys():
        if any(card in TIERS[tier] for card in CARD_SETS[set_name]):
            keyboard.append([InlineKeyboardButton(f"📁 {set_name}", callback_data=f"{prefix}{set_name}")])
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data=back_data), InlineKeyboardButton("❌ Cancel", callback_data="stop_exchange")])
    return InlineKeyboardMarkup(keyboard)

def get_card_keyboard(set_name, tier, prefix, back_data):
    filtered_cards = [c for c in CARD_SETS[set_name] if c in TIERS[tier]]
    keyboard = []
    for i in range(0, len(filtered_cards), 2):
        row = [InlineKeyboardButton(c, callback_data=f"{prefix}{c}") for c in filtered_cards[i:i+2]]
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data=back_data), InlineKeyboardButton("❌ Cancel", callback_data="stop_exchange")])
    return InlineKeyboardMarkup(keyboard)

def get_browser_sets_keyboard():
    keyboard = [[InlineKeyboardButton(f"📊 {set_name}", callback_data=f"browse_set_{set_name}")] for set_name in CARD_SETS.keys()]
    keyboard.append([InlineKeyboardButton("❌ Close Dashboard", callback_data="close_browser")])
    return InlineKeyboardMarkup(keyboard)


# --- 5. HANDLERS ---
async def start_exchange(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_market_data(context)
    text = "🟩 <b>STEP 1: SELECT CARD TIER</b>\n\n<i>Note: Trades match items belonging strictly within the same value tiers.</i>"
    markup = get_tier_keyboard()
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
    return HAVE_TIER

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "❓ <b>How to use BGMI Card Exchange</b>\n\n"
        "1️⃣ Run /exchange to invoke the trading pipeline.\n"
        "2️⃣ Select the target tier, relative sets, and identity tokens.\n"
        "3️⃣ Enter your 8-digit in-game exchange code via /excode.\n"
        "4️⃣ Choose your listing lifespan allocation.\n\n"
        "📊 Type /viewsets at any time to inspect live global metrics!"
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(help_text, parse_mode="HTML")
    else:
        await update.message.reply_text(help_text, parse_mode="HTML")

async def view_sets_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_market_data(context)
    text = "📋 <b>BGMI Live Market Analytics</b>\nSelect a collection package below to view current supply and demand indexes."
    markup = get_browser_sets_keyboard()
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")

async def set_browsed_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    set_name = query.data.replace("browse_set_", "")
    
    market = context.bot_data["market"]
    cards_in_set = CARD_SETS[set_name]
    
    text_lines = [f"📊 <b>LIVE VOLUME MATRIX: {set_name.upper()}</b>\n"]
    for card in cards_in_set:
        tier_name, emoji = get_card_tier(card)
        sup = market.get(card, {}).get("supply", 0)
        dem = market.get(card, {}).get("demand", 0)
        
        trend = " 🔥 <i>[High Demand]</i>" if dem > sup else ""
        text_lines.append(f"{emoji} <b>{card}</b> ({tier_name})")
        text_lines.append(f"  供给 (Supply): {sup} | 需求 (Demand): {dem}{trend}\n")
        
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back to Collections", callback_data="back_to_browser_main")],
        [InlineKeyboardButton("❌ Exit Analytics", callback_data="close_browser")]
    ])
    await query.edit_message_text("\n".join(text_lines), reply_markup=markup, parse_mode="HTML")

async def close_browser_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🔒 Live Analytics Browser session closed.")

async def tier_picked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("back_to_hset_"):
        tier = query.data.replace("back_to_hset_", "")
    else:
        tier = query.data.replace("tier_", "")
        context.user_data['tier'] = tier

    await query.edit_message_text(f"✨ <b>Active Tier: {tier}</b>\n\nSelect the <b>Set</b> containing the card you <u>HAVE</u>:", 
                                  reply_markup=get_set_keyboard(tier, "hset_", "go_to_start"), parse_mode="HTML")
    return HAVE_SET

async def have_set_picked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    tier = context.user_data['tier']
    if query.data.startswith("back_to_wset_list"):
        set_name = context.user_data['h_set']
    else:
        set_name = query.data.replace("hset_", "")
        context.user_data['h_set'] = set_name
        
    await query.edit_message_text(f"📁 <b>Set Group: {set_name}</b>\n\nWhich explicit card do you <u>HAVE</u>?", 
                                  reply_markup=get_card_keyboard(set_name, tier, "hcard_", f"back_to_hset_{tier}"), parse_mode="HTML")
    return HAVE_CARD

async def have_card_picked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    tier = context.user_data['tier']
    if query.data.startswith("back_to_wset_"):
        card_name = context.user_data['have_card']
    else:
        card_name = query.data.replace("hcard_", "")
        context.user_data['have_card'] = card_name
        
    await query.edit_message_text(f"📤 <b>Offered Asset:</b> {card_name}\n\nSelect the <b>Set</b> containing the item you <u>WANT</u>:", 
                                  reply_markup=get_set_keyboard(tier, "wset_", "back_to_wset_list"), parse_mode="HTML")
    return WANT_SET

async def want_set_picked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    set_name = query.data.replace("wset_", "")
    context.user_data['w_set'] = set_name
    tier = context.user_data['tier']
    
    await query.edit_message_text(f"📁 <b>Target Set: {set_name}</b>\n\nWhich specific item do you <u>WANT</u>?", 
                                  reply_markup=get_card_keyboard(set_name, tier, "wcard_", f"back_to_wset_"), parse_mode="HTML")
    return WANT_CARD

async def want_card_picked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    card_name = query.data.replace("wcard_", "")
    context.user_data['want_card'] = card_name
    await query.edit_message_text("📝 <b>IDENTIFICATION CHALLENGE</b>\n\nPlease submit your unique alphanumeric credentials via command:\n\n👉 <code>/excode YOUR_CODE_HERE</code>", parse_mode="HTML")
    return GET_CODE

async def save_code_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Invalid formatting. Execute using: <code>/excode 12345678</code>", parse_mode="HTML")
        return GET_CODE
    context.user_data['code'] = context.args[0]
    times = ["6 Hours", "12 Hours", "24 Hours", "36 Hours"]
    buttons = [[InlineKeyboardButton(t, callback_data=f"time_{t}") for t in times[i:i+2]] for i in range(0, 4, 2)]
    buttons.append([InlineKeyboardButton("❌ Abort Request", callback_data="stop_exchange")])
    await update.message.reply_text(f"✅ Code payload registered: <code>{html.escape(context.user_data['code'])}</code>\n\nSpecify listing expiration term:", 
                                    reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")
    return GET_TIME

async def finalize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    time_val = query.data.replace("time_", "")
    user = query.from_user
    
    h_card = context.user_data.get('have_card')
    w_card = context.user_data.get('want_card')
    
    if not h_card or not w_card:
        await query.edit_message_text("❌ Session loss occurred. Please restart using /exchange.")
        return ConversationHandler.END

    context.bot_data["market"][h_card]["supply"] += 1
    context.bot_data["market"][w_card]["demand"] += 1
    save_market_backup(context.bot_data["market"])
    
    username = f"@{html.escape(user.username)}" if user.username else "Private User"
    
    admin_msg = (
        f"📢 <b>NEW TRANSACTION SUBMISSION</b>\n\n"
        f"👤 User: {username} (ID: <code>{user.id}</code>)\n"
        f"📤 Allocation: <b>{html.escape(h_card)}</b>\n"
        f"📥 Requirement: <b>{html.escape(w_card)}</b>\n"
        f"🔑 Code payload: <code>{html.escape(context.user_data['code'])}</code>\n"
        f"⏳ Time Window: {html.escape(time_val)}"
    )
    
    admin_buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve / Match", callback_data=f"adm_comp__{h_card}__{w_card}"),
            InlineKeyboardButton("❌ Drop Order", callback_data=f"adm_rejc__{h_card}__{w_card}")
        ]
    ])
    
    try:
        await context.bot.send_message(chat_id=ADMIN_GROUP_ID, text=admin_msg, reply_markup=admin_buttons, parse_mode="HTML")
        await query.edit_message_text("🚀 <b>Submission Successful!</b>\nYour order payload was successfully queued for verification workflows.")
    except Exception as e:
        logger.error(f"Failed sending admin message: {e}")
        await query.edit_message_text("❌ Interface transmission breakdown. Administration group unreachable.")
        
    return ConversationHandler.END

async def admin_decision_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    raw_data = query.data.replace("adm_", "")
    action, cards_part = raw_data.split("__", 1)
    try:
        h_card, w_card = cards_part.split("__")
    except ValueError:
        await query.edit_message_text("❌ Error unpacking routing data parameters.")
        return
    
    market = context.bot_data.get("market", {})
    if h_card in market and market[h_card]["supply"] > 0:
        market[h_card]["supply"] -= 1
    if w_card in market and market[w_card]["demand"] > 0:
        market[w_card]["demand"] -= 1
        
    save_market_backup(market)
        
    original_text = query.message.text_html
    status_label = "🟩 <b>RESOLVED / DISPATCHED</b>" if action == "comp" else "🟥 <b>DECLINED / ARCHIVED</b>"
    
    await query.edit_message_text(text=f"{original_text}\n\n🏁 <b>Action Resolution:</b> {status_label}", reply_markup=None, parse_mode="HTML")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: 
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("⚙️ Session lifecycle terminated.")
    else:
        await update.message.reply_text("⚙️ Session lifecycle terminated.")
    return ConversationHandler.END


# --- 6. ASYNC PRODUCTION COMPLIANT COUPLING ---
flask_app = Flask(__name__)

# Initialize Application as a global object singleton context
telegram_app = Application.builder().token(TOKEN).build()

conv = ConversationHandler(
    entry_points=[
        CommandHandler("start", start_exchange), 
        CommandHandler("exchange", start_exchange)
    ],
    states={
        HAVE_TIER: [CallbackQueryHandler(tier_picked, pattern="^tier_")],
        HAVE_SET: [
            CallbackQueryHandler(start_exchange, pattern="^go_to_start$"), 
            CallbackQueryHandler(have_set_picked, pattern="^hset_")
        ],
        HAVE_CARD: [
            CallbackQueryHandler(tier_picked, pattern="^back_to_hset_"), 
            CallbackQueryHandler(have_card_picked, pattern="^hcard_")
        ],
        WANT_SET: [
            CallbackQueryHandler(have_set_picked, pattern="^back_to_wset_list$"), 
            CallbackQueryHandler(want_set_picked, pattern="^wset_")
        ],
        WANT_CARD: [
            CallbackQueryHandler(have_card_picked, pattern="^back_to_wset_$"), 
            CallbackQueryHandler(want_card_picked, pattern="^wcard_")
        ],
        GET_CODE: [CommandHandler("excode", save_code_command)],
        GET_TIME: [CallbackQueryHandler(finalize, pattern="^time_")],
    },
    fallbacks=[
        CommandHandler("help", help_command),
        CommandHandler("viewsets", view_sets_command),
        CallbackQueryHandler(stop, pattern="^stop_exchange$"), 
        CommandHandler("stop", stop)
    ],
)

telegram_app.add_handler(CommandHandler("help", help_command))
telegram_app.add_handler(CommandHandler("viewsets", view_sets_command))
telegram_app.add_handler(CallbackQueryHandler(view_sets_command, pattern="^back_to_browser_main$"))
telegram_app.add_handler(CallbackQueryHandler(set_browsed_callback, pattern="^browse_set_"))
telegram_app.add_handler(CallbackQueryHandler(close_browser_callback, pattern="^close_browser$"))
telegram_app.add_handler(CallbackQueryHandler(admin_decision_callback, pattern="^adm_"))
telegram_app.add_handler(conv)

# Safe lifecycle loop instantiation hook
@flask_app.before_all_requests
def start_bot_lifecycle():
    """Initializes the persistent background runner loop without multi-instance compilation problems."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    if not telegram_app.running:
        loop.run_until_complete(telegram_app.initialize())
        loop.run_until_complete(telegram_app.start())

@flask_app.route("/webhook", methods=["POST"])
def webhook_handler():
    if request.method == "POST":
        try:
            payload = request.get_json(force=True)
            update = Update.de_json(payload, telegram_app.bot)
            
            loop = asyncio.get_event_loop()
            loop.run_until_complete(telegram_app.process_update(update))
            
            return jsonify({"status": "fixed structural loop resolution complete"}), 200
        except Exception as e:
            logger.error(f"Webhook tracking execution dropped: {e}")
            return jsonify({"error": str(e)}), 500
    return "Forbidden", 403

if __name__ == "__main__":
    # Get the port from Render's environment, fallback to 5000 if running locally
    port = int(os.environ.get("PORT", 5000))
    # Bind to 0.0.0.0 so the external cloud network can route traffic to it
    flask_app.run(host="0.0.0.0", port=port)
