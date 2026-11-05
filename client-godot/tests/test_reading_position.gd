extends SceneTree
var failures: Array[String] = []
func check(value: bool,text: String) -> void:
	if not value:
		failures.append(text)
		print("FAIL: ",text)
func _initialize() -> void:
	check(ResourceLoader.exists("res://src/storage/reading_position.gd"),"local reading boundary exists")
	if not failures.is_empty():
		quit(1)
		return
	var directory := "user://reading-test-%s"%Time.get_ticks_usec()
	var script = load("res://src/storage/reading_position.gd")
	var cursor = script.new(directory)
	var messages: Array[Dictionary] = []
	for i in 5:
		messages.append({"id":str(i),"role":"assistant","history":true})
	cursor.start("HTTPS://EXAMPLE.COM:443/","a")
	cursor.update(messages,{"phase":"first_loading"})
	cursor.report_visible(["4"],true)
	check(cursor.get_state().saved_id.is_empty() and cursor.get_state().pending,"download doesn't mark read before location")
	cursor.update(messages,{"phase":"complete"})
	check(cursor.get_state().target_id == "4","first login targets latest")
	cursor.located()
	cursor.report_visible(["1"],false)
	check(cursor.get_state().saved_id.is_empty(),"background doesn't mark read")
	cursor.report_visible(["1"],true)
	check(cursor.get_state().saved_id == "1","actually visible foreground advances read")
	cursor.report_visible(["0"],true)
	check(cursor.get_state().saved_id == "1","scrolling backward doesn't regress read")
	var second = script.new(directory)
	second.start("https://example.com","a")
	second.update([messages[4]],{"phase":"loading"})
	second.report_visible(["4"],true)
	check(second.get_state().saved_id == "1" and second.get_state().pending,"recent page doesn't overwrite old anchor")
	second.update(messages,{"phase":"complete"})
	check(second.get_state().target_id == "2","next login targets first after last read")
	second.start("https://example.com","a")
	second.interact()
	second.update(messages,{"phase":"complete"})
	check(second.get_state().manual,"user action suppresses delayed auto jump")
	second.start("https://example.com","a")
	second.update([messages[4]],{"phase":"complete"})
	check(second.get_state().target_id == "4" and second.get_state().reason == "NOT_FOUND","missing anchor explicit latest fallback")
	second.start("https://example.com","b")
	check(second.get_state().saved_id.is_empty(),"account isolation")
	second.start("https://other.example.com","a")
	check(second.get_state().saved_id.is_empty(),"server isolation")
	for file in DirAccess.get_files_at(directory):
		DirAccess.remove_absolute(directory.path_join(file))
	DirAccess.remove_absolute(directory)
	print("Reading position: ","PASS" if failures.is_empty() else "FAIL")
	quit(0 if failures.is_empty() else 1)
