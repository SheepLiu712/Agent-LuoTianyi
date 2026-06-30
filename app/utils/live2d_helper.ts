import { LIVE2D_CONFIG } from '@/config/live2d';
import { WebView } from 'react-native-webview';
import { addDebugTrace } from './debug_trace';

const expressionProjection = LIVE2D_CONFIG.expression_projection;
function getExpressionCmd(expression: string) {
  // 先尝试作为 key（中文描述）查找映射值
  const mappedExpression = expressionProjection[expression as keyof typeof expressionProjection];
  if (mappedExpression) {
    return mappedExpression;
  }
  // 如果本身就是 value（英文命令），直接透传
  const values: string[] = Object.values(expressionProjection);
  if (values.includes(expression)) {
    return expression;
  }
  // 完全未知
  addDebugTrace('live2d', 'unknown expression', { expression });
  return '';
}

export function setExpression(expression: string, webviewRef: React.RefObject<WebView | null>) {
  const cmd = getExpressionCmd(expression);
  if (cmd && webviewRef.current) {
    const jsCode = `window.setExpression(${JSON.stringify(cmd)}); true;`;
    webviewRef.current.injectJavaScript(jsCode);
  }
}