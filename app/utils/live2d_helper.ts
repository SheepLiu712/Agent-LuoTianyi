import { LIVE2D_CONFIG } from '@/config/live2d';
import { WebView } from 'react-native-webview';

const expressionProjection = LIVE2D_CONFIG.expression_projection;
function getExpressionCmd(expression: string) {
  const mappedExpression = expressionProjection[expression as keyof typeof expressionProjection];
  if (!mappedExpression) {
    console.warn(`Expression "${expression}" not found in projection mapping.`);
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