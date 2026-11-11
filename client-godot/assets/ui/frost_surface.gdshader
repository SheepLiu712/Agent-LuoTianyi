shader_type canvas_item;
render_mode unshaded;
uniform sampler2D screen_texture : hint_screen_texture, repeat_disable, filter_linear_mipmap;
uniform vec4 tint : source_color = vec4(0.95, 0.98, 1.0, 0.86);
uniform float radius : hint_range(0.0, 12.0) = 4.0;
void fragment() {
	vec3 blur = textureLod(screen_texture, SCREEN_UV, radius).rgb;
	COLOR = vec4(mix(blur, tint.rgb, tint.a), 1.0);
}
