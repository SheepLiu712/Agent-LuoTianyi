extends RefCounted
## Popup auto-dismissal occurs during the trigger press, before its release.
## Remember the initial visibility regardless of hide/button_down signal order.
var _popup: Popup
var _just_dismissed := false
var _dismissed_on_press := false

func _init(trigger: BaseButton, popup: Popup) -> void:
	_popup = popup
	_popup.popup_hide.connect(_on_hidden)
	trigger.button_down.connect(func(): _dismissed_on_press = _popup.visible or _just_dismissed)

func should_open() -> bool:
	if _dismissed_on_press:
		_dismissed_on_press = false
		_popup.hide()
		return false
	if _popup.visible:
		_popup.hide()
		return false
	return true

func _on_hidden() -> void:
	_just_dismissed = true
	_clear_dismissal.call_deferred()

func _clear_dismissal() -> void:
	_just_dismissed = false
