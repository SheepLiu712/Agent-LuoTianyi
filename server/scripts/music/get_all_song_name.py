import os
import json
import re
import pathlib
import psutil


work_dir = "res/music/songs"
all_song_names = []
for file in os.listdir(work_dir):
    # 查找包含song_name的文件
    if not file.endswith(".mp3") and not file.endswith(".wav"):
        continue
    song_name = file.rsplit(".", 1)[0]
    try:
        song_name = song_name.split("-")[1] # 前面是歌手名字
    except:
        pass
    song_name = song_name.split("_")[0] # 后面是后处理标记
    song_name = song_name.lstrip().rstrip()
    all_song_names.append(song_name)

print(all_song_names)
print(len(all_song_names))