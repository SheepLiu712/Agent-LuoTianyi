extends Resource
## CA bundle 读取端口：network 只消费探测结果，不直接触碰文件系统。


func read(_path: String) -> Dictionary:
	return {"present": false, "bytes": PackedByteArray(), "loaded": false}
