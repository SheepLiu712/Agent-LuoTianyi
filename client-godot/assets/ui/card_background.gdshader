shader_type canvas_item;
uniform vec2 panel_size = vec2(400.0, 704.0);
uniform float corner_radius = 8.0;

void fragment() {
	vec2 point = UV * panel_size;
	vec2 center = clamp(point, vec2(corner_radius), panel_size - vec2(corner_radius));
	float edge = length(point - center) - corner_radius;
	float mask = 1.0 - smoothstep(-0.5, 0.5, edge);
	COLOR.a *= mask;
}
