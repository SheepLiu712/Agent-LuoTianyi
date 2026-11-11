extends RefCounted
## 缓存配额淘汰：按修改时间从旧到新删除，直到总字节回到上限。
## 只处理调用方筛选出的文件，不解析文件内容。


static func prune(directory: String, include: Callable, remove: Callable, max_bytes: int) -> void:
	if directory.is_empty() or not DirAccess.dir_exists_absolute(directory):
		return
	var items: Array[Dictionary] = []
	var total := 0
	for name in DirAccess.get_files_at(directory):
		if not include.call(name):
			continue
		var path := directory.path_join(name)
		var size := _file_size(path)
		total += size
		items.append({"path": path, "size": size, "saved": FileAccess.get_modified_time(path)})
	if total <= max_bytes:
		return
	items.sort_custom(func(a, b): return int(a.saved) < int(b.saved))
	for item in items:
		if total <= max_bytes:
			break
		if int(remove.call(item)) == OK:
			total -= int(item.size)


static func _file_size(path: String) -> int:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return 0
	var size := file.get_length()
	file.close()
	return size
