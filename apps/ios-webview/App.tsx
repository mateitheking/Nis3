import { useCallback, useRef, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import WebView, { type WebViewNavigation } from 'react-native-webview';

const SITE_URL = 'https://nis3.fly.dev/';

export default function App() {
  const webviewRef = useRef<WebView>(null);
  const [loading, setLoading] = useState(true);
  const [canGoBack, setCanGoBack] = useState(false);

  const onNavigationStateChange = useCallback((nav: WebViewNavigation) => {
    setCanGoBack(nav.canGoBack);
  }, []);

  return (
    <SafeAreaProvider>
      <SafeAreaView style={styles.root} edges={['top', 'bottom']}>
        <StatusBar style="light" />
        <WebView
          ref={webviewRef}
          source={{ uri: SITE_URL }}
          style={styles.webview}
          onLoadEnd={() => setLoading(false)}
          onNavigationStateChange={onNavigationStateChange}
          sharedCookiesEnabled
          allowsBackForwardNavigationGestures
          startInLoadingState={false}
          decelerationRate="normal"
        />
        {loading && (
          <View style={styles.loading} pointerEvents="none">
            <ActivityIndicator size="large" color="#d9a441" />
          </View>
        )}
      </SafeAreaView>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: '#0d0d0d',
  },
  webview: {
    flex: 1,
    backgroundColor: '#0d0d0d',
  },
  loading: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#0d0d0d',
  },
});
