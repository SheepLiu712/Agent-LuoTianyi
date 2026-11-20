export function validateClientModelRequirements(options: {
  requiredKind: string;
  configuredKind: string;
  requiresJson: boolean;
  requiresThinking: boolean;
  canUseJson: boolean;
  canEnableThinking: boolean;
}): string | null {
  const requiredKind = options.requiredKind.trim().toLowerCase();
  if (requiredKind !== 'llm' && requiredKind !== 'vlm') {
    return `服务端下发了未知模型类型：${requiredKind}`;
  }
  if (options.configuredKind !== requiredKind) {
    return `本地配置是 ${options.configuredKind || '未知'} 模型，当前调用要求 ${requiredKind.toUpperCase()} 模型`;
  }
  if (options.requiresJson && !options.canUseJson) {
    return '当前客户端模型未声明 JSON 输出能力';
  }
  if (options.requiresThinking && !options.canEnableThinking) {
    return '当前客户端模型未声明 thinking 能力';
  }
  return null;
}

export function validateJsonResponse(content: string, required: boolean): string | null {
  if (!required) return null;
  try {
    JSON.parse(content);
    return null;
  } catch {
    return '客户端模型未返回有效 JSON';
  }
}
