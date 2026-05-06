/**
 * live2d_helper 单元测试
 * 测试表情映射逻辑：已知表情能正确转换，未知表情返回空字符串。
 */

// Mock the config module before importing the helper
jest.mock('../config/live2d', () => ({
  LIVE2D_CONFIG: {
    expression_projection: {
      微笑脸: 'normal',
      生气脸: 'angry',
      呆呆脸: 'dumb',
      害怕脸: 'fear',
      难过脸: 'sad',
      温柔脸: 'ease',
      喜欢脸: 'like',
      卖萌: 'moemoe',
      唱歌: 'sing',
    },
  },
}));

import { setExpression } from '../utils/live2d_helper';
import { WebView } from 'react-native-webview';

describe('setExpression', () => {
  let mockWebViewRef: { current: WebView | null };

  beforeEach(() => {
    mockWebViewRef = { current: null };
  });

  it('should return empty string for unknown expression', () => {
    // WebView ref为空时，不应该crash
    expect(() => {
      setExpression('不存在的表情', mockWebViewRef as any);
    }).not.toThrow();
  });

  it('should do nothing when webview ref is null', () => {
    const injectJs = jest.fn();
    mockWebViewRef.current = { injectJavaScript: injectJs } as any;

    setExpression('不存在的表情', mockWebViewRef as any);
    // 未知表情不应调用 injectJavaScript
    expect(injectJs).not.toHaveBeenCalled();
  });

  it('should inject correct JS for known expression', () => {
    const injectJs = jest.fn();
    mockWebViewRef.current = { injectJavaScript: injectJs } as any;

    setExpression('微笑脸', mockWebViewRef as any);
    expect(injectJs).toHaveBeenCalledWith(
      `window.setExpression("normal"); true;`,
    );
  });

  it('should inject correct JS for 唱歌 expression', () => {
    const injectJs = jest.fn();
    mockWebViewRef.current = { injectJavaScript: injectJs } as any;

    setExpression('唱歌', mockWebViewRef as any);
    expect(injectJs).toHaveBeenCalledWith(
      `window.setExpression("sing"); true;`,
    );
  });
});
