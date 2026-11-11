shader_type canvas_item;

// 圆形头像遮罩：圆外透明，圆内以浅色底与头像像素按 alpha 混合。
void fragment() {
	vec4 p = texture(TEXTURE,UV);
	float a = 1.0-smoothstep(0.47,0.5,length(UV-vec2(0.5)));
	COLOR = vec4(mix(vec3(0.91,0.97,1.0),p.rgb,p.a),a);
}