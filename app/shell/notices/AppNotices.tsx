import React, { createContext, useCallback, useContext, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import type { AppTheme } from '../../shared/ui/theme';

interface Button {
  label: string;
  accessibilityLabel?: string;
  action?: () => void;
}
export interface Notice {
  title?: string;
  message: string;
  theme: AppTheme;
  primary?: Button;
  cancel?: Button;
  position?: 'top' | 'center' | 'bottom';
  layout?: 'banner' | 'card';
  blocking?: boolean;
  dimmed?: boolean;
  scope?: 'page' | 'app';
}
interface Entry {
  id: symbol;
  owner: symbol;
  notice: Notice;
}
const blocks = (notice: Notice) => notice.blocking ?? Boolean(notice.cancel);
const Context = createContext<{
  show(owner: symbol, notice: Notice): () => void;
  leave(owner: symbol): void;
} | null>(null);

/** A new business screen gets a new identity even if React keeps the host mounted. */
export function usePageNotices(page: string) {
  const context = useContext(Context);
  if (!context) throw new Error('缺少应用提示入口');
  const owner = useMemo(() => Symbol(page), [page]);
  const active = useRef<symbol | null>(null);
  useLayoutEffect(() => {
    active.current = owner;
    return () => { active.current = null; context.leave(owner); };
  }, [context, owner]);
  return useCallback((notice: Notice) => {
    if (active.current !== owner) return () => {};
    return context.show(owner, notice);
  }, [context, owner]);
}

export function AppNotices({ children }: React.PropsWithChildren) {
  const entries = useRef<Entry[]>([]);
  const [visible, setVisible] = useState<Entry>();
  const afterDismiss = useRef<Button['action']>(undefined);
  useLayoutEffect(() => {
    const action = afterDismiss.current;
    afterDismiss.current = undefined;
    action?.();
  }, [visible]);
  const publish = useCallback(() => {
    const queue = entries.current;
    setVisible(queue.find(entry => blocks(entry.notice)) ?? queue[0]);
  }, []);
  const remove = useCallback((id: symbol) => {
    const index = entries.current.findIndex(entry => entry.id === id);
    if (index < 0) return false;
    entries.current.splice(index, 1);
    publish();
    return true;
  }, [publish]);
  const context = useMemo(() => ({
    show(owner: symbol, notice: Notice) {
      const id = Symbol();
      entries.current.push({ id, owner, notice });
      publish();
      return remove.bind(null, id);
    },
    leave(owner: symbol) {
      entries.current = entries.current.filter(entry => entry.owner !== owner || entry.notice.scope === 'app');
      publish();
    },
  }), [publish, remove]);
  return <Context.Provider value={context}>
    <View style={{ flex: 1 }}>{children}
      {/* 常驻宿主接收键盘事件，提示在键盘已展开时也能按可见高度布局。 */}
      <KeyboardAvoidingView pointerEvents="box-none" behavior="padding" style={[StyleSheet.absoluteFill, { zIndex: 1000 }]}>
        {visible && <NoticeView notice={visible.notice} choose={button => {
          const current = entries.current.find(entry => blocks(entry.notice)) ?? entries.current[0];
          if (current !== visible) return;
          afterDismiss.current = button?.action;
          remove(visible.id);
        }} />}
      </KeyboardAvoidingView>
    </View>
  </Context.Provider>;
}

function NoticeView({ notice, choose }: { notice: Notice; choose(button?: Button): void }) {
  const insets = useSafeAreaInsets();
  const { width, fontScale } = useWindowDimensions();
  const blocking = blocks(notice);
  const position = notice.position ?? (notice.cancel ? 'center' : 'top');
  const banner = !notice.cancel && (notice.layout ?? (position === 'center' ? 'card' : 'banner')) === 'banner';
  const compact = width / Math.max(1, fontScale) < 320;
  const theme = notice.theme;
  const primary = notice.primary ?? { label: '知道了' };
  const overlay = <View pointerEvents={blocking ? 'auto' : 'box-none'} style={{
      flex: 1, paddingHorizontal: 16, paddingTop: insets.top + 8, paddingBottom: insets.bottom + 8,
      justifyContent: position === 'center' ? 'center' : position === 'bottom' ? 'flex-end' : 'flex-start',
      backgroundColor: (notice.dimmed ?? Boolean(notice.cancel)) ? 'rgba(0,0,0,0.45)' : 'transparent',
    }}>
    <View accessibilityRole="alert" style={{ backgroundColor: theme.surface, borderColor: theme.border,
      borderWidth: 1, borderRadius: 14, padding: 14, maxHeight: '100%', maxWidth: 520, width: '100%', alignSelf: 'center',
      flexDirection: banner && !compact ? 'row' : 'column', alignItems: 'center' }}>
      <ScrollView style={{ flexShrink: 1, alignSelf: 'stretch' }} contentContainerStyle={{ flexGrow: 1, justifyContent: 'center' }} keyboardShouldPersistTaps="handled">
        {notice.title ? <Text style={{ color: theme.text, fontWeight: 'bold' }}>{notice.title}</Text> : null}
        <Text style={{ color: theme.text }}>{notice.message}</Text>
      </ScrollView>
      <NoticeButtons key={JSON.stringify([width, fontScale, notice.cancel?.label, primary.label])}
        cancel={notice.cancel} primary={primary} theme={theme} choose={choose} inline={banner && !compact} />
    </View>
  </View>;
  // Android dispatches back to the modal before the underlying business screen.
  return blocking ? <Modal transparent visible onRequestClose={() => choose(notice.cancel)}>
    <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={{ flex: 1 }}>
      {overlay}
    </KeyboardAvoidingView>
  </Modal> : overlay;
}

function NoticeButtons({ cancel, primary, theme, choose, inline }: {
  cancel?: Button; primary: Button; theme: AppTheme; choose(button: Button): void; inline: boolean;
}) {
  const [stacked, setStacked] = useState(false);
  return <View style={{ flexDirection: stacked ? 'column' : 'row', alignSelf: cancel ? 'stretch' : 'flex-end',
    marginLeft: inline ? 'auto' : 0 }}>
    {(cancel ? [cancel, primary] : [primary]).map((button, index) =>
      <Pressable key={index} accessibilityRole="button" accessibilityLabel={button.accessibilityLabel}
        onPress={() => choose(button)}
        style={{ flexGrow: cancel ? 1 : 0, flexBasis: cancel && !stacked ? 0 : 'auto', padding: 8,
          minHeight: 44, justifyContent: 'center', alignItems: 'center' }}>
        <Text style={{ color: theme.accentText, textAlign: 'center' }}
          onTextLayout={cancel && !stacked ? event => {
            if (event.nativeEvent.lines.length > 1) setStacked(true);
          } : undefined}>{button.label}</Text>
      </Pressable>)}
  </View>;
}
