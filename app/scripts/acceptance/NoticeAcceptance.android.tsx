import { registerRootComponent } from 'expo';
import React, { useState } from 'react';
import { Button, ScrollView, Text, TextInput, View } from 'react-native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import { AppNotices, usePageNotices } from '../../shell/notices/AppNotices';
import { THEMES } from '../../shared/ui/theme';

// 独立的真机验收入口，只装配生产提示组件和可观察的背景操作。
function NoticeExamples() {
  const show = usePageNotices('提示验收');
  const [clicks, setClicks] = useState(0);
  const [offset, setOffset] = useState(0);
  const [choice, setChoice] = useState('未选择');
  const theme = THEMES.light;
  const showChoice = (blocking: boolean) => show({
    title: '麦克风权限',
    message: '仍未获得麦克风权限，可前往系统设置为本应用开启麦克风权限。请确认以下选择。',
    layout: 'banner', theme, blocking,
    primary: { label: '去设置', action: () => setChoice('已确认') },
    cancel: { label: '取消', action: () => setChoice('已取消') },
  });
  return <SafeAreaView style={{ flex: 1, paddingHorizontal: 12, backgroundColor: '#ffffff' }}>
    <Button title="有蒙版可操作" onPress={() => show({ message: '有蒙版', theme, dimmed: true, blocking: false })} />
    <Button title="无蒙版阻挡" onPress={() => show({ message: '无蒙版', theme, dimmed: false, blocking: true })} />
    <Button title="双按钮阻挡" onPress={() => showChoice(true)} />
    <Button title="双按钮保留背景输入" onPress={() => showChoice(false)} />
    <TextInput placeholder="打开软键盘" />
    <Button title="背景点击" onPress={() => setClicks(value => value + 1)} />
    <Text>{`点击 ${clicks}，滚动 ${offset}，${choice}`}</Text>
    <ScrollView style={{ flex: 1 }} scrollEventThrottle={32}
      onScroll={event => setOffset(Math.round(event.nativeEvent.contentOffset.y))}>
      {Array.from({ length: 80 }, (_, i) =>
        <Text key={i} style={{ paddingVertical: 12 }}>{`列表项 ${i + 1}`}</Text>)}
    </ScrollView>
  </SafeAreaView>;
}

function AcceptanceApp() {
  return <SafeAreaProvider><AppNotices><NoticeExamples /></AppNotices></SafeAreaProvider>;
}
registerRootComponent(AcceptanceApp);
