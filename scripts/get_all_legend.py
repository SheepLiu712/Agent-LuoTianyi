import json

memory_file = r"data/MemoryReadable/memory_stable.json"

with open(memory_file, 'r', encoding='utf-8') as f:
    memories = json.load(f)
song_memories = memories['song']

legend_songs = []   
for mem in song_memories:
    if isinstance(mem, list) and len(mem) >= 2:
        if mem[2] == "传说曲（播放超百万）":
            song_title = mem[0]
            # 如果有书名号则去掉
            if song_title.startswith("《") and song_title.endswith("》"):
                song_title = song_title[1:-1]
            legend_songs.append(song_title)

with open('data/legend_songs.txt', 'w', encoding='utf-8') as f:
    for song in legend_songs:
        f.write("\"" + song + "\",\n")