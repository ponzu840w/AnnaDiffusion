# -*- coding: utf-8 -*-

# 絵を描いてくれる Discord bot

# Copyright 2024 @ponzu840w
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from discord.ext import commands, tasks
from glob import glob
import asyncio
import discord
import hashlib
import os
import random
import re
import subprocess
import sys

# 設定項目
DISCORD_TOKEN   = os.environ.get('DISCORD_TOKEN_ANNA')
MODEL_PATH      = "./models/7thAB_anna_hv8_r0-4.safetensors"
VAE_PATH        = "./vae/kl-f8-anime2.ckpt"
OUT_DIR         = "./outputs"
CH_NAME         = "生成aiの遊び場"
GAMES           = ['スチームパンクキッチンペーパー女遊びクイズ王',
                   'Il|タイピング',
                   '単位を落とすな！',
                   'カーソルどこ？',
                   'GPAじゃんけん',
                   'ﾄﾗｲﾌﾞﾗｰﾒﾝｱｼﾞｺｲﾒﾆﾝﾆｸｱﾌﾞﾗﾏｼﾏｼ'
                  ]

# 初期化
gaming_reg = False   # さっきまでゲームしてたか？
job_running = False
initializing = True
progress = 0

print("Python version")
print(sys.version)
print("Version info.")
print(sys.version_info)

# Discord bot 立ち上げ
intents=discord.Intents.default()
intents.message_content=True
bot=commands.Bot(command_prefix='!', intents=intents)

tasks_queue = asyncio.Queue()  # ジョブキューの作成

# 注文をハッシュで表示する（ユーザ側が識別しやすいようにってだけ、プロンプト全部はだるいし）
def create_8char_hash(s: str) -> str:
    hash_object = hashlib.md5(s.encode())
    full_hash = hash_object.hexdigest()
    return full_hash[:8]

# 生成ファイルディレクトリから最新のファイルのパスを得る
def get_latest_modified_file_path(dirname):
  target = os.path.join(dirname, '*')
  files = [(f, os.path.getmtime(f)) for f in glob(target)]
  if not files:
    return ""
  latest_modified_file_path = sorted(files, key=lambda files: files[1])[-1]
  return latest_modified_file_path[0]

# 生成スクリプトを走らせる
async def start_gen_script():
    cmd = [
        "python", "gen_img_diffusers.py",
        "--ckpt", MODEL_PATH,
        "--outdir", OUT_DIR,
        "--W", "512",
        "--H", "512",
        "--scale", "7",
        "--sampler", "k_euler_a",
        "--steps", "20",
        "--batch_size", "1",
        "--images_per_prompt", "1",
        "--no_preview",
        "--interactive",
        "--vae", VAE_PATH
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    return process

# 標準出力から特定のキーワードを待機する
async def wait_for_output(script_stdout, keyword):
    while True:
        line = await script_stdout.readline()
        if not line:
            continue

        line = line.decode().strip()
        print(line)
        if line == keyword:
            return

# 標準エラー出力から進捗を取り出す
async def read_progress(process):
    global progress
    progress_pattern = re.compile(r"(\d+)%")
    buf = bytearray()

    while True:
        chunk = await process.stderr.read(1)
        buf.extend(chunk)

        # ターミナルの標準エラーに生の出力を表示
        sys.stderr.buffer.write(chunk)
        sys.stderr.flush()

        try:
            decoded_buf = buf.decode()
        except UnicodeDecodeError:
            continue

        # マッチしたら進捗率を取得
        percent_match = progress_pattern.search(decoded_buf)
        if percent_match:
            progress = int(percent_match.group(1))
            print(f"Progress: {progress}%")
            # 進捗率を取得した後、バッファをリセット
            buf.clear()

        # 行頭でバッファリセット
        if b'\r' in buf or b'\n' in buf:
            buf.clear()

# 労働者
async def worker(process):
    global job_running
    global progress
    global initializing
    await wait_for_output(process.stdout, "Type prompt:")       # "Type prompt:" を待機
    initializing = False
    while True:
        message = await tasks_queue.get()           # キューからメッセージを取得
        print(f"生成を開始:hash={create_8char_hash(message.content)}")

        job_running = True
        progress = 0
        try:
            old_file_path=get_latest_modified_file_path(OUT_DIR)        # 生成前の最新ファイルを取得
            process.stdin.write((message.content[4:].replace("\n", " ") + '\n').encode())  # プロンプトを送信
            await process.stdin.drain()

            await wait_for_output(process.stdout, "Type prompt:")       # "Type prompt:" を待機
            latest_file_path = get_latest_modified_file_path(OUT_DIR)   # 生成後の最新ファイルを取得

            # 新しいファイルが生成されていない->エラーがあった
            if latest_file_path==old_file_path:
                await message.channel.send((f"{message.author.name}の{create_8char_hash(message.content)}じゃが…"
                                            "どっか行っちゃったのじゃ。"))
            # 新しいファイルがある->正常（たぶん）
            else:
                # 成果をDiscordに送信
                with open(latest_file_path, 'rb') as f:
                    pict = discord.File(f)
                    print(f"生成ファイルを発表:{latest_file_path}, hash={create_8char_hash(message.content)}")
                    await message.channel.send(f"{message.author.name}の"
                                               f"{create_8char_hash(message.content)}じゃ！")
                    await message.channel.send(file=pict)

        except Exception as e:
            print(f"キュー処理スレッドの例外:{e}")
            message.channel.send(f"{message.author.name}の{create_8char_hash(message.content)}じゃが…"
                                 f"{e}って文字が浮いてきてびっくりしたのじゃ。")

        tasks_queue.task_done()                     # ジョブが完了したことをキューに通知
        if tasks_queue.empty():
            job_running = False

# アクティビティの定期更新
@tasks.loop(seconds=5)
async def change_activity():
    global gaming_reg
    # 初期化中
    if initializing:
        text = '寝起き'
    else:
        # 暇なとき
        if not job_running:
            if gaming_reg:
                return
            else:
                gaming_reg = True
                text = random.choice(GAMES)
        # 忙しい時
        else:
            gaming_reg = False
            text = f'{progress}%+{tasks_queue.qsize()}'

    # アクティビティ変更
    activity = discord.Game(text)
    await bot.change_presence(activity=activity)

# 起動時
@bot.event
async def on_ready():
    print(f'bot connection ready as {bot.user}')
    process=await start_gen_script()                # スクリプトを開始
    change_activity.start()                         # アクティビティ表示器稼働開始
    asyncio.create_task(read_progress(process))     # 進捗読み取り機稼働開始
    asyncio.create_task(worker(process))            # 労働者稼働開始

# 呼ばれた時
@bot.command(name='img')
async def on_request(ctx, *, message):
    if ctx.channel.name == CH_NAME:
        print(f"え、{ctx.message}って?")

        # キューにメッセージを追加する前のサイズを取得
        qsize = tasks_queue.qsize()

        # キューにメッセージを追加
        await tasks_queue.put(ctx.message)

        print(f'キューの{qsize}番目に{ctx.message.content}を追加しました。')
        tmp=ctx.message.content[4:].replace("\n", " ")
        print(f'改行を処理すると{tmp}')

        # ジョブが走っていない
        if not job_running and qsize==0:
            oktext=(f'{ctx.author.name}、すぐ描いてやるぞ。'
                    f'(hash:{create_8char_hash(ctx.message.content)})')
        # ジョブが走っている
        elif qsize==0:
            oktext=(f'{ctx.author.name}、次に描いてやるから待っておれよ。'
                    f'(hash:{create_8char_hash(ctx.message.content)})')
        # ジョブが走っている+キューが積まれている
        else:
            oktext=(f'{ctx.author.name}、{qsize+1}番目に描いてやるから待っておれよ。'
                    f'(hash:{create_8char_hash(ctx.message.content)})')
        await ctx.send(oktext)

# boot
bot.run(DISCORD_TOKEN)

