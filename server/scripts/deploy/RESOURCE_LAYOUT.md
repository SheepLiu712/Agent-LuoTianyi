# 运行资源迁移

新环境的歌曲目录为 `data/singing/<角色>`，知识库为 `data/knowledge`。旧环境仍可使用原配置中的显式路径；不要直接用仓库配置覆盖实例配置。

迁移前停止全部服务、手动启动进程和数据维护工具。使用原部署目录执行：

```bash
python scripts/deploy/migrate_resource_layout.py --server-root /path/to/server
python scripts/deploy/migrate_resource_layout.py --server-root /path/to/server --apply --offline
```

工具复制歌曲与知识库，原文件不删除；在所有复制成功后原子替换配置，并保留 `config.before-resource-layout.json`。已有目标或备份会导致拒绝执行。锁只覆盖遵循现有启动约定的进程，`--offline` 不是自动停服。复制数据库必须在所有写入者停止后执行。

旧 QQ 凭据仅在新路径不存在时复制到 `config/qq_music_credential.json`，不覆盖现有凭据。外部绝对路径和自定义路径不改写，需要单独迁移。失败后的清理仅删除本次创建的目标。迁移后若已经启动并产生新数据，不能仅恢复旧配置作为数据回滚。

学歌流水线使用 `.runtime/song_learner` 作为工作目录，输出歌曲仍按配置写入歌曲库。可以通过 `world.auto_song_learner.work_dir` 指定独立目录。
