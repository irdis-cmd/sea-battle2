import asyncio
import random
import json
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

# --- НАСТРОЙКИ ---
TOKEN = "8463038644:AAE3DAFzN2Edrv3VfoDqAx0YVhLQVEGAZaM"
SIZE = 7
SHIPS_CONFIG = {3: 1, 2: 2, 1: 3} # Корабли: 1 трехпалубный, 2 двухпалубных, 3 однопалубных
STATS_FILE = "sea_battle_stats.json"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Глобальные хранилища
games = {}         # game_id: {данные игры}
user_to_game = {}  # user_id: game_id
waiting_player = None # ID игрока в очереди

# --- ЛОГИКА СТАТИСТИКИ ---
def save_win(user_id, name):
    stats = {}
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                stats = json.load(f)
        except: stats = {}
    
    uid = str(user_id)
    if uid not in stats:
        stats[uid] = {"name": name, "wins": 0}
    stats[uid]["wins"] += 1
    
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=4)

# --- ГЕНЕРАЦИЯ ПОЛЯ ---
def create_board():
    board = [[0 for _ in range(SIZE)] for _ in range(SIZE)]
    ships_coords = []
    for size, count in sorted(SHIPS_CONFIG.items(), reverse=True):
        for _ in range(count):
            placed = False
            while not placed:
                orient = random.choice(['h', 'v'])
                x = random.randint(0, SIZE - (size if orient == 'h' else 1))
                y = random.randint(0, SIZE - (1 if orient == 'h' else size))
                new_ship = [(x+i, y) if orient == 'h' else (x, y+i) for i in range(size)]
                
                # Проверка окружения (дистанция 1 клетка)
                can_place = True
                for sx, sy in new_ship:
                    for dx in range(-1, 2):
                        for dy in range(-1, 2):
                            nx, ny = sx + dx, sy + dy
                            if 0 <= nx < SIZE and 0 <= ny < SIZE:
                                if board[ny][nx] != 0: can_place = False
                
                if can_place:
                    for sx, sy in new_ship: board[sy][sx] = 1
                    ships_coords.append(new_ship)
                    placed = True
    return board, ships_coords

# --- ОТРИСОВКА ПОЛЯ ---
def get_game_kb(game_id, viewer_id):
    game = games[game_id]
    # Стреляем по полю оппонента
    enemy_id = game['p2'] if viewer_id == game['p1'] else game['p1']
    enemy_board = game['boards'][enemy_id]
    enemy_ships = game['ships'][enemy_id]
    hits = game['hits'][enemy_id]
    
    builder = InlineKeyboardBuilder()
    for y in range(SIZE):
        for x in range(SIZE):
            coord = (x, y)
            text = "🌊"
            if coord in hits:
                if enemy_board[y][x] == 1:
                    ship = next(s for s in enemy_ships if coord in s)
                    text = "💀" if all(c in hits for c in ship) else "🔥"
                else:
                    text = "💧"
            builder.button(text=text, callback_data=f"fire_{x}_{y}")
    builder.adjust(SIZE)
    return builder.as_markup()

# --- ОБРАБОТКА КОМАНД ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("⚓️ Добро пожаловать в Морской Бой!\n\n/play — Найти случайного игрока\n/stats — Таблица лидеров\n/cancel — Отменить поиск")

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if not os.path.exists(STATS_FILE):
        return await message.answer("Статистика пока пуста.")
    with open(STATS_FILE, "r", encoding="utf-8") as f:
        stats = json.load(f)
    top = sorted(stats.values(), key=lambda x: x['wins'], reverse=True)[:10]
    text = "🏆 ТОП АДМИРАЛОВ:\n" + "\n".join([f"{i+1}. {p['name']}: {p['wins']} побед" for i, p in enumerate(top)])
    await message.answer(text)

@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message):
    global waiting_player
    if waiting_player == message.from_user.id:
        waiting_player = None
        await message.answer("Поиск отменен. ⚓️")
    else:
        await message.answer("Вы не находитесь в очереди.")

@dp.message(Command("play"))
async def cmd_play(message: types.Message):
    global waiting_player
    uid = message.from_user.id
    if uid in user_to_game:
        return await message.answer("Вы уже в игре!")
    
    if waiting_player is None:
        waiting_player = uid
        await message.answer("🔎 Ищем случайного противника...")
    elif waiting_player == uid:
        await message.answer("Вы уже ищете игру.")
    else:
        p1, p2 = waiting_player, uid
        waiting_player = None
        game_id = f"g_{p1}_{p2}"
        
        b1, s1 = create_board()
        b2, s2 = create_board()
        
        games[game_id] = {
            'p1': p1, 'p2': p2,
            'names': {p1: (await bot.get_chat(p1)).first_name, p2: message.from_user.first_name},
            'turn': p1,
            'boards': {p1: b1, p2: b2},
            'ships': {p1: s1, p2: s2},
            'hits': {p1: set(), p2: set()},
            'ships_left': {p1: len(s1), p2: len(s2)},
            'msgs': {} # Для хранения ID сообщений (чтобы обновлять у обоих)
        }
        user_to_game[p1] = user_to_game[p2] = game_id
        
        m1 = await bot.send_message(p1, f"🎮 Игра найдена! Твой ход против {games[game_id]['names'][p2]}", reply_markup=get_game_kb(game_id, p1))
        m2 = await bot.send_message(p2, f"🎮 Игра найдена! Ход игрока {games[game_id]['names'][p1]}", reply_markup=get_game_kb(game_id, p2))
        games[game_id]['msgs'] = {p1: m1.message_id, p2: m2.message_id}

# --- ЛОГИКА ВЫСТРЕЛА ---
@dp.callback_query(F.data.startswith("fire_"))
async def handle_fire(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if uid not in user_to_game:
        return await callback.answer("Игра завершена или не найдена.")
    
    gid = user_to_game[uid]
    game = games[gid]
    
    if game['turn'] != uid:
        return await callback.answer("Сейчас ход противника! ⏳", show_alert=True)

    x, y = map(int, callback.data.split("_")[1:])
    enemy_id = game['p2'] if uid == game['p1'] else game['p1']
    
    if (x, y) in game['hits'][enemy_id]:
        return await callback.answer("Сюда уже стреляли!")

    game['hits'][enemy_id].add((x, y))
    hit = (game['boards'][enemy_id][y][x] == 1)
    
    if hit:
        ship = next(s for s in game['ships'][enemy_id] if (x, y) in s)
        if all(c in game['hits'][enemy_id] for c in ship):
            game['ships_left'][enemy_id] -= 1
            res_msg = "Потопил! 🔥💀"
        else:
            res_msg = "Попал! 💥"
    else:
        game['turn'] = enemy_id
        res_msg = "Мимо... 💧"

    await callback.answer(res_msg)

    # Проверка победы
    if game['ships_left'][enemy_id] == 0:
        save_win(uid, game['names'][uid])
        await bot.send_message(uid, "🏆 ПОБЕДА! Вы разгромили флот врага!")
        await bot.send_message(enemy_id, "💀 ПОРАЖЕНИЕ! Ваш флот потоплен.")
        del user_to_game[game['p1']], user_to_game[game['p2']], games[gid]
        return

    # Обновление экранов у обоих игроков
    for p_id in [game['p1'], game['p2']]:
        turn_status = "🔴 Твой ход!" if game['turn'] == p_id else "⚪️ Ход противника..."
        enemy_current = game['p2'] if p_id == game['p1'] else game['p1']
        ships_val = game['ships_left'][enemy_current]
        
        try:
            await bot.edit_message_text(
                chat_id=p_id,
                message_id=game['msgs'][p_id],
                text=f"⚓️ {turn_status}\nОсталось кораблей врага: {ships_val}",
                reply_markup=get_game_kb(gid, p_id)
            )
        except: pass

async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
