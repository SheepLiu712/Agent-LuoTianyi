extends Window
signal confirmed
signal canceled
signal custom_action(action: String)
@export_multiline var dialog_text := ""
@export var ok_button_text := "确认"
@export var cancel_button_text := "取消"
@export var show_save := false

func _ready() -> void:
	%Confirm.pressed.connect(func(): hide(); confirmed.emit())
	%Cancel.pressed.connect(_cancel)
	%CloseDecision.pressed.connect(_cancel)
	%SaveAndClose.pressed.connect(func(): hide(); custom_action.emit("save"))
	close_requested.connect(_cancel)
	visibility_changed.connect(_display)
	_display()

func _display() -> void:
	%Message.text = dialog_text
	%DecisionTitle.text = title
	%Confirm.text = ok_button_text
	%Cancel.text = cancel_button_text
	%SaveAndClose.visible = show_save
	if visible: %Cancel.grab_focus.call_deferred()

func _cancel() -> void:
	hide()
	canceled.emit()

func get_ok_button() -> Button:
	return %Confirm

func get_cancel_button() -> Button:
	return %Cancel

func _input(event: InputEvent) -> void:
	if visible and event.is_action_pressed("ui_cancel"):
		get_viewport().set_input_as_handled()
		_cancel()
