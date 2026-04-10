#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JOSEPH BATTLE ROYALE – النسخة النهائية (100 لاعب، أسلحة، شخصيات، عملات، خريطة)
صانع اللعبة: جورج فهمي
تشغيل محلي: python battleroyale.py
"""

import asyncio
import random
import math
import time
import json
import os
from typing import Dict, List, Tuple
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import socketio
import uvicorn

# ---------- إعدادات الخادم ----------
sio = socketio.AsyncServer(cors_allowed_origins='*', async_mode='asgi')
app = FastAPI(title="JOSEPH BATTLE ROYALE")
app.add_api_websocket_route("/ws", sio.handle_asgi)

# ---------- إعدادات اللعبة ----------
MAP_SIZE = 2000
MAX_PLAYERS = 100
SAFE_ZONE_START_RADIUS = 1800
SAFE_ZONE_END_RADIUS = 300
ZONE_SHRINK_TIME = 300  # 5 دقائق
ZONE_DAMAGE_PER_SEC = 5

# الأسلحة (الاسم، الضرر، سرعة الرمي، المدى، نوع الذخيرة، حجم المخزن)
WEAPONS = {
    "M416": {"damage": 25, "fire_rate": 0.1, "range": 300, "ammo_type": "5.56", "mag_size": 30, "reload_time": 2.0},
    "AKM": {"damage": 35, "fire_rate": 0.12, "range": 280, "ammo_type": "7.62", "mag_size": 30, "reload_time": 2.2},
    "AWM": {"damage": 100, "fire_rate": 1.5, "range": 500, "ammo_type": ".300", "mag_size": 5, "reload_time": 3.0},
    "Shotgun": {"damage": 90, "fire_rate": 0.8, "range": 50, "ammo_type": "12", "mag_size": 8, "reload_time": 2.5},
    "Pistol": {"damage": 18, "fire_rate": 0.2, "range": 150, "ammo_type": "9mm", "mag_size": 15, "reload_time": 1.5},
}

# الشخصيات
CHARACTERS = {
    "soldier": {"health": 100, "speed": 5.0, "ability": "none", "color": "#33aaff"},
    "scout": {"health": 80, "speed": 6.0, "ability": "silent_footsteps", "color": "#88ff88"},
    "tank": {"health": 150, "speed": 4.0, "ability": "damage_reduction", "color": "#ff6666"},
    "medic": {"health": 100, "speed": 5.0, "ability": "self_heal", "color": "#ffaa44"},
}

# عناصر الشفاء والدروع
HEAL_ITEMS = {
    "bandage": {"heal": 10, "use_time": 3.0},
    "firstaid": {"heal": 50, "use_time": 5.0},
    "medkit": {"heal": 100, "use_time": 8.0},
}
ARMOR_ITEMS = {
    "vest_level1": {"armor": 30, "damage_reduction": 0.2},
    "vest_level2": {"armor": 50, "damage_reduction": 0.3},
    "vest_level3": {"armor": 80, "damage_reduction": 0.4},
}
HELMET_ITEMS = {
    "helmet_level1": {"armor": 20, "headshot_reduction": 0.3},
    "helmet_level2": {"armor": 40, "headshot_reduction": 0.4},
    "helmet_level3": {"armor": 60, "headshot_reduction": 0.5},
}

# ---------- حالة اللعبة ----------
players: Dict[str, dict] = {}
loot_items: List[dict] = []
airdrops: List[dict] = []
game_state = {
    "safe_zone_center": (0.0, 0.0),
    "safe_zone_radius": SAFE_ZONE_START_RADIUS,
    "zone_shrink_start": time.time(),
    "game_active": True,
}
leaderboard = []

def random_spawn() -> Tuple[float, float]:
    return (random.uniform(-MAP_SIZE/2, MAP_SIZE/2), random.uniform(-MAP_SIZE/2, MAP_SIZE/2))

SPAWN_POINTS = [random_spawn() for _ in range(MAX_PLAYERS)]

def generate_loot():
    global loot_items
    loot_items = []
    for _ in range(500):
        pos = (random.uniform(-MAP_SIZE/2, MAP_SIZE/2), random.uniform(-MAP_SIZE/2, MAP_SIZE/2))
        loot_type = random.choice(["weapon", "ammo", "heal", "armor", "helmet"])
        if loot_type == "weapon":
            weapon_name = random.choice(list(WEAPONS.keys()))
            loot_items.append({"type": "weapon", "name": weapon_name, "position": pos, "ammo": WEAPONS[weapon_name]["mag_size"]})
        elif loot_type == "ammo":
            ammo_type = random.choice(["5.56", "7.62", ".300", "12", "9mm"])
            loot_items.append({"type": "ammo", "ammo_type": ammo_type, "count": random.randint(30, 90), "position": pos})
        elif loot_type == "heal":
            heal_name = random.choice(list(HEAL_ITEMS.keys()))
            loot_items.append({"type": "heal", "name": heal_name, "position": pos})
        elif loot_type == "armor":
            armor_name = random.choice(list(ARMOR_ITEMS.keys()))
            loot_items.append({"type": "armor", "name": armor_name, "position": pos})
        else:
            helmet_name = random.choice(list(HELMET_ITEMS.keys()))
            loot_items.append({"type": "helmet", "name": helmet_name, "position": pos})

async def spawn_airdrop():
    while True:
        await asyncio.sleep(random.randint(60, 120))
        if game_state["game_active"]:
            pos = (random.uniform(-MAP_SIZE/2 + 200, MAP_SIZE/2 - 200), random.uniform(-MAP_SIZE/2 + 200, MAP_SIZE/2 - 200))
            weapon = random.choice(list(WEAPONS.keys()))
            airdrops.append({"position": pos, "weapon": weapon, "ammo": 100, "armor": "vest_level3", "helmet": "helmet_level3"})
            await sio.emit("airdrop_spawned", {"position": pos})

async def zone_updater():
    start_time = time.time()
    while game_state["game_active"]:
        await asyncio.sleep(1)
        elapsed = time.time() - start_time
        if elapsed >= ZONE_SHRINK_TIME:
            game_state["safe_zone_radius"] = SAFE_ZONE_END_RADIUS
        else:
            t = elapsed / ZONE_SHRINK_TIME
            game_state["safe_zone_radius"] = SAFE_ZONE_START_RADIUS * (1 - t) + SAFE_ZONE_END_RADIUS * t
        for sid, player in players.items():
            if player["alive"]:
                dist = math.hypot(player["position"][0] - game_state["safe_zone_center"][0], player["position"][1] - game_state["safe_zone_center"][1])
                if dist > game_state["safe_zone_radius"]:
                    player["health"] -= ZONE_DAMAGE_PER_SEC
                    if player["health"] <= 0:
                        player["alive"] = False
                        await sio.emit("player_killed", {"killer": "zone", "victim": sid})
        await sio.emit("zone_update", {"radius": game_state["safe_zone_radius"], "center": game_state["safe_zone_center"]})

# ---------- أحداث Socket.IO ----------
@sio.event
async def connect(sid, environ):
    print(f"Player {sid} connected")
    character = random.choice(list(CHARACTERS.keys()))
    spawn = random.choice(SPAWN_POINTS)
    players[sid] = {
        "id": sid,
        "name": f"Player_{random.randint(1000,9999)}",
        "character": character,
        "health": CHARACTERS[character]["health"],
        "max_health": CHARACTERS[character]["health"],
        "armor": 0,
        "armor_type": None,
        "helmet": 0,
        "helmet_type": None,
        "weapons": [{"name": "Pistol", "ammo": 15}],
        "current_weapon": "Pistol",
        "ammo": {"5.56": 0, "7.62": 0, ".300": 0, "12": 0, "9mm": 15},
        "money": 0,
        "gems": 0,
        "xp": 0,
        "level": 1,
        "position": spawn,
        "rotation": 0,
        "alive": True,
        "last_shot": 0,
    }
    await sio.emit("game_state", {
        "players": {pid: {k: v for k, v in p.items() if k != "ammo"} for pid, p in players.items()},
        "loot": loot_items,
        "airdrops": airdrops,
        "weapons": WEAPONS,
        "characters": CHARACTERS,
        "safe_zone": game_state["safe_zone_radius"],
    }, to=sid)
    await sio.emit("player_joined", {k: v for k, v in players[sid].items() if k != "ammo"}, skip_sid=sid)
    update_leaderboard()

@sio.event
async def disconnect(sid):
    if sid in players:
        del players[sid]
        await sio.emit("player_left", sid)
        update_leaderboard()

@sio.event
async def player_move(sid, data):
    if sid in players and players[sid]["alive"]:
        players[sid]["position"] = (data["x"], data["z"])
        players[sid]["rotation"] = data["rotation"]
        await sio.emit("player_moved", {"id": sid, "x": data["x"], "z": data["z"], "rot": data["rotation"]})

@sio.event
async def player_shoot(sid, data):
    if sid not in players or not players[sid]["alive"]:
        return
    shooter = players[sid]
    weapon_name = shooter["current_weapon"]
    weapon = WEAPONS[weapon_name]
    if shooter["ammo"][weapon["ammo_type"]] <= 0:
        await sio.emit("reload_needed", to=sid)
        return
    now = time.time()
    if now - shooter["last_shot"] < weapon["fire_rate"]:
        return
    shooter["last_shot"] = now
    shooter["ammo"][weapon["ammo_type"]] -= 1
    direction = data["direction"]
    for target_id, target in players.items():
        if target_id != sid and target["alive"]:
            dist = math.hypot(shooter["position"][0] - target["position"][0], shooter["position"][1] - target["position"][1])
            if dist < weapon["range"]:
                damage = weapon["damage"]
                if target["armor"] > 0 and target["armor_type"]:
                    damage *= (1 - ARMOR_ITEMS[target["armor_type"]]["damage_reduction"])
                if target["helmet"] > 0 and target["helmet_type"] and data.get("headshot", False):
                    damage *= (1 - HELMET_ITEMS[target["helmet_type"]]["headshot_reduction"])
                target["health"] -= damage
                await sio.emit("player_hit", {"id": target_id, "health": target["health"], "damage": damage, "shooter": sid})
                if target["health"] <= 0:
                    target["alive"] = False
                    shooter["money"] += 100
                    shooter["gems"] += random.randint(1, 5)
                    shooter["xp"] += 50
                    if shooter["xp"] >= shooter["level"] * 100:
                        shooter["level"] += 1
                    await sio.emit("player_killed", {"killer": sid, "victim": target_id, "killer_name": shooter["name"]})
                    update_leaderboard()
                break

@sio.event
async def pick_up_item(sid, data):
    if sid not in players:
        return
    player = players[sid]
    for i, item in enumerate(loot_items):
        if math.hypot(item["position"][0] - player["position"][0], item["position"][1] - player["position"][1]) < 3:
            if item["type"] == "weapon":
                player["weapons"].append({"name": item["name"], "ammo": item["ammo"]})
                player["ammo"][WEAPONS[item["name"]]["ammo_type"]] += item["ammo"]
            elif item["type"] == "ammo":
                player["ammo"][item["ammo_type"]] += item["count"]
            elif item["type"] == "heal":
                player["health"] = min(player["max_health"], player["health"] + HEAL_ITEMS[item["name"]]["heal"])
            elif item["type"] == "armor":
                if not player["armor_type"] or ARMOR_ITEMS[item["name"]]["armor"] > ARMOR_ITEMS.get(player["armor_type"], {}).get("armor", 0):
                    player["armor"] = ARMOR_ITEMS[item["name"]]["armor"]
                    player["armor_type"] = item["name"]
            elif item["type"] == "helmet":
                if not player["helmet_type"] or HELMET_ITEMS[item["name"]]["armor"] > HELMET_ITEMS.get(player["helmet_type"], {}).get("armor", 0):
                    player["helmet"] = HELMET_ITEMS[item["name"]]["armor"]
                    player["helmet_type"] = item["name"]
            del loot_items[i]
            await sio.emit("item_picked", {"item": item, "player": sid})
            break

@sio.event
async def switch_weapon(sid, data):
    if sid in players:
        weapon_name = data["weapon"]
        if any(w["name"] == weapon_name for w in players[sid]["weapons"]):
            players[sid]["current_weapon"] = weapon_name
            await sio.emit("weapon_switched", {"player": sid, "weapon": weapon_name})

def update_leaderboard():
    global leaderboard
    leaderboard = sorted([{"name": p["name"], "xp": p["xp"], "level": p["level"], "kills": 0} for p in players.values() if p["alive"]], key=lambda x: x["xp"], reverse=True)[:10]
    asyncio.create_task(sio.emit("leaderboard_update", leaderboard))

async def background_tasks():
    asyncio.create_task(zone_updater())
    asyncio.create_task(spawn_airdrop())
    generate_loot()

# ---------- واجهة المستخدم (HTML + JS + Three.js) ----------
HTML_PAGE = """ (سيتم وضع محتوى HTML الكامل هنا – لضيق المساحة سأختصره، لكنك ستأخذ النسخة الكاملة من الرد السابق) """

# اختصار: لأن الـ HTML طويل جدًا، تأكد من استخدام النسخة الكاملة التي أعطيتك إياها سابقًا.
# سأضع هنا رابطًا لاستكماله، أو يمكنك نسخ الـ HTML من الرد السابق مباشرة.
# (في التطبيق العملي، انسخ محتوى HTML_PAGE من الرد السابق الذي يبدأ بـ <!DOCTYPE html> ... )

@app.get("/")
async def get_game():
    return HTMLResponse(HTML_PAGE)

@app.on_event("startup")
async def startup():
    asyncio.create_task(background_tasks())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
  fastapi==0.110.0
uvicorn[standard]==0.27.0
python-socketio==5.10.0
cryptography==42.0.2pip install fastapi uvicorn python-socketio cryptography#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JOSEPH BATTLE ROYALE – النسخة النهائية (100 لاعب، أسلحة، شخصيات، عملات، خريطة)
صانع اللعبة: جورج فهمي
تشغيل: python battleroyale.py ثم افتح http://localhost:8000
"""

import asyncio
import random
import math
import time
import json
import os
from typing import Dict, List, Tuple
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import socketio
import uvicorn

# ---------- إعدادات الخادم ----------
sio = socketio.AsyncServer(cors_allowed_origins='*', async_mode='asgi')
app = FastAPI(title="JOSEPH BATTLE ROYALE")
app.mount("/static", StaticFiles(directory="static"), name="static")  # سيتم إنشاء مجلد static تلقائياً
app.add_api_websocket_route("/ws", sio.handle_asgi)

# ---------- إعدادات اللعبة ----------
MAP_SIZE = 2000
MAX_PLAYERS = 100
SAFE_ZONE_START_RADIUS = 1800
SAFE_ZONE_END_RADIUS = 300
ZONE_SHRINK_TIME = 300  # 5 دقائق
ZONE_DAMAGE_PER_SEC = 5

# الأسلحة (الاسم، الضرر، سرعة الرمي، المدى، نوع الذخيرة، حجم المخزن)
WEAPONS = {
    "M416": {"damage": 25, "fire_rate": 0.1, "range": 300, "ammo_type": "5.56", "mag_size": 30, "reload_time": 2.0},
    "AKM": {"damage": 35, "fire_rate": 0.12, "range": 280, "ammo_type": "7.62", "mag_size": 30, "reload_time": 2.2},
    "AWM": {"damage": 100, "fire_rate": 1.5, "range": 500, "ammo_type": ".300", "mag_size": 5, "reload_time": 3.0},
    "Shotgun": {"damage": 90, "fire_rate": 0.8, "range": 50, "ammo_type": "12", "mag_size": 8, "reload_time": 2.5},
    "Pistol": {"damage": 18, "fire_rate": 0.2, "range": 150, "ammo_type": "9mm", "mag_size": 15, "reload_time": 1.5},
}

# الشخصيات
CHARACTERS = {
    "soldier": {"health": 100, "speed": 5.0, "ability": "none", "color": "#33aaff"},
    "scout": {"health": 80, "speed": 6.0, "ability": "silent_footsteps", "color": "#88ff88"},
    "tank": {"health": 150, "speed": 4.0, "ability": "damage_reduction", "color": "#ff6666"},
    "medic": {"health": 100, "speed": 5.0, "ability": "self_heal", "color": "#ffaa44"},
}

# عناصر الشفاء والدروع
HEAL_ITEMS = {
    "bandage": {"heal": 10, "use_time": 3.0},
    "firstaid": {"heal": 50, "use_time": 5.0},
    "medkit": {"heal": 100, "use_time": 8.0},
}
ARMOR_ITEMS = {
    "vest_level1": {"armor": 30, "damage_reduction": 0.2},
    "vest_level2": {"armor": 50, "damage_reduction": 0.3},
    "vest_level3": {"armor": 80, "damage_reduction": 0.4},
}
HELMET_ITEMS = {
    "helmet_level1": {"armor": 20, "headshot_reduction": 0.3},
    "helmet_level2": {"armor": 40, "headshot_reduction": 0.4},
    "helmet_level3": {"armor": 60, "headshot_reduction": 0.5},
}

# ---------- حالة اللعبة ----------
players: Dict[str, dict] = {}
loot_items: List[dict] = []      # صناديق عتاد متناثرة
airdrops: List[dict] = []        # صناديق إمداد جوي
game_state = {
    "safe_zone_center": (0.0, 0.0),
    "safe_zone_radius": SAFE_ZONE_START_RADIUS,
    "zone_shrink_start": time.time(),
    "game_active": True,
}
leaderboard = []  # ترتيب اللاعبين حسب XP

# توليد نقاط عشوائية للهبوط
def random_spawn() -> Tuple[float, float]:
    return (random.uniform(-MAP_SIZE/2, MAP_SIZE/2), random.uniform(-MAP_SIZE/2, MAP_SIZE/2))

SPAWN_POINTS = [random_spawn() for _ in range(MAX_PLAYERS)]

# توليد عتاد عشوائي على الخريطة (أسلحة، ذخيرة، شفاء، دروع)
def generate_loot():
    global loot_items
    loot_items = []
    for _ in range(500):  # 500 قطعة متناثرة
        pos = (random.uniform(-MAP_SIZE/2, MAP_SIZE/2), random.uniform(-MAP_SIZE/2, MAP_SIZE/2))
        loot_type = random.choice(["weapon", "ammo", "heal", "armor", "helmet"])
        if loot_type == "weapon":
            weapon_name = random.choice(list(WEAPONS.keys()))
            loot_items.append({"type": "weapon", "name": weapon_name, "position": pos, "ammo": WEAPONS[weapon_name]["mag_size"]})
        elif loot_type == "ammo":
            ammo_type = random.choice(["5.56", "7.62", ".300", "12", "9mm"])
            loot_items.append({"type": "ammo", "ammo_type": ammo_type, "count": random.randint(30, 90), "position": pos})
        elif loot_type == "heal":
            heal_name = random.choice(list(HEAL_ITEMS.keys()))
            loot_items.append({"type": "heal", "name": heal_name, "position": pos})
        elif loot_type == "armor":
            armor_name = random.choice(list(ARMOR_ITEMS.keys()))
            loot_items.append({"type": "armor", "name": armor_name, "position": pos})
        else:
            helmet_name = random.choice(list(HELMET_ITEMS.keys()))
            loot_items.append({"type": "helmet", "name": helmet_name, "position": pos})

# إسقاط صندوق إمداد جوي عشوائي
async def spawn_airdrop():
    while True:
        await asyncio.sleep(random.randint(60, 120))  # كل 1-2 دقيقة
        if game_state["game_active"]:
            pos = (random.uniform(-MAP_SIZE/2 + 200, MAP_SIZE/2 - 200), random.uniform(-MAP_SIZE/2 + 200, MAP_SIZE/2 - 200))
            weapon = random.choice(list(WEAPONS.keys()))
            airdrops.append({"position": pos, "weapon": weapon, "ammo": 100, "armor": "vest_level3", "helmet": "helmet_level3"})
            await sio.emit("airdrop_spawned", {"position": pos})

# تحديث المنطقة الزرقاء
async def zone_updater():
    start_time = time.time()
    while game_state["game_active"]:
        await asyncio.sleep(1)
        elapsed = time.time() - start_time
        if elapsed >= ZONE_SHRINK_TIME:
            game_state["safe_zone_radius"] = SAFE_ZONE_END_RADIUS
        else:
            t = elapsed / ZONE_SHRINK_TIME
            game_state["safe_zone_radius"] = SAFE_ZONE_START_RADIUS * (1 - t) + SAFE_ZONE_END_RADIUS * t
        # إلحاق ضرر باللاعبين خارج المنطقة
        for sid, player in players.items():
            if player["alive"]:
                dist = math.hypot(player["position"][0] - game_state["safe_zone_center"][0], player["position"][1] - game_state["safe_zone_center"][1])
                if dist > game_state["safe_zone_radius"]:
                    player["health"] -= ZONE_DAMAGE_PER_SEC
                    if player["health"] <= 0:
                        player["alive"] = False
                        await sio.emit("player_killed", {"killer": "zone", "victim": sid})
        await sio.emit("zone_update", {"radius": game_state["safe_zone_radius"], "center": game_state["safe_zone_center"]})

# ---------- أحداث Socket.IO ----------
@sio.event
async def connect(sid, environ):
    print(f"Player {sid} connected")
    character = random.choice(list(CHARACTERS.keys()))
    spawn = random.choice(SPAWN_POINTS)
    players[sid] = {
        "id": sid,
        "name": f"Player_{random.randint(1000,9999)}",
        "character": character,
        "health": CHARACTERS[character]["health"],
        "max_health": CHARACTERS[character]["health"],
        "armor": 0,
        "armor_type": None,
        "helmet": 0,
        "helmet_type": None,
        "weapons": [{"name": "Pistol", "ammo": 15}],
        "current_weapon": "Pistol",
        "ammo": {"5.56": 0, "7.62": 0, ".300": 0, "12": 0, "9mm": 15},
        "money": 0,
        "gems": 0,
        "xp": 0,
        "level": 1,
        "position": spawn,
        "rotation": 0,
        "alive": True,
        "last_shot": 0,
    }
    await sio.emit("game_state", {
        "players": {pid: {k: v for k, v in p.items() if k != "ammo"} for pid, p in players.items()},
        "loot": loot_items,
        "airdrops": airdrops,
        "weapons": WEAPONS,
        "characters": CHARACTERS,
        "safe_zone": game_state["safe_zone_radius"],
    }, to=sid)
    await sio.emit("player_joined", {k: v for k, v in players[sid].items() if k != "ammo"}, skip_sid=sid)
    # تحديث لوحة المتصدرين
    update_leaderboard()

@sio.event
async def disconnect(sid):
    if sid in players:
        del players[sid]
        await sio.emit("player_left", sid)
        update_leaderboard()

@sio.event
async def player_move(sid, data):
    if sid in players and players[sid]["alive"]:
        players[sid]["position"] = (data["x"], data["z"])
        players[sid]["rotation"] = data["rotation"]
        await sio.emit("player_moved", {"id": sid, "x": data["x"], "z": data["z"], "rot": data["rotation"]})

@sio.event
async def player_shoot(sid, data):
    if sid not in players or not players[sid]["alive"]:
        return
    shooter = players[sid]
    weapon_name = shooter["current_weapon"]
    weapon = WEAPONS[weapon_name]
    if shooter["ammo"][weapon["ammo_type"]] <= 0:
        await sio.emit("reload_needed", to=sid)
        return
    # التحقق من سرعة الرمي (rate of fire)
    now = time.time()
    if now - shooter["last_shot"] < weapon["fire_rate"]:
        return
    shooter["last_shot"] = now
    shooter["ammo"][weapon["ammo_type"]] -= 1
    direction = data["direction"]  # (x, z) اتجاه الطلقة
    # كشف التصادم مع لاعبين آخرين
    for target_id, target in players.items():
        if target_id != sid and target["alive"]:
            dist = math.hypot(shooter["position"][0] - target["position"][0], shooter["position"][1] - target["position"][1])
            if dist < weapon["range"]:
                # حساب الضرر مع الدروع
                damage = weapon["damage"]
                if target["armor"] > 0:
                    damage *= (1 - ARMOR_ITEMS[target["armor_type"]]["damage_reduction"])
                if target["helmet"] > 0 and "headshot" in data and data["headshot"]:
                    damage *= (1 - HELMET_ITEMS[target["helmet_type"]]["headshot_reduction"])
                target["health"] -= damage
                await sio.emit("player_hit", {"id": target_id, "health": target["health"], "damage": damage, "shooter": sid})
                if target["health"] <= 0:
                    target["alive"] = False
                    # مكافأة القاتل
                    shooter["money"] += 100
                    shooter["gems"] += random.randint(1, 5)
                    shooter["xp"] += 50
                    # رفع المستوى
                    if shooter["xp"] >= shooter["level"] * 100:
                        shooter["level"] += 1
                    await sio.emit("player_killed", {"killer": sid, "victim": target_id, "killer_name": shooter["name"]})
                    update_leaderboard()
                break

@sio.event
async def pick_up_item(sid, data):
    if sid not in players:
        return
    player = players[sid]
    item_pos = (data["x"], data["z"])
    for i, item in enumerate(loot_items):
        if math.hypot(item["position"][0] - player["position"][0], item["position"][1] - player["position"][1]) < 3:
            if item["type"] == "weapon":
                player["weapons"].append({"name": item["name"], "ammo": item["ammo"]})
                player["ammo"][WEAPONS[item["name"]]["ammo_type"]] += item["ammo"]
            elif item["type"] == "ammo":
                player["ammo"][item["ammo_type"]] += item["count"]
            elif item["type"] == "heal":
                # تخزين عنصر الشفاء في المخزون (يمكن تنفيذ نظام مخزون لاحقاً)
                player["health"] = min(player["max_health"], player["health"] + HEAL_ITEMS[item["name"]]["heal"])
            elif item["type"] == "armor":
                if player["armor"] < ARMOR_ITEMS[item["name"]]["armor"]:
                    player["armor"] = ARMOR_ITEMS[item["name"]]["armor"]
                    player["armor_type"] = item["name"]
            elif item["type"] == "helmet":
                if player["helmet"] < HELMET_ITEMS[item["name"]]["armor"]:
                    player["helmet"] = HELMET_ITEMS[item["name"]]["armor"]
                    player["helmet_type"] = item["name"]
            del loot_items[i]
            await sio.emit("item_picked", {"item": item, "player": sid})
            break

@sio.event
async def switch_weapon(sid, data):
    if sid in players:
        weapon_name = data["weapon"]
        if any(w["name"] == weapon_name for w in players[sid]["weapons"]):
            players[sid]["current_weapon"] = weapon_name
            await sio.emit("weapon_switched", {"player": sid, "weapon": weapon_name})

def update_leaderboard():
    global leaderboard
    leaderboard = sorted([{"name": p["name"], "xp": p["xp"], "level": p["level"], "kills": 0} for p in players.values() if p["alive"]], key=lambda x: x["xp"], reverse=True)[:10]
    asyncio.create_task(sio.emit("leaderboard_update", leaderboard))

# ---------- تشغيل المهام الخلفية ----------
async def background_tasks():
    asyncio.create_task(zone_updater())
    asyncio.create_task(spawn_airdrop())
    generate_loot()  # توليد العتاد الأولي

# ---------- واجهة المستخدم (HTML + JS + Three.js) ----------
HTML_PAGE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>JOSEPH BATTLE ROYALE - القتال المطلق</title>
    <style>
        body { margin: 0; overflow: hidden; font-family: 'Cairo', 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; direction: rtl; }
        #hud {
            position: absolute;
            top: 20px;
            left: 20px;
            background: rgba(0,0,0,0.75);
            color: #0f0;
            padding: 10px 20px;
            border-radius: 10px;
            font-family: monospace;
            font-size: 14px;
            pointer-events: none;
            z-index: 10;
            backdrop-filter: blur(5px);
            border-left: 4px solid #0f0;
        }
        #health-bar-container {
            position: absolute;
            bottom: 30px;
            left: 20px;
            width: 300px;
            height: 24px;
            background: rgba(0,0,0,0.6);
            border: 2px solid #fff;
            border-radius: 12px;
            overflow: hidden;
            z-index: 10;
        }
        #health-fill {
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, #ff3333, #ff8888);
            transition: width 0.2s ease;
        }
        #weapon-info {
            position: absolute;
            bottom: 30px;
            right: 20px;
            background: rgba(0,0,0,0.7);
            color: #ffaa44;
            padding: 8px 16px;
            border-radius: 8px;
            font-family: monospace;
            font-size: 18px;
            font-weight: bold;
            direction: ltr;
            text-align: left;
            border-right: 3px solid #ffaa44;
        }
        #ammo-info {
            font-size: 14px;
            color: #ccc;
        }
        #minimap {
            position: absolute;
            bottom: 20px;
            right: 20px;
            width: 200px;
            height: 200px;
            background: rgba(0,0,0,0.5);
            border: 2px solid #0f0;
            border-radius: 12px;
            z-index: 10;
        }
        canvas.minimap-canvas {
            width: 100%;
            height: 100%;
            border-radius: 10px;
        }
        #leaderboard {
            position: absolute;
            top: 20px;
            right: 20px;
            background: rgba(0,0,0,0.75);
            color: white;
            padding: 10px;
            border-radius: 10px;
            font-size: 12px;
            font-family: monospace;
            width: 200px;
            backdrop-filter: blur(4px);
            border: 1px solid gold;
            pointer-events: none;
        }
        #leaderboard h4 { margin: 0 0 5px 0; text-align: center; color: gold; }
        #leaderboard-list { list-style: none; padding: 0; margin: 0; }
        #leaderboard-list li { display: flex; justify-content: space-between; margin-bottom: 4px; }
        #controls-info {
            position: absolute;
            bottom: 10px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(0,0,0,0.5);
            color: #ccc;
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 12px;
            white-space: nowrap;
            direction: ltr;
            font-family: monospace;
        }
        .hit-effect {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: radial-gradient(circle, rgba(255,0,0,0.3), transparent);
            pointer-events: none;
            z-index: 20;
            animation: hitFade 0.3s ease-out;
        }
        @keyframes hitFade {
            from { opacity: 1; }
            to { opacity: 0; }
        }
    </style>
</head>
<body>
    <div id="hud">
        🎮 JOSEPH BATTLE ROYALE | لاعبين: <span id="player-count">0</span>/100
    </div>
    <div id="health-bar-container">
        <div id="health-fill"></div>
    </div>
    <div id="weapon-info">
        🔫 <span id="weapon-name">Pistol</span><br>
        <span id="ammo-info">15/∞</span>
    </div>
    <div id="minimap">
        <canvas id="minimapCanvas" class="minimap-canvas" width="200" height="200"></canvas>
    </div>
    <div id="leaderboard">
        <h4>🏆 أفضل اللاعبين</h4>
        <ul id="leaderboard-list"></ul>
    </div>
    <div id="controls-info">
        🖱️ الماوس: تصويب | 🔫 زر الفأرة الأيسر: إطلاق النار | WASD: تحرك | 1-5: تبديل السلاح
    </div>
    <div id="hitEffect" class="hit-effect" style="display: none;"></div>

    <script type="importmap">
        {
            "imports": {
                "three": "https://unpkg.com/three@0.128.0/build/three.module.js",
                "socket.io-client": "https://cdn.socket.io/4.7.4/socket.io.esm.min.js"
            }
        }
    </script>
    <script type="module">
        import * as THREE from 'three';
        import { io } from 'socket.io-client';

        // --- اتصال بالخادم ---
        const socket = io();

        // --- إعداد المشهد ثلاثي الأبعاد ---
        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0x87CEEB);
        scene.fog = new THREE.FogExp2(0x87CEEB, 0.0005);

        const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 2000);
        camera.position.y = 1.8;

        const renderer = new THREE.WebGLRenderer({ antialias: true });
        renderer.setSize(window.innerWidth, window.innerHeight);
        renderer.shadowMap.enabled = true;
        document.body.appendChild(renderer.domElement);

        // --- إضاءة واقعية ---
        const ambientLight = new THREE.AmbientLight(0x404060);
        scene.add(ambientLight);
        const dirLight = new THREE.DirectionalLight(0xffffff, 1);
        dirLight.position.set(50, 100, 50);
        dirLight.castShadow = true;
        dirLight.receiveShadow = true;
        scene.add(dirLight);
        const fillLight = new THREE.PointLight(0x4466cc, 0.5);
        fillLight.position.set(-30, 50, -30);
        scene.add(fillLight);

        // --- أرضية التضاريس (خريطة كبيرة) ---
        const groundGeometry = new THREE.PlaneGeometry(2000, 2000, 256, 256);
        const groundMaterial = new THREE.MeshStandardMaterial({ color: 0x4a7a4a, roughness: 0.8, metalness: 0.1 });
        const ground = new THREE.Mesh(groundGeometry, groundMaterial);
        ground.rotation.x = -Math.PI / 2;
        ground.position.y = -0.5;
        ground.receiveShadow = true;
        scene.add(ground);

        // شبكة إرشادية
        const gridHelper = new THREE.GridHelper(2000, 50, 0x88aaff, 0x335588);
        gridHelper.position.y = -0.4;
        scene.add(gridHelper);

        // أشجار ومباني بسيطة (زخرفة)
        const treeTrunk = new THREE.CylinderGeometry(0.6, 0.8, 1.5, 6);
        const treeMat = new THREE.MeshStandardMaterial({ color: 0x8B5A2B });
        const treeTop = new THREE.ConeGeometry(1.0, 1.8, 8);
        const leafMat = new THREE.MeshStandardMaterial({ color: 0x3a9e3a });
        for (let i = 0; i < 300; i++) {
            const x = (Math.random() - 0.5) * 1800;
            const z = (Math.random() - 0.5) * 1800;
            const trunk = new THREE.Mesh(treeTrunk, treeMat);
            trunk.position.set(x, -0.2, z);
            trunk.castShadow = true;
            const foliage = new THREE.Mesh(treeTop, leafMat);
            foliage.position.set(x, 0.6, z);
            foliage.castShadow = true;
            scene.add(trunk);
            scene.add(foliage);
        }

        // --- تمثيل اللاعبين (نماذج بشرية بسيطة) ---
        const playersMap = new Map();
        let myId = null;
        let myHealth = 100;
        let myWeapon = "Pistol";
        let myAmmo = 15;
        let myCharacter = "soldier";

        function createPlayerModel(color, isLocal = false) {
            const group = new THREE.Group();
            const bodyGeo = new THREE.BoxGeometry(0.7, 1.2, 0.7);
            const bodyMat = new THREE.MeshStandardMaterial({ color: color, metalness: 0.2 });
            const body = new THREE.Mesh(bodyGeo, bodyMat);
            body.position.y = 0.6;
            body.castShadow = true;
            group.add(body);
            const headGeo = new THREE.SphereGeometry(0.45, 16, 16);
            const headMat = new THREE.MeshStandardMaterial({ color: color });
            const head = new THREE.Mesh(headGeo, headMat);
            head.position.y = 1.2;
            head.castShadow = true;
            group.add(head);
            if (!isLocal) {
                // اسم اللاعب
                const canvas = document.createElement('canvas');
                canvas.width = 256;
                canvas.height = 128;
                const ctx = canvas.getContext('2d');
                ctx.fillStyle = 'rgba(0,0,0,0.6)';
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                ctx.font = 'Bold 24px Cairo';
                ctx.fillStyle = 'white';
                ctx.textAlign = 'center';
                ctx.fillText('لاعب', canvas.width/2, canvas.height/2);
                const texture = new THREE.CanvasTexture(canvas);
                const nameMat = new THREE.SpriteMaterial({ map: texture });
                const nameSprite = new THREE.Sprite(nameMat);
                nameSprite.scale.set(1.2, 0.6, 1);
                nameSprite.position.y = 1.8;
                group.add(nameSprite);
            }
            return group;
        }

        // --- التحكم بالحركة والتصويب ---
        const keyState = { w: false, s: false, a: false, d: false };
        let yaw = -Math.PI / 4;
        let pitch = 0;
        let moveSpeed = 5.0;
        let lastShoot = 0;
        const shootDelay = 200; // مللي ثانية

        window.addEventListener('keydown', (e) => {
            switch(e.code) {
                case 'KeyW': keyState.w = true; break;
                case 'KeyS': keyState.s = true; break;
                case 'KeyA': keyState.a = true; break;
                case 'KeyD': keyState.d = true; break;
                case 'Digit1': socket.emit('switch_weapon', { weapon: 'Pistol' }); break;
                case 'Digit2': socket.emit('switch_weapon', { weapon: 'M416' }); break;
                case 'Digit3': socket.emit('switch_weapon', { weapon: 'AKM' }); break;
                case 'Digit4': socket.emit('switch_weapon', { weapon: 'AWM' }); break;
                case 'Digit5': socket.emit('switch_weapon', { weapon: 'Shotgun' }); break;
            }
        });
        window.addEventListener('keyup', (e) => {
            switch(e.code) {
                case 'KeyW': keyState.w = false; break;
                case 'KeyS': keyState.s = false; break;
                case 'KeyA': keyState.a = false; break;
                case 'KeyD': keyState.d = false; break;
            }
        });

        renderer.domElement.addEventListener('click', () => renderer.domElement.requestPointerLock());
        document.addEventListener('pointerlockchange', lockChange);
        function lockChange() {
            if (document.pointerLockElement === renderer.domElement) {
                document.addEventListener('mousemove', onMouseMove);
            } else {
                document.removeEventListener('mousemove', onMouseMove);
            }
        }
        function onMouseMove(e) {
            yaw -= e.movementX * 0.002;
            pitch -= e.movementY * 0.002;
            pitch = Math.max(-Math.PI/2.2, Math.min(Math.PI/2.2, pitch));
            camera.rotation.order = 'YXZ';
            camera.rotation.y = yaw;
            camera.rotation.x = pitch;
        }

        window.addEventListener('mousedown', (e) => {
            if (e.button === 0) {
                const now = Date.now();
                if (now - lastShoot >= shootDelay) {
                    lastShoot = now;
                    const direction = new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion);
                    socket.emit('player_shoot', { direction: { x: direction.x, z: direction.z }, headshot: pitch < -0.5 });
                }
            }
        });

        // --- تحديث الحركة وإرسالها للخادم ---
        let lastSentPos = { x: 0, z: 0, rot: 0 };
        function updateMovement(deltaTime) {
            const move = new THREE.Vector3();
            if (keyState.w) move.z -= 1;
            if (keyState.s) move.z += 1;
            if (keyState.a) move.x -= 1;
            if (keyState.d) move.x += 1;
            move.normalize();
            const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion);
            const right = new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion);
            let delta = new THREE.Vector3();
            delta.addScaledVector(forward, move.z);
            delta.addScaledVector(right, move.x);
            delta.y = 0;
            delta.multiplyScalar(moveSpeed * deltaTime);
            let newX = camera.position.x + delta.x;
            let newZ = camera.position.z + delta.z;
            const limit = 980;
            newX = Math.min(limit, Math.max(-limit, newX));
            newZ = Math.min(limit, Math.max(-limit, newZ));
            camera.position.x = newX;
            camera.position.z = newZ;
            if (Math.abs(newX - lastSentPos.x) > 0.5 || Math.abs(newZ - lastSentPos.z) > 0.5 || Math.abs(yaw - lastSentPos.rot) > 0.05) {
                socket.emit('player_move', { x: newX, z: newZ, rotation: yaw });
                lastSentPos = { x: newX, z: newZ, rot: yaw };
            }
        }

        // --- عرض الخريطة المصغرة (Canvas 2D) ---
        const minimapCanvas = document.getElementById('minimapCanvas');
        const minimapCtx = minimapCanvas.getContext('2d');
        function updateMinimap() {
            minimapCtx.fillStyle = '#1a3a1a';
            minimapCtx.fillRect(0, 0, 200, 200);
            // رسم اللاعبين
            for (let [id, player] of playersMap.entries()) {
                const x = (player.position.x / 2000 + 0.5) * 200;
                const z = (player.position.z / 2000 + 0.5) * 200;
                minimapCtx.fillStyle = id === myId ? '#0f0' : '#f00';
                minimapCtx.beginPath();
                minimapCtx.arc(x, z, 3, 0, 2*Math.PI);
                minimapCtx.fill();
            }
        }

        // --- أحداث Socket.IO ---
        socket.on('connect', () => console.log('Connected'));
        socket.on('game_state', (data) => {
            myId = socket.id;
            document.getElementById('player-count').innerText = Object.keys(data.players).length;
            for (const [id, p] of Object.entries(data.players)) {
                if (id !== myId && !playersMap.has(id)) {
                    const model = createPlayerModel(p.character === 'tank' ? '#ff6666' : (p.character === 'scout' ? '#88ff88' : '#33aaff'), false);
                    model.position.set(p.position[0], 0, p.position[1]);
                    model.userData = { id, name: p.name };
                    scene.add(model);
                    playersMap.set(id, model);
                }
            }
            // تحديث السلاح والشخصية للاعب المحلي
            if (data.players[myId]) {
                myCharacter = data.players[myId].character;
                moveSpeed = data.characters[myCharacter].speed;
            }
        });
        socket.on('player_joined', (p) => {
            if (p.id !== myId && !playersMap.has(p.id)) {
                const model = createPlayerModel(p.character === 'tank' ? '#ff6666' : (p.character === 'scout' ? '#88ff88' : '#33aaff'), false);
                model.position.set(p.position[0], 0, p.position[1]);
                scene.add(model);
                playersMap.set(p.id, model);
                document.getElementById('player-count').innerText = playersMap.size + 1;
            }
        });
        socket.on('player_left', (id) => {
            if (playersMap.has(id)) {
                scene.remove(playersMap.get(id));
                playersMap.delete(id);
                document.getElementById('player-count').innerText = playersMap.size + 1;
            }
        });
        socket.on('player_moved', (data) => {
            if (playersMap.has(data.id)) {
                playersMap.get(data.id).position.set(data.x, 0, data.z);
                playersMap.get(data.id).rotation.y = data.rot;
            }
        });
        socket.on('player_hit', (data) => {
            if (data.id === myId) {
                myHealth = data.health;
                const percent = Math.max(0, (myHealth / 100) * 100);
                document.getElementById('health-fill').style.width = percent + '%';
                document.getElementById('hitEffect').style.display = 'block';
                setTimeout(() => document.getElementById('hitEffect').style.display = 'none', 300);
            }
        });
        socket.on('player_killed', (data) => {
            if (data.victim === myId) {
                alert("لقد تم القضاء عليك!");
                location.reload();
            } else if (playersMap.has(data.victim)) {
                scene.remove(playersMap.get(data.victim));
                playersMap.delete(data.victim);
            }
        });
        socket.on('weapon_switched', (data) => {
            if (data.player === myId) {
                myWeapon = data.weapon;
                document.getElementById('weapon-name').innerText = myWeapon;
            }
        });
        socket.on('leaderboard_update', (list) => {
            const ul = document.getElementById('leaderboard-list');
            ul.innerHTML = '';
            list.forEach(p => {
                const li = document.createElement('li');
                li.innerHTML = `<span>${p.name}</span><span>${p.xp} XP</span>`;
                ul.appendChild(li);
            });
        });
        socket.on('zone_update', (data) => {
            // يمكن إظهار تأثير المنطقة الزرقاء (تغيير لون السماء مثلاً)
        });
        socket.on('airdrop_spawned', (data) => {
            // إضافة صندوق إمداد على الخريطة (يمكن رسمه لاحقاً)
        });

        // --- النموذج المحلي للاعب (يتبع الكاميرا) ---
        const localPlayerModel = createPlayerModel('#33aaff', true);
        scene.add(localPlayerModel);
        window.localPlayerModel = localPlayerModel;

        // --- حلقة اللعبة ---
        let lastTime = performance.now();
        function animate() {
            const now = performance.now();
            let delta = Math.min(0.033, (now - lastTime) / 1000);
            lastTime = now;
            updateMovement(delta);
            if (localPlayerModel) {
                localPlayerModel.position.copy(camera.position);
                localPlayerModel.position.y = 0;
                localPlayerModel.rotation.y = yaw;
            }
            updateMinimap();
            renderer.render(scene, camera);
            requestAnimationFrame(animate);
        }
        animate();
    </script>
</body>
</html>
"""

# ---------- تشغيل الخادم ----------
@app.get("/")
async def get_game():
    return HTMLResponse(HTML_PAGE)

@app.on_event("startup")
async def startup():
    asyncio.create_task(background_tasks())

if __name__ == "__main__":
    # إنشاء مجلد static فارغ لتجنب خطأ mounting
    os.makedirs("static", exist_ok=True)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
