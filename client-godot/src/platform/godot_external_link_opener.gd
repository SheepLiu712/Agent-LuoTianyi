extends "res://src/platform/external_link_opener.gd"

func open_project() -> Error:
	return OS.shell_open(PROJECT_URL)
