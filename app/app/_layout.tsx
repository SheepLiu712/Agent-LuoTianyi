import { requestAccountReset } from '../features/account/credentials';
import { voicePlaybackManager } from '../features/chat/voice_playback_manager';
import { AppNotices } from '../shell/notices/AppNotices';
import React, { useRef, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from "react-native";
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { useAuth } from '../features/account/useAuth';
import MainScreen from '../shell/MainScreen';
import LoginScreen from '../features/account/LoginScreen';

export default function RootLayout() {
  const { session, isLoading, login, register, logout, pendingAgreement, acceptAgreement, dismissAgreement, retryAgreement } = useAuth();

  const [leaving, setLeaving] = useState(false);
  const exitStarted = useRef(false);
  const resetAccount = async (username: string, password: string, inviteCode: string) => {
    await requestAccountReset(username, password, inviteCode);
    await voicePlaybackManager.clear();
  };
  const leaveAccount = async (closeCall: () => Promise<void>) => {
    if (exitStarted.current) return;
    exitStarted.current = true;
    setLeaving(true);
    try {
      await Promise.all([closeCall(), voicePlaybackManager.clear()]);
      await logout();
    } finally {
      exitStarted.current = false;
      setLeaving(false);
    }
  };
  let screen;
  if (isLoading || leaving) {
    screen = <View style={styles.loadingContainer}><ActivityIndicator size="large" color="#66CCFF" /></View>;
  } else if (session) {
    screen = <MainScreen key={session.token} session={session} onLogout={leaveAccount} />;
  } else {
    screen = <LoginScreen onLogin={login} onRegister={register} resetAccount={resetAccount} pendingAgreement={pendingAgreement} onAcceptAgreement={() => acceptAgreement(pendingAgreement!)} onAgreementClose={dismissAgreement} onRetryAgreement={retryAgreement} />;
  }
  return (
    <SafeAreaProvider>
      <AppNotices>{screen}</AppNotices>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#f5f5f5',
  },
});
