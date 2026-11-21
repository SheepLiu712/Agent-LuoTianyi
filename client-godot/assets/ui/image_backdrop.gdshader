shader_type canvas_item;

void fragment() {
	vec2 cell = floor(FRAGCOORD.xy / 12.0);
	float checker = mod(cell.x + cell.y, 2.0);
	vec3 light = vec3(0.969, 0.980, 0.988);
	vec3 dim = vec3(0.929, 0.953, 0.969);
	COLOR = vec4(mix(light, dim, checker), 1.0);
}
