export type ColorMode = 'light' | 'dark' | 'system';
export type ResolvedThemeName = 'light' | 'dark';

export interface AppTheme {
  name: ResolvedThemeName;
  root: string;
  chatList: string;
  safeArea: string;
  inputBar: string;
  inputBorder: string;
  inputBackground: string;
  inputText: string;
  placeholder: string;
  surface: string;
  surfaceAlt: string;
  surfacePressed: string;
  elevated: string;
  border: string;
  text: string;
  textMuted: string;
  textSoft: string;
  accent: string;
  accentSoft: string;
  accentText: string;
  menuButton: string;
  userBubble: string;
  botBubble: string;
  bubbleText: string;
  userBubbleText: string;
  dangerSurface: string;
  dangerText: string;
  debugBackground: string;
  debugBorder: string;
  debugHeader: string;
  debugText: string;
  debugAction: string;
  shadow: string;
  dim: string;
  live2dOverlay: string;
}

export const COLOR_MODE_LABELS: Record<ColorMode, string> = {
  light: '浅色',
  dark: '深色',
  system: '跟随系统',
};

export const COLOR_MODE_STORAGE_KEY = 'color_mode';

export const THEMES: Record<ResolvedThemeName, AppTheme> = {
  light: {
    name: 'light',
    root: '#ffffff',
    chatList: '#E8E8E8',
    safeArea: '#ffffff',
    inputBar: '#f0f0f0',
    inputBorder: '#dddddd',
    inputBackground: '#ffffff',
    inputText: '#243447',
    placeholder: '#999999',
    surface: '#ffffff',
    surfaceAlt: '#f4f8fb',
    surfacePressed: '#e8f6ff',
    elevated: '#ffffff',
    border: '#d9e1e8',
    text: '#243447',
    textMuted: '#7b8794',
    textSoft: '#4b5967',
    accent: '#66CCFF',
    accentSoft: '#e8f6ff',
    accentText: '#1674a3',
    menuButton: 'rgba(255, 255, 255, 0.72)',
    userBubble: '#ffffff',
    botBubble: '#88EDFF',
    bubbleText: '#000000',
    userBubbleText: '#000000',
    dangerSurface: '#fff1f1',
    dangerText: '#c24141',
    debugBackground: '#0f1720',
    debugBorder: '#203244',
    debugHeader: '#b9d7ff',
    debugText: '#d9e4f0',
    debugAction: '#79ffa8',
    shadow: '#000000',
    dim: '#000000',
    live2dOverlay: 'rgba(0, 0, 0, 0)',
  },
  dark: {
    name: 'dark',
    root: '#0F1419',
    chatList: '#121A22',
    safeArea: '#0F1419',
    inputBar: '#151C24',
    inputBorder: '#2C3642',
    inputBackground: '#202A34',
    inputText: '#EEF4F8',
    placeholder: '#7D8B99',
    surface: '#18202A',
    surfaceAlt: '#202A34',
    surfacePressed: '#12384B',
    elevated: '#202833',
    border: '#2E3946',
    text: '#EEF4F8',
    textMuted: '#9AA8B7',
    textSoft: '#C6D0DA',
    accent: '#66CCFF',
    accentSoft: '#12384B',
    accentText: '#BDEEFF',
    menuButton: 'rgba(15, 20, 25, 0.78)',
    userBubble: '#2B3542',
    botBubble: '#0D5B73',
    bubbleText: '#F4FAFC',
    userBubbleText: '#F4FAFC',
    dangerSurface: '#3A2024',
    dangerText: '#FF9A9A',
    debugBackground: '#0A1118',
    debugBorder: '#2E4357',
    debugHeader: '#BDEEFF',
    debugText: '#D7E6F1',
    debugAction: '#8EF2BE',
    shadow: '#000000',
    dim: '#000000',
    live2dOverlay: 'rgba(19, 24, 30, 0.42)',
  },
};

export function resolveTheme(mode: ColorMode, systemScheme: 'light' | 'dark' | null | undefined): AppTheme {
  if (mode === 'system') {
    return THEMES[systemScheme === 'dark' ? 'dark' : 'light'];
  }
  return THEMES[mode];
}
