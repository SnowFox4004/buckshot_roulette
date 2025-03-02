from flask import Flask, render_template, request, redirect, url_for
from flask_socketio import SocketIO, emit, join_room, leave_room
import random
import uuid
import time

app = Flask(__name__)
app.config["SECRET_KEY"] = "your-secret-key"
socketio = SocketIO(app, cors_allowed_origins="*")

# 游戏房间数据
rooms = {}
# 玩家数据
players = {}

# 道具类型
ITEMS = ["香烟", "放大镜", "手铐", "锯子", "啤酒"]
# 表情符号列表
EMOJIS = ["😀", "😎", "🤠", "👽", "👻", "🤖", "🦊", "🐱"]


class Room:
    def __init__(self, room_id, owner_id):
        self.id = room_id
        self.owner_id = owner_id
        self.players = []  # 存储玩家ID
        self.status = "waiting"  # waiting, playing
        self.game = None

    def add_player(self, player_id):
        if len(self.players) < 4 and player_id not in self.players:
            self.players.append(player_id)
            return True
        return False

    def remove_player(self, player_id):
        if player_id in self.players:
            self.players.remove(player_id)
            # 如果房主离开，转移房主权限
            if player_id == self.owner_id and self.players:
                self.owner_id = self.players[0]
            return True
        return False

    def start_game(self):
        if len(self.players) > 0:
            self.status = "playing"
            self.game = Game(self.players)
            return True
        return False

    def to_dict(self):
        return {
            "id": self.id,
            "owner_id": self.owner_id,
            "players": [players[p].to_dict() for p in self.players],
            "status": self.status,
        }


class Player:
    def __init__(self, id, name, emoji):
        self.id = id
        self.name = name
        self.emoji = emoji
        self.room_id = None
        self.items = []
        self.health = 4

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "emoji": self.emoji,
            "room_id": self.room_id,
            "items": self.items,
            "health": self.health,
        }


class Game:
    def __init__(self, player_ids):
        self.players = player_ids
        self.current_player_index = 0
        self.dealer_index = 0  # 最后一个玩家默认为庄家
        self.bullets = []
        self.remaining_bullets = []
        self.items_deck = []
        self.initialize_game()

        self.had_handcuff = False
        self.had_saw = False

        self.last_shot_bullet = 0

    def initialize_game(self):
        # 为每个玩家重置状态
        for p_id in self.players:
            players[p_id].health = 4
            players[p_id].items = []

        # 初始化子弹和道具
        self.load_gun()
        self.initialize_items()
        self.deal_items()

    def load_gun(self):
        # 1/3比例的致命子弹，2/3比例的空子弹
        total_bullets = random.randint(4, 8)
        live_bullets = random.randint(1, total_bullets)
        blank_bullets = total_bullets - live_bullets

        self.bullets = ["live"] * live_bullets + ["blank"] * blank_bullets
        random.shuffle(self.bullets)
        self.remaining_bullets = self.bullets.copy()

    def initialize_items(self):
        # 创建道具牌组
        self.items_deck = ITEMS * 3  # 每种道具3张
        random.shuffle(self.items_deck)

    def deal_items(self):
        # 每个玩家发2个道具
        for p_id in self.players:
            for _ in range(random.randint(2, 4)):
                if self.items_deck:
                    players[p_id].items.append(random.choice(self.items_deck))

    def next_turn(self):
        self.current_player_index = (self.current_player_index + 1) % len(self.players)
        if self.had_handcuff:
            self.had_handcuff = False
            # print("有玩家的回合被跳过了")
            self.next_turn()

        # 如果枪里没有子弹了，重新装填
        if not self.remaining_bullets:
            self.load_gun()
            self.deal_items()

    def handcuffs_reg(self):
        self.had_handcuff = True

    def saw_reg(self):
        self.had_saw = True

    def use_item(self, player_id, item_index):
        player = players[player_id]
        if 0 <= item_index < len(player.items):
            item = player.items.pop(item_index)
            result = ""
            # 处理各种道具效果
            if item == "香烟":
                player.health = min(player.health + 1, 4)
                result = f"{player.name} 使用了香烟，恢复了1点生命值"

            elif item == "放大镜":
                if self.remaining_bullets:
                    result = f"{player.name} 使用了放大镜，查看到下一颗子弹是 {'致命的' if self.remaining_bullets[0] == 'live' else '空的'}"
                else:
                    result = f"{player.name} 使用了放大镜，但枪里没有子弹了"

            elif item == "手铐":
                # self.next_turn()  # 直接跳过下一个玩家的回合
                self.handcuffs_reg()
                result = f"{player.name} 使用了手铐，跳过了下一个玩家的回合"

            elif item == "啤酒":
                if self.remaining_bullets:
                    # 移除下一颗子弹
                    removed_bullet = self.remaining_bullets.pop(0)
                    result = f"{player.name} 使用了啤酒，移除了一颗{'致命' if removed_bullet == 'live' else '空'}子弹"
                else:
                    result = f"{player.name} 使用了啤酒，但枪里没有子弹了"

            elif item == "锯子":
                # 伤害翻倍
                self.saw_reg()
                result = f"{player.name} 使用了锯子，下一次的射击伤害翻倍"

            # result = f"{player.name} 使用了未知道具"
            if not self.remaining_bullets:
                self.load_gun()
                self.deal_items()

            return result

    def pull_trigger(self, target_id, player_id):
        print(f"{player_id} 开枪射击 {target_id}")

        if not self.remaining_bullets:
            return "枪里没有子弹了", False, True  # 添加布尔值返回

        bullet = self.remaining_bullets.pop(0)
        target = players[target_id]
        game_ended = False  # 新增结束标志
        if_next = True

        if bullet == "live":
            target.health -= 1
            result = f"砰！{target.name} 被击中，生命值减少1点"
            if self.had_saw:
                target.health -= 1
                self.had_saw = False
                result = f"砰！{target.name} 被锯断的枪击中，生命值减少 2 点"

            if target.health <= 0:
                result += f"，{target.name} 已经死亡"
                if target_id in self.players:
                    self.players.remove(target_id)

            # 添加立即结束判断
            if len(self.players) == 1:
                winner = players[self.players[0]]
                result += f"，游戏结束！{winner.name} 获胜！"
                game_ended = True  # 设置结束标志

            # 返回元组
        else:
            if target_id == player_id:
                if_next = False
            result = "咔嚓， 空枪！"
        self.had_saw = False
        if not self.remaining_bullets:
            self.load_gun()
            self.deal_items()

        return result, game_ended, if_next

    def get_game_state(self):
        return {
            "players": [players[p].to_dict() for p in self.players],
            "current_player": self.players[self.current_player_index],
            "dealer": self.players[self.dealer_index],
            "remaining_bullets": len(self.remaining_bullets),
        }


# 路由
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/create_room")
def create_room():
    name = request.args.get("name")
    room_id = str(uuid.uuid4())[:4]  # 创建一个唯一的房间ID
    return redirect(url_for(f"room", room_id=room_id, name=name))


@app.route("/room/<room_id>")
def room(room_id):
    return render_template("room.html", room_id=room_id)


# Socket.IO 事件
@socketio.on("connect")
def on_connect():
    print("Client connected:", request.sid)


@socketio.on("disconnect")
def on_disconnect():
    print("Client disconnected:", request.sid)
    # 查找并从房间中移除玩家
    for player_id, player in list(players.items()):
        if player.id == request.sid:
            if player.room_id and player.room_id in rooms:
                room = rooms[player.room_id]
                room.remove_player(player_id)

                # 通知房间内其他玩家
                emit("player_left", player.to_dict(), to=player.room_id)

                # 如果房间空了，删除房间
                if not room.players:
                    del rooms[player.room_id]
                # 否则更新房间信息
                else:
                    emit("room_updated", room.to_dict(), to=player.room_id)

            del players[player_id]
            break


@socketio.on("join_room")
def on_join_room(data):
    room_id = data.get("room_id")
    player_name = data.get("name", f"玩家_{request.sid[:4]}")

    # 分配一个随机表情
    emoji = random.choice(EMOJIS)

    # 创建玩家
    player = Player(request.sid, player_name, emoji)
    players[request.sid] = player

    # 如果房间不存在，创建房间
    if room_id not in rooms:
        rooms[room_id] = Room(room_id, request.sid)

    room = rooms[room_id]

    # 尝试加入房间
    if room.add_player(request.sid):
        player.room_id = room_id
        join_room(room_id)

        # 向客户端发送玩家信息
        emit("joined_room", {"player": player.to_dict(), "room": room.to_dict()})

        # 通知房间内其他玩家
        emit("player_joined", player.to_dict(), to=room_id, include_self=False)
    else:
        emit("error", {"message": "房间已满或您已在房间内"})


@socketio.on("leave_room")
def on_leave_room(data):
    room_id = data.get("room_id")
    if room_id in rooms:
        room = rooms[room_id]

        if request.sid in players:
            player = players[request.sid]

            if room.remove_player(request.sid):
                leave_room(room_id)
                player.room_id = None

                # 通知客户端
                emit("left_room", {"success": True})

                # 通知房间内其他玩家
                emit("player_left", player.to_dict(), to=room_id)

                # 如果房间空了，删除房间
                if not room.players:
                    del rooms[room_id]
                else:
                    # 更新房间信息
                    emit("room_updated", room.to_dict(), to=room_id)


@socketio.on("start_game")
def on_start_game(data):
    room_id = data.get("room_id")
    if room_id in rooms:
        room = rooms[room_id]

        # 只有房主可以开始游戏
        if request.sid == room.owner_id:
            if room.start_game():
                # 通知所有玩家游戏开始
                emit("game_started", room.game.get_game_state(), to=room_id)
            else:
                emit("error", {"message": "无法开始游戏，请确保至少有一名玩家"})
        else:
            emit("error", {"message": "只有房主可以开始游戏"})


@socketio.on("use_item")
def on_use_item(data):
    room_id = data.get("room_id")
    item_index = data.get("item_index")

    if room_id in rooms:
        room = rooms[room_id]

        if room.status == "playing" and request.sid in players:
            game = room.game

            # 检查是否轮到该玩家
            if request.sid == game.players[game.current_player_index]:
                result = game.use_item(request.sid, item_index)

                # 更新游戏状态并通知所有玩家
                emit(
                    "game_updated",
                    {
                        "action": "use_item",
                        "result": result,
                        "game_state": game.get_game_state(),
                    },
                    to=room_id,
                )
            else:
                emit("error", {"message": "现在不是您的回合"})


@socketio.on("pull_trigger")
def on_pull_trigger(data):
    room_id = data.get("room_id")
    target_id = data.get("target_id")

    if room_id in rooms:
        room = rooms[room_id]

        if room.status == "playing" and request.sid in players:
            game = room.game

            if request.sid == game.players[game.current_player_index]:
                result, game_ended, if_next = game.pull_trigger(
                    target_id, request.sid
                )  # 接收新返回值

                if game_ended:  # 直接处理游戏结束
                    room.status = "waiting"
                    room.game = None
                    emit(
                        "game_ended",
                        {
                            "winner": players[game.players[0]].to_dict(),
                            "result": result,
                            "room": room.to_dict(),
                        },
                        to=room_id,
                    )
                    return  # 提前返回，避免后续操作

                if if_next:
                    game.next_turn()

                emit(
                    "game_updated",
                    {
                        "action": "pull_trigger",
                        "result": result,
                        "game_state": game.get_game_state(),
                    },
                    to=room_id,
                )


if __name__ == "__main__":
    socketio.run(app, debug=True)
