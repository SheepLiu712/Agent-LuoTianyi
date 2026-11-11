extends Window

const ModalStack = preload("res://src/ui/modal_stack.gd")
const ModalWindowLayout = preload("res://src/ui/modal_window_layout.gd")
signal confirmed
signal canceled
signal custom_action(action: String)
@export_multiline var dialog_text := ""
@export var ok_button_text := "确认"
@export var cancel_button_text := "取消"
@export var show_save := false
@export var destructive_action := false

var _fitting := false
var _refining := false


func _ready() -> void:
	%Confirm.pressed.connect(func(): hide(); confirmed.emit())
	%Cancel.pressed.connect(_cancel)
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
	_apply_action_hierarchy()
	if visible:
		ModalStack.activate(self)
		if not _fitting:
			_fitting = true
			ModalWindowLayout.present(self, %Panel, %Message)
			_fitting = false
		%Cancel.grab_focus.call_deferred()


func _apply_action_hierarchy() -> void:
	%Confirm.theme_type_variation = &"SettingsDangerButton" if destructive_action else &"SettingsPrimaryButton"
	%Cancel.theme_type_variation = &"SettingsPrimaryButton" if destructive_action else &"SettingsButton"
	%SaveAndClose.theme_type_variation = &"SettingsPrimaryButton"


func _refine_modal_height() -> void:
	if _refining:
		return
	_refining = true
	for _pass in 3:
		await get_tree().process_frame
		if not visible:
			_refining = false
			return
		if %Message.size.x > 1.0:
			break
	if visible:
		ModalWindowLayout.refine_height(self, %Panel, %Message)
	_refining = false


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
