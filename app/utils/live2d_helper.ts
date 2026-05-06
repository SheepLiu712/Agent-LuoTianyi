import { LIVE2D_CONFIG } from '@/config/live2d';
import { WebView } from 'react-native-webview';
import { addDebugTrace } from './debug_trace';

const expressionProjection = LIVE2D_CONFIG.expression_projection;
function getExpressionCmd(expression: string) {
  const mappedExpression = expressionProjection[expression as keyof typeof expressionProjection];
  if (!mappedExpression) {
    addDebugTrace('live2d', 'unknown expression', { expression });
    return '';
  }
  return mappedExpression;
}

export function setExpression(expression: string, webviewRef: React.RefObject<WebView | null>) {
  const cmd = getExpressionCmd(expression);
  if (cmd && webviewRef.current) {
    const jsCode = `window.setExpression(${JSON.stringify(cmd)}); true;`;
    webviewRef.current.injectJavaScript(jsCode);
  }
}